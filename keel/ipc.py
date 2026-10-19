"""Probe Windows named-pipe capability in the interpreter that needs it."""
import json
from pathlib import Path
import subprocess
import sys
import uuid


def probe_named_pipe(interpreter, timeout=10):
    if sys.platform != 'win32':
        return {'status': 'not_required', 'transport': 'windows_named_pipe'}
    try:
        result = subprocess.run([str(interpreter), str(Path(__file__).resolve()), '--check'],
            capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        data = json.loads(result.stdout)
        data['interpreter'] = str(Path(interpreter).resolve())
        return data
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {'status': 'unavailable', 'transport': 'windows_named_pipe',
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


if __name__ == '__main__':
    print(json.dumps(_check() if sys.argv[1] == '--check' else _endpoint(*sys.argv[1:3])))
