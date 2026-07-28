"""Grammar discovery from the authoritative weavec source and test corpus."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .retained_artifact_io import (
    RetainedArtifactTooLarge,
    read_bounded_regular_bytes,
)
from .sexpr import JsonObject, head_symbol, parse_source, render_node, walk_nodes
from .structural_limits import MAX_SOURCE_BYTES

MAX_GRAMMAR_DIRECTORY_ENTRIES = 16_384
MAX_GRAMMAR_CORPUS_FILES = 4_096
MAX_GRAMMAR_CORPUS_BYTES = 64 * 1024 * 1024
MAX_GRAMMAR_SOURCE_BYTES = MAX_SOURCE_BYTES
MAX_GRAMMAR_FORMS = 16_384
MAX_GRAMMAR_FORM_NAME_BYTES = 256
MAX_GRAMMAR_ARITIES_PER_FORM = 256
MAX_GRAMMAR_PARENTS_PER_FORM = 64
MAX_GRAMMAR_EXAMPLES_PER_FORM = 12
MAX_GRAMMAR_EXAMPLE_ATTEMPTS = 4_096
MAX_GRAMMAR_EXAMPLE_NODES = 256
MAX_GRAMMAR_EXAMPLE_DEPTH = 32
MAX_GRAMMAR_EXAMPLE_BYTES = 64 * 1024
MAX_GRAMMAR_EXAMPLE_TOTAL_BYTES = 16 * 1024 * 1024
MAX_GRAMMAR_PARSE_FAILURES = 256
MAX_GRAMMAR_ERROR_BYTES = 1_024
MAX_GRAMMAR_QUERY_BYTES = 4_096
MAX_GRAMMAR_HELP_LIMIT = 50


@dataclass
class FormInfo:
    name: str
    arities: set[int] = field(default_factory=set)
    parents: set[str] = field(default_factory=set)
    examples: list[dict[str, str]] = field(default_factory=list)
    arities_truncated: bool = False
    parents_truncated: bool = False
    examples_truncated: bool = False

    def as_dict(self, *, limit: int = 6) -> dict[str, Any]:
        return {
            "form": self.name,
            "observed_arities": sorted(self.arities),
            "observed_parents": sorted(self.parents),
            "examples": self.examples[:limit],
            "arities_truncated": self.arities_truncated,
            "parents_truncated": self.parents_truncated,
            "examples_truncated": self.examples_truncated,
            "note": (
                "Observed from the weavec surface corpus. This is guidance, not a "
                "second normative grammar; validate completed programs with weavec."
            ),
        }


class GrammarIndex:
    """Searchable bounded examples inferred from weavec's own surface programs."""

    def __init__(self, source_root: str | Path | None = None) -> None:
        self.source_root = self._resolve_source_root(source_root)
        self.forms: dict[str, FormInfo] = {}
        self.files_discovered = 0
        self.files_considered = 0
        self.files_scanned = 0
        self.bytes_scanned = 0
        self.example_attempts = 0
        self.example_bytes_retained = 0
        self.parse_failure_count = 0
        self.parse_failures: list[dict[str, str]] = []
        self.corpus_truncated = False
        self.forms_truncated = False
        self.examples_truncated = False
        self.corpus_error: str | None = None
        if self.source_root is not None:
            self.refresh()

    @staticmethod
    def _resolve_source_root(source_root: str | Path | None) -> Path | None:
        candidates: list[Path] = []
        if source_root is not None:
            candidates.append(Path(source_root))
        candidates.extend(
            [
                Path.cwd() / "weavec",
                Path.cwd().parent / "weavec",
                Path(__file__).resolve().parents[3] / "weavec",
            ]
        )
        for candidate in candidates:
            if (candidate / "test" / "correctness" / "surface").is_dir():
                return candidate.resolve()
        return None

    def refresh(self) -> None:
        self.forms.clear()
        self.files_discovered = 0
        self.files_considered = 0
        self.files_scanned = 0
        self.bytes_scanned = 0
        self.example_attempts = 0
        self.example_bytes_retained = 0
        self.parse_failure_count = 0
        self.parse_failures.clear()
        self.corpus_truncated = False
        self.forms_truncated = False
        self.examples_truncated = False
        self.corpus_error = None
        if self.source_root is None:
            return

        surface = self.source_root / "test" / "correctness" / "surface"
        paths = self._bounded_surface_paths(surface)
        if paths is None:
            return
        self.files_discovered = len(paths)
        if len(paths) > MAX_GRAMMAR_CORPUS_FILES:
            paths = paths[:MAX_GRAMMAR_CORPUS_FILES]
            self.corpus_truncated = True

        for path in paths:
            self.files_considered += 1
            try:
                size = path.lstat().st_size
            except OSError as exc:
                self._record_failure(path, exc)
                continue
            if size > MAX_GRAMMAR_SOURCE_BYTES:
                self._record_failure(
                    path,
                    ValueError(
                        f"grammar source exceeds {MAX_GRAMMAR_SOURCE_BYTES} bytes"
                    ),
                )
                continue

            remaining = MAX_GRAMMAR_CORPUS_BYTES - self.bytes_scanned
            if remaining <= 0 or size > remaining:
                self.corpus_truncated = True
                break
            read_limit = min(MAX_GRAMMAR_SOURCE_BYTES, remaining)
            try:
                payload = read_bounded_regular_bytes(path, max_bytes=read_limit)
            except RetainedArtifactTooLarge as exc:
                if read_limit < MAX_GRAMMAR_SOURCE_BYTES:
                    self.corpus_truncated = True
                    break
                self._record_failure(path, exc)
                continue
            except Exception as exc:  # corpus diagnostics must not disable help
                self._record_failure(path, exc)
                continue

            self.bytes_scanned += len(payload)
            try:
                source = payload.decode("utf-8")
                root = parse_source(source)
            except Exception as exc:  # corpus diagnostics must not disable help
                self._record_failure(path, exc)
                continue
            self.files_scanned += 1
            self._index_tree(root, path.relative_to(self.source_root))

    def _bounded_surface_paths(self, surface: Path) -> list[Path] | None:
        entries: list[Path] = []
        try:
            for index, path in enumerate(surface.iterdir()):
                if index >= MAX_GRAMMAR_DIRECTORY_ENTRIES:
                    self.corpus_error = (
                        "surface corpus directory exceeds the bounded entry limit "
                        f"{MAX_GRAMMAR_DIRECTORY_ENTRIES}"
                    )
                    self.corpus_truncated = True
                    return None
                if path.suffix == ".weave":
                    entries.append(path)
        except OSError as exc:
            self.corpus_error = self._bounded_error(exc)
            return None
        return sorted(entries, key=lambda path: path.name)

    def _record_failure(self, path: Path, error: Exception) -> None:
        self.parse_failure_count += 1
        if len(self.parse_failures) >= MAX_GRAMMAR_PARSE_FAILURES:
            return
        self.parse_failures.append(
            {
                "path": str(path),
                "error": self._bounded_error(error),
            }
        )

    @staticmethod
    def _bounded_error(error: Exception) -> str:
        text = str(error)
        payload = text.encode("utf-8", errors="replace")
        if len(payload) <= MAX_GRAMMAR_ERROR_BYTES:
            return text
        bounded = payload[:MAX_GRAMMAR_ERROR_BYTES].decode(
            "utf-8",
            errors="ignore",
        )
        return bounded + "…"

    def _index_tree(self, root: JsonObject, path: Path) -> None:
        parent_by_id: dict[str, str] = {}
        for node in walk_nodes(root):
            if node.get("kind") != "list":
                continue
            parent_head = head_symbol(node)
            if parent_head is None:
                continue
            for child in node.get("children", [])[1:]:
                if child.get("kind") == "list":
                    parent_by_id[child["id"]] = parent_head

        for node in walk_nodes(root):
            name = head_symbol(node)
            if name is None:
                continue
            if len(name.encode("utf-8")) > MAX_GRAMMAR_FORM_NAME_BYTES:
                self.forms_truncated = True
                continue
            info = self.forms.get(name)
            if info is None:
                if len(self.forms) >= MAX_GRAMMAR_FORMS:
                    self.forms_truncated = True
                    continue
                info = FormInfo(name)
                self.forms[name] = info

            arity = max(0, len(node["children"]) - 1)
            if arity not in info.arities:
                if len(info.arities) < MAX_GRAMMAR_ARITIES_PER_FORM:
                    info.arities.add(arity)
                else:
                    info.arities_truncated = True

            parent = parent_by_id.get(node["id"])
            if (
                parent
                and len(parent.encode("utf-8")) <= MAX_GRAMMAR_FORM_NAME_BYTES
                and parent not in info.parents
            ):
                if len(info.parents) < MAX_GRAMMAR_PARENTS_PER_FORM:
                    info.parents.add(parent)
                else:
                    info.parents_truncated = True

            if len(info.examples) >= MAX_GRAMMAR_EXAMPLES_PER_FORM:
                info.examples_truncated = True
                continue
            if self.example_attempts >= MAX_GRAMMAR_EXAMPLE_ATTEMPTS:
                info.examples_truncated = True
                self.examples_truncated = True
                continue
            self.example_attempts += 1
            if not self._example_render_within_limits(node):
                info.examples_truncated = True
                self.examples_truncated = True
                continue
            try:
                sexpr = render_node(node)
            except Exception:
                info.examples_truncated = True
                self.examples_truncated = True
                continue
            example_bytes = len(sexpr.encode("utf-8"))
            if example_bytes > MAX_GRAMMAR_EXAMPLE_BYTES:
                info.examples_truncated = True
                self.examples_truncated = True
                continue
            if (
                self.example_bytes_retained + example_bytes
                > MAX_GRAMMAR_EXAMPLE_TOTAL_BYTES
            ):
                info.examples_truncated = True
                self.examples_truncated = True
                continue
            example = {
                "source": str(path),
                "sexpr": sexpr,
            }
            if example not in info.examples:
                info.examples.append(example)
                self.example_bytes_retained += example_bytes

    @staticmethod
    def _example_render_within_limits(root: JsonObject) -> bool:
        node_count = 0
        upper_bytes = 0
        stack: list[tuple[JsonObject, int]] = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            node_count += 1
            if (
                node_count > MAX_GRAMMAR_EXAMPLE_NODES
                or depth > MAX_GRAMMAR_EXAMPLE_DEPTH
            ):
                return False

            if node.get("kind") == "list":
                children = node.get("children", [])
                upper_bytes += 2
                if children:
                    upper_bytes += max(0, len(children) - 1) * (2 * depth + 3)
                    for child in reversed(children):
                        stack.append((child, depth + 1))
            else:
                kind = node.get("kind")
                value = node.get("value")
                if kind == "string":
                    upper_bytes += 2 + 2 * len(str(value).encode("utf-8"))
                elif kind == "boolean":
                    upper_bytes += 5
                elif kind == "float":
                    upper_bytes += len(repr(float(value)).encode("utf-8"))
                else:
                    upper_bytes += len(str(value).encode("utf-8"))

            if upper_bytes > MAX_GRAMMAR_EXAMPLE_BYTES:
                return False
        return True

    def help(
        self,
        *,
        form: str | None = None,
        query: str | None = None,
        parent_form: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        self._validate_limit(limit)
        self._validate_query_value("form", form)
        self._validate_query_value("query", query)
        self._validate_query_value("parent_form", parent_form)
        status = self.status()
        if form:
            info = self.forms.get(form)
            if info is None:
                matches = self.search(form, limit=limit)
                return {
                    **status,
                    "found": False,
                    "requested_form": form,
                    "matches": matches,
                    "next": "Call grammar_help with one of the matching form names.",
                }
            return {**status, "found": True, **info.as_dict(limit=limit)}

        if parent_form:
            children = [
                info.as_dict(limit=2)
                for info in self.forms.values()
                if parent_form in info.parents
            ]
            children.sort(key=lambda item: item["form"])
            return {
                **status,
                "parent_form": parent_form,
                "observed_child_forms": children[:limit],
            }

        if query:
            return {
                **status,
                "query": query,
                "matches": self.search(query, limit=limit),
            }

        return {
            **status,
            "usage": [
                "grammar_help(form='fn')",
                "grammar_help(form='while')",
                "grammar_help(parent_form='program')",
                "grammar_help(query='ptr')",
            ],
            "workflow": (
                "Inspect examples before creating an unfamiliar form. Build it one node "
                "at a time, inspect the result, then call program_validate."
            ),
        }

    def search(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        self._validate_limit(limit)
        self._validate_query_value("query", query)
        needle = query.casefold()
        matches = [
            info
            for name, info in self.forms.items()
            if needle in name.casefold()
            or any(needle in parent.casefold() for parent in info.parents)
            or any(
                needle in example["sexpr"].casefold()
                for example in info.examples
            )
        ]
        matches.sort(
            key=lambda item: (
                not item.name.casefold().startswith(needle),
                item.name,
            )
        )
        return [info.as_dict(limit=2) for info in matches[:limit]]

    @staticmethod
    def _validate_limit(limit: Any) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_GRAMMAR_HELP_LIMIT
        ):
            raise ValidationError(
                "INVALID_GRAMMAR_HELP_LIMIT",
                f"limit must be between 1 and {MAX_GRAMMAR_HELP_LIMIT}",
            )

    @staticmethod
    def _validate_query_value(name: str, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, str):
            raise ValidationError(
                "INVALID_GRAMMAR_HELP_QUERY",
                f"{name} must be a string or null",
            )
        if len(value.encode("utf-8")) > MAX_GRAMMAR_QUERY_BYTES:
            raise ValidationError(
                "INVALID_GRAMMAR_HELP_QUERY",
                f"{name} exceeds {MAX_GRAMMAR_QUERY_BYTES} UTF-8 bytes",
            )

    def hint_for_node(self, node: JsonObject) -> dict[str, Any] | None:
        name = head_symbol(node)
        if name is None:
            return None
        info = self.forms.get(name)
        if info is None:
            return {
                "form": name,
                "known": False,
                "message": "Form was not observed in the configured weavec surface corpus.",
            }
        actual_arity = len(node["children"]) - 1
        return {
            "form": name,
            "known": True,
            "actual_arity": actual_arity,
            "observed_arities": sorted(info.arities),
            "complete_by_observed_arity": actual_arity in info.arities,
            "examples": info.examples[:2],
            "arities_truncated": info.arities_truncated,
            "parents_truncated": info.parents_truncated,
            "examples_truncated": info.examples_truncated,
        }

    def status(self) -> dict[str, Any]:
        return {
            "source_root": str(self.source_root) if self.source_root else None,
            "available": self.source_root is not None and self.corpus_error is None,
            "files_discovered": self.files_discovered,
            "files_considered": self.files_considered,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "forms_indexed": len(self.forms),
            "example_attempts": self.example_attempts,
            "example_bytes_retained": self.example_bytes_retained,
            "parse_failure_count": self.parse_failure_count,
            "parse_failures_retained": len(self.parse_failures),
            "corpus_truncated": self.corpus_truncated,
            "forms_truncated": self.forms_truncated,
            "examples_truncated": self.examples_truncated,
            "corpus_error": self.corpus_error,
            "limits": {
                "directory_entries": MAX_GRAMMAR_DIRECTORY_ENTRIES,
                "files": MAX_GRAMMAR_CORPUS_FILES,
                "source_bytes": MAX_GRAMMAR_SOURCE_BYTES,
                "total_source_bytes": MAX_GRAMMAR_CORPUS_BYTES,
                "forms": MAX_GRAMMAR_FORMS,
                "form_name_bytes": MAX_GRAMMAR_FORM_NAME_BYTES,
                "arities_per_form": MAX_GRAMMAR_ARITIES_PER_FORM,
                "parents_per_form": MAX_GRAMMAR_PARENTS_PER_FORM,
                "examples_per_form": MAX_GRAMMAR_EXAMPLES_PER_FORM,
                "example_attempts": MAX_GRAMMAR_EXAMPLE_ATTEMPTS,
                "example_nodes": MAX_GRAMMAR_EXAMPLE_NODES,
                "example_depth": MAX_GRAMMAR_EXAMPLE_DEPTH,
                "example_bytes": MAX_GRAMMAR_EXAMPLE_BYTES,
                "total_example_bytes": MAX_GRAMMAR_EXAMPLE_TOTAL_BYTES,
                "parse_failures": MAX_GRAMMAR_PARSE_FAILURES,
                "query_bytes": MAX_GRAMMAR_QUERY_BYTES,
                "help_limit": MAX_GRAMMAR_HELP_LIMIT,
            },
            "authority": "weavec surface sources and the weavec frontend validator",
        }
