"""The fixed reporting catalog. No schema-wide operation generation."""

from .registry import TOOL_METADATA


def inventory() -> list[dict]:
    from .mcp import CONVENIENCE

    return [
        {
            "name": name,
            "category": TOOL_METADATA[name][0],
            "writes": TOOL_METADATA[name][1],
            "destructive": TOOL_METADATA[name][2],
            "description": fn.__doc__.strip(),
        }
        for name, fn in sorted(CONVENIENCE.items())
    ]
