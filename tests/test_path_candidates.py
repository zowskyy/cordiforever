from __future__ import annotations

from core.path_candidates import classify_path, mentioned_in, near_paths


def _seed(root, *paths):
    for rel in paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")


def test_exact_basename_dominates_and_matcher_is_narrow(tmp_path):
    _seed(tmp_path, "src/mathlib/add.py", "src/adder.py", "lib/add.py", "node_modules/add.py", "src/ad.py")
    found = near_paths(tmp_path, "add.py")
    assert [(c.path, c.kind) for c in found] == [("lib/add.py", "exact_basename"), ("src/mathlib/add.py", "exact_basename")]


def test_near_name_requires_same_extension_and_close_stem(tmp_path):
    _seed(tmp_path, "config/config.json", "config/config.yaml", "app.test.json")
    assert [(c.path, c.kind) for c in near_paths(tmp_path, "confg.json")] == [("config/config.json", "near_name")]
    assert near_paths(tmp_path, "app.json") == []
    assert near_paths(tmp_path, "config.toml") == []


def test_mentioned_in_matches_path_or_standalone_name():
    assert mentioned_in("Create src/new_module.py with hello()", "src/new_module.py")
    assert mentioned_in("create notes.md in docs", "docs/notes.md")
    assert not mentioned_in("change the port in app.json.bak", "app.json")
    assert not mentioned_in("update config", "config.json")
    assert not mentioned_in("create notes.md in docs", "docs/notes.md", exact_only=True)


def test_request_path_refs_extracts_only_path_like_tokens():
    from core.path_candidates import request_path_refs

    assert request_path_refs("Fix add.py, then read ./src/app.json and app.json. Version 1.2, port 3000.") == ["add.py", "src/app.json", "app.json"]
    assert request_path_refs("Say hello") == []


def test_grounding_control_task_keeps_requested_new_path(tmp_path):
    from core.path_candidates import ground_request

    _seed(tmp_path, "docs/README.md")
    lines = ground_request(tmp_path, "Create src/README.md with the line 'source code'.")
    assert lines == ["src/README.md → new file at exactly src/README.md"]
    assert "docs/README.md" not in "\n".join(lines)


def test_grounding_single_ambiguous_none_and_existing(tmp_path):
    from core.path_candidates import ground_request

    _seed(tmp_path, "src/mathlib/add.py", "config/app.json", "deploy/app.json", "notes.txt")
    assert ground_request(tmp_path, "Fix the bug in add.py") == ["add.py → src/mathlib/add.py"]
    assert ground_request(tmp_path, "Change the port in app.json") == ["app.json → ambiguous: config/app.json, deploy/app.json"]
    assert ground_request(tmp_path, "Create brand_new.py") == []
    assert ground_request(tmp_path, "Read notes.txt") == []
    assert ground_request(tmp_path, "Create lib/new.py") == []
    assert ground_request(tmp_path, "Read ../secret.txt") == []


def test_named_existing_files_requirements(tmp_path):
    from core.path_candidates import named_existing_files

    _seed(tmp_path, "notes.txt", "docs/notes.txt", "src/mathlib/add.py", "config/app.json", "deploy/app.json")
    assert named_existing_files(tmp_path, "Read notes.txt and write count.txt") == [["notes.txt"]]
    assert named_existing_files(tmp_path, "Fix add.py") == [["src/mathlib/add.py"]]
    assert named_existing_files(tmp_path, "Change app.json") == [["config/app.json", "deploy/app.json"]]
    assert named_existing_files(tmp_path, "Create src/new.py and hello.py") == []
    assert named_existing_files(tmp_path, "Read ../x.txt") == []


def test_classify_path_rules(tmp_path):
    _seed(tmp_path, "config/app.json", "src/old_module.py", "settings/confg.json")

    def verdict(tool, path, request):
        v = classify_path(tmp_path, tool, path, request)
        return (v.wrong_path, v.conflict)

    # existing target: not this guard's concern
    assert verdict("write_file", "config/app.json", "change port") == (False, None)
    # missing with exact-name conflict
    assert verdict("read_file", "app.json", "Change the port") == (True, "exact_basename")
    assert verdict("write_file", "app.json", "Change the port in app.json") == (True, "exact_basename")
    assert verdict("write_file", "backup/app.json", "Copy settings into app.json") == (True, "exact_basename")
    assert verdict("write_file", "backup/app.json", "Copy settings into backup/app.json") == (False, None)
    # missing with near-name conflict: naming the file authorizes
    assert verdict("write_file", "settings/config.json", "Create settings/config.json") == (False, None)
    assert verdict("write_file", "settings/config.json", "fix the settings") == (True, "near_name")
    # missing, no conflict: legitimate new files
    assert verdict("write_file", "src/new_module.py", "Create src/new_module.py") == (False, None)
    assert verdict("write_file", "app.test.json", "make a test fixture") == (False, None)
    assert verdict("write_file", "brand_new.txt", "make something") == (False, None)
    # out of scope for this guard
    assert verdict("read_file", "*.json", "read json") == (False, None)
    assert verdict("read_file", "../app.json", "escape") == (False, None)
    assert verdict("delete_file", "app.json", "delete") == (False, None)
