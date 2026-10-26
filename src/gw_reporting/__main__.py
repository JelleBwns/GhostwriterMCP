"""Local MCP entry point: python -m gw_reporting (no HTTP server required)."""

import sys

from .logging import configure_logging
from .mcp import mcp


def main() -> None:
    """Serve MCP over stdin/stdout; diagnostics are written to stderr."""
    if len(sys.argv) > 1 and sys.argv[1] == "tools":
        from .cli import run

        run(sys.argv[2:])
        return
    configure_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
