"""Explicit local transport entry point, independent of the PORT environment."""

from server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
