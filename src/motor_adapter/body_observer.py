"""Observe the first nonempty D body bytes without changing the byte stream."""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class FirstBodyObserver:
    def __init__(self, release, tasks: set):
        self.release = release
        self.tasks = tasks
        self.seen = False

    def observe(self, chunk: bytes) -> None:
        if not chunk or self.seen:
            return
        self.seen = True
        task = asyncio.create_task(self.release())
        self.tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("P FG release failed; request finalizer will retry: %s", task.exception())


class ObservedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, observer: FirstBodyObserver):
        self.stream = stream
        self.observer = observer

    async def __aiter__(self):
        async for chunk in self.stream:
            self.observer.observe(chunk)
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()
