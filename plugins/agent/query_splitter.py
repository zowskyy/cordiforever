"""
Query Splitter — decomposes multi-domain queries into classified fragments.

Uses sentence boundaries and keyword heuristics.
Zero tokens — pure regex, no LLM calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.plugin import Plugin


@dataclass
class Fragment:
    text: str
    domain: str


class QuerySplitter(Plugin):
    name = "query_splitter"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        # P1 FIX: Hardened classification to avoid collisions
        # Math requires explicit math verbs/symbols, not generic words like "add"/"time"
        self._math_strong = re.compile(
            r'(\b(derivative|derive|differentiate|integrate|integral|simplify|expand|factor|solve|evaluate|eval|limit|lim|'
            r'trig_simplify|trigsimp|det|determinant|inverse|eigenvalue|trace|rank)\b'
            r'|x\^?\*?\d|\*\*\d|\b(sin|cos|tan|sqrt|log|ln)\s*\(|\bpi\b|\bexp\b)',
            re.IGNORECASE,
        )
        self._math_arithmetic = re.compile(r'\d+\s*[\*\+\-\/]\s*\d+|\d+\s*\*\*\s*\d+')
        # Datetime requires explicit temporal anchors, not bare "add" or "time"
        self._datetime_strong = re.compile(
            r'(\b(today|tomorrow|yesterday)\b|\d{4}-\d{2}-\d{2}|'
            r'\b(add|subtract)\s+\d+\s+(days?|weeks?|months?|years?|hours?|minutes?|seconds?)\b|'
            r'\bdays?\s+between\b|\bweekday\b|\bwhat\s+day\b|\bcurrent\s+date\b)',
            re.IGNORECASE,
        )
        self._datetime_weak = re.compile(
            r'\b(date|time|day|week|month|year|hour|minute|second|days?|weeks?|months?|years?)\b',
            re.IGNORECASE,
        )
        # Units requires convert pattern or value+unit
        self._units_strong = re.compile(
            r'(\bconvert\b|\d+\s*(km|miles?|kg|pounds?|grams?|meters?|feet|inches?|celsius|fahrenheit|liters?|gallons?)\b.*\b(to|in)\b|\bto\s+(miles|km|kg|pounds)\b)',
            re.IGNORECASE,
        )
        self._units_weak = re.compile(
            r'\b(km|miles?|kg|pounds?|grams?|meters?|feet|inches?|celsius|fahrenheit|liters?|gallons?)\b',
            re.IGNORECASE,
        )

    def split(self, text: str) -> list[Fragment]:
        if not text or not isinstance(text, str):
            return [Fragment(text or "", "general")]

        sentences = self._split_sentences(text)
        result = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            domain = self._classify(sentence)
            result.append(Fragment(text=sentence, domain=domain))

        return result if result else [Fragment(text, "general")]

    def _split_sentences(self, text: str) -> list[str]:
        parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
        return [p.strip() for p in parts if p.strip()]

    def _classify(self, text: str) -> str:
        # Priority: strong math > strong datetime > strong units > arithmetic (with date guard) > weak
        if self._math_strong.search(text):
            return "math"
        if self._datetime_strong.search(text):
            return "datetime"
        if self._units_strong.search(text):
            return "units"
        if self._math_arithmetic.search(text):
            # Guard: date "2024-01-01" looks like arithmetic (2024-01) but is datetime
            if re.search(r'\d{4}-\d{2}-\d{2}', text):
                return "datetime"
            return "math"
        # Weak signals only if no strong match elsewhere; require additional context
        if self._units_weak.search(text) and re.search(r'\b(convert|to|in)\b', text, re.IGNORECASE):
            return "units"
        if self._datetime_weak.search(text) and re.search(r'\b(today|tomorrow|yesterday|between|add|subtract)\b', text, re.IGNORECASE):
            return "datetime"
        return "general"
