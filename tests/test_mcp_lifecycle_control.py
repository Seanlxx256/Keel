"""Cancellation ownership contracts; no MCP server or external tool is launched."""
import asyncio
import os
import threading
import unittest
from unittest.mock import Mock, patch

from keel.async_process_lifecycle import RequestControl, run_request
from keel.control_service import ControlService
from keel.mcp_broker import McpBroker
from keel.remote_governance import RemoteSession


class McpLifecycleTests(unittest.TestCase):
    def test_cancel_before_binding_does_not_enter_factory(self):
        control=RequestControl();control.cancel();entered=[]
        async def factory():entered.append(True)
        with self.assertRaises(asyncio.CancelledError):run_request(factory,control=control)
        self.assertEqual(entered,[])
        self.assertTrue(control.report()['request_finished'])

    def test_other_thread_cancels_only_owned_request_loop(self):
        control=RequestControl()
        async def factory():await asyncio.Event().wait()
        timer=threading.Timer(.02,control.cancel);timer.start()
        try:
            with self.assertRaises(asyncio.CancelledError):run_request(factory,control=control)
        finally:timer.join(timeout=1)
        receipt=control.report()
        self.assertTrue(receipt['cancellation_requested']);self.assertTrue(receipt['direct_children_exited'])

    def test_required_lifecycle_storage_error_prevents_factory(self):
        control=RequestControl();entered=[]
        control.on_update=Mock(side_effect=OSError('fixture storage unavailable'))
        async def factory():entered.append(True)
        with self.assertRaises(OSError):run_request(factory,control=control)
        self.assertEqual(entered,[]);self.assertTrue(control.storage_failed)

    def test_unreaped_direct_child_is_not_certified_closed(self):
        control=RequestControl();transport=Mock()
        transport.get_pid.return_value=123;transport.get_returncode.return_value=None
        control.register(transport);control.finish()
        self.assertFalse(control.report()['direct_children_exited'])

    def test_active_mcp_after_shutdown_budget_remains_unconfirmed(self):
        broker=object.__new__(McpBroker)
        broker.lifecycle_lock=threading.Lock();broker.stopping=threading.Event()
        control=RequestControl();broker.active={('principal','operation'):control};broker.recent={};broker.receipt_failures=0
        result=broker.shutdown(timeout=.01)
        self.assertEqual(result['status'],'cleanup_unconfirmed')
        self.assertTrue(control.requested.is_set())

    def test_service_stops_both_brokers_before_waiting_on_one(self):
        service=object.__new__(ControlService)
        acceptance=Mock();mcp=Mock();service.execution_broker=acceptance;service.mcp_broker=mcp
        def accept_shutdown(**kwargs):
            mcp.request_stop.assert_called_once()
            return {'status':'stopped'}
        acceptance.shutdown.side_effect=accept_shutdown;mcp.shutdown.return_value={'status':'stopped'}
        result=service.close(timeout=.1)
        self.assertEqual(result['status'],'stopped');self.assertEqual(result['schema_version'],2)

    def test_out_of_band_cancel_preserves_original_pending_operation(self):
        with patch.dict(os.environ,{'KEEL_CANCEL_TEST':'t'*48}):
            session=RemoteSession({'endpoint':'http://127.0.0.1:8788','token_env':'KEEL_CANCEL_TEST','task_id':'task'})
        pending={'operation_id':'original','action':'mcp_call','run_id':'run','data':{}}
        session.pending=pending
        with session._lock, patch.object(session,'_send',return_value={'status':'cancel_requested'}) as send:
            session.cancel_pending_mcp()
        self.assertIs(session.pending,pending)
        self.assertEqual(send.call_args.args[0]['data']['target_operation_id'],'original')


if __name__=='__main__':unittest.main()
