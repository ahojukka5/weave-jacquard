from __future__ import annotations

import pytest

from weave_frontend import SExpressionWorkspace, Workspace


@pytest.fixture
def workspace(tmp_path):
    with Workspace(tmp_path / "typed.db") as value:
        value.initialize("demo")
        value.create_module("demo", "main", "app")
        yield value


@pytest.fixture
def sexpr_workspace(tmp_path):
    with SExpressionWorkspace(tmp_path / "sexpr.db") as value:
        value.initialize("sexpr-demo")
        yield value
