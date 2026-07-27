"""Public Jacquard entry point for the Weave MCP server."""

from weave_frontend.mcp_build import main, mcp
from weave_frontend.mcp_capabilities import install_public_capabilities

PUBLIC_CAPABILITY_MANIFEST = install_public_capabilities(mcp)

__all__ = ["PUBLIC_CAPABILITY_MANIFEST", "main"]


if __name__ == "__main__":
    main()
