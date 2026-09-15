from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class MathResult:
    success: bool
    result: str = ""
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    operation: str | None = None


class SymbolicEnginePlugin(EventDrivenPlugin):
    name = "symbolic_engine"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self._cache: dict[str, MathResult] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def compute(self, operation: str, **kwargs: Any) -> MathResult:
        key = f"{operation}:{sorted(kwargs.items())}"
        if key in self._cache:
            return self._cache[key]
        try:
            from sympy import (
                Eq,
                Matrix,
                Symbol,
                diff,
                expand,
                factor,
                integrate,
                limit as sym_limit,
                simplify,
                solve,
                sympify,
            )
        except ImportError as exc:
            result = MathResult(success=False, error=f"sympy_unavailable: {exc}", operation=operation)
            self._cache[key] = result
            return result
        try:
            if operation == "arithmetic":
                result = self._arithmetic(**kwargs)
            elif operation == "derivative":
                result = self._derivative(**kwargs)
            elif operation == "integral":
                result = self._integral(**kwargs)
            elif operation == "limit":
                result = self._limit(**kwargs)
            elif operation == "solve":
                result = self._solve(**kwargs)
            elif operation == "solve_linear":
                result = self._solve_linear(**kwargs)
            elif operation == "solve_quadratic":
                result = self._solve_quadratic(**kwargs)
            elif operation == "trig_simplify":
                result = self._trig_simplify(**kwargs)
            elif operation == "expand":
                result = self._expand(**kwargs)
            elif operation == "factor":
                result = self._factor(**kwargs)
            elif operation == "simplify":
                result = self._simplify(**kwargs)
            elif operation == "determinant":
                result = self._matrix_op("det", **kwargs)
            elif operation == "inverse":
                result = self._matrix_op("inv", **kwargs)
            elif operation == "eigenvalues":
                result = self._matrix_op("eigenvals", **kwargs)
            elif operation == "trace":
                result = self._matrix_op("trace", **kwargs)
            elif operation == "rank":
                result = self._matrix_op("rank", **kwargs)
            elif operation == "evaluate":
                result = self._evaluate(**kwargs)
            else:
                expr = sympify(kwargs.get("expression", ""))
                value = simplify(expr)
                result = MathResult(success=True, result=str(value), steps=[f"simplify({expr}) = {value}"], operation=operation)
        except Exception as exc:
            result = MathResult(success=False, error=str(exc), operation=operation)
        self._cache[key] = result
        return result

    def _arithmetic(self, **kwargs: Any) -> MathResult:
        left = float(kwargs["left"])
        right = float(kwargs["right"])
        op = kwargs["op"]
        if op == "+":
            value = left + right
        elif op == "-":
            value = left - right
        elif op == "*":
            value = left * right
        else:
            if right == 0:
                return MathResult(success=False, error="Division by zero", operation="arithmetic")
            value = left / right
        return MathResult(success=True, result=str(value), steps=[f"{left} {op} {right} = {value}"], operation="arithmetic")

    def _detect_variable(self, expr_str: str) -> str:
        from sympy import sympify
        clean = expr_str.split("=")[0].strip() if "=" in expr_str else expr_str
        expr = sympify(clean)
        free_symbols = expr.free_symbols
        if free_symbols:
            return str(next(iter(free_symbols)))
        return "x"

    def _derivative(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, Symbol, diff
        expr = sympify(kwargs["expression"])
        var_name = kwargs.get("variable") or self._detect_variable(kwargs["expression"])
        x = Symbol(var_name)
        value = diff(expr, x)
        return MathResult(success=True, result=str(value), steps=[f"d/d{var_name} ({expr}) = {value}"], operation="derivative")

    def _integral(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, Symbol, integrate
        expr = sympify(kwargs["expression"])
        var_name = kwargs.get("variable") or self._detect_variable(kwargs["expression"])
        x = Symbol(var_name)
        value = integrate(expr, x)
        return MathResult(success=True, result=str(value), steps=[f"∫ {expr} d{var_name} = {value}"], operation="integral")

    def _limit(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, Symbol, limit as sym_limit
        expr = sympify(kwargs["expression"])
        var_name = kwargs.get("variable") or self._detect_variable(kwargs["expression"])
        x = Symbol(var_name)
        point = kwargs.get("point", 0)
        value = sym_limit(expr, x, point)
        return MathResult(success=True, result=str(value), steps=[f"lim_{var_name}->{point} ({expr}) = {value}"], operation="limit")

    def _solve(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, Eq, solve, Symbol, nsolve
        var_name = kwargs.get("variable") or self._detect_variable(kwargs["expression"])
        x = Symbol(var_name)
        expr_str = kwargs["expression"]
        if "=" in expr_str:
            lhs, rhs = expr_str.split("=", 1)
            expr = Eq(sympify(lhs), sympify(rhs))
        else:
            expr = sympify(expr_str)
        try:
            value = solve(expr, x)
            if not value:
                return MathResult(success=True, result="No closed-form solution found", steps=[f"solve({expr}, {var_name}) = No closed-form solution"], operation="solve")
            return MathResult(success=True, result=str(value), steps=[f"solve({expr}, {var_name}) = {value}"], operation="solve")
        except Exception:
            return MathResult(success=True, result="No closed-form solution found", steps=[f"solve({expr}, {var_name}) = No closed-form solution (transcendental or unsupported)"], operation="solve")

    def _solve_linear(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, Symbol, solve, Eq
        expr_str = kwargs["expression"]
        var_name = kwargs.get("variable") or self._detect_variable(expr_str)
        x = Symbol(var_name)
        if "=" in expr_str:
            lhs, rhs = expr_str.split("=", 1)
            expr = Eq(sympify(lhs), sympify(rhs))
        else:
            expr = sympify(expr_str)
        poly = expr.as_poly(x) if hasattr(expr, "as_poly") else None
        if poly is not None and poly.degree() == 1:
            a = poly.LC()
            b = poly.nth(0)
            if a == 0:
                return MathResult(success=False, error="Not a linear equation (a=0)", operation="solve_linear")
            solution = -b / a
            return MathResult(success=True, result=str(solution), steps=[f"Linear: {a}*x + {b} = 0", f"x = -{b}/{a} = {solution}"], operation="solve_linear")
        value = solve(expr, x)
        return MathResult(success=True, result=str(value), steps=[f"solve_linear({expr}, {var_name}) = {value}"], operation="solve_linear")

    def _solve_quadratic(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, Symbol, solve, Eq, sqrt
        expr_str = kwargs["expression"]
        var_name = kwargs.get("variable") or self._detect_variable(expr_str)
        x = Symbol(var_name)
        if "=" in expr_str:
            lhs, rhs = expr_str.split("=", 1)
            expr = Eq(sympify(lhs), sympify(rhs))
        else:
            expr = sympify(expr_str)
        poly = expr.as_poly(x) if hasattr(expr, "as_poly") else None
        if poly is not None and poly.degree() == 2:
            a = poly.LC()
            b = poly.nth(1)
            c = poly.nth(0)
            discriminant = b**2 - 4 * a * c
            if discriminant >= 0:
                sqrt_d = sqrt(discriminant)
                x1 = (-b + sqrt_d) / (2 * a)
                x2 = (-b - sqrt_d) / (2 * a)
                steps = [
                    f"Quadratic: {a}*x^2 + {b}*x + {c} = 0",
                    f"a={a}, b={b}, c={c}",
                    f"Discriminant = b^2 - 4ac = {discriminant}",
                    f"x = (-b ± sqrt(D)) / (2a)",
                    f"x1 = {x1}",
                    f"x2 = {x2}",
                ]
                return MathResult(success=True, result=f"[{x1}, {x2}]", steps=steps, operation="solve_quadratic")
            else:
                return MathResult(success=False, error=f"Complex roots (discriminant={discriminant})", operation="solve_quadratic")
        value = solve(expr, x)
        return MathResult(success=True, result=str(value), steps=[f"solve_quadratic({expr}, {var_name}) = {value}"], operation="solve_quadratic")

    def _trig_simplify(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, trigsimp
        expr = sympify(kwargs["expression"])
        value = trigsimp(expr)
        return MathResult(success=True, result=str(value), steps=[f"trigsimp({expr}) = {value}"], operation="trig_simplify")

    def _expand(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, expand
        expr = sympify(kwargs["expression"])
        value = expand(expr)
        return MathResult(success=True, result=str(value), steps=[f"expand({expr}) = {value}"], operation="expand")

    def _factor(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, factor
        expr = sympify(kwargs["expression"])
        value = factor(expr)
        return MathResult(success=True, result=str(value), steps=[f"factor({expr}) = {value}"], operation="factor")

    def _simplify(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, simplify
        expr = sympify(kwargs["expression"])
        value = simplify(expr)
        return MathResult(success=True, result=str(value), steps=[f"simplify({expr}) = {value}"], operation="simplify")

    def _matrix_op(self, op: str, **kwargs: Any) -> MathResult:
        from sympy import Matrix
        data = kwargs["matrix"]
        m = Matrix(data)
        if op == "det":
            value = m.det()
            return MathResult(success=True, result=str(value), steps=[f"det({m}) = {value}"], operation="determinant")
        if op == "inv":
            value = m.inv()
            return MathResult(success=True, result=str(value), steps=[f"inverse({m}) = {value}"], operation="inverse")
        if op == "eigenvals":
            value = m.eigenvals()
            return MathResult(success=True, result=str(value), steps=[f"eigenvalues({m}) = {value}"], operation="eigenvalues")
        if op == "trace":
            value = m.trace()
            return MathResult(success=True, result=str(value), steps=[f"trace({m}) = {value}"], operation="trace")
        if op == "rank":
            value = m.rank()
            return MathResult(success=True, result=str(value), steps=[f"rank({m}) = {value}"], operation="rank")
        return MathResult(success=False, error=f"Unknown matrix op: {op}", operation=op)

    def _evaluate(self, **kwargs: Any) -> MathResult:
        from sympy import sympify, Symbol
        expr = sympify(kwargs["expression"])
        var_name = kwargs.get("variable") or self._detect_variable(kwargs["expression"])
        x = Symbol(var_name)
        point = kwargs.get("point", 0)
        if isinstance(point, str):
            try:
                point = sympify(point)
            except Exception:
                point = float(point)
        value = expr.subs(x, point)
        return MathResult(success=True, result=str(value), steps=[f"evaluate {expr} at {var_name}={point} = {value}"], operation="evaluate")

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
