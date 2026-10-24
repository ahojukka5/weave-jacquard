#!/usr/bin/env python3
"""Offline bounded mutation replay; uncaught target failures stop the run."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fuzz.targets import MAX_CASE_BYTES, TARGETS, replay  # noqa: E402
from tests.test_parser_fuzz_corpus import CORPUS, cases  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        parser.error("seconds must be in (0,3600]")
    rng = random.Random(args.seed)
    seeds = [payload for _, target, payload in cases() if target == args.target] or [b"{}"]
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    count = 0
    inputs_digest = hashlib.sha256()
    value = b""
    record = {
        "target": args.target,
        "seed": args.seed,
        "requested_seconds": args.seconds,
        "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        "case_byte_limit": MAX_CASE_BYTES,
    }
    try:
        with tempfile.TemporaryDirectory(dir=args.output) as directory:
            while time.monotonic() - started < args.seconds:
                payload = bytearray(rng.choice(seeds))
                for _ in range(rng.randint(1, 4)):
                    if payload:
                        index = rng.randrange(len(payload))
                        if rng.randrange(2):
                            payload[index] = rng.randrange(256)
                        else:
                            del payload[index:]
                value = bytes(payload)
                inputs_digest.update(hashlib.sha256(value).digest())
                first = replay(args.target, value, Path(directory))
                assert first == replay(args.target, value, Path(directory))
                count += 1
    except BaseException:
        (args.output / "failure.bin").write_bytes(value)
        record["failure_sha256"] = hashlib.sha256(value).hexdigest()
        raise
    finally:
        record.update(
            cases=count,
            elapsed_seconds=time.monotonic() - started,
            inputs_sha256=inputs_digest.hexdigest(),
        )
        (args.output / "run.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
