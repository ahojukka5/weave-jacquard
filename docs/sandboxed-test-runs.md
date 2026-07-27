# Strict sandboxed behavioral test runs

Jacquard can execute one revisioned behavioral test only through a successfully
probed isolation backend. The public interface does not expose an unrestricted
program runner and never falls back to ordinary host subprocess execution.

## Workflow

Define the program, named build target, and behavioral test first. Then inspect
sandbox support and execute the test at the exact reviewed revision:

```text
sandbox_capabilities()

test_run(
  project = "demo",
  test_target = "cli-smoke",
  branch = "main",
  revision_id = "<reviewed-revision>"
)
```

Use `test_run_get` to re-read and verify one retained run manifest. Use
`test_run_output_page` for bounded stdout or stderr bytes. Public MCP responses
never include server-local artifact paths.

## Exact identity

Every run binds all of the following evidence:

- project, branch, and immutable `revision_id`;
- test name and deterministic `definition_hash`;
- retained compiler `build_id` and build revision hash;
- compiler and executable SHA-256 hashes;
- sandbox backend, reported policy, and `policy_hash`;
- exact resource limits;
- expected exit status and output hashes;
- observed termination, output sizes, and output hashes;
- each individual behavioral assertion and the final pass status.

Running a test does not mutate the project, advance a branch, or create a new
program revision. Run evidence is stored separately from revisioned source and
test-definition metadata.

## Isolation contract

The initial backend is Linux Bubblewrap. `sandbox_capabilities` is authoritative:
execution is allowed only when its real isolation probe returns
`available = true`.

The backend currently enforces:

- new user, mount, PID, network, IPC, and UTS namespaces;
- denied host networking through a separate network namespace;
- dropped Linux capabilities;
- an empty environment followed by a small explicit environment;
- read-only bindings for required host runtime paths;
- only the executable bound under `/app`;
- ephemeral writable tmpfs mounts at `/tmp` and `/work`;
- wall-clock timeout;
- address-space and CPU-time limits;
- generated-file-size, open-file, process-count, and core-dump limits;
- a combined bounded stdout and stderr capture limit;
- process-group termination on timeout or excess output.

The current backend reports `seccomp = false`. Callers must not infer syscall
filtering, stronger kernel hardening, or any protection not explicitly present
in the capability response.

## Refusal versus behavioral failure

These outcomes are intentionally distinct:

- `SANDBOX_UNAVAILABLE`: strict isolation could not be proven, so no program was
  executed and no behavioral run manifest was published;
- `TEST_BUILD_FAILED`: the exact revision did not produce a verified executable,
  so no behavioral run manifest was published;
- `passed = false`: the sandbox did execute the verified build, and the observed
  behavior disagreed with one or more stored expectations. This is valid,
  immutable evidence rather than an infrastructure error;
- `passed = true`: every stored behavioral assertion matched the observed run.

A failed behavioral assertion is retained because it is often the most useful
evidence for an autonomous repair loop.

## Immutable evidence

Each execution creates a random run identity and a dedicated retained directory
containing:

- `run-manifest.json`;
- `stdout.bin`;
- `stderr.bin`.

The outputs are hashed in the manifest. Reads verify the manifest identity,
artifact paths, file existence, artifact hashes, and observed output hashes.
Publication verifies staged evidence first and then publishes it atomically under
an exclusive run lock. Existing run identities are never overwritten.

The manifest hash returned by `test_run` and `test_run_get` identifies the exact
retained manifest. It is evidence of one execution, not a project revision or a
replacement for the test definition hash.

## Bounded output reads

`test_run_output_page` accepts:

- `run_id`;
- `stream = "stdout"` or `"stderr"`;
- `start_byte`;
- `max_bytes`.

It verifies the complete retained run before returning a page. The response
contains base64 bytes, UTF-8 text when the selected page is valid UTF-8, the total
stream size, continuation, EOF status, the complete stream hash, and the
manifest hash. A page is only a bounded view; its hash fields identify the whole
retained evidence.

## Operational requirements

- Install Bubblewrap on Linux hosts that are permitted to execute tests.
- Call `sandbox_capabilities` before relying on execution availability.
- Pin `revision_id` when testing reviewed or merge-candidate work.
- Treat `definition_hash`, build identity, executable hash, and policy hash as a
  single evidence boundary.
- Never interpret timestamps or repeated passing runs as proof that a different
  revision, definition, executable, or sandbox policy is correct.
