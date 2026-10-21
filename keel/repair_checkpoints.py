"""Preserve verified repair candidates; never turn a partial improvement into a pass."""
import hashlib
import json


def verification_score(rows):
    if len(rows) != 1 or rows[0].get('timeout'):
        return None
    try:
        value = json.loads(rows[0].get('stdout', ''))
        if value.get('grading_status') != 'graded' or value.get('failure_kind') not in {'none','test_failure'}:
            return None
        identity = value['test_universe_sha256']
        if not isinstance(identity,str) or len(identity)!=64:
            return None
        counts=value['test_counts']
        if not {'FAIL_TO_PASS','PASS_TO_PASS'} <= counts.keys():
            return None
        for group in counts.values():
            if set(group) != {'success','failure'} or any(type(n) is not int or n<0 for n in group.values()):
                return None
        totals=tuple(sorted((k,sum(v.values())) for k,v in counts.items()))
        if not sum(n for _,n in totals):
            return None
        # Explicit conservative policy: preservation failures before target failures.
        rank=(counts['PASS_TO_PASS']['failure'],counts['FAIL_TO_PASS']['failure'])
        return (identity,totals),rank
    except (ValueError,KeyError,TypeError,AttributeError):
        return None


class RepairCheckpoints:
    def __init__(self, workspace, output):
        self.ws=workspace
        self.output=output/'repair-candidates'
        self.best=None
        self.records=[]

    def observe(self, verification, names, label):
        score=verification_score(verification)
        if score is None:
            return
        self.output.mkdir(exist_ok=True)
        directory=self.output/str(len(self.records));directory.mkdir()
        sources={}
        for index,name in enumerate(sorted(set(names))):
            path=self.ws.path(name,write=True)
            if not path.is_file():
                raise ValueError('Repair checkpoint requires an existing declared source')
            raw=path.read_bytes()
            blob=directory/f'{index}.source';blob.write_bytes(raw)
            sources[name]={'blob':str(blob),'sha256':hashlib.sha256(raw).hexdigest()}
        row={'label':label,'test_universe':score[0],'rank':score[1],
             'sources':sources,'verification':verification,
             'policy':'Minimize PASS_TO_PASS failures, then FAIL_TO_PASS failures; equal rank retains earlier candidate'}
        self.records.append(row)
        if self.best is None or (score[0]==self.best['test_universe'] and score[1]<self.best['rank']):
            self.best=row
        (directory/'candidate.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
        self.ws.trace.emit('verifier','repair_candidate_saved',label=label,rank=score[1],
                           selected=self.best is row)

    def restore_on_failure(self, originals):
        if self.best is None:
            return None
        planned=[]
        # Fully validate every checkpoint blob/path before the first write.
        for name,before in originals.items():
            path=self.ws.path(name,write=True)
            saved=self.best['sources'].get(name)
            raw=before
            if saved:
                from pathlib import Path
                raw=Path(saved['blob']).read_bytes()
                if hashlib.sha256(raw).hexdigest()!=saved['sha256']:
                    raise ValueError('Repair checkpoint source hash changed')
            if path.read_bytes()!=raw:
                planned.append((path,raw))
        for path,raw in planned:
            path.write_bytes(raw)
        return {'selected_label':self.best['label'],'rank':self.best['rank'],
                'restored_files':[p.relative_to(self.ws.root).as_posix() for p,_ in planned],
                'candidate_count':len(self.records),'verification':self.best['verification'],
                'scope':'Selected by preservation-first policy; historical evidence, not a fresh verification or runtime pass'}
