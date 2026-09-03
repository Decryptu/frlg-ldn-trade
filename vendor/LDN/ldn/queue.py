
import math
import trio


class Queue[T]:
    _sender: trio.MemorySendChannel[T]
    _receiver: trio.MemoryReceiveChannel[T]

    def __init__(
        self, sender: trio.MemorySendChannel,
        receiver: trio.MemoryReceiveChannel
    ):
        self._sender = sender
        self._receiver = receiver
    
    async def put(self, value: T) -> None:
        await self._sender.send(value)
    
    async def get(self) -> T:
        return await self._receiver.receive()


def create(size: int | float = math.inf) -> Queue:
    send, recv = trio.open_memory_channel(size)
    return Queue(send, recv)
