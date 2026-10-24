"""Bounded, non-mutating host/container repository connectivity diagnostics."""
import json
from pathlib import Path
import subprocess
import sys
import uuid
import tempfile
import re
import os
import time


def transient_apt_download(log):
    """Retry only fetch errors with transient transport evidence, not all exit 100s."""
    lines = log.lower().splitlines()
    fatal = [line for line in lines if re.search(r'(?:^|\s)e: ', line)]
    transport = ('502', '503', '504', 'connection timed out', 'unable to connect',
                 'could not connect', 'temporary failure resolving', 'connection reset')
    if any(marker in log.lower() for marker in ('no_pubkey', 'badsig', 'expkeysig', 'invalid signature')):
        return False
    fetches = [line for line in fatal if 'failed to fetch ' in line]
    if not fetches or any(not any(item in line for item in transport) for line in fetches):
        return False
    failed_repositories = set()
    for line in fetches:
        match = re.search(r'failed to fetch (https?://\S+)/dists/([^/\s]+)/inrelease(?:\s|$)', line)
        if match:
            failed_repositories.add((match[1].rstrip('/'), match[2]))
    for line in fatal:
        if 'failed to fetch ' in line or 'unable to fetch some archives' in line:
            continue
        match = re.search(r"the repository '(https?://\S+) ([^\s']+) inrelease' is not signed\.", line)
        if match and (match[1].rstrip('/'), match[2]) in failed_repositories:
            continue
        return False
    return True


def bounded_apt_attempts(execute, output, *, attempts, deadline, save=lambda rows: None):
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError('APT attempts must be 1..3')
    rows = []
    for index in range(1, attempts+1):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            break
        log = Path(output)/f'apt-build-attempt-{index}.log'
        process = execute(log, remaining)
        content = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
        partial_index = 'Some index files failed to download' in content
        success = process.returncode == 0 and not partial_index
        retryable = process.returncode != 0 and transient_apt_download(content)
        rows.append({'attempt': index, 'returncode': process.returncode, 'log': log.name,
                     'passed': success, 'retryable_download_failure': retryable,
                     'partial_index_failure': partial_index})
        save(rows)
        if success or not retryable or index == attempts:
            break
        wait = min(2**index, max(0, deadline-time.monotonic()))
        print(f'[APT recovery] transient download failure; retry {index+1}/{attempts} after {wait:.0f}s', flush=True)
        time.sleep(wait)
    return rows


def diagnostic_excerpt(stderr):
    """Bounded diagnostics with URL credentials and known secret values removed."""
    value = stderr[-6000:]
    for name, secret in os.environ.items():
        if len(secret) >= 8 and any(word in name.upper() for word in ('TOKEN', 'PASSWORD', 'SECRET', 'API_KEY', 'PROXY')):
            value = value.replace(secret, '[REDACTED]')
    value = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', value)
    value = re.sub(r'(?i)(authorization\s*[:=]\s*)([^\r\n]+)', r'\1[REDACTED]', value)
    return value[-3000:]


PROBE = r'''
import json,socket,sys,urllib.request,urllib.error
from urllib.parse import urlsplit
url=sys.argv[1]
cap=int(sys.argv[2]) if len(sys.argv)>2 else 128
full=len(sys.argv)>3 and sys.argv[3]=='full'
result={'url':url,'interpreter':sys.executable}
try:
 result['addresses']=sorted({a[4][0] for a in socket.getaddrinfo(urlsplit(url).hostname,None)})
except Exception as e:
 result['dns_error_type']=type(e).__name__
try:
 with urllib.request.urlopen(url,timeout=10) as response:
  result['http_status']=response.status
  count=0
  while count<=cap:
   chunk=response.read(min(65536,cap+1-count))
   if not chunk: break
   count+=len(chunk)
  result['sample_bytes']=count
  result['download_complete']=full and count<=cap
  result['byte_limit_reached']=count>cap
  if full and response.headers.get('Content-Length'):
   result['expected_bytes']=int(response.headers['Content-Length'])
   result['download_complete']=result['download_complete'] and count==result['expected_bytes']
 result['reachable']=True
except urllib.error.HTTPError as e:
 result.update(reachable=False,http_status=e.code,error_type=type(e).__name__)
except Exception as e:
 result.update(reachable=False,error_type=type(e).__name__)
print('KEEL_NETWORK_RESULT='+json.dumps(result))
'''


def run_probe(command, *, timeout=20):
    from examples.swebench_bridge import run_harness
    try:
        with tempfile.TemporaryDirectory(prefix='keel-probe-process-') as directory:
            root=Path(directory);log=root/'probe.log'
            # Same bounded process containment as APT workloads. Raw proxy/tool
            # output stays off the console; reports retain only redacted snippets.
            process=run_harness(command,cwd=root,log_path=log,timeout=timeout,echo_output=False)
            with log.open('rb') as stream:raw=stream.read(4_000_001)
            if len(raw)>4_000_000:return {'status':'probe_output_limit'}
            text=raw.decode('utf-8',errors='replace')
            if process.returncode:
                lower=text.lower()
                category=('permission_boundary' if 'permission denied' in lower or 'access is denied' in lower
                          else 'image_unavailable' if 'no such image' in lower else 'process_error')
                result={'status':category,'returncode':process.returncode}
                if category=='process_error':result['diagnostic']=diagnostic_excerpt(text)
                return result
            marker='KEEL_NETWORK_RESULT='
            lines=[line.split(marker,1)[1] for line in text.splitlines() if marker in line]
            value=json.loads(lines[-1] if lines else text)
            return {'status':'completed','observation':value}
    except subprocess.TimeoutExpired:
        return {'status':'timeout'}
    except (OSError,ValueError) as error:
        return {'status':'probe_error','error_type':type(error).__name__}


