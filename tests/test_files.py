import json

import pytest

from core.errors import ToolError, WorkspaceError
from plugins.tools.file import FileTools


@pytest.fixture
def files(tmp_path):
    tool = FileTools(tmp_path)
    tool.start()
    return tool


def test_read_file_in_workspace(files):
    (files.workspace / "hello.txt").write_text("hello", encoding="utf-8")
    assert files.read_file("hello.txt") == "hello"


def test_read_file_outside_workspace_rejected(files, tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        files.read_file(str(outside))


def test_write_creates_parent_directories(files):
    files.write_file("a/b/c.txt", "data")
    assert (files.workspace / "a/b/c.txt").read_text(encoding="utf-8") == "data"


def test_absolute_path_rejected(files):
    with pytest.raises(WorkspaceError):
        files._resolve(str(files.workspace / "x.txt"))


def test_parent_escape_rejected(files):
    with pytest.raises(WorkspaceError):
        files._resolve("../outside.txt")


def test_list_directory_contents(files):
    files.write_file("a.txt", "a")
    files.write_file("b.txt", "b")
    assert files.list_directory(".") == ["a.txt", "b.txt"]


def test_read_json_invalid_rejected(files):
    files.write_file("bad.json", "{not-json")
    with pytest.raises(ToolError):
        files.read_json("bad.json")


def test_delete_file_success(files):
    files.write_file("to_delete.txt", "content")
    result = files.delete_file("to_delete.txt")
    assert "Deleted" in result
    assert not (files.workspace / "to_delete.txt").exists()


def test_delete_file_nonexistent_raises(files):
    with pytest.raises(ToolError, match="does not exist"):
        files.delete_file("nonexistent.txt")


def test_delete_file_directory_raises(files):
    files.write_file("subdir/file.txt", "content")
    with pytest.raises(ToolError, match="directory"):
        files.delete_file("subdir")


# ---------------------------------------------------------------------------
# Protected file enforcement
# ---------------------------------------------------------------------------

def test_write_protected_file_default_raises(files):
    """AGENTS.md is protected by default — write must fail deterministically."""
    # Create the file directly on disk (bypassing FileTools) to set initial content
    (files.workspace / "AGENTS.md").write_text("# instructions", encoding="utf-8")
    with pytest.raises(ToolError, match="(?i)protected"):
        files.write_file("AGENTS.md", "# modified")
    assert (files.workspace / "AGENTS.md").read_text(encoding="utf-8") == "# instructions"


def test_delete_protected_file_default_raises(files):
    """AGENTS.md is protected by default — delete must fail deterministically."""
    (files.workspace / "AGENTS.md").write_text("# instructions", encoding="utf-8")
    with pytest.raises(ToolError, match="(?i)protected"):
        files.delete_file("AGENTS.md")
    assert (files.workspace / "AGENTS.md").exists()


def test_custom_protected_file_rejected(files):
    """Files specified in config['protected_files'] must also be protected."""
    # Register with a context that has protected_files config
    from core.context import Context
    ctx = Context(config={"protected_files": ["secret.txt"], "profile": "lite"})
    files.register(ctx)
    # Create the file directly on disk
    (files.workspace / "secret.txt").write_text("data", encoding="utf-8")
    with pytest.raises(ToolError, match="(?i)protected"):
        files.write_file("secret.txt", "modified")
    assert (files.workspace / "secret.txt").read_text(encoding="utf-8") == "data"


def test_non_protected_file_writable(files):
    """Regular files must still be writable."""
    files.write_file("normal.txt", "data")
    files.write_file("normal.txt", "updated")
    assert (files.workspace / "normal.txt").read_text(encoding="utf-8") == "updated"


def test_search_files_basic(files):
    files.write_file("a.py", "print(1)")
    files.write_file("b.txt", "hello")
    files.write_file("c.py", "print(2)")
    assert files.search_files("*.py") == ["a.py", "c.py"]


def test_search_files_recursive(files):
    files.write_file("root.txt", "root")
    files.write_file("sub/inner.py", "x")
    assert files.search_files("*.py") == ["sub/inner.py"]


def test_search_files_no_matches(files):
    files.write_file("a.txt", "hello")
    assert files.search_files("*.py") == []


def test_search_files_from_subdir(files):
    files.write_file("top.py", "1")
    files.write_file("sub/bottom.py", "2")
    assert files.search_files("*.py", path="sub") == ["bottom.py"]
