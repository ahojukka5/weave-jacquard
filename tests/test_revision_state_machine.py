"""Generated histories checked against a separate head/ancestry model."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zlib
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from weave_frontend import SExpressionWorkspace, ValidationError, WeaveFrontendError
from weave_frontend.agent_checkpoint import AgentCheckpointRegistry
from weave_frontend.batch_edit import EditBatchExecutor
from weave_frontend.builds import MetadataBuildTargetRegistry
from weave_frontend.merge_policy import MergePolicyRegistry
from weave_frontend.merges import MergePreviewService
from weave_frontend.revert import RevertService
from weave_frontend.task_contracts import TaskContractRegistry
from weave_frontend.test_targets import TestTargetRegistry

BRANCHES = st.sampled_from(("main", "left", "right"))


def digest(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


class RevisionHistory(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.directory = tempfile.TemporaryDirectory(prefix="jacquard-state-")
        self.workspace = SExpressionWorkspace(Path(self.directory.name) / "history.db")
        _, initial = self.workspace.initialize("model")
        program = self.workspace.create_program("model", "main", "main.weave", program_name="model")
        self.root = str(program["node_id"])
        head = str(program["revision_id"])
        self.parents = {initial: (None, None), head: (initial, None)}
        self.heads = {"main": head}
        for name in ("left", "right"):
            self.workspace.create_branch("model", name, expected_revision_id=head)
            self.heads[name] = head
        self.counter = 0
        self.historical_rows = {}
        self.previews = MergePreviewService(self.workspace)
        self.reverts = RevertService(self.workspace, self.previews)

    def teardown(self):
        self.workspace.close()
        self.directory.cleanup()

    def dump(self):
        return tuple(self.workspace.db.connection.iterdump())

    def publish(self, branch, call, *, second=None, allow_rejection=False):
        before = self.dump()
        parent = self.heads[branch]
        try:
            result = call()
        except WeaveFrontendError:
            if not allow_rejection:
                raise
            assert self.dump() == before, "a rejected operation mutated durable state"
            return None
        revision = str(result["revision_id"] if isinstance(result, dict) else result.revision_id)
        assert revision not in self.parents
        self.parents[revision] = (parent, second)
        self.heads[branch] = revision
        return result

    def has_program(self, branch):
        return any(
            d["document"] == "main.weave" for d in self.workspace.list_documents("model", branch)
        )

    @rule(branch=BRANCHES, number=st.integers(0, 3))
    def create_document(self, branch, number):
        name = f"extra{number}.weave"
        if any(d["document"] == name for d in self.workspace.list_documents("model", branch)):
            return
        self.publish(
            branch,
            lambda: self.workspace.create_program(
                "model",
                branch,
                name,
                program_name=f"extra{number}",
                expected_revision_id=self.heads[branch],
            ),
        )

    @rule(branch=BRANCHES, number=st.integers(-100, 100))
    def edit_batch(self, branch, number):
        if not self.has_program(branch):
            return
        self.publish(
            branch,
            lambda: EditBatchExecutor(self.workspace).apply(
                "model",
                branch,
                "main.weave",
                [
                    {"op": "create_form", "parent": self.root, "head": "item", "as": "item"},
                    {"op": "add_atom", "parent": "@item", "kind": "integer", "value": number},
                ],
                expected_revision_id=self.heads[branch],
            ),
        )

    @rule(branch=BRANCHES, value=st.integers(-50, 50))
    def edit_atom(self, branch, value):
        if not self.has_program(branch):
            return
        atoms = self.workspace.find_nodes("model", branch, "main.weave", kind="integer")
        if not atoms:
            return
        node = atoms[0]["node_id"]
        self.publish(
            branch,
            lambda: self.workspace.set_atom(
                "model", branch, "main.weave", node, value, expected_revision_id=self.heads[branch]
            ),
        )

    @rule(branch=BRANCHES)
    def invalid_batch_rolls_back(self, branch):
        if not self.has_program(branch):
            return
        before = self.dump()
        try:
            EditBatchExecutor(self.workspace).apply(
                "model",
                branch,
                "main.weave",
                [
                    {"op": "create_form", "parent": self.root, "head": "temporary"},
                    {"op": "set_atom", "node": self.root, "value": 3},
                ],
                expected_revision_id=self.heads[branch],
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("invalid list-as-atom mutation succeeded")
        assert self.dump() == before

    @rule(branch=BRANCHES)
    def stale_publication_rolls_back(self, branch):
        old = next(rev for rev in self.parents if rev != self.heads[branch])
        before = self.dump()
        try:
            self.workspace.create_form(
                "model", branch, "main.weave", self.root, "stale", expected_revision_id=old
            )
        except ValidationError as error:
            assert error.code in {"STALE_BRANCH_HEAD", "STALE_REVISION"}
        else:
            raise AssertionError("stale mutation succeeded")
        assert self.dump() == before

    @rule(source=BRANCHES, destination=BRANCHES)
    def merge(self, source, destination):
        if source == destination:
            return
        second = self.heads[source]
        self.publish(
            destination,
            lambda: self.workspace.merge(
                "model",
                target_branch=destination,
                source_branch=source,
                expected_target_head=self.heads[destination],
                expected_source_head=second,
            ),
            second=second,
            allow_rejection=True,
        )

    @rule(branch=BRANCHES)
    def revert_latest(self, branch):
        selected = self.heads[branch]
        before = self.dump()
        try:
            preview = self.reverts.preview("model", branch, selected)
        except ValidationError:
            assert self.dump() == before
            return
        assert self.dump() == before, "preview published durable state"
        if preview["revertible"] and preview["would_change_branch"]:
            self.publish(
                branch,
                lambda: self.reverts.revert(
                    "model", branch, selected, preview_id=preview["preview_id"]
                ),
            )

    @rule(source=BRANCHES)
    def historical_fork(self, source):
        if self.counter >= 5:
            return
        self.counter += 1
        name = f"fork-{self.counter}"
        selected = self.heads[source]
        result = self.workspace.create_branch_at_revision("model", name, selected)
        assert result == selected
        self.heads[name] = selected

    @rule(branch=BRANCHES, value=st.integers(0, 50))
    def version_context(self, branch, value):
        self.publish(
            branch,
            lambda: self.workspace.add_context(
                "model",
                branch,
                scope_kind="project",
                scope_name="model",
                title="generated context",
                body=f"value={value}",
            ),
        )

    @rule(branch=BRANCHES)
    def checkpoint(self, branch):
        self.publish(
            branch,
            lambda: AgentCheckpointRegistry(self.workspace).create(
                "model",
                branch,
                objective="Check revision invariants",
                summary="Generated checkpoint",
                status="in_progress",
                expected_revision_id=self.heads[branch],
            ),
        )

    @rule(branch=BRANCHES, allowed=st.booleans())
    def policy(self, branch, allowed):
        self.publish(
            branch,
            lambda: MergePolicyRegistry(self.workspace).set(
                "model",
                branch,
                require_preflight=False,
                require_affected_validation=False,
                allow_uncovered_documents=allowed,
            ),
        )

    @rule(branch=BRANCHES)
    def task(self, branch):
        self.publish(
            branch,
            lambda: TaskContractRegistry(self.workspace).create(
                "model",
                branch,
                "generated-task",
                owner="tester",
                objective="Check histories",
                allowed_documents=["main.weave"],
                expected_revision_id=self.heads[branch],
            ),
            allow_rejection=True,
        )

    @rule(branch=BRANCHES, value=st.integers(0, 20))
    def test_definition(self, branch, value):
        if not self.has_program(branch):
            return
        target = self.publish(
            branch,
            lambda: MetadataBuildTargetRegistry(self.workspace).set(
                "model", branch, "generated", "main.weave"
            ),
        )
        if target is not None:
            self.publish(
                branch,
                lambda: TestTargetRegistry(self.workspace).set(
                    "model",
                    branch,
                    "generated",
                    "generated",
                    expected_stdout=str(value),
                    expected_revision_id=self.heads[branch],
                ),
            )

    @invariant()
    def persistent_history_matches_reference(self):
        connection = self.workspace.db.connection
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
        actual_heads = {
            row["name"]: row["head_revision_id"]
            for row in connection.execute("SELECT name, head_revision_id FROM branches")
        }
        assert actual_heads == self.heads
        actual_parents = {
            row["id"]: (row["parent1_id"], row["parent2_id"])
            for row in connection.execute("SELECT * FROM revisions")
        }
        assert actual_parents == self.parents
        assert not list(
            connection.execute("""SELECT r.id FROM revisions r JOIN revisions p
            ON p.id=r.parent1_id OR p.id=r.parent2_id WHERE r.project_id != p.project_id""")
        )
        # The independent model walks its own recorded parents, rather than a
        # production ancestry helper or branch-head query.
        for head in self.heads.values():
            pending, seen = [head], set()
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                pending.extend(parent for parent in self.parents[current] if parent is not None)
            assert seen <= self.parents.keys()
        for table in (
            "revisions",
            "operations",
            "module_snapshots_compressed",
            "documents",
            "revision_documents",
        ):
            rows = set(tuple(row) for row in connection.execute(f"SELECT * FROM {table}"))
            assert self.historical_rows.get(table, set()) <= rows, f"{table} history mutated"
            self.historical_rows[table] = rows
        states = {}
        for row in connection.execute("SELECT * FROM module_snapshots_compressed"):
            raw = bytes(row["ast_blob"])
            text = zlib.decompress(raw[4:]) if raw[:4] == b"WJZ1" else raw[4:]
            tree = json.loads(text)
            assert digest(tree) == row["ast_hash"]
            states.setdefault(row["revision_id"], {})[row["qualified_name"]] = tree
        for row in connection.execute("SELECT id, root_hash FROM revisions"):
            assert digest(states.get(row["id"], {})) == row["root_hash"]
        for branch in self.heads:
            for document in self.workspace.list_documents("model", branch):
                name = document["document"]
                first = self.workspace.render("model", branch, name)
                assert first == self.workspace.render("model", branch, name)


TestRevisionHistory = RevisionHistory.TestCase
TestRevisionHistory.settings = settings(
    max_examples=100 if os.environ.get("JACQUARD_EXTENDED_PROPERTIES") else 25,
    stateful_step_count=150 if os.environ.get("JACQUARD_EXTENDED_PROPERTIES") else 30,
    deadline=None,
    database=None,
    derandomize=True,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
