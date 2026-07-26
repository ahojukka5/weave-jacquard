"""Public Jacquard entry point for the Weave MCP server."""

from weave_frontend import mcp_policy as _mcp_policy
from weave_frontend import mcp_preflight as _mcp_preflight
from weave_frontend.mcp_build import main

_ = (_mcp_policy, _mcp_preflight)

__all__ = ["main"]


if __name__ == "__main__":
    main()
