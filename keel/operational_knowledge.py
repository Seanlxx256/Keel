"""Reviewed operational advice; never executable recovery code or acceptance proof."""
import hashlib
import json
import platform
import re
import sqlite3
import time
from pathlib import Path

from .experience import ExperienceStore


DIMENSIONS={'stage','tool','error_type','platform'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_config(value):
    if value is None:
        return None
    if (not isinstance(value,dict) or set(value)-{'path','catalog_sha256'}
            or not isinstance(value.get('path'),str) or not Path(value['path']).is_absolute()):
        raise ValueError('Operational knowledge requires an explicit absolute store path')
    if 'catalog_sha256' in value and (not isinstance(value['catalog_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['catalog_sha256'])):
        raise ValueError('Invalid knowledge catalog hash')
    return value


def validate_card(card):
    fields={'id','revision','scope','match','guidance','checks','evidence','compatibility'}
    if not isinstance(card,dict) or set(card)!=fields or card['scope']!='operational':
        raise ValueError('Expected an operational advice card, not a source patch')
    if not isinstance(card['id'],str) or not re.fullmatch('[a-z0-9][a-z0-9_.-]{0,79}',card['id']):
        raise ValueError('Invalid card id')
    if type(card['revision']) is not int or card['revision']<1:
        raise ValueError('Positive card revision required')
    match=card['match']
    if not isinstance(match,dict) or not 2<=len(match)<=4 or set(match)-DIMENSIONS:
        raise ValueError('At least two exact applicability dimensions required')
    for values in match.values():
        if (not isinstance(values,list) or not 1<=len(values)<=8
                or any(not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,80}',v) for v in values)):
            raise ValueError('Applicability values must be bounded exact tags')
    if not isinstance(card['guidance'],str) or not 1<=len(card['guidance'])<=800:
        raise ValueError('Bounded guidance required')
    if (not isinstance(card['checks'],list) or not 1<=len(card['checks'])<=4
            or any(not isinstance(v,str) or not 1<=len(v)<=200 for v in card['checks'])):
        raise ValueError('Bounded verification checks required')
    for name in ('evidence','compatibility'):
        refs=card[name]
        if not isinstance(refs,list) or not 1<=len(refs)<=8:
            raise ValueError('Evidence and implementation compatibility hashes required')
        for ref in refs:
            if (not isinstance(ref,dict) or set(ref)!={'path','sha256'}
                    or not isinstance(ref['path'],str) or len(ref['path'])>1024
                    or not Path(ref['path']).is_absolute()
                    or not isinstance(ref['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',ref['sha256'])):
                raise ValueError('Hash-bound absolute evidence references required')
    return card


def fresh(card,deadline=None):
    for ref in [*card['evidence'],*card['compatibility']]:
        if deadline is not None and time.monotonic()>=deadline:
            raise TimeoutError('Knowledge evidence check deadline')
        path=Path(ref['path'])
        if not path.is_file() or path.stat().st_size>1024*1024:
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:
            return False
    return True


class OperationalKnowledge(ExperienceStore):
    """Share SQLite/attempt recording with the existing narrow ExperienceStore."""
    def __init__(self,path):
        super().__init__(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operational_cards '
                       '(id TEXT,revision INTEGER,status TEXT,payload TEXT,sha256 TEXT,PRIMARY KEY(id,revision))')

    def register(self,card):
        validate_card(card)
        with self.connect() as db:
            latest=db.execute('SELECT max(revision) FROM operational_cards WHERE id=?',(card['id'],)).fetchone()[0]
            if latest is not None and card['revision']<=latest:
                raise ValueError('Preserve old cards; use a higher revision')
            db.execute('INSERT INTO operational_cards VALUES(?,?,?,?,?)',
                       (card['id'],card['revision'],'candidate',json.dumps(card,sort_keys=True),digest(card)))

    def import_episodes(self,source):
        """Explicit, idempotent migration of typed episodes; never import cards."""
        source=Path(source).resolve()
        if source==self.path.resolve() or not source.is_file():
            raise ValueError('A separate existing source store is required')
        db=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            rows=db.execute('SELECT task,signature,action,outcome,evidence FROM attempts '
                'WHERE action IN ("operational_retrieval","runtime_outcome") LIMIT 1001').fetchall()
        finally:
            db.close()
        if len(rows)>1000:
            raise ValueError('Episode migration exceeds bounded batch')
        prepared=[]
        for task,signature,action,outcome,payload in rows:
            if (any(not isinstance(v,str) or not 1<=len(v)<=160 for v in (task,signature,outcome))
                    or not isinstance(payload,str) or len(payload)>16000):
                raise ValueError('Invalid bounded episode envelope')
            evidence=json.loads(payload)
            if not isinstance(evidence,dict):raise ValueError('Typed episode evidence required')
            cards=evidence.get('cards')
            if (not isinstance(cards,list) or len(cards)>512 or any(
                    not isinstance(c,list) or len(c)!=2 or not isinstance(c[0],str)
                    or not re.fullmatch('[a-z0-9][a-z0-9_.-]{0,79}',c[0])
                    or type(c[1]) is not int or c[1]<1 for c in cards)):
                raise ValueError('Typed card identities required')
            clean={'cards':cards}
            if action=='operational_retrieval':
                features=evidence.get('features');catalog=evidence.get('catalog_sha256')
                if (not isinstance(features,dict) or set(features)!=DIMENSIONS
                        or any(not isinstance(values,list) or len(values)>16 or any(
                            not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,80}',v)
                            for v in values) for values in features.values())
                        or catalog is not None and (not isinstance(catalog,str) or not re.fullmatch('[a-f0-9]{64}',catalog))):
                    raise ValueError('Typed retrieval features required')
                clean.update(features=features,catalog_sha256=catalog)
            else:
                clean['scope']='Imported historical outcome; correlation only, not verified learning.'
            prepared.append((task,signature,action,outcome,clean))
        inventory=digest(prepared);imported=0
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operational_episode_imports '
                       '(episode_sha256 TEXT PRIMARY KEY,source_inventory_sha256 TEXT)')
            for row in prepared:
                identity=digest(row)
                if db.execute('INSERT OR IGNORE INTO operational_episode_imports VALUES(?,?)',
                              (identity,inventory)).rowcount:
                    db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',(*row[:4],json.dumps(row[4],sort_keys=True)))
                    imported+=1
        return {'imported':imported,'duplicates':len(prepared)-imported,
                'source_inventory_sha256':inventory,'cards_imported':0}

    def promote(self,identity,revision):
        with self.connect() as db:
            row=db.execute('SELECT payload,sha256,status FROM operational_cards WHERE id=? AND revision=?',
                           (identity,revision)).fetchone()
            if not row or row[2]!='candidate':
                raise ValueError('Only a reviewed candidate can be promoted')
            card=validate_card(json.loads(row[0]))
            if digest(card)!=row[1] or not fresh(card):
                raise ValueError('Card evidence or implementation changed')
            db.execute('UPDATE operational_cards SET status="verified" WHERE id=? AND revision=?',(identity,revision))

    def deprecate(self,identity,revision):
        with self.connect() as db:
            changed=db.execute('UPDATE operational_cards SET status="deprecated" WHERE id=? AND revision=?',
                               (identity,revision)).rowcount
            if not changed:
                raise ValueError('Unknown card revision')

    def latest(self):
        with self.connect() as db:
            rows=db.execute('SELECT a.id,a.revision,a.status,a.payload,a.sha256 FROM operational_cards a '
                'WHERE a.revision=(SELECT max(b.revision) FROM operational_cards b WHERE b.id=a.id) '
                'ORDER BY a.id LIMIT 513').fetchall()
        if len(rows)>512:
            raise ValueError('Knowledge catalog exceeds bounded first-version inventory')
        return rows

    def catalog_hash(self):
        return digest([(identity,revision,status,sha) for identity,revision,status,_,sha in self.latest()])

    def retrieve(self,features,*,limit=3,max_bytes=4000):
        if type(limit) is not int or not 1<=limit<=3 or type(max_bytes) is not int or not 256<=max_bytes<=8000:
            raise ValueError('Bounded knowledge retrieval required')
        matches=[];excluded=[];deadline=time.monotonic()+2
        for identity,revision,status,payload,sha in self.latest():
            if time.monotonic()>=deadline:
                raise TimeoutError('Knowledge retrieval deadline')
            if status!='verified':
                continue
            card=validate_card(json.loads(payload))
            if digest(card)!=sha:
                raise ValueError('Knowledge card content hash mismatch')
            if not all(set(values)&set(features.get(key,[])) for key,values in card['match'].items()):
                continue
            matches.append((len(card['match']),identity,revision,sha,card))
        selected=[]
        for number,(_,identity,revision,sha,card) in enumerate(sorted(matches,key=lambda row:(-row[0],row[1]))):
            if len(selected)>=limit or number>=16:
                excluded.append({'id':identity,'reason':'retrieval_limit'})
                break
            if not fresh(card,deadline):
                excluded.append({'id':identity,'reason':'evidence_or_implementation_changed'})
                continue
            view={k:card[k] for k in ('id','revision','scope','match','guidance','checks')}
            view.update(sha256=sha,evidence_sha256=[ref['sha256'] for ref in card['evidence']])
            if len(selected)>=limit or len(json.dumps([*selected,view]).encode())>max_bytes:
                excluded.append({'id':identity,'reason':'request_capacity'})
            else:
                selected.append(view)
        return {'cards':selected,'excluded':excluded[:8]}


def failure_features(stage,tool,observation):
    strings=[];names=set()
    def visit(value):
        if isinstance(value,BaseException):
            names.add(type(value).__name__)
            strings.append(type(value).__name__+': '+str(value))
        elif isinstance(value,str):
            strings.append(value[:32000])
        elif isinstance(value,dict):
            error_type=value.get('error_type')
            if isinstance(error_type,str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,79}',error_type):
                names.add(error_type)
            for v in value.values(): visit(v)
        elif isinstance(value,(list,tuple)):
            for v in value[:16]: visit(v)
    visit(observation)
    for text in strings:
        names.update(re.findall(r'\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))(?=:)',text))
    return {'stage':[stage],'tool':[tool],'platform':[platform.system()],'error_type':sorted(names)[:16]}


class RuntimeKnowledge:
    def __init__(self,config,run_id):
        validate_config(config)
        self.run_id=run_id;self.lookups=0;self.matches=set();self.errors=[];self.seen=set();self.store=None
        try:
            self.store=OperationalKnowledge(config['path'])
            self.catalog=self.store.catalog_hash()
            if config.get('catalog_sha256',self.catalog)!=self.catalog:
                raise ValueError('Knowledge catalog differs from configured snapshot')
        except Exception as error:
            # Knowledge is optional support, not the required result/checkpoint.
            self.store=None;self.catalog=None;self.errors.append(type(error).__name__)

    def context(self,workspace,stage,tool,observation):
        features=failure_features(stage,tool,observation);self.lookups+=1
        result={'status':'available','query':features,'cards':[],
                'catalog_sha256':self.catalog,'scope':'Historical operational advice, not current facts. '
                'Check applicability and fresh observations. Never grants tools, writes, budgets, or acceptance.'}
        try:
            if self.store is None or self.store.catalog_hash()!=self.catalog:
                raise ValueError('Knowledge unavailable or changed during run')
            result.update(self.store.retrieve(features))
        except Exception as error:
            result.update(status='unavailable',error_type=type(error).__name__)
            self.errors.append(type(error).__name__)
        ids=[(r['id'],r['revision']) for r in result['cards']];self.matches.update(ids)
        # Persist only typed features and identities, never logs, source, or model prose.
        signature=digest(features)
        if self.store and signature not in self.seen:
            try:
                self.store.record(self.run_id,signature,'operational_retrieval','observed',
                                  {'features':features,'cards':ids,'catalog_sha256':self.catalog})
                self.seen.add(signature)
            except Exception as error:
                self.errors.append(type(error).__name__)
                result['experience_write_error']=type(error).__name__
        # Required local ledger/trace failures deliberately propagate.
        fact=workspace.ledger.add('decision','runtime','Operational knowledge retrieval',result)
        workspace.trace.emit('runtime','operational_knowledge_retrieved',fact_id=fact,stage=stage,
                             card_ids=[r[0] for r in ids],status=result['status'])
        return result

    def finish(self,status):
        if self.store:
            try:
                self.store.record(self.run_id,self.catalog,'runtime_outcome',status,
                                  {'cards':sorted(self.matches),'scope':'Correlation only; no automatic card promotion.'})
            except Exception as error:
                self.errors.append(type(error).__name__)

    def report(self):
        return {'enabled':True,'catalog_sha256':self.catalog,'lookups':self.lookups,
                'matched_cards':[{'id':i,'revision':r} for i,r in sorted(self.matches)],
                'storage_errors':self.errors[-8:],'scope':'Reviewed advice retrieval and observed episodes, not automatic verified learning.'}


def attach(workspace,config,run_id):
    validate_config(config)
    if config is not None:
        if Path(config['path']).resolve().is_relative_to(workspace.root.resolve()):
            raise ValueError('Operational knowledge store must be outside the candidate workspace')
        workspace.operational_knowledge=RuntimeKnowledge(config,run_id)


def context(workspace,stage,tool,observation):
    memory=getattr(workspace,'operational_knowledge',None)
    return memory.context(workspace,stage,tool,observation) if memory else None
