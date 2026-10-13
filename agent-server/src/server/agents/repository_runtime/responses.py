"""Bounded JSON parsing and small, actionable model validation feedback."""

import json

from pydantic import ValidationError


def parse_json_value(text, max_characters):
    if not isinstance(text, str) or len(text) > max_characters:
        raise ValueError("Model output must be bounded JSON text.")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON keys are not permitted.")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("Nonstandard JSON numeric constants are not permitted.")

    return json.loads(
        text, object_pairs_hook=unique_object, parse_constant=reject_constant
    )


def validation_feedback(error):
    if isinstance(error, ValidationError):
        return tuple(
            f"{'.'.join(map(str, item['loc'])) or 'response'}: {item['type']}: {item['msg'][:240]}"
            for item in error.errors(include_input=False, include_url=False)[:6]
        )
    return (str(error)[:500],)


def normalize_record_arrays(value, schema):
    """Recover singleton object arrays without changing facts or primitive fields."""
    definitions = schema.get("$defs", {})

    def visit(item, contract):
        if "$ref" in contract:
            contract = definitions[contract["$ref"].rsplit("/", 1)[1]]
        if "anyOf" in contract:
            contract = next(
                (child for child in contract["anyOf"] if child.get("type") != "null"),
                contract,
            )
            return visit(item, contract) if "anyOf" not in contract else item
        if contract.get("type") == "array":
            child = contract.get("items", {})
            resolved = definitions.get(child.get("$ref", "").rsplit("/", 1)[-1], child)
            if isinstance(item, dict) and resolved.get("type") == "object":
                item = [item]
            return (
                [visit(member, child) for member in item]
                if isinstance(item, list)
                else item
            )
        if isinstance(item, dict):
            properties = contract.get("properties", {})
            return {
                key: visit(member, properties[key]) if key in properties else member
                for key, member in item.items()
            }
        return item

    return visit(value, schema)
