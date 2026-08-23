
from collections.abc import AsyncIterator

import contextlib
import trio


@contextlib.asynccontextmanager
async def create_nursery() -> AsyncIterator[trio.Nursery]:
	"""
	Creates a nursery that automatically cancels itself when the context manager
	exits.
	"""
	async with trio.open_nursery() as nursery:
		yield nursery
		nursery.cancel_scope.cancel()


@contextlib.asynccontextmanager
async def background_task(task, *args) -> AsyncIterator[None]:
    """
    Starts a task in the background and cancels it as soon as the context
    manager exits.
    """
    async with create_nursery() as nursery:
        nursery.start_soon(task, *args)
        yield
