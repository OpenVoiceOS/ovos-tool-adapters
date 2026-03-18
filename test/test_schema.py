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
