import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from keel.async_process_lifecycle import run_request


class AsyncLifecycleTests(unittest.TestCase):
    def test_owned_transports_close_before_request_loop_on_success_and_failure(self):
        for fail in (False,True):
            with self.subTest(fail=fail):
                transport=Mock()
                loops=[]
                def close():
                    loop=asyncio.get_running_loop()
                    self.assertFalse(loop.is_closed())
                transport.close.side_effect=close
                async def operation():
                    loop=asyncio.get_running_loop()
                    loops.append(loop)
                    await loop.subprocess_exec(lambda:None,'fixture-not-executed')
                    if fail:
                        raise ValueError('request failed')
                    return 'result'
                with patch.object(asyncio.BaseEventLoop,'subprocess_exec',new=AsyncMock(return_value=(transport,object()))):
                    if fail:
                        with self.assertRaisesRegex(ValueError,'request failed'):
                            run_request(operation)
                    else:
                        self.assertEqual(run_request(operation),'result')
                transport.close.assert_called_once()
                self.assertTrue(loops[0].is_closed())

    def test_timeout_also_closes_owned_transport(self):
        transport=Mock()
        async def operation():
            await asyncio.get_running_loop().subprocess_exec(lambda:None,'fixture-not-executed')
            await asyncio.sleep(10)
        with patch.object(asyncio.BaseEventLoop,'subprocess_exec',new=AsyncMock(return_value=(transport,object()))):
            with self.assertRaises(TimeoutError):
                run_request(lambda:asyncio.wait_for(operation(),0.01))
        transport.close.assert_called_once()
