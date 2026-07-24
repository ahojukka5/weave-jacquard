from __future__ import annotations

from weave_frontend.grammar_help import GrammarIndex


def test_help_is_derived_from_weavec2_surface_examples(tmp_path):
    surface = tmp_path / "test" / "correctness" / "surface"
    surface.mkdir(parents=True)
    (surface / "sample.weave").write_text(
        """(program
  (name \"sample\")
  (version \"0.1\")
  (entry main)
  (fn main
    (params)
    (returns i32)
    (do (return (const_i32 42)))))
""",
        encoding="utf-8",
    )

    grammar = GrammarIndex(tmp_path)
    help_result = grammar.help(form="fn")
    child_result = grammar.help(parent_form="program")

    assert help_result["found"] is True
    assert help_result["observed_arities"] == [4]
    assert help_result["examples"][0]["source"].endswith("sample.weave")
    assert any(
        item["form"] == "fn"
        for item in child_result["observed_child_forms"]
    )
