"""Close subprocess transports owned by one synchronous async request."""
import asyncio


def run_request(factory):
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
            return transport,protocol
        loop.subprocess_exec=subprocess_exec
        return loop
    async def request():
        try:
            return await factory()
        finally:
            # SDK contexts first perform their graceful shutdown. Explicit transport
            # close prevents late GC on a closed Windows Proactor loop/pipe.
            for transport in owned:
                transport.close()
            await asyncio.sleep(0)
    with asyncio.Runner(loop_factory=make_loop) as runner:
        return runner.run(request())
