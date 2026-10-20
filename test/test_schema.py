"""Tests for _schema_to_pydantic and AdapterToolOutput."""
from typing import Any

import pytest
from ovos_tool_adapters._schema import AdapterToolOutput, _schema_to_pydantic


def test_basic_string_field():
    Model = _schema_to_pydantic("TestArgs", {
        "properties": {"url": {"type": "string", "description": "A URL"}},
        "required": ["url"],
    })
    instance = Model(url="https://example.com")
    assert instance.url == "https://example.com"


def test_optional_field_defaults_to_none():
    Model = _schema_to_pydantic("TestArgs", {
        "properties": {"limit": {"type": "integer"}},
        "required": [],
    })
    instance = Model()
    assert instance.limit is None


def test_required_field_missing_raises():
    Model = _schema_to_pydantic("TestArgs", {
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    })
    with pytest.raises(Exception):
        Model()


def test_unknown_type_falls_back_to_any():
    Model = _schema_to_pydantic("TestArgs", {
        "properties": {"data": {"type": "unknown_type"}},
        "required": [],
    })
    # Should accept any value
    instance = Model(data={"nested": True})
    assert instance.data == {"nested": True}


def test_empty_schema():
    Model = _schema_to_pydantic("EmptyArgs", {})
    instance = Model()
    assert instance.model_dump() == {}


def test_adapter_tool_output_defaults():
    out = AdapterToolOutput()
    assert out.content == ""
    assert out.is_error is False
    assert out.raw == []


def test_adapter_tool_output_with_values():
    out = AdapterToolOutput(content="hello", is_error=True, raw=[{"type": "text", "text": "hello"}])
    assert out.content == "hello"
    assert out.is_error is True
    assert len(out.raw) == 1


def test_nested_object_fields_are_validated():
    Model = _schema_to_pydantic("Args", {
        "properties": {"body": {"type": "object",
                                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                                "required": ["query"]}},
        "required": ["body"],
    })
    assert Model(body={"query": "x", "limit": "3"}).model_dump(exclude_none=True) == {"body": {"query": "x", "limit": 3}}
    with pytest.raises(Exception):
        Model(body={"limit": 3})


def test_enum_rejects_values_outside_the_list():
    Model = _schema_to_pydantic("Args", {"properties": {"lang": {"type": "string", "enum": ["en", "pt"]}}})
    assert Model(lang="pt").lang == "pt"
    with pytest.raises(Exception):
        Model(lang="xx")


def test_local_ref_and_nullable_any_of_are_followed():
    schema = {
        "$defs": {"Point": {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"]}},
        "properties": {"at": {"anyOf": [{"$ref": "#/$defs/Point"}, {"type": "null"}]}},
    }
    Model = _schema_to_pydantic("Args", schema)
    assert Model(at={"x": 1}).model_dump() == {"at": {"x": 1.0}}
    assert Model(at=None).at is None
    with pytest.raises(Exception):
        Model(at={"y": 1})


def test_unknown_keys_in_a_nested_object_are_kept_unless_forbidden():
    schema = {"properties": {
        "open": {"type": "object", "properties": {"a": {"type": "string"}}},
        "closed": {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False},
    }}
    Model = _schema_to_pydantic("Args", schema)
    assert Model(open={"a": "1", "b": "2"}).model_dump(exclude_none=True) == {"open": {"a": "1", "b": "2"}}
    with pytest.raises(Exception):
        Model(closed={"a": "1", "b": "2"})


def test_model_json_schema_is_the_declared_schema():
    schema = {"type": "object",
              "properties": {"body": {"type": "object", "properties": {"q": {"type": "string", "description": "Query."}}}},
              "required": ["body"]}
    assert _schema_to_pydantic("Args", schema).model_json_schema() == schema


def test_self_referencing_schema_builds_and_validates():
    schema = {
        "$defs": {"Node": {"type": "object",
                           "properties": {"label": {"type": "string"},
                                          "children": {"type": "array", "items": {"$ref": "#/$defs/Node"}}},
                           "required": ["label"]}},
        "properties": {"tree": {"$ref": "#/$defs/Node"}},
        "required": ["tree"],
    }
    Model = _schema_to_pydantic("Args", schema)
    tree = {"label": "root", "children": [{"label": "leaf", "children": []}]}
    assert Model(tree=tree).model_dump(exclude_none=True) == {"tree": tree}
    with pytest.raises(Exception):
        Model(tree={"children": []})


@pytest.mark.parametrize("key", ["_id", "model_dump"])
def test_nested_object_with_a_name_pydantic_refuses_still_builds(key):
    # Pydantic cannot make a field named `_id` (leading underscore) or
    # `model_dump` (its own method); the nested value is then kept as a dict.
    Model = _schema_to_pydantic("Args", {
        "properties": {"doc": {"type": "object", "properties": {key: {"type": "string"}, "title": {"type": "string"}}}},
        "required": ["doc"],
    })
    assert Model(doc={key: "1", "title": "t"}).model_dump()["doc"] == {key: "1", "title": "t"}


def test_required_nullable_field_accepts_null_but_must_be_given():
    Model = _schema_to_pydantic("Args", {
        "properties": {"context": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["context"],
    })
    assert Model(context=None).context is None
    with pytest.raises(Exception):
        Model()


def test_model_json_schema_returns_a_copy():
    Model = _schema_to_pydantic("Args", {"properties": {"q": {"type": "string"}}})
    Model.model_json_schema()["properties"]["q"]["type"] = "integer"
    assert Model.model_json_schema()["properties"]["q"]["type"] == "string"
