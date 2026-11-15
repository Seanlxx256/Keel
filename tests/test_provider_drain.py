"""Provider lifecycle fixtures; never call an external model."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from keel.control_service import ControlService
from keel.core import ModelError
from keel.governance import GovernanceUnavailable
from keel.models import Reply
from keel.remote_governance import RemoteSession


class ProviderDrainTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.provider=Mock();self.provider.complete.return_value=Reply('sensitive completion',7)
        config={'path':str(Path(temp.name)/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':10000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_DRAIN_TEST',
                           'tools':{},'models':['repair']}],
            'model_proxy':{'models':{'repair':{'provider':'ollama','name':'fixture'}}}}
        env=patch.dict(os.environ,{'KEEL_DRAIN_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        with patch('keel.models.from_config',return_value=self.provider):self.service=ControlService(config)
        self.proxy=self.service.model_proxy
        self.run_id=self.service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})['result']['run_id']

    def request(self):
        return {'operation_id':'call','action':'model_complete','run_id':self.run_id,
            'data':{'alias':'repair','messages':[{'role':'user','content':'private prompt'}],
                    'schema':None,'max_output':100,'timeout':10}}

    def test_stopping_rejects_new_provider_dispatch(self):
        self.proxy.request_stop()
        with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',self.request())
        self.provider.complete.assert_not_called()
        self.assertEqual(self.proxy.shutdown(timeout=.01)['status'],'stopped')

    def test_completed_cache_can_be_reconciled_after_stop(self):
        first=self.service.operate('worker',self.request());self.proxy.request_stop()
        self.assertEqual(self.service.operate('worker',self.request()),first)
        self.provider.complete.assert_called_once()

    def test_live_call_is_not_cancelled_or_refunded_at_shutdown_deadline(self):
        entered=threading.Event();release=threading.Event();results=[];errors=[]
        def reply(*args,**kwargs):entered.set();release.wait(timeout=2);return Reply('done',7)
        def invoke():
            try:results.append(self.service.operate('worker',self.request()))
            except BaseException as error:errors.append(error)
        self.provider.complete.side_effect=reply
        thread=threading.Thread(target=invoke);thread.start()
        try:
            self.assertTrue(entered.wait(timeout=1))
            receipt=self.proxy.shutdown(timeout=.01)
            self.assertFalse(receipt['current_calls_drained'])
            self.assertFalse(receipt['unknown_reservations_released'])
            self.assertEqual(receipt['persisted_inflight_records'],1)
        finally:release.set();thread.join(timeout=2)
        self.assertFalse(errors);self.assertTrue(results[0]['ok'])
        self.assertEqual(self.proxy.shutdown(timeout=.01)['status'],'stopped')

    def test_unknown_usage_remains_unconfirmed_even_after_local_return(self):
        self.provider.complete.side_effect=ModelError('unknown usage')
        self.service.operate('worker',self.request())
        receipt=self.proxy.shutdown(timeout=.01)
        self.assertTrue(receipt['current_calls_drained'])
        self.assertEqual(receipt['unknown_usage_records'],1)
        self.assertEqual(receipt['status'],'cleanup_unconfirmed')

    def test_status_excludes_prompt_reply_and_credentials(self):
        self.service.operate('worker',self.request())
        value=self.proxy.inspect('worker',self.run_id,'call');text=json.dumps(value)
        self.assertNotIn('private prompt',text);self.assertNotIn('sensitive completion',text)
        self.assertNotIn('t'*48,text);self.assertEqual(value['actual'],7)

    def test_out_of_band_inspection_preserves_original_pending_call(self):
        session=RemoteSession({'endpoint':'http://127.0.0.1:8788','token_env':'KEEL_DRAIN_TEST','task_id':'task'})
        pending=self.request();session.pending=pending
        with session._lock,patch.object(session,'_send',return_value={'status':'inflight'}) as send:
            session.inspect_pending_model()
        self.assertIs(session.pending,pending)
        self.assertEqual(send.call_args.args[0]['action'],'model_status')

    def test_service_close_includes_provider_component(self):
        receipt=self.service.close(timeout=.01)
        self.assertIn('provider',receipt['components'])
        self.assertEqual(receipt['status'],'stopped')


if __name__=='__main__':unittest.main()
