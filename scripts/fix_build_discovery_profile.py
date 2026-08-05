from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, found {count}: {old[:100]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


service = ROOT / "src/weave_frontend/build_discovery.py"
replace_once(
    service,
    "from .compiler import BUILD_KEY_FORMAT\n",
    "from .compiler import BUILD_KEY_FORMAT, normalize_evidence_profile\n",
)
replace_once(
    service,
    '''        return {
            "build_id": build_id,
            "status": manifest["status"],
''',
    '''        return {
            "build_id": build_id,
            "status": manifest["status"],
            "evidence_profile": manifest.get("evidence_profile"),
''',
)
replace_once(
    service,
    '''    ) -> None:
        sources = manifest.get("sources")
        artifact_hashes = manifest.get("artifact_sha256")
''',
    '''    ) -> None:
        if "evidence_profile" not in manifest:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "current build key requires an explicit evidence profile",
            )
        evidence_profile = normalize_evidence_profile(manifest["evidence_profile"])
        sources = manifest.get("sources")
        artifact_hashes = manifest.get("artifact_sha256")
''',
)
replace_once(
    service,
    '''            "compiler_output_limit_bytes": output_limit,
            "target": target,
        }
''',
    '''            "compiler_output_limit_bytes": output_limit,
            "target": target,
            "evidence_profile": evidence_profile,
        }
''',
)

tests = ROOT / "tests/test_build_discovery.py"
replace_once(
    tests,
    '''    assert result["builds"][0]["build_key_format"] == BUILD_KEY_FORMAT
    assert result["builds"][0]["build_key_verified"] is True
''',
    '''    assert result["builds"][0]["build_key_format"] == BUILD_KEY_FORMAT
    assert result["builds"][0]["evidence_profile"] == "none"
    assert result["builds"][0]["build_key_verified"] is True
''',
)

Path(__file__).unlink()
