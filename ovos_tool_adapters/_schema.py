# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""JSON Schema → Pydantic bridge and shared output type for adapters."""

import copy
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Type, Union

from ovos_plugin_manager.templates.agent_tools import ToolArguments, ToolOutput
from pydantic import BaseModel, ConfigDict, Field, PydanticUserError, create_model


# OpenAI-style function calling accepts only these characters in a tool name,
# and at most _MAX_TOOL_NAME_LENGTH of them. UTCP joins the manual name and the
# tool name with a dot, and MCP allows dots too, so a remote name can reach the
# model only after this substitution.
_DISALLOWED_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")
_MAX_TOOL_NAME_LENGTH = 64


def _llm_tool_name(name: str) -> str:
    """Return *name* in the form a function-calling provider accepts: every other character becomes ``_``,
    and the result is cut to 64 characters."""
    return _DISALLOWED_NAME_CHARS.sub("_", name)[:_MAX_TOOL_NAME_LENGTH]


# Mapping from JSON Schema primitive types to Python types.
_TYPE_MAP: Dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


class _RemoteToolArguments(ToolArguments):
    """Arguments of a remote tool, published to the model as the server declared them."""

    remote_schema: ClassVar[Dict[str, Any]] = {}
    nullable_fields: ClassVar[frozenset] = frozenset()

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return copy.deepcopy(cls.remote_schema)


def _resolve_ref(schema: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    """Follow a local ``#/$defs/...`` or ``#/definitions/...`` reference."""
    seen = set()
    while isinstance(schema.get("$ref"), str) and schema["$ref"].startswith("#/") and schema["$ref"] not in seen:
        seen.add(schema["$ref"])
        target: Any = root
        for part in schema["$ref"][2:].split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        schema = target
    return schema


def _allows_null(schema: Dict[str, Any], root: Dict[str, Any], seen: frozenset = frozenset()) -> bool:
    """Whether *schema* accepts ``null``: a ``null`` type, ``nullable``, a ``null`` enum value,
    a ``null`` branch of ``anyOf``/``oneOf``, or no type constraint at all."""
    ref = schema.get("$ref")
    if ref in seen:
        return False
    if isinstance(ref, str):
        seen = seen | {ref}
    schema = _resolve_ref(schema, root)
    if schema.get("nullable") is True:
        return True
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return any(_allows_null(option, root, seen) for option in schema[key])
    json_type = schema.get("type")
    if isinstance(json_type, list):
        return "null" in json_type
    if json_type is not None:
        return json_type == "null"
    if "enum" in schema:
        return None in schema["enum"]
    return True


def _python_type(schema: Dict[str, Any], root: Dict[str, Any], name: str,
                 building: frozenset = frozenset()) -> Any:
    """Return the Python type that validates values of *schema*.

    *building* holds the ``$ref`` targets being built further up, so a schema
    that refers to itself ends in a plain ``dict`` instead of endless recursion.
    """
    ref = schema.get("$ref")
    if ref in building:
        return dict
    if isinstance(ref, str):
        building = building | {ref}
    schema = _resolve_ref(schema, root)
    enum = schema.get("enum")
    if enum and all(isinstance(value, (str, int, float, bool)) for value in enum):
        return Literal[tuple(enum)]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = schema[key]
            types = [_python_type(option, root, f"{name}_{i}", building)
                     for i, option in enumerate(options)
                     if _resolve_ref(option, root).get("type") != "null"]
            py_type = Union[tuple(types)] if types else Any
            return Optional[py_type] if len(types) < len(options) else py_type
    json_type = schema.get("type")
    if isinstance(json_type, list):
        types = [_python_type({**schema, "type": t}, root, name, building) for t in json_type if t != "null"]
        py_type = Union[tuple(types)] if types else Any
        return Optional[py_type] if "null" in json_type else py_type
    if json_type == "object" and schema.get("properties"):
        extra = "forbid" if schema.get("additionalProperties") is False else "allow"
        try:
            model = create_model(name, __config__=ConfigDict(extra=extra),  # type: ignore[call-overload]
                                 **_field_definitions(schema, root, name, building))
            model.nullable_fields = _nullable_fields(schema, root)
            return model
        except (PydanticUserError, TypeError, ValueError):
            # Pydantic refuses some property names, such as `_id` or `model_dump`;
            # the server still validates the object, so it is passed on as a dict.
            return dict
    if json_type == "array" and isinstance(schema.get("items"), dict):
        return List[_python_type(schema["items"], root, f"{name}_item", building)]
    return _TYPE_MAP.get(json_type, Any)


def _field_definitions(schema: Dict[str, Any], root: Dict[str, Any], name: str,
                       building: frozenset = frozenset()) -> Dict[str, Any]:
    required: List[str] = schema.get("required", [])
    fields: Dict[str, Any] = {}
    for prop_name, prop_schema in schema.get("properties", {}).items():
        py_type = _python_type(prop_schema, root, f"{name}_{prop_name}", building)
        description: str = _resolve_ref(prop_schema, root).get("description", "")
        if prop_name in required:
            fields[prop_name] = (py_type, Field(..., description=description))
        else:
            fields[prop_name] = (Optional[py_type], Field(None, description=description))
    return fields


def _nullable_fields(schema: Dict[str, Any], root: Dict[str, Any]) -> frozenset:
    return frozenset(prop_name for prop_name, prop_schema in schema.get("properties", {}).items()
                     if _allows_null(prop_schema, root))


def _schema_to_pydantic(model_name: str, json_schema: Dict[str, Any]) -> Type[ToolArguments]:
    """
    Build a dynamic Pydantic ``ToolArguments`` subclass from a JSON Schema dict.

    Nested objects, arrays of objects, ``enum``, ``anyOf``/``oneOf`` and local
    ``$ref`` references become nested types, so validation checks what the
    server checks. ``model_json_schema()`` returns *json_schema* itself, so the
    model sees the arguments exactly as the server declared them.

    Args:
        model_name: Name for the generated class (used in error messages).
        json_schema: A JSON Schema object with at least a ``properties`` key.

    Returns:
        A ``ToolArguments`` subclass with fields matching the schema.
    """
    model = create_model(model_name, __base__=_RemoteToolArguments,  # type: ignore[call-overload]
                         **_field_definitions(json_schema, json_schema, model_name))
    model.remote_schema = {"type": "object", "properties": {}, **json_schema}
    model.nullable_fields = _nullable_fields(json_schema, json_schema)
    return model


def _wire_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _call_arguments(value)
    if isinstance(value, list):
        return [_wire_value(item) for item in value]
    return value


def _call_arguments(args: BaseModel) -> Dict[str, Any]:
    """Return the arguments to send to the server, at every nesting level: the fields
    the caller gave, without a ``null`` where the field's schema does not allow ``null``.
    A field the caller left out is never sent, so the server applies its own default."""
    nullable = getattr(type(args), "nullable_fields", frozenset())
    sent: Dict[str, Any] = {}
    for key in type(args).model_fields:
        if key not in args.model_fields_set:
            continue
        value = getattr(args, key)
        if value is None and key not in nullable:
            continue
        sent[key] = _wire_value(value)
    sent.update(args.model_extra or {})
    return sent


class AdapterToolOutput(ToolOutput):
    """
    Generic output type for both MCP and UTCP tool calls.

    Attributes:
        content: Concatenated text content from the server response.
        is_error: ``True`` if the server reported an error.
        raw: Original content blocks preserved for downstream inspection.
    """

    content: str = Field("", description="Concatenated text content from the server response.")
    is_error: bool = Field(False, description="True if the server reported an error.")
    raw: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Original content blocks from the server response.",
    )
