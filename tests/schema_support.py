"""Source-verified schema assembly for offline contract tests only."""

import gzip
import json
from functools import lru_cache
from pathlib import Path

from graphql import (
    DocumentNode,
    ObjectTypeDefinitionNode,
    ObjectTypeExtensionNode,
    build_client_schema,
    extend_schema,
    parse,
)
from graphql.language import NameNode


@lru_cache
def api_schema():
    root = Path(__file__).parent / "fixtures"
    base = build_client_schema(
        json.loads(gzip.decompress((root / "upstream-schema.json.gz").read_bytes()))
    )
    definitions = []
    roots = {"Query": base.query_type, "Mutation": base.mutation_type}
    for node in parse((root / "upstream-actions.graphql").read_text()).definitions:
        name = node.name.value
        if isinstance(node, ObjectTypeDefinitionNode) and name in roots:
            target = roots[name]
            missing = tuple(f for f in node.fields if f.name.value not in target.fields)
            if missing:
                definitions.append(
                    ObjectTypeExtensionNode(name=NameNode(value=target.name), fields=missing)
                )
        elif name not in base.type_map:
            definitions.append(node)
    return extend_schema(base, DocumentNode(definitions=tuple(definitions)))
