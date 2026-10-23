"""Diagnose urllib TLS/proxy setup without credentials or model generation."""
import argparse
import json
import os
from pathlib import Path
import ssl
import sys
import traceback
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def inspect(offline=False):
    result={'model_calls':0,'credential_sent':False,'python':sys.executable,
            'openssl':ssl.OPENSSL_VERSION,'scope':'Unauthenticated GET only; not credential or model completion validation'}
    result['environment']={}
    for name in ('SSL_CERT_FILE','SSL_CERT_DIR','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE'):
        value=os.getenv(name)
        result['environment'][name]={'configured':bool(value),'path_exists':Path(value).exists() if value else None}
    result['proxy_schemes']=sorted(urllib.request.getproxies())
    paths=ssl.get_default_verify_paths()
    result['default_ca']={key:bool(getattr(paths,key)) for key in ('cafile','capath')}
    try:
        ssl.create_default_context()
        result['ssl_context']='created'
    except Exception as error:
        result['ssl_context']=type(error).__name__
    if offline:
        result['status']='offline_inspection_only'
        return result
    try:
        req=urllib.request.Request('https://api.openai.com/v1/models',method='GET')
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
            result.update(status='http_response',http_status=response.status)
    except urllib.error.HTTPError as error:
        result.update(status='http_response',http_status=error.code)
        error.close()
    except Exception as error:
        reason=error.reason if isinstance(error,urllib.error.URLError) else error
        result.update(status='transport_error',error_type=type(error).__name__,reason_type=type(reason).__name__)
        if isinstance(reason,OSError):
            result['errno']=reason.errno
            result['winerror']=getattr(reason,'winerror',None)
            # Never publish arbitrary exception strings, URLs, proxy credentials or filenames.
            result['filename_present']=bool(reason.filename)
        result['frames']=[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name}
                          for frame in traceback.extract_tb(getattr(reason,'__traceback__',None) or error.__traceback__)]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    result=inspect(args.offline)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
