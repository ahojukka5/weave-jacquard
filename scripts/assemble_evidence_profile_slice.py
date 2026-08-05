from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
GENERATED_COMMIT = "3744edda48a28ba72d0521e8ac09c51e803b5335"
FILES = [
    "docs/compiler-package.md",
    "src/weave_frontend/build_targets.py",
    "src/weave_frontend/compiler/__init__.py",
    "src/weave_frontend/compiler/bridge.py",
    "src/weave_frontend/compiler/capabilities.py",
    "src/weave_frontend/compiler/evidence.py",
    "src/weave_frontend/compiler/limits.py",
    "tests/test_build_targets.py",
    "tests/test_compiler_capabilities.py",
    "tests/test_compiler_evidence_profiles.py",
    "tests/test_compiler_package_architecture.py",
]

subprocess.run(
    ["git", "fetch", "origin", "agent/evidence-profile-generator"],
    cwd=ROOT,
    check=True,
)
subprocess.run(
    ["git", "checkout", GENERATED_COMMIT, "--", *FILES],
    cwd=ROOT,
    check=True,
)

bridge = ROOT / "src/weave_frontend/compiler/bridge.py"
text = bridge.read_text(encoding="utf-8")
old = '''        evidence_profile = normalize_evidence_profile(manifest.get("evidence_profile"))
'''
new = '''        if "evidence_profile" not in manifest:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires an explicit evidence profile",
            )
        evidence_profile = normalize_evidence_profile(manifest["evidence_profile"])
'''
if text.count(old) != 1:
    raise SystemExit("generated bridge evidence-profile verification was not found")
bridge.write_text(text.replace(old, new), encoding="utf-8")

tests = ROOT / "tests/test_compiler_evidence_profiles.py"
tests.write_text(
    tests.read_text(encoding="utf-8")
    + '''


def test_current_build_key_requires_explicit_evidence_profile() -> None:
    with pytest.raises(ValidationError) as captured:
        CompilerBridge._verify_current_build_key({})

    assert captured.value.code == "INVALID_BUILD_MANIFEST"
    assert "explicit evidence profile" in str(captured.value)
''',
    encoding="utf-8",
)

(ROOT / ".github/workflows/assemble-evidence-profile-slice.yml").unlink()
Path(__file__).unlink()
