from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence

import pytest


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", content_type: str = "text/plain", final_url: str = "https://example.com/"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}
        self.url = final_url


@pytest.fixture
def fake_get_factory() -> Callable[[dict[str, tuple]], Callable]:
    def _factory(route_map: dict[str, tuple]):
        async def _fake_get(self, url, *args, **kwargs):
            if url in route_map:
                entry = route_map[url]
                if not isinstance(entry, Sequence):
                    raise TypeError("Route map entries must be tuples.")
                if len(entry) == 2:
                    status, text = entry
                    content_type = "text/plain"
                    final_url = url
                elif len(entry) == 3:
                    status, text, content_type = entry
                    final_url = url
                elif len(entry) == 4:
                    status, text, content_type, final_url = entry
                else:
                    raise ValueError("Route map tuple must have 2-4 items.")
                return FakeResponse(status, text, content_type, final_url)
            return FakeResponse(404, "", "text/plain", url)

        return _fake_get

    return _factory
