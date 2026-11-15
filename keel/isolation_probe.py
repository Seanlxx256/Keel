"""Standard-library fixture copied into a disposable Docker workspace.

Never run this probe against a real repository or on the host: it deliberately
attempts writes to disposable files. No actual secrets or destructive signals.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import time


def cannot_write(path):
    try:
        Path(path).write_text('UNEXPECTED_WRITE',encoding='utf-8')
    except OSError:
        return True
    return False


def cannot_connect(host,port):
    try:
        with socket.create_connection((host,port),timeout=.3):pass
    except OSError:return True
    return False


def peer_not_addressable(pid,namespace):
    try:os.kill(pid,0)
    except (ProcessLookupError,PermissionError):return True
    try:
        # Equal numeric PIDs can name unrelated processes in different PID
        # namespaces. Never mistake that collision for access to the peer.
        return os.readlink('/proc/'+str(pid)+'/ns/pid')!=namespace
    except OSError:return False  # Accessible PID, identity unknown: not a pass.


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role',choices=['a','b'],required=True)
    parser.add_argument('--secret-name',required=True)
    parser.add_argument('--foreign-path',required=True)
    parser.add_argument('--controller-port',type=int,required=True)
    parser.add_argument('--peer-pid',type=int,default=0)
    parser.add_argument('--peer-namespace')
    parser.add_argument('--hold-seconds',type=float,default=90)
    parser.add_argument('--report',default='/keel-reports/probe.json')
    args=parser.parse_args()
    status={}
    for line in Path('/proc/self/status').read_text().splitlines():
        if ':' in line:
            key,value=line.split(':',1);status[key]=value.strip()
    foreign='b_only.txt' if args.role=='a' else 'a_only.txt'
    checks={
        'workspace_read_allowed':Path('/workspace/app.py').read_text(encoding='utf-8').startswith('VERSION = '),
        'non_root':os.getuid()!=0,
        'no_effective_capabilities':int(status.get('CapEff','1'),16)==0,
        'no_new_privileges':status.get('NoNewPrivs')=='1',
        'workspace_readonly':cannot_write('/workspace/app.py'),
        'root_readonly':cannot_write('/etc/keel-isolation-fixture-'+args.role),
        'only_loopback_interface':sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo'],
        'external_connect_denied':cannot_connect('192.0.2.1',443),
        'controller_loopback_unreachable':cannot_connect('127.0.0.1',args.controller_port),
        'host_secret_not_in_environment':args.secret_name not in os.environ,
        'control_path_unavailable':not Path(args.foreign_path).exists(),
        'other_workspace_not_mounted':not Path('/workspace',foreign).exists(),
        'docker_socket_not_mounted':not Path('/var/run/docker.sock').exists(),
    }
    if args.peer_pid:
        # Signal 0 tests PID visibility/permission without killing anything.
        checks['peer_process_not_addressable']=peer_not_addressable(args.peer_pid,args.peer_namespace)
    Path('/tmp/fixture-write').write_text('allowed temporary write')
    checks['temporary_write_allowed']=True
    result={'role':args.role,'pid':os.getpid(),
            'pid_namespace':os.readlink('/proc/self/ns/pid'),
            'net_namespace':os.readlink('/proc/self/ns/net'),
            'checks':checks,'scope':'Finite fixture checks, not proof against all container escapes.'}
    checks['reports_write_allowed']=True  # Receipt existence establishes completion of the write.
    path=Path(args.report);temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(result),encoding='utf-8');os.replace(temporary,path)
    print(json.dumps(result),flush=True)
    if not all(checks.values()):return 1
    time.sleep(args.hold_seconds)
    return 0


if __name__=='__main__':raise SystemExit(main())
