# Sandbox process policy

Jacquard behavioral tests execute one native process inside the canonical
Bubblewrap namespace. The sandbox does not permit the tested program to create
child processes or threads.

## Enforcement sequence

The outer launcher must be allowed to create the Bubblewrap namespace before a
process-count limit is applied. Jacquard therefore launches:

```text
host Jacquard process
→ bubblewrap namespace setup
→ clean inner environment
→ prlimit --nproc=1:1
→ /app/program
```

Applying `RLIMIT_NPROC` in Python's `preexec_fn` would constrain Bubblewrap
itself and can prevent namespace setup. Applying it through `prlimit` inside the
namespace launch path constrains the program instead.

`prlimit` from util-linux is a mandatory sandbox dependency. The backend is
unavailable when either Bubblewrap or `prlimit` is absent or non-executable.

## Admission probe

Finding the executables is not sufficient evidence. `capabilities()` performs:

1. the Bubblewrap version probe;
2. a minimal isolated `/usr/bin/true` execution;
3. a process-policy probe whose shell attempts to create a subshell under
   `RLIMIT_NPROC=1`.

A shell cannot reliably continue after the kernel refuses that fork. In
particular, `/bin/sh` may terminate with exit code `2` and `Cannot fork` instead
of returning control to an `if` statement. The admission probe therefore treats
only a recognized fork-denial diagnostic as success. If the subshell runs, the
probe exits with a dedicated failure code. Any unrelated nonzero exit still
fails closed.

The backend reports `available=true` only when the isolated command succeeds and
the process-creation attempt is denied. Privilege contexts that bypass
`RLIMIT_NPROC`, including an unsuitable root execution context, therefore fail
closed.

## Capability evidence

The policy document reports:

```text
process_creation = deny
max_processes = 1
process_limit_backend = prlimit-RLIMIT_NPROC
```

The policy hash binds these fields. Retained behavioral-run evidence binds that
policy hash and the complete policy object.

`resource_limits.process_count=true` means that the admitted backend proved the
single-process rule. It must not be interpreted as cgroup-based accounting.

## Remaining boundary

The process rule prevents fork- and thread-based multiplication of per-process
limits. Jacquard still reports:

```text
aggregate_memory = false
seccomp = false
```

Address-space and CPU limits are POSIX resource limits inherited by the target.
They are not an aggregate cgroup quota. The namespace also exposes a broad
read-only host runtime surface under `/usr`, `/bin`, libraries, and related
loader paths.

A later hardened backend should add:

- cgroup v2 aggregate memory and CPU accounting;
- a PID cgroup as defense in depth;
- a reviewed seccomp syscall profile;
- a minimized immutable runtime image instead of broad host runtime mounts.

Until those protections are implemented, the canonical backend is suitable for
single-process untrusted test programs within the explicitly reported policy,
but its evidence must not be described as seccomp- or cgroup-backed isolation.

## Resource-limit validation

Every `SandboxLimits` field must be a positive non-boolean integer. Invalid
limits are rejected before process launch with `INVALID_SANDBOX_LIMIT`.

This validation covers:

- wall-clock timeout;
- address-space limit;
- captured-output limit;
- generated-file limit.

The process ceiling is fixed by the sandbox policy rather than selected by an
individual test target.
