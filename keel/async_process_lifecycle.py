"""Close subprocess transports owned by one synchronous async request."""
import asyncio
import threading
import time


class RequestControl:
    """Cancel one owned event-loop request, never an arbitrary process ID."""
    def __init__(self):
        self.lock=threading.Lock();self.requested=threading.Event()
        self.loop=None;self.task=None;self.owned=[];self.finished=False
        self.processes=[];self.errors=[];self.on_update=None;self.storage_failed=False

    def _notify(self):
        if self.on_update is not None:
            try:self.on_update(self.report())
            except Exception as error:
                self.storage_failed=True
                with self.lock:self.errors.append(type(error).__name__)
                raise

    def checkpoint(self):self._notify()

    def note_error(self,error):
        with self.lock:
            if len(self.errors)<32:self.errors.append(type(error).__name__)

    def bind(self,loop,task):
        with self.lock:self.loop=loop;self.task=task
        self._notify()
        if self.requested.is_set():task.cancel()

    def register(self,transport):
        with self.lock:self.owned.append(transport)
        self._notify()
        if self.requested.is_set():transport.close()

    def cancel(self):
        self.requested.set()
        with self.lock:loop=self.loop;task=self.task
        def stop_owned():
            if task is not None and not task.done():task.cancel()
            with self.lock:owned=list(self.owned)
            for transport in owned:
                try:transport.close()
                except Exception as error:
                    with self.lock:self.errors.append(type(error).__name__)
        if loop is not None and not loop.is_closed():
            try:loop.call_soon_threadsafe(stop_owned)
            except RuntimeError:pass
        # Cancellation is attempted even if required lifecycle storage failed.
        try:self._notify()
        except Exception:pass

    def finish(self):
        with self.lock:
            self.finished=True
            for transport in self.owned:
                try:self.processes.append({'pid':transport.get_pid(),'returncode':transport.get_returncode()})
                except Exception as error:self.errors.append(type(error).__name__)
            self.owned=[]
        self._notify()

    def report(self):
        with self.lock:
            processes=list(self.processes)
            if not self.finished:
                for transport in self.owned:
                    try:processes.append({'pid':transport.get_pid(),'returncode':transport.get_returncode()})
                    except Exception:processes.append({'pid':None,'returncode':None})
            return {'cancellation_requested':self.requested.is_set(),'request_finished':self.finished,
                    'owned_processes':processes,
                    'direct_children_exited':self.finished and not self.errors and not self.storage_failed and all(p['returncode'] is not None for p in processes),
                    'storage_failed':self.storage_failed,'errors':list(self.errors),
                    'scope':'Owned SDK subprocess transports only; remote effects and descendants not certified'}


def run_request(factory,*,control=None):
    """Keep SDK-owned process transports alive until explicit cleanup on their loop.

    Only the newly created event loop is instrumented. No global event-loop policy,
    SDK function or unrelated process is changed. Uses public subprocess transport APIs.
    """
    owned=[]
    def make_loop():
        loop=asyncio.new_event_loop()
        original=loop.subprocess_exec
        async def subprocess_exec(*args,**kwargs):
            transport,protocol=await original(*args,**kwargs)
            owned.append(transport)
            if control is not None:control.register(transport)
            return transport,protocol
        loop.subprocess_exec=subprocess_exec
        return loop
    async def request():
        try:
            if control is not None:control.bind(asyncio.get_running_loop(),asyncio.current_task())
            if control is not None and control.requested.is_set():raise asyncio.CancelledError()
            return await factory()
        finally:
            # SDK contexts first perform their graceful shutdown. Explicit transport
            # close prevents late GC on a closed Windows Proactor loop/pipe.
            close_error=None
            for transport in owned:
                try:transport.close()
                except Exception as error:
                    if control is not None:control.note_error(error)
                    elif close_error is None:close_error=error
            await asyncio.sleep(0)
            if control is not None:
                deadline=time.monotonic()+3
                while any(transport.get_returncode() is None for transport in owned) and time.monotonic()<deadline:
                    await asyncio.sleep(.05)
            if close_error is not None:raise close_error
    try:
        with asyncio.Runner(loop_factory=make_loop) as runner:
            return runner.run(request())
    finally:
        if control is not None:control.finish()
