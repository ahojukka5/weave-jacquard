"""Public Jacquard entry point for the Weave MCP server."""

import weave_frontend.mcp_concurrent_nodes as _mcp_concurrent_nodes
from weave_frontend import mcp_build_discovery as _mcp_build_discovery
from weave_frontend import mcp_concurrent_branches as _mcp_concurrent_branches
from weave_frontend import mcp_concurrent_context as _mcp_concurrent_context
from weave_frontend import mcp_concurrent_targets as _mcp_concurrent_targets
from weave_frontend import mcp_policy as _mcp_policy
from weave_frontend import mcp_preflight as _mcp_preflight
from weave_frontend import mcp_resume_snapshot as _mcp_resume_snapshot
from weave_frontend import mcp_revision_reads as _mcp_revision_reads
from weave_frontend.mcp_build import main

_ = (
    _mcp_concurrent_nodes,
    _mcp_concurrent_branches,
    _mcp_build_discovery,
    _mcp_concurrent_targets,
    _mcp_policy,
    _mcp_concurrent_context,
    _mcp_preflight,
    _mcp_resume_snapshot,
    _mcp_revision_reads,
)

__all__ = ["main"]


if __name__ == "__main__":
    main()
