"""Optional tracked-text retrieval for code, documentation and configuration."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from .lexical import tokens

POLICY = dict(name='tracked_text_fts_v1', extensions=['.py','.md','.rst','.toml','.ini','.cfg','.yaml','.yml','.json'],
    chunk_lines=32, max_file_bytes=1_000_000, query_terms=128, candidates=100,
    tokenizer='compass.lexical.tokens', ranking='SQLite FTS5 bm25, then path/start',
    scope='Regular Git-tracked files only; no symlinks/submodules; UTF-8; no generation or embeddings')


def inventory(root):
    root=Path(root).resolve(strict=True)
    process=subprocess.run(['git','-c','safe.directory='+root.as_posix(),'ls-files','--stage','-z'],
        cwd=root,capture_output=True,timeout=30)
    if process.returncode:
        raise ValueError('Cannot list Git-tracked source files (exit '+str(process.returncode)+'); check repository access')
    listing=process.stdout
    files=[];omitted=[]
    for raw in listing.split(b'\0'):
        if not raw:continue
        attrs,name=raw.split(b'\t',1);mode,oid,stage=attrs.decode('ascii').split()
        name=name.decode('utf-8');relative=Path(name)
        if stage!='0':raise ValueError('Unmerged tracked entry')
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe tracked path')
        if relative.suffix not in POLICY['extensions']:continue
        path=root/name
        if mode not in ('100644','100755'):
            omitted.append(dict(path=name,reason='nonregular_git_entry',blob=oid));continue
        if any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1,len(relative.parts)+1)) or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Source symlink or escape: '+name)
        if path.stat().st_size>POLICY['max_file_bytes']:
            omitted.append(dict(path=name,reason='file_size_limit',blob=oid));continue
        files.append((name,path))
    return files,omitted


def chunks(text):
    lines=text.splitlines()
    for start in range(0,len(lines),POLICY['chunk_lines']):
        yield start+1,min(start+POLICY['chunk_lines'],len(lines)),'\n'.join(lines[start:start+POLICY['chunk_lines']])


class TextCorpus:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,sha256 TEXT,status TEXT);
          CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path UNINDEXED,start UNINDEXED,end UNINDEXED,
            kind UNINDEXED,text,tokenize="unicode61 tokenchars '_'");''')

    def close(self):self.db.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def build(self,root,*,timeout=300,progress=None):
        deadline=time.monotonic()+timeout;notify=progress or (lambda **kwargs:None)
        root=Path(root).resolve(strict=True);files,omitted=inventory(root)
        policy=json.dumps(POLICY,sort_keys=True)
        previous=dict(self.db.execute('SELECT key,value FROM metadata'))
        if previous and (previous.get('root')!=str(root) or previous.get('policy')!=policy):
            raise ValueError('Text checkpoint root/policy mismatch')
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO metadata VALUES (?,?)',
                [('root',str(root)),('policy',policy),('complete','false')])
        manifest={};reused=0
        for number,(name,path) in enumerate(files,1):
            if time.monotonic()>=deadline:raise TimeoutError('Text index deadline; per-file checkpoints retained')
            data=path.read_bytes();digest=hashlib.sha256(data).hexdigest();manifest[name]=digest
            old=self.db.execute('SELECT sha256,status FROM files WHERE path=?',(name,)).fetchone()
            if old and old['sha256']==digest:
                reused+=1
                if old['status']!='indexed':omitted.append(dict(path=name,reason=old['status']))
            else:
                try:text=data.decode('utf-8');status='indexed'
                except UnicodeError:text='';status='non_utf8'
                with self.db:
                    if old:self.db.execute('DELETE FROM chunks WHERE path=?',(name,))
                    if status=='indexed':
                        self.db.executemany('INSERT INTO chunks(path,start,end,kind,text) VALUES (?,?,?,?,?)',
                            [(name,a,b,'python' if path.suffix=='.py' else 'text',
                              ' '.join(tokens(name+'\n'+body))) for a,b,body in chunks(text)])
                    self.db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?)',(name,digest,status))
                if status!='indexed':omitted.append(dict(path=name,reason=status))
            if number==len(files) or number%50==0:notify(files=number,total=len(files),reused=reused)
        removed=set(r[0] for r in self.db.execute('SELECT path FROM files'))-manifest.keys()
        if any(hashlib.sha256(path.read_bytes()).hexdigest()!=manifest[name] for name,path in files):
            raise ValueError('Source changed during text indexing')
        with self.db:
            for name in removed:
                self.db.execute('DELETE FROM chunks WHERE path=?',(name,));self.db.execute('DELETE FROM files WHERE path=?',(name,))
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('complete','true')")
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('manifest',?)",
                (hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),))
        return dict(files=len(files),chunks=self.db.execute('SELECT count(*) FROM chunks').fetchone()[0],
            reused_files=reused,removed_files=len(removed),omitted=omitted,
            source_manifest_sha256=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest())

    def indexed_paths(self):
        return {r[0] for r in self.db.execute("SELECT path FROM files WHERE status='indexed'")}

    def require_fresh(self):
        complete=self.db.execute("SELECT value FROM metadata WHERE key='complete'").fetchone()
        if not complete or complete[0]!='true':raise ValueError('Text index is incomplete')
        meta=dict(self.db.execute('SELECT key,value FROM metadata'))
        files,_=inventory(Path(meta['root']))
        current={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files}
        if hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()!=meta['manifest']:
            raise ValueError('Text index is stale; rebuild using per-file checkpoints')
        return meta['manifest']

    def search(self,query,kind=None):
        self.require_fresh()
        if kind not in (None,'python','text'):raise ValueError('Unknown text corpus kind')
        wanted=list(dict.fromkeys(tokens(query)))[:POLICY['query_terms']]
        if not wanted:return []
        expression=' OR '.join('"'+term.replace('"','""')+'"' for term in wanted)
        sql='SELECT path,start,end,bm25(chunks) AS score FROM chunks WHERE chunks MATCH ?'
        params=[expression]
        if kind:sql+=' AND kind=?';params.append(kind)
        sql+=' ORDER BY score,path,CAST(start AS INTEGER) LIMIT ?';params.append(POLICY['candidates'])
        return [dict(path=r['path'],start_line=int(r['start']),end_line=int(r['end']),score=r['score'])
            for r in self.db.execute(sql,params)]
