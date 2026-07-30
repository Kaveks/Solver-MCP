"""
Unit-test fixtures (apply to tests/unit only).

Backs the job store with fakeredis and stubs the Celery dispatch so submit_job creates a
PENDING record without a real broker. Scoped to unit tests so integration/regression tests
(which use the real stack) are unaffected.
"""

from __future__ import annotations

import fakeredis
import pytest

from execution import cache, job_store
from mcp_server import router


@pytest.fixture(autouse=True)
def fake_job_store_and_no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    job_store.set_client(fakeredis.FakeStrictRedis(decode_responses=True))
    cache.set_client(fakeredis.FakeStrictRedis(decode_responses=True))
    monkeypatch.setattr(router, "_dispatch", lambda *args, **kwargs: None)
    yield
    job_store.set_client(None)
    cache.set_client(None)
