"""Grammar discovery from the authoritative weavec2 source and test corpus."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sexpr import JsonObject, head_symbol, parse_source, render_node, walk_nodes


@dataclass
class FormInfo:
    name: str
    arities: set[int] = field(default_factory=set)
    parents: set[str] = field(default_factory=set)
    examples: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self, *, limit: int = 6) -> dict[str, Any]:
        return {
            "form": self.name,
            "observed_arities": sorted(self.arities),
            "observed_parents": sorted(self.parents),
            "examples": self.examples[:limit],
            "note": (
                "Observed from the weavec2 surface corpus. This is guidance, not a "
                "second normative grammar; validate completed programs with weavec2."
            ),
        }


class GrammarIndex:
    """Searchable examples inferred from weavec2's own surface programs."""

    def __init__(self, source_root: str | Path | None = None) -> None:
        self.source_root = self._resolve_source_root(source_root)
        self.forms: dict[str, FormInfo] = {}
        self.files_scanned = 0
        self.parse_failures: list[dict[str, str]] = []
        if self.source_root is not None:
            self.refresh()

    @staticmethod
    def _resolve_source_root(source_root: str | Path | None) -> Path | None:
        candidates: list[Path] = []
        if source_root is not None:
            candidates.append(Path(source_root))
        candidates.extend(
            [
                Path.cwd() / "weavec2",
                Path.cwd().parent / "weavec2",
                Path(__file__).resolve().parents[3] / "weavec2",
            ]
        )
        for candidate in candidates:
            if (candidate / "test" / "correctness" / "surface").is_dir():
                return candidate.resolve()
        return None

    def refresh(self) -> None:
        self.forms.clear()
        self.files_scanned = 0
        self.parse_failures.clear()
        if self.source_root is None:
            return
        surface = self.source_root / "test" / "correctness" / "surface"
        for path in sorted(surface.glob("*.weave")):
            try:
                root = parse_source(path.read_text(encoding="utf-8"))
            except Exception as exc:  # corpus diagnostics must not disable help
                self.parse_failures.append({"path": str(path), "error": str(exc)})
                continue
            self.files_scanned += 1
            self._index_tree(root, path.relative_to(self.source_root))

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
            info = self.forms.setdefault(name, FormInfo(name))
            info.arities.add(max(0, len(node["children"]) - 1))
            parent = parent_by_id.get(node["id"])
            if parent:
                info.parents.add(parent)
            example = {
                "source": str(path),
                "sexpr": render_node(node),
            }
            if example not in info.examples and len(info.examples) < 12:
                info.examples.append(example)

    def help(
        self,
        *,
        form: str | None = None,
        query: str | None = None,
        parent_form: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
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
            return {**status, "query": query, "matches": self.search(query, limit=limit)}

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
        needle = query.casefold()
        matches = [
            info
            for name, info in self.forms.items()
            if needle in name.casefold()
            or any(needle in parent.casefold() for parent in info.parents)
            or any(needle in example["sexpr"].casefold() for example in info.examples)
        ]
        matches.sort(key=lambda item: (not item.name.casefold().startswith(needle), item.name))
        return [info.as_dict(limit=2) for info in matches[:limit]]

    def hint_for_node(self, node: JsonObject) -> dict[str, Any] | None:
        name = head_symbol(node)
        if name is None:
            return None
        info = self.forms.get(name)
        if info is None:
            return {
                "form": name,
                "known": False,
                "message": "Form was not observed in the configured weavec2 surface corpus.",
            }
        actual_arity = len(node["children"]) - 1
        return {
            "form": name,
            "known": True,
            "actual_arity": actual_arity,
            "observed_arities": sorted(info.arities),
            "complete_by_observed_arity": actual_arity in info.arities,
            "examples": info.examples[:2],
        }

    def status(self) -> dict[str, Any]:
        return {
            "source_root": str(self.source_root) if self.source_root else None,
            "available": self.source_root is not None,
            "files_scanned": self.files_scanned,
            "forms_indexed": len(self.forms),
            "parse_failure_count": len(self.parse_failures),
            "authority": "weavec2 surface sources and the weavec2 frontend validator",
        }
