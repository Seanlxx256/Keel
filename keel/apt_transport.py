"""Registered isolated APT settings shared by diagnostics and official grading."""


def transport_prefix(policy):
    if policy=='original':return ''
    configs={
        'no_pipeline':['Acquire::http::Pipeline-Depth "0";'],
        'retry_acquire':['Acquire::Retries "2";','Acquire::http::Timeout "20";',
                         'Acquire::https::Timeout "20";','APT::Keep-Downloaded-Packages "true";'],
    }
    if policy not in configs:raise ValueError('Unsupported transport policy')
    return "printf '%s\\n' "+' '.join("'"+line+"'" for line in configs[policy])+\
           ' > /tmp/keel-apt-transport.conf\nexport APT_CONFIG=/tmp/keel-apt-transport.conf\n'


CACHE_PROBE = r'''
import json,os,sys
from pathlib import Path
root=Path('/var/cache/apt/archives')
files=sorted(root.glob('*.deb'))
rows=[]
for path in files[:2000]:
 try:
  if path.is_file() and not path.is_symlink(): rows.append({'name':path.name,'bytes':path.stat().st_size})
 except OSError: pass
partial=0
for path in (root/'partial').glob('*'):
 try:
  if path.is_file() and not path.is_symlink(): partial+=path.stat().st_size
 except OSError: pass
print('KEEL_APT_CACHE='+json.dumps({'phase':sys.argv[1],'files':rows,'listed_bytes':sum(x['bytes'] for x in rows),
 'omitted_files':max(0,len(files)-len(rows)),'partial_bytes':partial,
 'scope':'Archive presence/size only, not a cache-hit or integrity certificate; APT retains its checks'}),flush=True)
'''
