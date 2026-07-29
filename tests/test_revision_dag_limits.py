from __future__ import annotations

import sqlite3

import pytest

from weave_frontend.errors import ConflictError, ValidationError
from weave_frontend.revision_dag import analyze_common_ancestors


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE revisions (
               id TEXT PRIMARY KEY,
               parent1_id TEXT,
               parent2_id TEXT
           )"""
    )
    return connection


def _revision(
    connection: sqlite3.Connection,
    revision_id: str,
    parent1: str | None = None,
    parent2: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO revisions(id, parent1_id, parent2_id) VALUES (?, ?, ?)",
        (revision_id, parent1, parent2),
    )


def test_linear_analysis_accepts_exact_node_and_edge_limits() -> None:
    connection = _connection()
    _revision(connection, "a")
    _revision(connection, "b", "a")
    _revision(connection, "c", "b")

    analysis = analyze_common_ancestors(
        connection,
        "c",
        "b",
        max_nodes=3,
        max_edges=2,
    )

    assert analysis.best_common_ancestors == ("b",)
    assert analysis.require_single_best() == "b"
    assert analysis.nodes_visited == 3
    assert analysis.edges_visited == 2
    assert analysis.evidence()["limits"] == {"nodes": 3, "edges": 2}


def test_node_and_edge_limit_plus_one_fail_closed() -> None:
    connection = _connection()
    _revision(connection, "a")
    _revision(connection, "b", "a")
    _revision(connection, "c", "b")

    with pytest.raises(ValidationError) as captured:
        analyze_common_ancestors(connection, "c", "b", max_nodes=2)
    assert captured.value.code == "REVISION_DAG_NODE_LIMIT_EXCEEDED"

    with pytest.raises(ValidationError) as captured:
        analyze_common_ancestors(connection, "c", "b", max_edges=1)
    assert captured.value.code == "REVISION_DAG_EDGE_LIMIT_EXCEEDED"


def test_criss_cross_best_common_ancestors_are_deterministic() -> None:
    connection = _connection()
    _revision(connection, "a")
    _revision(connection, "b", "a")
    _revision(connection, "c", "a")
    _revision(connection, "d", "b", "c")
    _revision(connection, "e", "c", "b")

    analysis = analyze_common_ancestors(connection, "d", "e")

    assert analysis.best_common_ancestors == ("b", "c")
    with pytest.raises(ConflictError, match="multiple best common ancestors"):
        analysis.require_single_best()


def test_revision_cycle_is_rejected_instead_of_returning_a_base() -> None:
    connection = _connection()
    _revision(connection, "a", "b")
    _revision(connection, "b", "a")

    with pytest.raises(ValidationError) as captured:
        analyze_common_ancestors(connection, "a", "b")

    assert captured.value.code == "REVISION_DAG_CYCLE"


def test_disconnected_cycle_is_rejected_before_no_common_ancestor() -> None:
    connection = _connection()
    _revision(connection, "left-a", "left-b")
    _revision(connection, "left-b", "left-a")
    _revision(connection, "right")

    with pytest.raises(ValidationError) as captured:
        analyze_common_ancestors(connection, "left-a", "right")

    assert captured.value.code == "REVISION_DAG_CYCLE"


def test_union_analysis_fetches_each_revision_once() -> None:
    connection = _connection()
    _revision(connection, "a")
    _revision(connection, "b", "a")
    _revision(connection, "c", "a")
    _revision(connection, "d", "b", "c")
    _revision(connection, "e", "c", "b")
    selects: list[str] = []
    connection.set_trace_callback(
        lambda statement: selects.append(statement)
        if statement.startswith("SELECT parent1_id")
        else None
    )

    analysis = analyze_common_ancestors(connection, "d", "e")

    assert analysis.nodes_visited == 5
    assert len(selects) == 5
