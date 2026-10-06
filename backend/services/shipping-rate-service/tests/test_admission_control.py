"""Admission control middleware tests (pure ASGI, no service dependencies)."""

import asyncio

from internal.middleware.admission_control import AdmissionControlMiddleware


def _scope(path="/shipping/quotes"):
    return {"type": "http", "path": path, "method": "POST", "headers": []}


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


class SlowApp:
    """Holds load requests until `release` is set; probes/metrics answer at once."""

    def __init__(self):
        self.release = asyncio.Event()
        self.started = 0

    async def __call__(self, scope, receive, send):
        self.started += 1
        if not scope["path"].startswith(("/metrics", "/health", "/ready")):
            await self.release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _call(middleware, path="/shipping/quotes"):
    messages = []

    async def send(message):
        messages.append(message)

    await middleware(_scope(path), _receive, send)
    return messages[0]["status"]


def test_disabled_by_default_passes_everything():
    async def run():
        app = SlowApp()
        app.release.set()
        mw = AdmissionControlMiddleware(app, max_inflight=0)
        statuses = await asyncio.gather(*[_call(mw) for _ in range(20)])
        assert statuses == [200] * 20

    asyncio.run(run())


def test_excess_requests_get_503_while_capped_ones_wait():
    async def run():
        app = SlowApp()
        mw = AdmissionControlMiddleware(app, max_inflight=3)
        admitted = [asyncio.create_task(_call(mw)) for _ in range(3)]
        await asyncio.sleep(0)
        assert mw.inflight == 3
        assert await _call(mw) == 503
        app.release.set()
        assert await asyncio.gather(*admitted) == [200, 200, 200]
        assert mw.inflight == 0
        assert await _call(mw) == 200

    asyncio.run(run())


def test_probes_and_metrics_bypass_a_full_pod():
    async def run():
        app = SlowApp()
        mw = AdmissionControlMiddleware(app, max_inflight=1)
        held = asyncio.create_task(_call(mw))
        await asyncio.sleep(0)
        assert mw.inflight == 1
        assert await _call(mw) == 503
        for path in ("/metrics", "/health", "/ready"):
            assert await _call(mw, path) == 200
        app.release.set()
        assert await held == 200

    asyncio.run(run())


def test_inflight_released_when_handler_raises():
    async def run():
        async def failing(scope, receive, send):
            raise RuntimeError("boom")

        mw = AdmissionControlMiddleware(failing, max_inflight=1)
        try:
            await mw(_scope(), _receive, lambda m: None)
        except RuntimeError:
            pass
        assert mw.inflight == 0

    asyncio.run(run())
