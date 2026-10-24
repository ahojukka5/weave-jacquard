from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

import pytest

from tests.fuzz.targets import MAX_CASE_BYTES, READERS, TARGETS, TREE, replay
from weave_frontend.compiler import read_bounded_json
from weave_frontend.errors import WeaveFrontendError
from weave_frontend.retained_artifact_io import RetainedArtifactReadError, read_bounded_regular_json
from weave_frontend.sexpr import parse_source
from weave_frontend.snapshot_codec import canonical_json

CORPUS = Path(__file__).parent / "fuzz/corpus/cases.json"
CASES = json.loads(CORPUS.read_text())


def cases():
    for case in CASES:
        yield case["name"], case["target"], bytes.fromhex(case["hex"])
    yield "valid-snapshot", "snapshot", b"WJR1" + canonical_json(TREE).encode()
    yield "compressed-snapshot", "snapshot", b"WJZ1" + zlib.compress(canonical_json(TREE).encode())
    yield "depth-boundary", "sexpr", b"(" * 514 + b")" * 514
    yield "integer-budget", "sexpr", b"9" * 5000
    yield "json-depth", "retained_json", b"[" * 1500 + b"0" + b"]" * 1500


@pytest.mark.parametrize(("name", "target", "payload"), list(cases()))
def test_committed_corpus_is_deterministic(tmp_path, name, target, payload):
    assert target in TARGETS
    assert len(payload) <= MAX_CASE_BYTES
    assert replay(target, payload, tmp_path) == replay(target, payload, tmp_path)


@pytest.mark.parametrize("target", TARGETS)
def test_deterministic_mutations(tmp_path, target):
    rng = random.Random(129)
    seeds = [payload for _, selected, payload in cases() if selected == target]
    if not seeds:
        seeds = [b"{}", b'{"format":"unknown","status":[]}']
    for _ in range(40):
        value = bytearray(rng.choice(seeds))
        if value:
            position = rng.randrange(len(value))
            if rng.randrange(2):
                value[position] = rng.randrange(256)
            else:
                del value[position:]
        payload = bytes(value)
        assert replay(target, payload, tmp_path) == replay(target, payload, tmp_path)


@pytest.mark.parametrize("reader", [*READERS.values(), read_bounded_json])
def test_file_targets_reject_symlinks_and_duplicate_keys(tmp_path, reader):
    outside = tmp_path / "outside.json"
    outside.write_text('{"x":1,"x":2}')
    path = tmp_path / "manifest.json"
    path.symlink_to(outside)
    kwargs = {"max_bytes": 1024} if reader is read_bounded_json else {}
    with pytest.raises((RetainedArtifactReadError, OSError, WeaveFrontendError)) as captured:
        reader(path, **kwargs)
    assert str(tmp_path) not in str(captured.value)
    path.unlink()
    path.write_bytes(outside.read_bytes())
    with pytest.raises((RetainedArtifactReadError, OSError, WeaveFrontendError)) as captured:
        reader(path, **kwargs)
    assert str(tmp_path) not in str(captured.value)


def test_source_surrogate_has_a_domain_error():
    from weave_frontend.errors import ValidationError

    with pytest.raises(ValidationError):
        parse_source("\ud800")


def test_fifo_is_rejected_without_opening(tmp_path):
    import os

    path = tmp_path / "fifo"
    os.mkfifo(path)
    with pytest.raises(RetainedArtifactReadError, match="regular"):
        read_bounded_regular_json(path, max_bytes=1024)
