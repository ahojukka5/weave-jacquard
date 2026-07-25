"""MCP server extension for revision-pinned native program builds."""

from __future__ import annotations

import os
from functools import lru_cache

from .compiler_bridge import CompilerBridge
from .mcp_server import _result, mcp, workspace


@lru_cache(maxsize=1)
def compiler_bridge() -> CompilerBridge:
    return CompilerBridge(
        workspace(),
        build_root=os.environ.get("WEAVE_BUILD_ROOT"),
    )


@mcp.tool()
def program_build(
    project: str,
    document: str,
    branch: str = "main",
    revision_id: str | None = None,
    target: str | None = None,
) -> dict[str, object]:
    """Build one immutable database revision into a native executable."""

    return _result(
        lambda: compiler_bridge().build(
            project,
            document,
            branch=branch,
            revision_id=revision_id,
            target=target,
        )
    )


@mcp.tool()
def build_get(build_id: str) -> dict[str, object]:
    """Return a stored build manifest and its artifact paths."""

    return _result(lambda: compiler_bridge().get(build_id))


def main() -> None:
    """Run the extended MCP server over stdio."""

    mcp.run()


if __name__ == "__main__":
    main()
