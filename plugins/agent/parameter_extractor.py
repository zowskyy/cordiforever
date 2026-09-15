"""
Parameter Extractor — translates natural language math expressions to SymPy syntax.

Additive plugin: sits between semantic router and existing math pipeline.
Uses regex replacements only — no LLM, no new dependencies.
"""

from __future__ import annotations

import re
from typing import Any

from core.plugin import EventDrivenPlugin


class ParameterExtractor(EventDrivenPlugin):
    name = "parameter_extractor"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self._rules: list[tuple[re.Pattern[str], str]] = []
        self._build_rules()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def extract_math_expression(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text
        result = text.strip()
        for pattern, replacement in self._rules:
            result = pattern.sub(replacement, result)
        result = re.sub(r'\s+', ' ', result).strip()
        result = re.sub(r'[.,;:!?]+$', '', result).strip()
        return result

    def extract_evaluate_point(self, text: str) -> tuple[str, str]:
        text = text.strip()
        m = re.search(r'at\s+(\w+)\s*=\s*(.+)', text, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2).strip()
        return "", text

    def _build_rules(self) -> None:
        self._rules = [
            (re.compile(r'\be\s+to\s+the\s+([\w\s]+?)\s*(?:power\s+)?(?:\s*times?\s*x)?$', re.IGNORECASE), lambda m: f'exp({self._convert_to_sympy(m.group(1))})'),
            (re.compile(r'\be\s+to\s+the\s+([\w\s]+?)\s*$', re.IGNORECASE), lambda m: f'exp({self._convert_to_sympy(m.group(1))})'),
            (re.compile(r'\bexp\s*\(\s*([^)]+)\s*\)', re.IGNORECASE), r'exp(\1)'),
            (re.compile(r'\bsin\s+of\s+(\w+)\b', re.IGNORECASE), r'sin(\1)'),
            (re.compile(r'\bsine\s+of\s+(\w+)\b', re.IGNORECASE), r'sin(\1)'),
            (re.compile(r'\bcos\s+of\s+(\w+)\b', re.IGNORECASE), r'cos(\1)'),
            (re.compile(r'\bcosine\s+of\s+(\w+)\b', re.IGNORECASE), r'cos(\1)'),
            (re.compile(r'\btan\s+of\s+(\w+)\b', re.IGNORECASE), r'tan(\1)'),
            (re.compile(r'\btangent\s+of\s+(\w+)\b', re.IGNORECASE), r'tan(\1)'),
            (re.compile(r'\bsin\s*\(\s*([^)]+)\s*\)', re.IGNORECASE), r'sin(\1)'),
            (re.compile(r'\bcos\s*\(\s*([^)]+)\s*\)', re.IGNORECASE), r'cos(\1)'),
            (re.compile(r'\btan\s*\(\s*([^)]+)\s*\)', re.IGNORECASE), r'tan(\1)'),
            (re.compile(r'\b(sqrt|square\s+root)\s+of\s+(\w+)\b', re.IGNORECASE), r'sqrt(\2)'),
            (re.compile(r'\b(sqrt|square\s+root)\s*\(\s*([^)]+)\s*\)', re.IGNORECASE), r'sqrt(\2)'),
            (re.compile(r'\blog\s+of\s+(\w+)\b', re.IGNORECASE), r'log(\1)'),
            (re.compile(r'\bln\s+of\s+(\w+)\b', re.IGNORECASE), r'ln(\1)'),
            (re.compile(r'\blog\s*\(\s*([^)]+)\s*\)', re.IGNORECASE), r'log(\1)'),
            (re.compile(r'\bln\s*\(\s*([^)]+)\s*\)', re.IGNORECASE), r'ln(\1)'),
            (re.compile(r'\bpi\b', re.IGNORECASE), r'pi'),
            (re.compile(r'\beulers?\s+number\b', re.IGNORECASE), r'E'),
            (re.compile(r'\bexponential\s+function\b', re.IGNORECASE), r'exp'),
            (re.compile(r'\b(\w+)\s+cubed\b', re.IGNORECASE), r'\1**3'),
            (re.compile(r'\b(\w+)\s+squared\b', re.IGNORECASE), r'\1**2'),
            (re.compile(r'\b(\w+)\s+to\s+the\s+(\w+)\s*(?:power)?\b', re.IGNORECASE), r'\1**\2'),
            (re.compile(r'\b(\w+)\s+times\s+(\w+)\b', re.IGNORECASE), r'\1*\2'),
            (re.compile(r'\b(\w+)\s+plus\s+(\w+)\b', re.IGNORECASE), r'\1+\2'),
            (re.compile(r'\b(\w+)\s+minus\s+(\w+)\b', re.IGNORECASE), r'\1-\2'),
            (re.compile(r'\b(\w+)\s+over\s+(\w+)\b', re.IGNORECASE), r'\1/\2'),
            (re.compile(r'\bthe\s+derivative\s+of\s+', re.IGNORECASE), r'derive '),
            (re.compile(r'\bthe\s+integral\s+of\s+', re.IGNORECASE), r'integrate '),
            (re.compile(r'\bantiderivative\s+of\s+', re.IGNORECASE), r'integrate '),
            (re.compile(r'\bthe\s+limit\s+of\s+', re.IGNORECASE), r'limit '),
            (re.compile(r'\bsimplify\s+', re.IGNORECASE), r'simplify '),
            (re.compile(r'\bexpand\s+', re.IGNORECASE), r'expand '),
            (re.compile(r'\bfactor\s+', re.IGNORECASE), r'factor '),
            (re.compile(r'\bsolve\s+for\s+(\w+)\s+in\s+', re.IGNORECASE), r'solve '),
            (re.compile(r'\bevaluate\s+', re.IGNORECASE), r'evaluate '),
            (re.compile(r'\bwhat\s+is\s+', re.IGNORECASE), r''),
            (re.compile(r'\bwhat\s+are\s+', re.IGNORECASE), r''),
            (re.compile(r'\bcan\s+you\s+', re.IGNORECASE), r''),
            (re.compile(r'\bplease\s+', re.IGNORECASE), r''),
            (re.compile(r'\bfind\s+', re.IGNORECASE), r''),
            (re.compile(r'\bthe\s+', re.IGNORECASE), r''),
            (re.compile(r'\bof\s+', re.IGNORECASE), r''),
        ]

    def _convert_to_sympy(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r'\b(\w+)\s+cubed\b', r'\1**3', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(\w+)\s+squared\b', r'\1**2', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(\w+)\s+times\s+(\w+)\b', r'\1*\2', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(\w+)\s+plus\s+(\w+)\b', r'\1+\2', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(\w+)\s+minus\s+(\w+)\b', r'\1-\2', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(\w+)\s+over\s+(\w+)\b', r'\1/\2', text, flags=re.IGNORECASE)
        text = re.sub(r'\bsine\s+of\s+(\w+)\b', r'sin(\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'\bcosine\s+of\s+(\w+)\b', r'cos(\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'\btangent\s+of\s+(\w+)\b', r'tan(\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'\bsquare\s+root\s+of\s+(\w+)\b', r'sqrt(\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'\blog\s+of\s+(\w+)\b', r'log(\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'\bln\s+of\s+(\w+)\b', r'ln(\1)', text, flags=re.IGNORECASE)
        text = re.sub(r'\bpi\b', r'pi', text, flags=re.IGNORECASE)
        text = re.sub(r'\be\s+to\s+the\s+', r'exp(', text, flags=re.IGNORECASE)
        text = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', text)
        if text.count('(') > text.count(')'):
            text += ')'
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
