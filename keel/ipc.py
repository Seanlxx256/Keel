"""Probe Windows named-pipe capability in the interpreter that needs it."""
import json
import math
from pathlib import Path
import subprocess
import sys
import uuid


def probe_named_pipe(interpreter, timeout=10):
    if sys.platform != 'win32':
        return {'status': 'not_required', 'transport': 'windows_named_pipe'}
    return _run_probe(interpreter,'--check',timeout)


def probe_async_stdio(interpreter,timeout=8):
    """Exercise only a known short Python child, never a configured MCP server."""
    return _run_probe(interpreter,'--async-check',timeout)


def probe_sync_stdio(interpreter,timeout=8):
    """Control: ordinary subprocess pipes in the same selected interpreter."""
    return _run_probe(interpreter,'--sync-check',timeout)


def _run_probe(interpreter,mode,timeout):
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
        raise ValueError('IPC probe timeout must be positive and at most 30 seconds')
    try:
        result = subprocess.run([str(interpreter), '-I', str(Path(__file__).resolve()), mode],
            capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        data = json.loads(result.stdout)
        if not isinstance(data,dict) or data.get('status') not in {'ok','unavailable'} or result.returncode!=0:
            raise ValueError('Invalid IPC probe response or failed launcher')
        data['interpreter'] = str(Path(interpreter).resolve())
        return data
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {'status': 'unavailable', 'transport': {'--async-check':'async_stdio','--sync-check':'sync_stdio'}.get(mode,'windows_named_pipe'),
                'error_type': type(error).__name__, 'interpreter': str(interpreter)}


def _endpoint(role, address):
    import threading
    import os
    from multiprocessing.connection import Client, Listener
    # A broken IPC implementation must not leave an orphaned diagnostic server.
    timer = threading.Timer(5, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        if role == '--server':
            with Listener(address, family='AF_PIPE') as listener, listener.accept() as connection:
                connection.send_bytes(b'keel-probe')
        else:
            import time
            until = time.monotonic()+3
            while True:
                try:
                    connection = Client(address, family='AF_PIPE')
                    break
                except FileNotFoundError:
                    if time.monotonic() >= until:
                        raise
                    time.sleep(.05)
            with connection:
                if connection.recv_bytes() != b'keel-probe':
                    raise ValueError('Unexpected probe payload')
        return {'role': role, 'status': 'ok'}
    except Exception as error:
        return {'role': role, 'status': 'failed', 'error_type': type(error).__name__,
                'winerror': getattr(error, 'winerror', None)}
    finally:
        timer.cancel()


def _check():
    address = r'\\.\pipe\keel-probe-'+uuid.uuid4().hex
    processes = []
    try:
        for role in ['--server', '--client']:
            processes.append(subprocess.Popen([sys.executable, __file__, role, address],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                creationflags=0x08000000 if sys.platform == 'win32' else 0))
        endpoints = []
        for process in processes:
            stdout, _ = process.communicate(timeout=7)
            endpoints.append(json.loads(stdout))
        return {'status': 'ok' if all(e['status'] == 'ok' for e in endpoints) else 'unavailable',
                'transport': 'windows_named_pipe', 'endpoints': endpoints,
                'permission_boundary': any(e.get('winerror') == 5 for e in endpoints)}
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()


def _sync_check():
    try:
        child=subprocess.run([sys.executable,'-I','-c',"import sys;sys.stdout.write('keel-sync-probe')"],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3)
        matched=child.returncode==0 and child.stdout==b'keel-sync-probe' and not child.stderr
        return {'status':'ok' if matched else 'unavailable','transport':'sync_stdio',
                'child_returncode':child.returncode,'protocol_matched':matched}
    except (OSError,subprocess.TimeoutExpired) as error:
        return {'status':'unavailable','transport':'sync_stdio','error_type':type(error).__name__,
                'errno':getattr(error,'errno',None),'winerror':getattr(error,'winerror',None)}


def _async_check():
    import asyncio
    async def check():
        child=None
        try:
            child=await asyncio.wait_for(asyncio.create_subprocess_exec(sys.executable,'-I','-c',
                "import sys;sys.stdout.write('keel-async-probe')",stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE),3)
            stdout,stderr=await asyncio.wait_for(child.communicate(),3)
            ok=child.returncode==0 and stdout==b'keel-async-probe' and not stderr
            return {'status':'ok' if ok else 'unavailable','transport':'async_stdio',
                    'child_returncode':child.returncode,'protocol_matched':ok,'mcp_tool_calls':0}
        except Exception as error:
            return {'status':'unavailable','transport':'async_stdio','error_type':type(error).__name__,
                    'errno':getattr(error,'errno',None),'winerror':getattr(error,'winerror',None),'mcp_tool_calls':0}
        finally:
            if child is not None and child.returncode is None:
                child.kill()
                await asyncio.wait_for(child.wait(),2)
    return asyncio.run(check())


if __name__ == '__main__':
    print(json.dumps(_sync_check() if sys.argv[1]=='--sync-check' else _async_check() if sys.argv[1]=='--async-check' else _check() if sys.argv[1]=='--check' else _endpoint(*sys.argv[1:3])))
