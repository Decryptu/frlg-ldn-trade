
"""Provides a simple asynchronous memory queue."""


import math
import trio


class Queue[T]:
    """
    Implements a simple asynchronous memory queue.
    """

    _sender: trio.MemorySendChannel[T]
    _receiver: trio.MemoryReceiveChannel[T]

    def __init__(
        self, sender: trio.MemorySendChannel,
        receiver: trio.MemoryReceiveChannel
    ):
        """Initializes the queue for the given sender and receiver."""
        self._sender = sender
        self._receiver = receiver
    
    async def put(self, value: T) -> None:
        """Adds a value to the queue. Blocks if the queue is full."""
        await self._sender.send(value)
    
    async def get(self) -> T:
        """
        Retrieves the oldest value from the queue. Blocks if the queue is empty.
        """
        return await self._receiver.receive()


def create(size: int | float = math.inf) -> Queue:
    send, recv = trio.open_memory_channel(size)
    return Queue(send, recv)
