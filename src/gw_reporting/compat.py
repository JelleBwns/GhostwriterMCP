"""Normalize verified Ghostwriter naming differences using the live role schema."""

from typing import Any

from graphql import (
    GraphQLInputObjectType,
    GraphQLList,
    GraphQLNonNull,
    GraphQLSchema,
    TypeInfo,
    TypeInfoVisitor,
    Visitor,
    parse,
    print_ast,
    type_from_ast,
    visit,
)
from graphql.language import FieldNode, NameNode

# Both spellings have been observed in upstream or deployed introspection schemas.
FIELD_NAMES = {
    "extra_fields": "extraFields",
    "added_as_blank": "addedAsBlank",
    "cvss_score": "cvssScore",
    "cvss_vector": "cvssVector",
    "report_id": "reportId",
    "include_bloodhound_data": "includeBloodhoundData",
}


def adapt_operation(schema: GraphQLSchema, query: str, variables: dict) -> tuple[str, dict]:
    document = parse(query)
    info = TypeInfo(schema)
    changed = False

    class Fields(Visitor):
        def enter_field(self, node: FieldNode, *_args):
            nonlocal changed
            parent = info.get_parent_type()
            original = node.name.value
            alternate = FIELD_NAMES.get(original)
            if parent is not None and original not in parent.fields and alternate in parent.fields:
                changed = True
                return FieldNode(
                    alias=node.alias or NameNode(value=original),
                    name=NameNode(value=alternate),
                    arguments=node.arguments,
                    directives=node.directives,
                    selection_set=node.selection_set,
                )
            return None

    adapted = visit(document, TypeInfoVisitor(info, Fields()))

    def inputs(value: Any, input_type: Any) -> Any:
        if isinstance(input_type, GraphQLNonNull):
            return inputs(value, input_type.of_type)
        if isinstance(input_type, GraphQLList):
            return (
                [inputs(item, input_type.of_type) for item in value]
                if isinstance(value, list)
                else inputs(value, input_type.of_type)
            )
        if isinstance(input_type, GraphQLInputObjectType) and isinstance(value, dict):
            result = {}
            for key, item in value.items():
                alternate = FIELD_NAMES.get(key)
                remote_key = (
                    alternate
                    if key not in input_type.fields and alternate in input_type.fields
                    else key
                )
                field = input_type.fields.get(remote_key)
                result[remote_key] = inputs(item, field.type) if field else item
            return result
        return value

    adapted_variables = dict(variables)
    for definition in document.definitions:
        for variable in getattr(definition, "variable_definitions", ()) or ():
            name = variable.variable.name.value
            if name in adapted_variables:
                adapted_variables[name] = inputs(
                    adapted_variables[name], type_from_ast(schema, variable.type)
                )
    return (print_ast(adapted) if changed else query), adapted_variables
