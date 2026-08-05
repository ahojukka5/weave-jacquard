from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]

targets = ROOT / "src/weave_frontend/build_targets.py"
text = targets.read_text(encoding="utf-8")
old = '''        profiles = fields.get("evidence-profile", [])
        if len(profiles) > 1:
            raise cls._invalid_tree(
                name,
                "at most one evidence-profile field is allowed",
            )
        primary = fields["primary"][0]
        sources = fields.get("source", [])
        cls._validate_document_set(primary, sources)
        return cls._config(
            name,
            primary,
            sources,
            fields["compiler-target"][0],
            normalize_evidence_profile(profiles[0] if profiles else None),
        )
'''
new = '''        profiles = fields.get("evidence-profile", [])
        if len(profiles) != 1:
            raise cls._invalid_tree(
                name,
                "exactly one evidence-profile field is required",
            )
        primary = fields["primary"][0]
        sources = fields.get("source", [])
        cls._validate_document_set(primary, sources)
        return cls._config(
            name,
            primary,
            sources,
            fields["compiler-target"][0],
            normalize_evidence_profile(profiles[0]),
        )
'''
if text.count(old) != 1:
    raise SystemExit("build-target evidence-profile parser was not found")
targets.write_text(text.replace(old, new), encoding="utf-8")

tests = ROOT / "tests/test_build_targets.py"
text = tests.read_text(encoding="utf-8")
old_import = "from weave_frontend.errors import ConflictError, NotFoundError, ValidationError\n"
new_import = (
    "from weave_frontend.errors import ConflictError, NotFoundError, ValidationError\n"
    "from weave_frontend.sexpr import make_atom, make_form\n"
)
if text.count(old_import) != 1:
    raise SystemExit("build-target test import anchor was not found")
text = text.replace(old_import, new_import)
text += '''


def test_persisted_target_requires_explicit_evidence_profile() -> None:
    root = make_form("build-target")
    for head, value in (
        ("primary", "main.weave"),
        ("compiler-target", "native"),
    ):
        field = make_form(head)
        field["children"].append(make_atom("string", value))
        root["children"].append(field)

    with pytest.raises(ValidationError) as captured:
        BuildTargetRegistry._parse_tree(root, name="app")

    assert captured.value.code == "INVALID_BUILD_TARGET"
    assert "exactly one evidence-profile" in str(captured.value)
'''
tests.write_text(text, encoding="utf-8")

(ROOT / ".github/workflows/enforce-explicit-evidence-profile.yml").unlink()
Path(__file__).unlink()
