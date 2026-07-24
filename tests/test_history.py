from __future__ import annotations


def test_every_mutation_is_a_revision_and_checkout_restores_old_state(workspace):
    module_revision = workspace.branch_head("demo")
    workspace.create_function("demo", "main", "app", "foo", params=[], returns="void")
    function_revision = workspace.branch_head("demo")

    assert module_revision != function_revision
    assert workspace.find_symbols("demo", name="foo")

    workspace.checkout("demo", "main", module_revision)
    assert workspace.find_symbols("demo", name="foo") == []

    workspace.checkout("demo", "main", function_revision)
    assert workspace.find_symbols("demo", name="foo")
    assert len(workspace.list_history("demo")) >= 3