APT_PROBE = r'''
import hashlib,json,os,signal,subprocess,sys,tempfile,resource,re
url,cap=sys.argv[1],int(sys.argv[2])
result={'url':url,'method':'apt-helper download-file','max_bytes':cap,'download_complete':False}
with tempfile.TemporaryDirectory(prefix='keel-apt-') as directory:
 destination=os.path.join(directory,'package.deb')
 def limits(): resource.setrlimit(resource.RLIMIT_FSIZE,(cap,cap))
 try:
  process=subprocess.Popen(['/usr/lib/apt/apt-helper','download-file',url,destination],
   stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,preexec_fn=limits)
  try:
   stdout,stderr=process.communicate(timeout=30)
   result['returncode']=process.returncode
   if process.returncode:
    result['failure_kind']='apt_download_failed'
    detail=(stdout+stderr).decode('utf-8',errors='replace').lower()
    for kind,markers in [('tls',('certificate','tls handshake')),('dns',('could not resolve','temporary failure resolving')),
                         ('connection',('unable to connect','could not connect','connection refused')),
                         ('timeout',('timed out','timeout'))]:
     if any(marker in detail for marker in markers):
      result['failure_hint']=kind
      break
    status=re.search(r'\b(4\d\d|5\d\d)\s+(?:bad|not|forbidden|service|gateway)',detail)
    if status:result['http_status']=int(status[1])
   if os.path.isfile(destination):
    result['downloaded_bytes']=os.path.getsize(destination)
    result['download_complete']=process.returncode==0 and 0<result['downloaded_bytes']<=cap
    if result['download_complete']:
     with open(destination,'rb') as stream: result['sha256']=hashlib.sha256(stream.read(cap)).hexdigest()
  except subprocess.TimeoutExpired:
   os.killpg(process.pid,signal.SIGKILL)
   process.communicate()
   result['failure_kind']='apt_timeout'
 except OSError as error:
  result.update(failure_kind='apt_unavailable',error_type=type(error).__name__)
print('KEEL_NETWORK_RESULT='+json.dumps(result))
'''


def diagnose(url, image, *, progress=lambda stage: None, download=False, build=False, max_bytes=8388608, apt_build=False):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTP(S) URL without credentials, query or fragment')
    if not image or image.startswith('-'):
        raise ValueError('A local diagnostic image is required')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 16777216:
        raise ValueError('Download cap must be 1..16777216 bytes')
    probe_args = [url, str(max_bytes if download else 128), 'full' if download else 'sample']
    progress('host')
    host = run_probe([sys.executable, '-c', PROBE, *probe_args], timeout=45)
    progress('container')
    name = 'keel-network-'+uuid.uuid4().hex
    try:
        container = run_probe(['docker', 'run', '--rm', '--pull=never', '--name', name,
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--entrypoint', 'python', image, '-c', PROBE, *probe_args], timeout=45)
    finally:
        # Killing docker CLI on timeout does not necessarily stop its container.
        try:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    result = {'status': 'observed', 'url': url, 'image': image, 'host': host,
        'container': container, 'model_calls': 0,
        'download_requested': download, 'max_bytes': max_bytes if download else 128,
        'scope': 'Bounded URL probes, not apt or reference recovery validation. No network settings changed.'}
    if build:
        progress('build')
        result['build'] = build_probe(image, probe_args)
    if apt_build:
        progress('apt-build')
        result['apt_build'] = build_probe(image, [url, str(max_bytes)], program=APT_PROBE)
    return result



def build_probe(image, probe_args, *, program=PROBE):
    """Probe an exact local base in a disposable build, without changing harness images."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]*', image) or image.startswith('sha256:'):
        raise ValueError('Use a local image name/tag, not a bare image ID')
    try:
        inspected = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
            capture_output=True, text=True, timeout=10)
        if inspected.returncode:
            return {'status': 'local_image_inspection_failed', 'returncode': inspected.returncode}
        base = inspected.stdout.strip()
        if not base.startswith('sha256:') or len(base) != 71 or any(c not in '0123456789abcdef' for c in base[7:]):
            return {'status': 'invalid_local_image_identity'}
        tag = 'keel-network-probe:'+uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix='keel-network-') as directory:
            root = Path(directory)
            (root/'probe.py').write_text(program, encoding='utf-8')
            command = json.dumps(['python', '/keel-probe.py', *probe_args])
            (root/'Dockerfile').write_text('FROM '+image+'\nCOPY probe.py /keel-probe.py\nRUN '+command+'\n', encoding='utf-8')
            try:
                result = run_probe(['docker', 'build', '--pull=false', '--no-cache', '--progress=plain',
                    '-t', tag, str(root)], timeout=55)
                after = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                    capture_output=True, text=True, timeout=10)
                if after.returncode or after.stdout.strip() != base:
                    return {'status': 'base_identity_changed_or_unverified', 'base_image_id_before': base,
                            'build_result': result}
                result['base_image_id'] = base
                return result
            finally:
                try:
                    subprocess.run(['docker', 'image', 'rm', tag], capture_output=True, timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'status': 'build_probe_error', 'error_type': type(error).__name__}
