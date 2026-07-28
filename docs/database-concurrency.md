# Database concurrency

Jacquard uses SQLite in WAL mode with short `BEGIN IMMEDIATE` write transactions.
Readers can continue while a writer is active, but SQLite still permits only one
writer at a time.

## Busy policy

Every `Database` connection configures the same explicit busy timeout through
both the Python connection timeout and `PRAGMA busy_timeout`.

The default is:

```text
5,000 ms
```

Internal tests and embedded applications may select another non-negative timeout
through `Database(..., busy_timeout_ms=...)`. The effective value is retained on
the connection object and is included in contention errors.

## Agent-facing failure

When `BEGIN IMMEDIATE`, a statement, or commit cannot acquire the required SQLite
lock before the timeout, the transaction rolls back and raises
`DatabaseBusyError`. MCP serializes it as:

```json
{
  "code": "DATABASE_BUSY",
  "message": "database remained busy or locked for the configured timeout",
  "node_id": null,
  "retryable": true,
  "busy_timeout_ms": 5000
}
```

Jacquard recognizes both primary and extended `SQLITE_BUSY` and `SQLITE_LOCKED`
result codes. The message fallback exists only for Python or SQLite builds that do
not expose `sqlite_errorcode`.

Non-contention `sqlite3.OperationalError` values are not relabeled. They roll back
and retain their original exception so schema mistakes and other operational
faults cannot be mistaken for harmless contention.

## Retry rule

Jacquard does not retry a complete mutation inside the database layer. A retry
must restart the application operation so it rereads current branch heads,
revalidates expected revisions, and recomputes any candidate state before
publication. Retrying only the final SQL statements could publish work derived
from stale state.

Callers should use bounded backoff and treat `DATABASE_BUSY` as transient. Every
other error keeps its existing retry semantics.

## Evidence

Regression tests hold a writer lock through both an independent connection and a
separate process. They verify timeout evidence, rollback, subsequent connection
reuse, the MCP error envelope, and preservation of unrelated SQLite operational
errors.
