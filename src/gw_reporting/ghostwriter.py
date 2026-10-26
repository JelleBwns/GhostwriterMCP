import asyncio
import logging
from typing import Any

import httpx
from graphql import build_client_schema, get_introspection_query, parse, validate

from . import queries as q
from .compat import adapt_operation
from .config import settings
from .schemas import DomainError

log = logging.getLogger(__name__)


class Ghostwriter:
    async def raw(self, query: str, variables: dict | None = None, retry: bool = True) -> dict:
        cfg = settings()  # Rotation requires settings cache clear or process restart.
        if not cfg.gw_base_url or not cfg.gw_token.get_secret_value():
            raise DomainError(
                "not_configured", "Set GW_BASE_URL and GW_TOKEN in your environment file"
            )
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, verify=cfg.gw_tls_verify
        ) as client:
            for attempt in range(3 if retry else 1):
                try:
                    response = await client.post(
                        cfg.gw_base_url.rstrip("/") + "/v1/graphql",
                        headers={"Authorization": f"Bearer {cfg.gw_token.get_secret_value()}"},
                        json={
                            "query": query,
                            "variables": variables or {},
                            "operationName": parse(query).definitions[0].name.value
                            if parse(query).definitions[0].name
                            else None,
                        },
                    )
                    if response.status_code in (429, 502, 503, 504) and retry and attempt < 2:
                        await asyncio.sleep(0.2 * 2**attempt)
                        continue
                    response.raise_for_status()
                    body = response.json()
                    if body.get("errors"):
                        raise DomainError(
                            "graphql_error",
                            "Ghostwriter rejected operation; verify schema and token grants",
                        )
                    return body["data"]
                except httpx.TransportError:
                    if not retry or attempt == 2:
                        raise DomainError(
                            "upstream_unavailable", "Ghostwriter transport failed"
                        ) from None
                    await asyncio.sleep(0.2 * 2**attempt)
                except httpx.HTTPStatusError:
                    raise DomainError(
                        "upstream_http_error", "Ghostwriter refused request"
                    ) from None
        raise DomainError("upstream_unavailable", "Retry budget exhausted")

    async def prepare(self, query: str, variables: dict | None = None) -> tuple[str, dict]:
        # Fetch capabilities for the current credential; never use the offline schema
        # as proof that an operation is available to this deployed token.
        schema = build_client_schema(await self.raw(get_introspection_query()))
        query, variables = adapt_operation(schema, query, variables or {})
        document = parse(query)
        if validate(schema, document):
            raise DomainError(
                "unsupported_operation",
                "Operation is unavailable to this token or Ghostwriter version",
            )
        from graphql import get_variable_values

        values = get_variable_values(
            schema, document.definitions[0].variable_definitions or (), variables
        )
        if isinstance(values, list):
            raise DomainError(
                "invalid_arguments", "Arguments are incompatible with the deployed token schema"
            )
        return query, variables

    async def input_fields(self, type_name: str) -> frozenset[str]:
        """Discover version-specific optional inputs without guessing API fields."""
        from graphql import GraphQLInputObjectType

        schema = build_client_schema(await self.raw(get_introspection_query()))
        value = schema.get_type(type_name)
        if not isinstance(value, GraphQLInputObjectType):
            raise DomainError(
                "unsupported_operation", "Required mutation input is unavailable to this identity"
            )
        return frozenset(value.fields)

    async def field_nullable(self, type_name: str, field_name: str) -> bool:
        from graphql import GraphQLNonNull

        from .compat import FIELD_NAMES

        schema = build_client_schema(await self.raw(get_introspection_query()))
        output = schema.get_type(type_name)
        fields = getattr(output, "fields", {})
        field = fields.get(field_name) or fields.get(FIELD_NAMES.get(field_name))
        if field is None:
            raise DomainError("unsupported_operation", "Required association field is unavailable")
        return not isinstance(field.type, GraphQLNonNull)

    async def report_field_specs(self) -> dict:
        import json

        data = (await self.execute(q.REPORT_FIELD_SPECS)).get("getExtraFieldSpec") or {}
        fields = data.get("extraFieldSpec")
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except ValueError:
                raise DomainError(
                    "invalid_response", "Report field specification is not valid JSON"
                ) from None
        if not isinstance(fields, dict):
            raise DomainError("invalid_response", "Report field specification must be an object")
        return fields

    async def execute(self, query: str, variables: dict | None = None) -> dict:
        query, variables = await self.prepare(query, variables)
        mutation = query.lstrip().startswith("mutation")
        return await self.raw(query, variables, retry=not mutation)

    @staticmethod
    def project_filter() -> dict:
        cfg = settings()
        filters = {}
        if cfg.allowed_projects:
            filters["id"] = {"_in": cfg.allowed_projects}
        if cfg.allowed_clients:
            filters["clientId"] = {"_in": cfg.allowed_clients}
        return filters

    async def project(self, project_id: int) -> dict:
        cfg = settings()
        if cfg.allowed_projects and project_id not in cfg.allowed_projects:
            raise DomainError("forbidden", "Project is outside configured engagement scope")
        result = (await self.execute(q.PROJECT, {"id": project_id}))["project_by_pk"]
        if not result:
            raise DomainError("forbidden", "Project is not visible to integration identity")
        if cfg.allowed_clients:
            try:
                client_id = int(result.get("clientId"))
            except (TypeError, ValueError):
                client_id = None
            if client_id not in cfg.allowed_clients:
                raise DomainError("forbidden", "Project is outside the allowed client scope")
        return result

    async def report(self, project_id: int, report_id: int) -> dict:
        await self.project(project_id)
        result = (await self.execute(q.REPORT, {"id": report_id}))["report_by_pk"]
        if not result or int(result["projectId"]) != project_id:
            raise DomainError("forbidden", "Report does not belong to authorized project")
        return result

    async def page(
        self, table: str, fields: str, where: dict[str, Any], offset: int = 0, limit: int = 100
    ) -> list[dict]:
        if table not in {
            "project",
            "report",
            "reportedFinding",
            "finding",
            "findingSeverity",
            "findingType",
            "evidence",
            "template",
        }:
            raise ValueError("Unknown table")
        query = f"query Page($where:{table}_bool_exp!,$offset:Int!,$limit:Int!){{{table}(where:$where,offset:$offset,limit:$limit,order_by:{{id:asc}}){{{fields}}}}}"
        return (
            await self.execute(
                query, {"where": where, "offset": offset, "limit": min(max(limit, 1), 100)}
            )
        )[table]

    async def all_findings(self, project_id: int, report_id: int) -> list[dict]:
        await self.report(project_id, report_id)
        rows = []
        while True:
            batch = await self.page(
                "reportedFinding",
                q.DIRECT_FINDING_FIELDS,
                {"reportId": {"_eq": report_id}},
                len(rows),
            )
            rows.extend(batch)
            if len(batch) < 100:
                return rows
