import asyncio
import httpx
import pytest

from motor_adapter.body_observer import FirstBodyObserver, ObservedStream


@pytest.mark.asyncio
async def test_first_body_observer_preserves_bytes_and_releases_once():
    releases = []
    async def release():
        releases.append("released")
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for value in (b"", b"data: role", b"data: token", b"done"):
                yield value
        async def aclose(self):
            self.closed = True
    underlying = Stream()
    tasks = set()
    stream = ObservedStream(underlying, FirstBodyObserver(release, tasks))
    assert [value async for value in stream] == [b"", b"data: role", b"data: token", b"done"]
    if tasks:
        await asyncio.gather(*list(tasks))
    await stream.aclose()
    assert releases == ["released"]
    assert underlying.closed
