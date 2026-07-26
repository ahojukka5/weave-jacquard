"""Public Jacquard entry point for the Weave MCP server."""

from weave_frontend import mcp_preflight as _mcp_preflight
from weave_frontend.mcp_build import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
