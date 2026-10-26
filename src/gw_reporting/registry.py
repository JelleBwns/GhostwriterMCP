"""Exactly 23 reporting tools, filtered by owner allowlist and blacklist."""

from functools import wraps

from fastmcp import FastMCP

from .schemas import DomainError, Result

# category, writes, destructive. There are no generated API/admin tools or aliases.
TOOL_METADATA = {
    "gw_list_projects": ("discovery", False, False),
    "gw_get_project": ("discovery", False, False),
    "gw_list_reports": ("discovery", False, False),
    "gw_get_report": ("discovery", False, False),
    "gw_list_findings": ("discovery", False, False),
    "gw_search_finding_library": ("discovery", False, False),
    "gw_get_finding_options": ("discovery", False, False),
    "gw_create_finding": ("findings", True, False),
    "gw_update_finding": ("findings", True, True),
    "gw_delete_finding": ("findings", True, True),
    "gw_attach_library_finding": ("findings", True, False),
    "gw_create_report": ("reports", True, False),
    "gw_update_report": ("reports", True, True),
    "gw_update_executive_summary": ("reports", True, True),
    "gw_list_evidence": ("evidence", False, False),
    "gw_upload_evidence": ("evidence", True, False),
    "gw_attach_evidence": ("evidence", True, True),
    "gw_download_evidence": ("evidence", False, False),
    "gw_delete_evidence": ("evidence", True, True),
    "gw_list_templates": ("templates", False, False),
    "gw_select_report_templates": ("templates", True, True),
    "gw_generate_report": ("export", False, False),
    "gw_get_export": ("export", False, False),
}


def effective_tools(
    functions: dict, enabled_names: list[str] | None = None, disabled_names: list[str] | None = None
) -> frozenset[str]:
    selections = {}
    for setting, names in [
        ("GW_ENABLED_TOOLS", enabled_names),
        ("GW_DISABLED_TOOLS", disabled_names),
    ]:
        names = [] if names is None else names
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ValueError(f"{setting} must be a JSON array of exact tool names")
        unknown = set(names) - functions.keys()
        if unknown:
            raise ValueError(f"Unknown {setting} entries: " + ", ".join(sorted(unknown)))
        selections[setting] = frozenset(names)
    allowed = selections["GW_ENABLED_TOOLS"] or frozenset(functions)
    return allowed - selections["GW_DISABLED_TOOLS"]


def build_server(
    functions: dict, enabled_names: list[str] | None = None, disabled_names: list[str] | None = None
) -> FastMCP:
    if set(functions) != set(TOOL_METADATA):
        raise ValueError("Registered functions must match the fixed 23-tool reporting catalog")
    enabled = effective_tools(functions, enabled_names, disabled_names)
    server = FastMCP("Ghostwriter")

    def protected(fn, name):
        @wraps(fn)
        async def call(*args, **kwargs):
            try:
                if name not in enabled:
                    raise DomainError(
                        "tool_disabled", "Tool is disabled by the configured tool policy"
                    )
                return Result(data=await fn(*args, **kwargs))
            except DomainError as exc:
                return Result(ok=False, error={"code": exc.code, "message": exc.message})

        call.__annotations__["return"] = Result
        return call

    for name in sorted(enabled):
        category, writes, destructive = TOOL_METADATA[name]
        server.tool(
            protected(functions[name], name),
            name=name,
            tags={category},
            annotations={"readOnlyHint": not writes, "destructiveHint": destructive},
        )
    return server
