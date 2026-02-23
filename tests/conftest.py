from __future__ import annotations

from collections.abc import Callable

import pytest


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def fake_get_factory() -> Callable[[dict[str, tuple[int, str]]], Callable]:
    def _factory(route_map: dict[str, tuple[int, str]]):
        async def _fake_get(self, url, *args, **kwargs):
            if url in route_map:
                status, text = route_map[url]
                return FakeResponse(status, text)
            return FakeResponse(404, "")

        return _fake_get

    return _factory
