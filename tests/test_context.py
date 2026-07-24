from __future__ import annotations


def test_design_context_is_versioned_and_selected_by_scope(workspace):
    workspace.add_document(
        "demo",
        "main",
        scope_kind="project",
        scope_name="demo",
        title="Project invariants",
        body="All public functions must be deterministic.",
    )
    workspace.add_document(
        "demo",
        "main",
        scope_kind="symbol",
        scope_name="app.foo",
        title="Foo contract",
        body="foo calls bar exactly once.",
    )

    context = workspace.context_for_symbol("demo", "main", "app.foo")
    assert [item["title"] for item in context] == ["Project invariants", "Foo contract"]
