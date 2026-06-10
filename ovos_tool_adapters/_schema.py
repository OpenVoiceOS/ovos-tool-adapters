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

from typing import Any, Dict, List, Optional, Type

try:
    from ovos_plugin_manager.templates.agent_tools import ToolArguments, ToolOutput
except ImportError:
    from pydantic import BaseModel

    class ToolArguments(BaseModel):
        pass

    class ToolOutput(BaseModel):
        pass

from pydantic import Field, create_model


# Mapping from JSON Schema primitive types to Python types.
_TYPE_MAP: Dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _schema_to_pydantic(model_name: str, json_schema: Dict[str, Any]) -> Type[ToolArguments]:
    """
    Build a dynamic Pydantic ``ToolArguments`` subclass from a JSON Schema dict.

    Handles ``string``, ``integer``, ``number``, ``boolean``, ``array``, and
    ``object`` types. Falls back to ``Any`` for unrecognised types.

    Args:
        model_name: Name for the generated class (used in error messages).
        json_schema: A JSON Schema object with at least a ``properties`` key.

    Returns:
        A ``ToolArguments`` subclass with fields matching the schema.
    """
    properties: Dict[str, Any] = json_schema.get("properties", {})
    required: List[str] = json_schema.get("required", [])
    field_definitions: Dict[str, Any] = {}

    for prop_name, prop_schema in properties.items():
        py_type: Any = _TYPE_MAP.get(prop_schema.get("type", ""), Any)
        description: str = prop_schema.get("description", "")
        if prop_name in required:
            field_definitions[prop_name] = (py_type, Field(..., description=description))
        else:
            field_definitions[prop_name] = (Optional[py_type], Field(None, description=description))

    return create_model(model_name, __base__=ToolArguments, **field_definitions)  # type: ignore[call-overload]


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
