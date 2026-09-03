
from collections.abc import AsyncIterator

import contextlib
import trio


@contextlib.asynccontextmanager
async def create_nursery() -> AsyncIterator[trio.Nursery]:
	"""Nursery that cancels itself when the context manager exits."""
	async with trio.open_nursery() as nursery:
		yield nursery
		nursery.cancel_scope.cancel()


@contextlib.asynccontextmanager
async def background_task(task, *args) -> AsyncIterator[None]:
    async with create_nursery() as nursery:
        nursery.start_soon(task, *args)
        yield
