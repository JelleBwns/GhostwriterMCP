"""Offline administration: inspect the fixed catalog without API requests."""

import argparse
import json

from fastmcp.tools import FunctionTool

from .catalog import inventory
from .config import settings
from .registry import effective_tools


def run(args: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Offline Ghostwriter reporting tool catalog")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--enabled-only", action="store_true")
    parser.add_argument("--describe", metavar="TOOL_NAME")
    opts = parser.parse_args(args)
    if opts.describe:
        from .mcp import CONVENIENCE

        fn = CONVENIENCE.get(opts.describe)
        if fn is None:
            parser.error("Unknown reporting tool")
        value = FunctionTool.from_function(fn)
        print(
            json.dumps(
                {
                    "name": opts.describe,
                    "description": value.description,
                    "inputSchema": value.parameters,
                },
                indent=2,
            )
        )
        return
    from .mcp import CONVENIENCE

    enabled = effective_tools(
        CONVENIENCE, settings().gw_enabled_tools, settings().gw_disabled_tools
    )
    items = inventory()
    if opts.enabled_only:
        items = [row for row in items if row["name"] in enabled]
    if opts.json:
        print(json.dumps({"tools": items}, indent=2))
    else:
        for row in items:
            print(
                f"{row['name']}\t{row['category']}\t{'enabled' if row['name'] in enabled else 'disabled'}"
            )
