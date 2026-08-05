from __future__ import annotations

import math

import pytest

from weave_frontend.errors import ConflictError, ValidationError
from weave_frontend.service import RevisionWorkspace
from weave_frontend.sexpr import make_atom, parse_source, render_node


class _GraphWorkspace(RevisionWorkspace):
    def __init__(
        self,
        parents: dict[str, tuple[str | None, str | None]],
    ) -> None:
        self._graph = parents

    def _parents(self, revision: str) -> tuple[str | None, str | None]:
        return self._graph[revision]


def test_unique_best_common_ancestor_is_selected() -> None:
    workspace = _GraphWorkspace(
        {
            "root": (None, None),
            "base": ("root", None),
            "left": ("base", None),
            "right": ("base", None),
        }
    )

    assert workspace._best_common_ancestors("left", "right") == ("base",)
    assert workspace._common_ancestor("left", "right") == "base"


def test_criss_cross_history_is_rejected_in_stable_order() -> None:
    parents = {
        "root": (None, None),
        "a": ("root", None),
        "b": ("root", None),
        "left": ("a", "b"),
        "right": ("b", "a"),
    }
    workspace = _GraphWorkspace(parents)
    reversed_workspace = _GraphWorkspace(
        {
            **parents,
            "left": ("b", "a"),
            "right": ("a", "b"),
        }
    )

    assert workspace._best_common_ancestors("left", "right") == ("a", "b")
    assert reversed_workspace._best_common_ancestors("left", "right") == (
        "a",
        "b",
    )

    for candidate in (workspace, reversed_workspace):
        with pytest.raises(ConflictError) as raised:
            candidate._common_ancestor("left", "right")
        assert raised.value.conflicts == ["branches have multiple best common ancestors: a, b"]


@pytest.mark.parametrize(
    "value",
    [True, False, math.nan, math.inf, -math.inf],
)
def test_float_atoms_reject_noncanonical_values(value: object) -> None:
    with pytest.raises(ValidationError) as raised:
        make_atom("float", value)

    assert raised.value.code == "INVALID_VALUE"


@pytest.mark.parametrize(
    "value",
    [0, 1, -2, 1.5, -0.0, 1.0e20, 1.0e-20],
)
def test_finite_float_atoms_round_trip_canonically(value: int | float) -> None:
    rendered = render_node(make_atom("float", value))
    parsed = parse_source(rendered)

    assert parsed["kind"] == "float"
    assert parsed["value"] == float(value)
    assert render_node(parsed) == rendered
