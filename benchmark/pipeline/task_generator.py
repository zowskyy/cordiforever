from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GeneratedTask:
    name: str
    description: str
    user_input: str
    tools_required: List[str]
    difficulty: str
    tags: List[str] = field(default_factory=list)


class TaskGenerator:
    def __init__(self, seed: int = 42) -> None:
        random.seed(seed)

    def generate(self, count: int = 100) -> List[GeneratedTask]:
        tasks: List[GeneratedTask] = []
        for i in range(count):
            difficulty = random.choice(["trivial", "medium", "hard"])
            task = self._generate_single(i, difficulty)
            tasks.append(task)
        return tasks

    def _generate_single(self, idx: int, difficulty: str) -> GeneratedTask:
        patterns = [
            self._pattern_trivial_read,
            self._pattern_trivial_write,
            self._pattern_trivial_list,
            self._pattern_write_file,
            self._pattern_read_file,
            self._pattern_list_directory,
            self._pattern_multi_write,
            self._pattern_read_write_sequence,
            self._pattern_create_nested,
            self._pattern_count_files,
            self._pattern_search_content,
            self._pattern_append_to_file,
        ]
        pattern_fn = random.choice(patterns)
        return pattern_fn(idx, difficulty)

    def _pattern_write_file(self, idx: int, difficulty: str) -> GeneratedTask:
        filename = f"file_{idx}.txt"
        content = f"content_{idx}"
        return GeneratedTask(
            name=f"write_{filename}",
            description=f"Write content to {filename}",
            user_input=f"write {content} to {filename}",
            tools_required=["write_file"],
            difficulty=difficulty,
            tags=["write", "basic"],
        )

    def _pattern_read_file(self, idx: int, difficulty: str) -> GeneratedTask:
        filename = f"file_{idx}.txt"
        content = f"content_{idx}"
        return GeneratedTask(
            name=f"read_{filename}",
            description=f"Read {filename}",
            user_input=f"read {filename}",
            tools_required=["read_file"],
            difficulty=difficulty,
            tags=["read", "basic"],
        )

    def _pattern_list_directory(self, idx: int, difficulty: str) -> GeneratedTask:
        return GeneratedTask(
            name=f"list_dir_{idx}",
            description=f"List files in workspace",
            user_input="list files",
            tools_required=["list_directory"],
            difficulty=difficulty,
            tags=["list", "basic"],
        )

    def _pattern_multi_write(self, idx: int, difficulty: str) -> GeneratedTask:
        a = f"a_{idx}.txt"
        b = f"b_{idx}.txt"
        return GeneratedTask(
            name=f"multi_write_{idx}",
            description=f"Create two files {a} and {b}",
            user_input=f"create {a} and {b}",
            tools_required=["write_file"],
            difficulty="medium",
            tags=["write", "multi"],
        )

    def _pattern_read_write_sequence(self, idx: int, difficulty: str) -> GeneratedTask:
        src = f"src_{idx}.txt"
        dst = f"dst_{idx}.txt"
        return GeneratedTask(
            name=f"seq_{idx}",
            description=f"Read {src} and write its contents to {dst}",
            user_input=f"copy {src} to {dst}",
            tools_required=["read_file", "write_file"],
            difficulty=difficulty,
            tags=["read", "write", "sequence"],
        )

    def _pattern_create_nested(self, idx: int, difficulty: str) -> GeneratedTask:
        path = f"nested/dir_{idx}/file_{idx}.txt"
        return GeneratedTask(
            name=f"nested_{idx}",
            description=f"Create nested file at {path}",
            user_input=f"create nested file at {path} with content hello",
            tools_required=["write_file"],
            difficulty="hard",
            tags=["write", "nested"],
        )

    def _pattern_count_files(self, idx: int, difficulty: str) -> GeneratedTask:
        return GeneratedTask(
            name=f"count_{idx}",
            description=f"Count files in workspace",
            user_input="how many files are in the workspace",
            tools_required=["list_directory"],
            difficulty=difficulty,
            tags=["list", "count"],
        )

    def _pattern_search_content(self, idx: int, difficulty: str) -> GeneratedTask:
        target = f"file_{idx}.txt"
        return GeneratedTask(
            name=f"search_{idx}",
            description=f"Find if {target} exists",
            user_input=f"find the file {target}",
            tools_required=["list_directory", "read_file"],
            difficulty="medium",
            tags=["search", "list", "read"],
        )

    def _pattern_append_to_file(self, idx: int, difficulty: str) -> GeneratedTask:
        filename = f"file_{idx}.txt"
        return GeneratedTask(
            name=f"append_{idx}",
            description=f"Append text to {filename}",
            user_input=f"append world to {filename}",
            tools_required=["write_file", "read_file"],
            difficulty="hard",
            tags=["write", "append"],
        )

    def _pattern_trivial_read(self, idx: int, difficulty: str) -> GeneratedTask:
        filename = f"file_{idx}.txt"
        return GeneratedTask(
            name=f"trivial_read_{idx}",
            description=f"Read the contents of {filename}",
            user_input=f"read {filename}",
            tools_required=["read_file"],
            difficulty="trivial",
            tags=["read", "trivial"],
        )

    def _pattern_trivial_write(self, idx: int, difficulty: str) -> GeneratedTask:
        filename = f"file_{idx}.txt"
        content = f"hello_{idx}"
        return GeneratedTask(
            name=f"trivial_write_{idx}",
            description=f"Write '{content}' to {filename}",
            user_input=f"write {content} to {filename}",
            tools_required=["write_file"],
            difficulty="trivial",
            tags=["write", "trivial"],
        )

    def _pattern_trivial_list(self, idx: int, difficulty: str) -> GeneratedTask:
        return GeneratedTask(
            name=f"trivial_list_{idx}",
            description="List files in the workspace",
            user_input="list files",
            tools_required=["list_directory"],
            difficulty="trivial",
            tags=["list", "trivial"],
        )
