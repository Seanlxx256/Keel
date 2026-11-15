"""Stable controller queue facade over a business-level storage backend."""
from .queue_store import QueueStore, SqliteQueueStore, text


class TaskQueue:
    def __init__(self,store,*,backend: QueueStore | None = None):
        self.store=store
        self.backend: QueueStore = backend if backend is not None else SqliteQueueStore(store)
        self._checked_backend()

    @property
    def transaction_domain(self):return self.backend.transaction_domain

    def _checked_backend(self):
        from .transaction_domain import require_shared_domain
        self.store.require_persistence()
        require_shared_domain(self.store,queue=self.backend)
        return self.backend

    def enqueue(self,item_id,principal,task_id,payload):
        return self._checked_backend().enqueue(item_id,principal,task_id,payload)

    def claim(self,principal,task_id,run_id,run_deadline):
        return self._checked_backend().claim(principal,task_id,run_id,run_deadline)

    def transition(self,principal,task_id,run_id,item_id,fence,action,report=None):
        return self._checked_backend().transition(principal,task_id,run_id,item_id,fence,action,report)

    def status(self,principal,task_id,item_id):
        return self._checked_backend().status(principal,task_id,item_id)

    def renew(self,principal,task_id,run_id,item_id,fence,run_deadline):
        return self._checked_backend().renew(principal,task_id,run_id,item_id,fence,run_deadline)

    def requeue(self,item_id,fence,reason):
        return self._checked_backend().requeue(item_id,fence,reason)
