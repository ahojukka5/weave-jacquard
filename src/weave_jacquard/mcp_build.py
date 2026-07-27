"""Public Jacquard MCP application."""

from weave_frontend.application import JacquardApp
from weave_frontend.mcp_build import main, mcp

PUBLIC_APP = JacquardApp.compose(mcp)
PUBLIC_CAPABILITY_MANIFEST = PUBLIC_APP.capability_manifest
PUBLIC_TOOL_MANIFEST = PUBLIC_APP.tool_manifest
PUBLIC_APPLICATION_MANIFEST = PUBLIC_APP.application_manifest

__all__ = [
    "PUBLIC_APP",
    "PUBLIC_APPLICATION_MANIFEST",
    "PUBLIC_CAPABILITY_MANIFEST",
    "PUBLIC_TOOL_MANIFEST",
    "main",
]


if __name__ == "__main__":
    main()
