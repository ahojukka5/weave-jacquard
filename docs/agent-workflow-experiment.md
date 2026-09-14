# Agent-workflow research protocol

This repository owns the executable comparison for
`ahojukka5/research#38`, implemented under issue #274. The first scientific
question is deliberately narrower than "are structural edits better than text
patches?": recent work already establishes structured action spaces as a serious
coding-agent baseline. The experiment asks whether Jacquard's immutable revision
and exact qualification layer adds reliability **beyond structure-aware editing**.

## Frozen arms

The first study has exactly three arms in this order:

1. `text` — ordinary source/text patching followed by the same compiler/test
   oracle;
2. `structure` — stable-ID structural editing and normal validation, without
   virtual-candidate qualification or evidence-bound publication;
3. `qualified` — the same structural editing plus immutable revisions, exact
   candidate build/test qualification, preflight and publication bound to the
   qualified state.

The task prompt, source base, retry budget and executable oracle must be identical
across arms. Interface guidance may explain operations but may not provide a
solution hint unavailable to another arm.

## Freeze-before-run rule

`scripts/agent_workflow_experiment.py` defines the manifest and result contracts.
A frozen manifest must contain:

- one immutable source revision;
- one named model/provider configuration;
- one retry budget;
- the exact three arms above;
- at least 16 tasks, with at least three parallel/conflict tasks;
- immutable base revision, task prompt, allowed paths and executable oracle for
  every task;
- a canonical `manifest_sha256` over the complete protocol.

The target is approximately 20 tasks. The validator uses a lower hard floor of
16 so an otherwise valid corpus is not forced to include weak tasks merely to
hit a round number. If fewer than 16 honest matched tasks survive qualification,
the study protocol must be revised in the parent research issue before execution.

Once `status` is `frozen`, any task, prompt, model, retry, source or oracle change
changes the manifest hash and therefore invalidates result files from the old
protocol.

## Candidate task sourcing

Prefer historical `weavec` defects and bounded feature/refactor changes whose
pre-fix state and independent executable oracle can be reconstructed. Candidate
families include formatter corruption, invalid WIR lowering, call/cast typing,
protocol publication, diagnostics and bounded build-driver behavior. Do not copy
the historical patch into the prompt or expose changed-file hunks to the model.
The fixed commit is provenance for the oracle, not a solution demonstration.

Conflict tasks must exercise genuinely independent or overlapping branch work and
set `parallel=true`. Do not manufacture a textual conflict solely to advantage the
qualified arm.

## Result contract

The result file has exactly one summary row for every `(task, arm)` pair. Missing
or duplicate rows are rejected. Each row records separately:

- executable-oracle success;
- unrelated regression status;
- attempt count and repair iterations;
- invalid/non-publishable intermediate states;
- whether recovery was required and whether it succeeded;
- input/output tokens when provider accounting exists;
- tool-operation count;
- wall time;
- retained evidence bytes.

The attempt count may not exceed the frozen retry budget. Failed and invalid
attempts therefore cannot disappear behind unlimited retries.

## Scoring

The scorer reports per-arm reliability and efficiency fields separately. It does
not collapse them into a weighted score. Primary reliability summaries are task
success, unrelated regressions, invalid intermediate states and recovery success.
Tokens, operations, time and retained bytes remain independent cost measures.

The scorer also reports paired success gains/losses for:

- `text -> structure`;
- `structure -> qualified`.

These are descriptive counts, not a statistical significance claim. The parent
research report owns uncertainty analysis and scientific interpretation.

## Commands

Before any production model run:

```bash
python scripts/agent_workflow_experiment.py validate-manifest \
  experiments/agent-workflow/manifest.json --require-frozen
```

The canonical hash can be calculated while constructing the manifest:

```bash
python scripts/agent_workflow_experiment.py hash-manifest \
  experiments/agent-workflow/manifest.json
```

After all three arms have produced complete result rows:

```bash
python scripts/agent_workflow_experiment.py score \
  experiments/agent-workflow/manifest.json \
  experiments/agent-workflow/results.json \
  --output experiments/agent-workflow/score.json
```

## Interpretation boundary

This protocol records experimental evidence; it does not decide whether
Jacquard is superior. In particular, a `structure` win with no further
`qualified` improvement is a valid result and would reject the strongest claim
of the parent study. Likewise, text may remain cheaper or more reliable on local
edits. Negative cases must stay in the corpus and result table.
