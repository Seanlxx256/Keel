"""Bounded package/build phase renewal from distinct observed milestones."""
import hashlib
import re


class AptProgressBudget:
    def __init__(self, hard_seconds, *, soft_seconds=600, extension_seconds=120, freshness_seconds=120,
                 phase_grace_seconds=240):
        if min(hard_seconds, soft_seconds, extension_seconds, freshness_seconds, phase_grace_seconds) <= 0:
            raise ValueError('Positive stage budgets required')
        self.hard = hard_seconds
        self.limit = min(soft_seconds, hard_seconds)
        self.extension = extension_seconds
        self.freshness = freshness_seconds
        self.seen = set()
        self.pending = ''
        self.last_progress = None
        self.granted_count = 0
        self.events = []
        self.reason = None
        self.phase = 'packages'
        self.phase_started = 0
        self.phase_grace = phase_grace_seconds
        self.export_step = None
        self.phase_transitions = []

    def _transition(self, phase, elapsed):
        ranks={'packages':0,'export':1,'unpack':2}
        if ranks[phase] <= ranks[self.phase]:
            return
        self.phase=phase
        self.phase_started=elapsed
        before=self.limit
        self.limit=min(self.hard,max(self.limit,elapsed+self.phase_grace))
        self.granted_count=len(self.seen)
        self.phase_transitions.append({'phase':phase,'elapsed':elapsed,
                                      'previous_limit':before,'new_limit':self.limit})

    def observe(self, text, elapsed):
        self.pending += text
        lines = self.pending.split('\n')
        self.pending = lines.pop()[-4096:]
        for line in lines:
            build=re.match(r'^#(\d+)\s+(.+)$',line.strip())
            if build:
                step,operation=build.groups()
                if operation=='exporting to image' and self.export_step is None:
                    self.export_step=step
                if step==self.export_step and re.match(
                        r'^(exporting (?:to image|layers|manifest|config|attestation)|naming to |unpacking to )',operation):
                    # BuildKit duration updates are not new milestones.
                    normalized=re.sub(r'\s+[\d.]+s(?:\s+done)?$',
                                      ' done' if operation.endswith(' done') else '',operation)
                    key=hashlib.sha256(('build:'+normalized).encode()).hexdigest()
                    if key not in self.seen and len(self.seen)<20000:
                        self.seen.add(key)
                        self.last_progress=elapsed
                    self._transition('unpack' if operation.startswith('unpacking to ') else 'export',elapsed)
                    continue
            # Strip BuildKit's timestamp; repeated package messages are not progress.
            line = re.sub(r'^#\d+\s+[\d.]+\s+', '', line).strip()
            if not re.match(r'^(Get:\d+\s+|Fetched \d|Unpacking \S|Setting up \S)', line):
                continue
            line = re.sub(r'^Get:\d+\s+', 'Get: ', line)
            line = re.sub(r'^(Fetched \S+\s+\S+).*$', r'\1', line)
            key = hashlib.sha256(line.encode()).hexdigest()
            if key not in self.seen and len(self.seen) < 20000:
                self.seen.add(key)
                self.last_progress = elapsed

    def remaining(self, elapsed):
        if elapsed >= self.hard:
            self.reason = 'hard_stage_deadline'
            return 0
        if elapsed >= self.limit:
            fresh = self.last_progress is not None and elapsed-self.last_progress <= self.freshness
            if fresh and len(self.seen) > self.granted_count:
                before = self.limit
                self.limit = min(self.hard, elapsed+self.extension)
                self.granted_count = len(self.seen)
                self.events.append({'elapsed': elapsed, 'previous_limit': before,
                                    'new_limit': self.limit, 'distinct_milestones': len(self.seen)})
            else:
                self.reason = 'no_fresh_distinct_progress'
                return 0
        return min(self.hard, self.limit)-elapsed

    def receipt(self):
        return {'hard_seconds': self.hard, 'current_soft_limit': self.limit,
                'distinct_milestones': len(self.seen), 'last_progress_seconds': self.last_progress,
                'extensions': self.events, 'stop_reason': self.reason,
                'phase':self.phase,'phase_started_seconds':self.phase_started,
                'phase_grace_seconds':self.phase_grace,'phase_transitions':self.phase_transitions,
                'scope': 'Package/build milestones and one grace per terminal phase; not success, liveness proof or daemon cleanup'}
