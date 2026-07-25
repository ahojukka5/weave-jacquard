from __future__ import annotations

import pytest

from weave_frontend import SExpressionWorkspace


@pytest.fixture
def sexpr_workspace(tmp_path):
    with SExpressionWorkspace(tmp_path / "sexpr.db") as value:
        value.initialize("sexpr-demo")
        yield value
