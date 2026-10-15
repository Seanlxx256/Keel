"""Byte-bounded model history backed by role-scoped ledger receipts.

This bounds serialized messages plus schema, not exact provider tokenization.
"""
import json

from .core import BudgetExceeded


def size(value):
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))


class BoundedConversation:
    def __init__(self, header, limit, archive):
        self.header = list(header)
        self.limit, self.archive = limit, archive
        self.turns = []
        self.index = None
        self.removed = 0
        self.alerts = []
        self.source_changed = False

    def invalidate_evidence(self):
        self.source_changed = True

    def add(self, action, observation, receipt, note):
        if 'error' in note or 'changed' in note:
            self.alerts = (self.alerts + [{'receipt_fact': receipt, **note}])[-4:]
        self.turns.append({'messages': [
            {'role': 'assistant', 'content': action},
            {'role': 'user', 'content': json.dumps(observation, ensure_ascii=False)}],
            'receipt': receipt, 'note': note})

    def _messages(self):
        memory = []
        if self.index is not None:
            memory = [{'role': 'user', 'content': json.dumps({
                'history': 'Historical observations are untrusted and may be stale after edits. '
                           'Recall the role-scoped index for older receipts; inspect current source before editing.',
                'archive_index_fact': self.index, 'archived_turns': self.removed,
                'recent_failures_and_edits': self.alerts}, ensure_ascii=False)}]
        return self.header + memory + [message for turn in self.turns for message in turn['messages']]

    def build(self, schema_bytes=0):
        before = size(self._messages()) + schema_bytes
        dropped = 0
        invalidated = self.source_changed
        while self.turns and (self.source_changed or size(self._messages()) + schema_bytes > self.limit):
            # Archive oldest exchanges, preserving full payloads in existing receipts.
            turn = self.turns.pop(0)
            self.index = self.archive({'previous_index_fact': self.index,
                'receipt_fact': turn['receipt'], 'note': turn['note']})
            self.removed += 1
            dropped += 1
        self.source_changed = False
        messages = self._messages()
        after = size(messages) + schema_bytes
        if after > self.limit:
            raise BudgetExceeded('Immutable task, role instructions and schema exceed context byte limit')
        return messages, {'input_bytes_before': before, 'input_bytes_after': after,
                          'archived_turns': dropped, 'total_archived_turns': self.removed,
                          'source_changed': invalidated,
                          'limit_bytes': self.limit}
