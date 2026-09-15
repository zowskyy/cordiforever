from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.context import Context
from core.registry import PluginRegistry
from plugins.core.event_logger import EventLogger
from plugins.tools.file import FileTools
from core.tool_protocol import JSONToolParser, TextToolParser, ToolProtocol


def test_json_parser_valid():
    p = JSONToolParser()
    r = p.parse('{"name": "read_file", "arguments": {"path": "a.txt"}}')
    assert r.name == "read_file"
    assert r.arguments["path"] == "a.txt"


def test_json_parser_list_format():
    p = JSONToolParser()
    r = p.parse('[{"name": "read_file", "arguments": {"path": "a.txt"}}]')
    assert r.name == "read_file"


def test_json_parser_markdown_wrapped():
    p = JSONToolParser()
    r = p.parse('```json\n{"name": "read_file", "arguments": {"path": "a.txt"}}\n```')
    assert r.name == "read_file"


def test_json_parser_rejects_non_json():
    p = JSONToolParser()
    with pytest.raises(Exception):
        p.parse("This is not JSON")


def test_text_parser_read_file():
    p = TextToolParser()
    r = p.parse("Please read the file test.txt")
    assert r.name == "read_file"
    assert r.arguments["path"] == "test.txt"


def test_text_parser_write_file():
    p = TextToolParser()
    r = p.parse("Write to output.txt")
    assert r.name == "write_file"
    assert r.arguments["path"] == "output.txt"


def test_text_parser_list_directory():
    p = TextToolParser()
    r = p.parse("List files in src/")
    assert r.name == "list_directory"
    assert r.arguments["path"] == "src/"


def test_text_parser_rejects_unrecognized():
    p = TextToolParser()
    with pytest.raises(Exception):
        p.parse("Random unrelated text")


def test_tool_protocol_json_fallback(tmp_path):
    files = FileTools(tmp_path)
    proto = ToolProtocol(tools=[files])
    r = proto.parse('{"name": "read_file", "arguments": {"path": "missing.txt"}}')
    assert r.name == "read_file"
    proto.validate(r)


def test_tool_protocol_text_fallback(tmp_path):
    files = FileTools(tmp_path)
    proto = ToolProtocol(tools=[files])
    r = proto.parse("Read the file test.txt")
    assert r.name == "read_file"
    assert r.parse_mode == "text"
