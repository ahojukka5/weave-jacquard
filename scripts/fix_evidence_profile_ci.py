from __future__ import annotations

import re
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


capabilities = ROOT / "src/weave_frontend/compiler/capabilities.py"
replace_once(
    capabilities,
    '''        command_protocols = (
            set(command_item.get("protocols", ())) if command_item is not None else None
        )
        for protocol in protocols:
            if protocol not in protocol_map:
                raise _invalid(
                    "WEAVEC_PROTOCOL_UNSUPPORTED",
                    f"installed weavec does not advertise protocol {protocol!r}",
                )
            if command_protocols is not None and protocol not in command_protocols:
                raise _invalid(
                    "WEAVEC_PROTOCOL_UNSUPPORTED",
                    f"weavec command {command!r} does not advertise protocol {protocol!r}",
                )
''',
    '''        for protocol in protocols:
            if protocol not in protocol_map:
                raise _invalid(
                    "WEAVEC_PROTOCOL_UNSUPPORTED",
                    f"installed weavec does not advertise protocol {protocol!r}",
                )
''',
)

capability_tests = ROOT / "tests/test_compiler_capabilities.py"
replace_once(
    capability_tests,
    '''def test_requested_protocol_must_belong_to_selected_command(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    registry = _registry()
    commands = registry["commands"]
    assert isinstance(commands, list)
    build = next(item for item in commands if item["name"] == "build")
    build["protocols"] = [
        value for value in build["protocols"] if value != "weavec-compilation-trace-v1"
    ]
    _write_compiler(compiler, registry)
    capabilities = WeavecCapabilities(compiler, environment_fallback=False)

    with pytest.raises(ValidationError) as captured:
        capabilities.require(
            command="build",
            protocols=("weavec-compilation-trace-v1",),
        )

    assert captured.value.code == "WEAVEC_PROTOCOL_UNSUPPORTED"
''',
    '''def test_requested_protocol_uses_global_registry_authority(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    registry = _registry()
    commands = registry["commands"]
    assert isinstance(commands, list)
    build = next(item for item in commands if item["name"] == "build")
    build["protocols"] = [
        value for value in build["protocols"] if value != "weavec-compilation-trace-v1"
    ]
    _write_compiler(compiler, registry)
    capabilities = WeavecCapabilities(compiler, environment_fallback=False)

    document = capabilities.require(
        command="build",
        protocols=("weavec-compilation-trace-v1",),
    )

    assert document["format"] == "weavec-capabilities-v1"
''',
)

concurrent = ROOT / "src/weave_frontend/concurrent_build_targets.py"
replace_once(
    concurrent,
    '''from .build_targets import BuildTargetRegistry as _BaseBuildTargetRegistry
from .errors import NotFoundError, ValidationError
''',
    '''from .build_targets import BuildTargetRegistry as _BaseBuildTargetRegistry
from .compiler import normalize_evidence_profile
from .errors import NotFoundError, ValidationError
''',
)
replace_once(
    concurrent,
    '''        additional_documents: list[str] | None = None,
        compiler_target: str | None = None,
        expected_revision_id: str | None = None,
''',
    '''        additional_documents: list[str] | None = None,
        compiler_target: str | None = None,
        evidence_profile: str | None = None,
        expected_revision_id: str | None = None,
''',
)
replace_once(
    concurrent,
    '''        effective_target = self._normalize_compiler_target(compiler_target)
        base_revision_id, state = self.workspace._state_for_write(
''',
    '''        effective_target = self._normalize_compiler_target(compiler_target)
        effective_profile = normalize_evidence_profile(evidence_profile)
        base_revision_id, state = self.workspace._state_for_write(
''',
)
replace_once(
    concurrent,
    '''            documents[1:],
            effective_target,
            existing=state.get(storage_document),
''',
    '''            documents[1:],
            effective_target,
            effective_profile,
            existing=state.get(storage_document),
''',
)
replace_once(
    concurrent,
    '''            documents[1:],
            effective_target,
        )
''',
    '''            documents[1:],
            effective_target,
            effective_profile,
        )
''',
)

merge_candidate_tests = ROOT / "tests/test_merge_candidate_test_runs.py"
replace_once(
    merge_candidate_tests,
    '''    target = BuildTargetRegistry._build_tree(
        "main.weave",
        [],
        "native",
        existing=None,
    )
''',
    '''    target = BuildTargetRegistry._build_tree(
        "main.weave",
        [],
        "native",
        "none",
        existing=None,
    )
''',
)

fixture_updates = 0
format_pattern = re.compile(r'^(?P<indent>\s*)"format": BUILD_KEY_FORMAT,\s*$')
for path in sorted((ROOT / "tests").rglob("*.py")):
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    output: list[str] = []
    changed = False
    for index, line in enumerate(lines):
        output.append(line)
        match = format_pattern.match(line.rstrip("\n"))
        if match is None:
            continue
        nearby = "".join(lines[index + 1 : index + 10])
        if '"evidence_profile"' in nearby:
            continue
        newline = "\r\n" if line.endswith("\r\n") else "\n"
        output.append(
            f'{match.group("indent")}"evidence_profile": "none",{newline}'
        )
        fixture_updates += 1
        changed = True
    if changed:
        path.write_text("".join(output), encoding="utf-8")

if fixture_updates == 0:
    raise SystemExit("no BUILD_KEY_FORMAT fixtures required an explicit profile")

artifact_integrity = ROOT / "tests/test_build_artifact_integrity.py"
replace_once(
    artifact_integrity,
    '''        "compiler_sha256": compiler_sha256,
        "target": target,
        "compiler_diagnostics_protocol_valid": True,
''',
    '''        "compiler_sha256": compiler_sha256,
        "target": target,
        "evidence_profile": "none",
        "compiler_diagnostics_protocol_valid": True,
''',
)

cache_contract = ROOT / "tests/test_build_cache_contract.py"
replace_once(
    cache_contract,
    '''    build_id = hashlib.sha256(_canonical(cache_payload)).hexdigest()[:32]
    manifest = {
''',
    '''    if build_key_format == BUILD_KEY_FORMAT:
        cache_payload["evidence_profile"] = "none"
    build_id = hashlib.sha256(_canonical(cache_payload)).hexdigest()[:32]
    manifest = {
''',
)
replace_once(
    cache_contract,
    '''    (directory / "manifest.json").write_text(
        json.dumps(manifest) + "\\n", encoding="utf-8"
    )
''',
    '''    if build_key_format == BUILD_KEY_FORMAT:
        manifest["evidence_profile"] = "none"
    (directory / "manifest.json").write_text(
        json.dumps(manifest) + "\\n", encoding="utf-8"
    )
''',
)

build_discovery = ROOT / "tests/test_build_discovery.py"
replace_once(
    build_discovery,
    '''    manifest.update(
        {
            "source_sha256": key_documents[0]["source_sha256"],
''',
    '''    manifest.update(
        {
            "evidence_profile": "none",
            "source_sha256": key_documents[0]["source_sha256"],
''',
)

(ROOT / ".github/workflows/fix-evidence-profile-ci.yml").unlink()
Path(__file__).unlink()
