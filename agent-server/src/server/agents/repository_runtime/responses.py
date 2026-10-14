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
    """Recover singleton object arrays and prune unknown keys.

    The model is never trusted to honour the schema exactly: a single object
    where the contract wants a one-member array is wrapped, and keys absent
    from the contract are dropped instead of failing the turn.

    Returns `(normalized, dropped_paths)`. Dropped paths use dotted notation
    with `[index]` for array members, so callers can audit what the model
    sent beyond the contract. Facts and primitive fields are never changed.
    """
    definitions = schema.get("$defs", {})
    dropped: list[str] = []

    def resolve(contract):
        seen = 0
        while ("$ref" in contract or "anyOf" in contract) and seen < 10:
            seen += 1
            if "$ref" in contract:
                contract = definitions.get(contract["$ref"].rsplit("/", 1)[-1], {})
                continue
            children = [
                child for child in contract["anyOf"] if child.get("type") != "null"
            ]
            if not children:
                return {}
            contract = children[0]
        return contract

    def visit(item, contract, path):
        contract = resolve(contract)
        if contract.get("type") == "array":
            child = contract.get("items", {})
            resolved = definitions.get(
                child.get("$ref", "").rsplit("/", 1)[-1], child
            )
            if isinstance(item, dict) and resolve(resolved).get("type") == "object":
                item = [item]
            if isinstance(item, list):
                return [
                    visit(member, child, f"{path}[{index}]")
                    for index, member in enumerate(item)
                ]
            return item
        if isinstance(item, dict):
            if "properties" not in contract:
                # Free-form maps (e.g. dict[str, str]) declare no properties:
                # nothing to prune without risking real facts.
                return item
            properties = contract["properties"]
            kept = {}
            for key, member in item.items():
                location = f"{path}.{key}" if path else key
                if key in properties:
                    kept[key] = visit(member, properties[key], location)
                else:
                    dropped.append(location)
            return kept
        return item

    return visit(value, schema, ""), tuple(dropped)
