from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class Route:
    intent: str
    confidence: float
    retrieval_mode: str
    context: dict[str, Any] = field(default_factory=dict)
    goal_scope: str = "unknown"
    action_type: str = "unknown"
    entity_type: str = "unknown"


class IntentRouter:
    """Routes queries to specialized memory paths based on latent intent cues."""

    ROUTES: dict[str, list[str]] = {
        "profile": ["prefer", "like", "favorite", "love", "hate", "dislike", "user is", "i am", "my name", "i like", "i prefer"],
        "factual": ["what is", "what are", "who is", "where is", "how many", "how much", "define", "explain", "tell me about"],
        "temporal": ["when", "last time", "first time", "recently", "yesterday", "today", "history", "timeline", "before", "after", "last"],
        "constraint": ["must", "always", "never", "require", "need to", "have to", "constraint", "rule", "policy", "limit"],
        "procedural": ["how to", "steps", "procedure", "process", "workflow", "guide", "tutorial", "instructions", "run", "execute"],
    }

    ENTITY_PATTERNS: dict[str, list[str]] = {
        "file": [".py", ".txt", ".json", ".md", ".yaml", ".yml", "file", "directory", "path"],
        "code": ["function", "class", "def ", "import", "variable", "method", "api", "syntax"],
        "command": ["run", "execute", "command", "terminal", "bash", "script", "pytest", "python"],
        "git": ["commit", "branch", "merge", "push", "pull", "repo", "git"],
        "config": ["config", "setting", "environment", "env", "parameter", "option"],
    }

    ACTION_PATTERNS: dict[str, list[str]] = {
        "read": ["read", "show", "display", "view", "inspect", "check", "list", "get"],
        "write": ["write", "create", "make", "build", "generate", "save", "store"],
        "search": ["search", "find", "locate", "grep", "look for", "query"],
        "execute": ["run", "execute", "test", "build", "deploy", "start"],
        "analyze": ["analyze", "explain", "debug", "review", "compare", "evaluate"],
    }

    GOAL_PATTERNS: dict[str, list[str]] = {
        "single_file": ["this file", "current file", "one file", "single"],
        "project_wide": ["all files", "entire", "project", "whole", "global", "every"],
        "exploration": ["explore", "browse", "overview", "map", "understand", "what is"],
        "modification": ["fix", "change", "update", "modify", "refactor", "edit", "improve"],
    }

    def __init__(self, default_intent: str = "factual") -> None:
        self._default_intent = default_intent

    def route(self, query: str) -> Route:
        q = query.strip().lower()
        best_intent = self._default_intent
        best_score = 0.0

        for intent, keywords in self.ROUTES.items():
            score = self._score_keywords(q, keywords)
            if score > best_score:
                best_score = score
                best_intent = intent

        retrieval_mode = self._intent_to_mode(best_intent)
        return Route(
            intent=best_intent,
            confidence=min(best_score, 1.0),
            retrieval_mode=retrieval_mode,
            context={"query": query},
            goal_scope=self._detect_goal_scope(q),
            action_type=self._detect_action_type(q),
            entity_type=self._detect_entity_type(q),
        )

    def _detect_goal_scope(self, query: str) -> str:
        best_scope = "unknown"
        best_score = 0.0
        for scope, keywords in self.GOAL_PATTERNS.items():
            score = self._score_keywords(query, keywords)
            if score > best_score:
                best_score = score
                best_scope = scope
        return best_scope

    def _detect_action_type(self, query: str) -> str:
        best_action = "unknown"
        best_score = 0.0
        for action, keywords in self.ACTION_PATTERNS.items():
            score = self._score_keywords(query, keywords)
            if score > best_score:
                best_score = score
                best_action = action
        return best_action

    def _detect_entity_type(self, query: str) -> str:
        best_entity = "unknown"
        best_score = 0.0
        for entity, keywords in self.ENTITY_PATTERNS.items():
            score = self._score_keywords(query, keywords)
            if score > best_score:
                best_score = score
                best_entity = entity
        return best_entity

    @staticmethod
    def _score_keywords(query: str, keywords: Sequence[str]) -> float:
        matches = sum(1 for kw in keywords if kw in query)
        if not matches:
            return 0.0
        return matches / len(keywords)

    @staticmethod
    def _intent_to_mode(intent: str) -> str:
        mapping = {
            "profile": "note_first",
            "factual": "note_first",
            "temporal": "episode_first",
            "constraint": "hybrid",
            "procedural": "hybrid",
        }
        return mapping.get(intent, "hybrid")
