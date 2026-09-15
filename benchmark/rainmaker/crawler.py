from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import urllib.request
import urllib.error

from benchmark.pipeline.task_generator import GeneratedTask


@dataclass
class GitHubTask:
    task_id: str
    source: str = "github"
    repo: str = ""
    issue_number: int = 0
    title: str = ""
    body: str = ""
    labels: List[str] = field(default_factory=list)
    difficulty: str = "medium"
    user_input: str = ""
    tools_required: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_generated_task(self) -> GeneratedTask:
        return GeneratedTask(
            name=self.task_id,
            description=self.title,
            user_input=self.user_input,
            tools_required=self.tools_required,
            difficulty=self.difficulty,
            tags=self.tags + ["github"],
        )


class GitHubCrawler:
    def __init__(self, token: Optional[str] = None, rate_limit_delay: float = 1.0) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.rate_limit_delay = rate_limit_delay
        self._cache: Dict[str, List[GitHubTask]] = {}
        self._last_request_time = 0.0

    def fetch_tasks(self, repos: List[str], max_per_repo: int = 20) -> List[GitHubTask]:
        tasks = []
        for repo in repos:
            repo_tasks = self._fetch_repo_issues(repo, max_per_repo)
            tasks.extend(repo_tasks)
        return tasks

    def _fetch_repo_issues(self, repo: str, max_count: int) -> List[GitHubTask]:
        cache_key = f"{repo}:{max_count}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        tasks = self._try_github_api(repo, max_count)
        if not tasks:
            tasks = self._generate_synthetic_tasks(repo, max_count)

        self._cache[cache_key] = tasks
        return tasks

    def _try_github_api(self, repo: str, max_count: int) -> List[GitHubTask]:
        if not self.token:
            return []

        self._respect_rate_limit()
        url = f"https://api.github.com/repos/{repo}/issues?per_page={max_count}&labels=good%20first%20issue&sort=updated&direction=desc"

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {self.token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "Cordelite-Rainmaker/1.0")

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                return [self._parse_issue(repo, issue) for issue in data if "pull_request" not in issue]
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return []

    def _parse_issue(self, repo: str, issue: Dict[str, Any]) -> GitHubTask:
        labels = [label["name"] for label in issue.get("labels", [])]
        difficulty = self._estimate_difficulty(issue)
        user_input = f"Resolve GitHub issue #{issue['number']} in {repo}: {issue['title']}\n\n{issue.get('body', '')}"
        tools_required = self._infer_tools(issue.get("body", ""), issue.get("title", ""))
        return GitHubTask(
            task_id=f"github_{repo.replace('/', '_')}_{issue['number']}",
            repo=repo,
            issue_number=issue["number"],
            title=issue["title"],
            body=issue.get("body", ""),
            labels=labels,
            difficulty=difficulty,
            user_input=user_input,
            tools_required=tools_required,
            tags=["github"] + labels,
        )

    def _estimate_difficulty(self, issue: Dict[str, Any]) -> str:
        labels = [label["name"].lower() for label in issue.get("labels", [])]
        if any(k in labels for k in ["good first issue", "easy", "trivial"]):
            return "trivial"
        if any(k in labels for k in ["hard", "complex", "difficult"]):
            return "hard"
        body = (issue.get("body") or "").lower()
        title = issue.get("title", "").lower()
        text = body + " " + title
        if any(k in text for k in ["refactor", "redesign", "breaking", "migration"]):
            return "hard"
        if any(k in text for k in ["typo", "readme", "documentation", "comment"]):
            return "trivial"
        return "medium"

    def _infer_tools(self, body: str, title: str) -> List[str]:
        text = (body + " " + title).lower()
        tools = ["read_file", "write_file", "list_directory"]
        if any(k in text for k in ["test", "pytest", "spec"]):
            tools.append("run_command")
        if any(k in text for k in ["json", "yaml", "config"]):
            tools.append("read_json")
        return tools

    def _generate_synthetic_tasks(self, repo: str, count: int) -> List[GitHubTask]:
        tasks = []
        base_name = repo.split("/")[-1] if "/" in repo else repo
        for i in range(count):
            task_id = f"github_{base_name}_{i}"
            difficulty = random.choice(["trivial", "medium", "hard"])
            title = f"Fix issue #{i+1} in {base_name}"
            body = f"Resolve the reported issue in {base_name} by modifying the relevant files and running tests."
            user_input = f"Fix issue #{i+1} in {base_name}: {body}"
            tasks.append(GitHubTask(
                task_id=task_id,
                repo=repo,
                issue_number=i + 1,
                title=title,
                body=body,
                labels=["bug", "good first issue"],
                difficulty=difficulty,
                user_input=user_input,
                tools_required=["read_file", "write_file", "list_directory"],
                tags=["github", "bug_fix"],
            ))
        return tasks

    def _respect_rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()
