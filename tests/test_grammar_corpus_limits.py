from __future__ import annotations

from pathlib import Path

import pytest

import weave_frontend.grammar_help as grammar_help_module
from weave_frontend.errors import ValidationError
from weave_frontend.grammar_help import GrammarIndex


def _surface_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "weavec"
    surface = root / "test" / "correctness" / "surface"
    surface.mkdir(parents=True)
    return root, surface


def test_corpus_total_bytes_stop_before_next_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, surface = _surface_root(tmp_path)
    source = "(program)"
    (surface / "a.weave").write_text(source, encoding="utf-8")
    (surface / "b.weave").write_text(source, encoding="utf-8")
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_CORPUS_BYTES", len(source))

    index = GrammarIndex(root)

    assert index.files_discovered == 2
    assert index.files_considered == 2
    assert index.files_scanned == 1
    assert index.bytes_scanned == len(source)
    assert index.corpus_truncated is True


def test_corpus_file_selection_is_lexical_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, surface = _surface_root(tmp_path)
    (surface / "b.weave").write_text("(from_b)", encoding="utf-8")
    (surface / "a.weave").write_text("(from_a)", encoding="utf-8")
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_CORPUS_FILES", 1)

    index = GrammarIndex(root)

    assert index.files_discovered == 2
    assert index.files_scanned == 1
    assert set(index.forms) == {"from_a"}
    assert index.corpus_truncated is True


def test_oversized_and_symlink_sources_are_not_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, surface = _surface_root(tmp_path)
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_SOURCE_BYTES", 16)
    (surface / "a.weave").write_text("(" + "x" * 16 + ")", encoding="utf-8")
    target = tmp_path / "target.weave"
    target.write_text("(ok)", encoding="utf-8")
    (surface / "b.weave").symlink_to(target.name)

    index = GrammarIndex(root)

    assert index.files_scanned == 0
    assert index.bytes_scanned == 0
    assert index.parse_failure_count == 2
    errors = "\n".join(item["error"] for item in index.parse_failures)
    assert "exceeds" in errors
    assert "symlink" in errors


def test_directory_entry_overflow_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, surface = _surface_root(tmp_path)
    (surface / "a.weave").write_text("(a)", encoding="utf-8")
    (surface / "b.weave").write_text("(b)", encoding="utf-8")
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_DIRECTORY_ENTRIES", 1)

    index = GrammarIndex(root)

    assert index.status()["available"] is False
    assert index.corpus_truncated is True
    assert index.corpus_error is not None
    assert index.files_scanned == 0
    assert index.forms == {}


def test_forms_and_examples_have_independent_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, surface = _surface_root(tmp_path)
    (surface / "forms.weave").write_text(
        "(program (first) (second))",
        encoding="utf-8",
    )
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_FORMS", 2)
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_EXAMPLE_NODES", 2)

    index = GrammarIndex(root)

    assert len(index.forms) == 2
    assert index.forms_truncated is True
    assert index.examples_truncated is True
    assert index.forms["program"].examples == []
    assert len(index.forms["first"].examples) == 1


def test_parse_failure_evidence_is_counted_but_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, surface = _surface_root(tmp_path)
    (surface / "a.weave").write_text("(", encoding="utf-8")
    (surface / "b.weave").write_text("(", encoding="utf-8")
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_PARSE_FAILURES", 1)
    monkeypatch.setattr(grammar_help_module, "MAX_GRAMMAR_ERROR_BYTES", 8)

    index = GrammarIndex(root)

    assert index.parse_failure_count == 2
    assert len(index.parse_failures) == 1
    assert len(index.parse_failures[0]["error"].encode("utf-8")) <= 11
    assert index.bytes_scanned == 2


@pytest.mark.parametrize("limit", [True, 0, -1, 51])
def test_help_rejects_unbounded_result_limit(limit: object) -> None:
    index = GrammarIndex(None)

    with pytest.raises(ValidationError) as captured:
        index.help(limit=limit)  # type: ignore[arg-type]

    assert captured.value.code == "INVALID_GRAMMAR_HELP_LIMIT"
