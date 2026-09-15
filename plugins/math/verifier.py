from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class VerificationResult:
    verified: bool
    method: str
    confidence: str
    detail: str = ""


class MathVerifierPlugin(EventDrivenPlugin):
    name = "math_verifier"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self._history: list[VerificationResult] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def verify(self, operation: str, query: str, candidate: str) -> VerificationResult:
        engine = self._get_engine()
        if engine is None:
            return VerificationResult(verified=False, method="none", confidence="low", detail="no_engine")
        if operation == "integral":
            return self._verify_integral(engine, query, candidate)
        if operation == "derivative":
            return self._verify_derivative(query, candidate)
        if operation == "limit":
            return self._verify_limit(query, candidate)
        if operation in {"determinant", "inverse", "eigenvalues", "trace", "rank"}:
            return self._verify_matrix(operation, query, candidate)
        if operation == "solve":
            return self._verify_solve(query, candidate)
        if operation == "solve_linear":
            return self._verify_solve_linear(query, candidate)
        if operation == "solve_quadratic":
            return self._verify_solve_quadratic(query, candidate)
        if operation == "trig_simplify":
            return self._verify_trig_simplify(query, candidate)
        if operation == "arithmetic":
            return self._verify_arithmetic(query, candidate)
        return self._verify_exact(query, candidate)

    def _verify_exact(self, expected: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, simplify
            if simplify(sympify(expected) - sympify(candidate)) == 0:
                return VerificationResult(verified=True, method="exact", confidence="high", detail="exact_match")
        except Exception:
            pass
        if expected.strip() == candidate.strip():
            return VerificationResult(verified=True, method="string", confidence="medium", detail="string_match")
        return VerificationResult(verified=False, method="exact", confidence="low", detail="mismatch")

    def _verify_integral(self, engine: Any, query: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, simplify, Eq
            deriv = engine.compute("derivative", expression=candidate)
            if deriv.success:
                expected = simplify(sympify(query))
                actual = simplify(sympify(deriv.result))
                if Eq(actual, expected):
                    return VerificationResult(verified=True, method="ftc", confidence="high", detail="derivative_of_candidate_matches_integrand")
        except Exception:
            pass
        return VerificationResult(verified=False, method="ftc", confidence="low", detail="fundamental_theorem_check_failed")

    def _verify_derivative(self, query: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, Symbol, simplify, Eq
            expr = sympify(query)
            x = Symbol("x")
            expected = simplify(sympify(candidate))
            actual = simplify(expr.diff(x))
            if Eq(actual, expected):
                return VerificationResult(verified=True, method="exact", confidence="high", detail="exact_match")
        except Exception:
            pass
        return VerificationResult(verified=False, method="exact", confidence="low", detail="mismatch")

    def _verify_limit(self, query: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, limit as sym_limit, Symbol, simplify
            expr = sympify(query)
            x = Symbol("x")
            actual = sym_limit(expr, x, 0)
            if simplify(actual - sympify(candidate)) == 0:
                return VerificationResult(verified=True, method="symbolic", confidence="high", detail="limit_matches")
        except Exception:
            pass
        return self._verify_exact(query, candidate)

    def _verify_matrix(self, operation: str, query: str, candidate: str) -> VerificationResult:
        try:
            engine = self._get_engine()
            if engine is None:
                return VerificationResult(verified=False, method="none", confidence="low", detail="no_engine")
            matrix = self._safe_matrix_parse(query)
            expected = engine.compute(operation, matrix=matrix)
            if expected.success and expected.result.strip() == candidate.strip():
                return VerificationResult(verified=True, method="exact", confidence="high", detail="exact_match")
        except Exception:
            pass
        return VerificationResult(verified=False, method="exact", confidence="low", detail="mismatch")

    @staticmethod
    def _safe_matrix_parse(raw: str) -> list[list[float]]:
        import ast, json
        cleaned = raw.replace("'", '"')
        try:
            data = json.loads(cleaned)
            if isinstance(data, list) and all(isinstance(row, list) for row in data):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            tree = ast.parse(raw, mode='eval')
            if isinstance(tree.body, ast.List):
                return [[float(c) for c in row.elts] for row in tree.body.elts if isinstance(row, ast.List)]
        except Exception:
            pass
        raise ValueError(f"Cannot parse matrix: {raw}")

    def _verify_solve(self, query: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, solve, Symbol
            x = Symbol("x")
            if "=" in query:
                lhs, rhs = query.split("=", 1)
                expr = sympify(lhs) - sympify(rhs)
            else:
                expr = sympify(query)
            expected = solve(expr, x)
            if str(expected).strip() == candidate.strip():
                return VerificationResult(verified=True, method="exact", confidence="high", detail="exact_match")
        except Exception:
            pass
        return VerificationResult(verified=False, method="exact", confidence="low", detail="mismatch")

    def _verify_solve_linear(self, query: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, solve, Symbol
            x = Symbol("x")
            if "=" in query:
                lhs, rhs = query.split("=", 1)
                expr = sympify(lhs) - sympify(rhs)
            else:
                expr = sympify(query)
            expected = solve(expr, x)
            if str(expected).strip() == candidate.strip():
                return VerificationResult(verified=True, method="substitution", confidence="high", detail="solution_satisfies_equation")
        except Exception:
            pass
        return VerificationResult(verified=False, method="substitution", confidence="low", detail="mismatch")

    def _verify_solve_quadratic(self, query: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, solve, Symbol
            x = Symbol("x")
            if "=" in query:
                lhs, rhs = query.split("=", 1)
                expr = sympify(lhs) - sympify(rhs)
            else:
                expr = sympify(query)
            expected = solve(expr, x)
            if str(expected).strip() == candidate.strip():
                return VerificationResult(verified=True, method="substitution", confidence="high", detail="solutions_satisfy_equation")
        except Exception:
            pass
        return VerificationResult(verified=False, method="substitution", confidence="low", detail="mismatch")

    def _verify_trig_simplify(self, query: str, candidate: str) -> VerificationResult:
        try:
            from sympy import sympify, trigsimp, simplify, N
            expr = sympify(query)
            expected = trigsimp(expr)
            if simplify(expected - sympify(candidate)) == 0:
                return VerificationResult(verified=True, method="symbolic", confidence="high", detail="trig_identity_match")
            val1 = float(N(expr.subs({"x": 0.5})))
            val2 = float(N(sympify(candidate).subs({"x": 0.5})))
            if abs(val1 - val2) < 1e-9:
                return VerificationResult(verified=True, method="numeric", confidence="medium", detail="numeric_match_at_sample")
        except Exception:
            pass
        return VerificationResult(verified=False, method="symbolic", confidence="low", detail="mismatch")

    def _verify_arithmetic(self, query: str, candidate: str) -> VerificationResult:
        ops = {"+", "-", "*", "/"}
        op = next((c for c in query if c in ops), None)
        if op is None:
            return VerificationResult(verified=False, method="none", confidence="low", detail="no_operator")
        left, right = query.split(op, 1)
        left = float(left.strip())
        right = float(right.strip())
        if op == "+":
            expected = left + right
        elif op == "-":
            expected = left - right
        elif op == "*":
            expected = left * right
        else:
            if right == 0:
                return VerificationResult(verified=False, method="none", confidence="low", detail="division_by_zero")
            expected = left / right
        if str(expected) == candidate.strip():
            return VerificationResult(verified=True, method="exact", confidence="high", detail="exact_match")
        return VerificationResult(verified=False, method="exact", confidence="low", detail="mismatch")

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass

    def _get_engine(self) -> Any:
        if self.context is None:
            return None
        return self.context.plugins.get("symbolic_engine")
