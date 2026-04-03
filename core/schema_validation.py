"""Lightweight JSON-schema validation for local tool definitions.

The project only needs a pragmatic subset of JSON Schema to validate MCP
tool inputs consistently without adding another dependency.
"""

from __future__ import annotations

from typing import Any, Dict


class SchemaValidationError(ValueError):
    """Raised when a value does not satisfy a tool schema."""


def ensure_object_schema(schema: Dict[str, Any] | None) -> Dict[str, Any]:
    """Normalize tool schemas to an object schema."""
    schema = dict(schema or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("required", [])
    schema.setdefault("additionalProperties", False)
    return schema


def validate_tool_schema(schema: Dict[str, Any] | None) -> Dict[str, Any]:
    """Validate schema structure at tool-registration time."""
    normalized = ensure_object_schema(schema)

    if normalized.get("type") != "object":
        raise SchemaValidationError("Tool schemas must have type='object'.")

    properties = normalized.get("properties", {})
    if not isinstance(properties, dict):
        raise SchemaValidationError("Tool schema 'properties' must be an object.")

    required = normalized.get("required", [])
    if not isinstance(required, list) or any(not isinstance(k, str) for k in required):
        raise SchemaValidationError("Tool schema 'required' must be a list of strings.")

    unknown_required = [key for key in required if key not in properties]
    if unknown_required:
        raise SchemaValidationError(
            f"Tool schema marks unknown required properties: {', '.join(unknown_required)}"
        )

    for key, subschema in properties.items():
        if not isinstance(subschema, dict):
            raise SchemaValidationError(
                f"Schema for property '{key}' must be an object."
            )
        _validate_schema_fragment(subschema, path=f"properties.{key}")

    return normalized


def validate_arguments(arguments: Dict[str, Any] | None, schema: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a tool call payload against a normalized schema."""
    payload = arguments or {}
    if not isinstance(payload, dict):
        raise SchemaValidationError("Tool arguments must be a JSON object.")

    normalized = ensure_object_schema(schema)
    _validate_object(payload, normalized, "$")
    return payload


def _validate_schema_fragment(schema: Dict[str, Any], path: str) -> None:
    declared_type = schema.get("type")
    if isinstance(declared_type, list):
        for item in declared_type:
            if not isinstance(item, str):
                raise SchemaValidationError(f"{path}.type entries must be strings.")
    elif declared_type is not None and not isinstance(declared_type, str):
        raise SchemaValidationError(f"{path}.type must be a string or list of strings.")

    if "properties" in schema:
        props = schema["properties"]
        if not isinstance(props, dict):
            raise SchemaValidationError(f"{path}.properties must be an object.")
        for child_name, child_schema in props.items():
            if not isinstance(child_schema, dict):
                raise SchemaValidationError(
                    f"{path}.properties.{child_name} must be an object."
                )
            _validate_schema_fragment(
                child_schema, path=f"{path}.properties.{child_name}"
            )

    if "items" in schema and not isinstance(schema["items"], dict):
        raise SchemaValidationError(f"{path}.items must be an object.")

    if "enum" in schema and not isinstance(schema["enum"], list):
        raise SchemaValidationError(f"{path}.enum must be a list.")


def _validate_object(value: Dict[str, Any], schema: Dict[str, Any], path: str) -> None:
    _validate_type(value, schema, path)

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in value:
            raise SchemaValidationError(f"{path}.{key} is required.")

    additional_allowed = schema.get("additionalProperties", True)
    for key, item in value.items():
        if key in properties:
            _validate_value(item, properties[key], f"{path}.{key}")
        elif additional_allowed is False:
            raise SchemaValidationError(f"{path}.{key} is not allowed.")


def _validate_value(value: Any, schema: Dict[str, Any], path: str) -> None:
    _validate_type(value, schema, path)

    if value is None:
        return

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaValidationError(
            f"{path} must be one of {', '.join(repr(v) for v in schema['enum'])}."
        )

    declared_type = schema.get("type")
    if _type_matches("object", declared_type, value):
        _validate_object(value, ensure_object_schema(schema), path)
        return

    if _type_matches("array", declared_type, value):
        items_schema = schema.get("items", {})
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaValidationError(f"{path} must have at least {schema['minItems']} items.")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaValidationError(f"{path} must have at most {schema['maxItems']} items.")
        for index, item in enumerate(value):
            _validate_value(item, items_schema, f"{path}[{index}]")
        return

    if _type_matches("string", declared_type, value):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(value) < min_length:
            raise SchemaValidationError(f"{path} must be at least {min_length} chars.")
        if max_length is not None and len(value) > max_length:
            raise SchemaValidationError(f"{path} must be at most {max_length} chars.")
        return

    if _type_matches("integer", declared_type, value) or _type_matches(
        "number", declared_type, value
    ):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise SchemaValidationError(f"{path} must be >= {minimum}.")
        if maximum is not None and value > maximum:
            raise SchemaValidationError(f"{path} must be <= {maximum}.")


def _validate_type(value: Any, schema: Dict[str, Any], path: str) -> None:
    declared_type = schema.get("type")
    if declared_type is None:
        return

    allowed_types = (
        declared_type if isinstance(declared_type, list) else [declared_type]
    )
    if not any(_type_matches(expected, declared_type, value) for expected in allowed_types):
        expected_text = ", ".join(allowed_types)
        actual = type(value).__name__
        raise SchemaValidationError(f"{path} must be of type {expected_text}, got {actual}.")


def _type_matches(expected: str, declared_type: Any, value: Any) -> bool:
    del declared_type
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return True
