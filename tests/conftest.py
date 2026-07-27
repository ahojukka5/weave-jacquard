from __future__ import annotations

from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace


def pytest_pycollect_makeitem(
    collector: pytest.Collector,
    name: str,
    obj: Any,
) -> list[pytest.Item] | None:
    """Do not treat imported production classes named ``Test*`` as test suites."""

    module = getattr(obj, "__module__", "")
    if name.startswith("Test") and module.startswith("weave_frontend."):
        return []
    return None


@pytest.fixture
def sexpr_workspace(tmp_path):
    with SExpressionWorkspace(tmp_path / "sexpr.db") as value:
        value.initialize("sexpr-demo")
        yield value
