from __future__ import annotations

import pytest

from weave_frontend import Workspace


@pytest.fixture
def workspace(tmp_path):
    with Workspace(tmp_path / "weave.db") as value:
        value.initialize("demo")
        value.create_module("demo", "main", "app")
        yield value
