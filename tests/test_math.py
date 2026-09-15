from __future__ import annotations

import pytest

from core.context import Context
from core.registry import PluginRegistry
from plugins.math.router import MathRouterPlugin
from plugins.math.symbolic_engine import SymbolicEnginePlugin
from plugins.math.verifier import MathVerifierPlugin
from plugins.math.pipeline import MathPipelinePlugin
from plugins.math.datetime_router import DateTimeRouterPlugin
from plugins.math.datetime_engine import DateTimeEnginePlugin
from plugins.math.units_router import UnitsRouterPlugin
from plugins.math.units_engine import UnitsEnginePlugin


def test_math_router_arithmetic():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("2 + 3")
    assert result.success is True
    assert result.operation == "arithmetic"
    assert result.args == {"left": "2", "op": "+", "right": "3"}
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert computed.result == "5.0"


def test_math_router_no_match():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("hello world")
    assert result.success is False


def test_symbolic_engine_derivative():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["symbolic_engine"]
    result = engine.compute("derivative", expression="x**2")
    assert result.success is True
    assert "2*x" in result.result


def test_symbolic_engine_integral():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["symbolic_engine"]
    result = engine.compute("integral", expression="x**2")
    assert result.success is True
    assert "x**3" in result.result


def test_math_verifier_validates_integral():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.start_all()
    verifier = ctx.plugins["math_verifier"]
    result = verifier.verify("integral", "x**2", "x**3/3")
    assert result.verified is True
    assert result.method == "ftc"


def test_router_algebra():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("solve x**2 - 4 = 0")
    assert result.success is True
    assert result.operation == "solve"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "2" in computed.result and "-2" in computed.result


def test_router_limit():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("limit (x**2 - 1)/(x - 1) as x -> 1")
    assert result.success is True
    assert result.operation == "limit"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "2" in computed.result


def test_router_matrix_det():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("det [[1,2],[3,4]]")
    assert result.success is True
    assert result.operation == "determinant"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert computed.result == "-2"


def test_router_matrix_inverse():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("inverse [[1,2],[3,4]]")
    assert result.success is True
    assert result.operation == "inverse"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "-2" in computed.result


def test_router_expand():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("expand (x + 1)**2")
    assert result.success is True
    assert result.operation == "expand"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "x**2" in computed.result


def test_router_factor():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("factor x**2 + 5*x + 6")
    assert result.success is True
    assert result.operation == "factor"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "(x + 2)" in computed.result


def test_router_evaluate():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("evaluate x**2 at x = 3")
    assert result.success is True
    assert result.operation == "evaluate"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "9" in computed.result


def test_pipeline_multi_step():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    pipeline = ctx.plugins["math_pipeline"]
    result = pipeline.run("derive x**2; then evaluate at x = 3")
    assert result.success is True
    assert len(result.steps) >= 2


def test_pipeline_single_step_fallback():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    pipeline = ctx.plugins["math_pipeline"]
    result = pipeline.run("2 + 3")
    assert result.success is True
    assert result.result == "5.0"


def test_engine_auto_detect_variable():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["symbolic_engine"]
    result = engine.compute("derivative", expression="t**2")
    assert result.success is True
    assert "2*t" in result.result


def test_verifier_limit():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.start_all()
    verifier = ctx.plugins["math_verifier"]
    result = verifier.verify("limit", "sin(x)/x", "1")
    assert result.verified is True


def test_verifier_matrix():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.start_all()
    verifier = ctx.plugins["math_verifier"]
    result = verifier.verify("determinant", "[[1,2],[3,4]]", "-2")
    assert result.verified is True


def test_router_solve_linear():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("solve linear 2*x + 4 = 0")
    assert result.success is True
    assert result.operation == "solve_linear"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "-2" in computed.result


def test_router_solve_quadratic():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("solve quadratic x**2 - 5*x + 6 = 0")
    assert result.success is True
    assert result.operation == "solve_quadratic"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "2" in computed.result
    assert "3" in computed.result


def test_router_trig_simplify():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MathRouterPlugin)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.register_class(MathPipelinePlugin)
    reg.start_all()
    router = ctx.plugins["math_router"]
    result = router.route("trig_simplify sin(x)**2 + cos(x)**2")
    assert result.success is True
    assert result.operation == "trig_simplify"
    engine = ctx.plugins["symbolic_engine"]
    computed = engine.compute(result.operation, **result.args)
    assert computed.success is True
    assert "1" in computed.result


def test_engine_solve_linear_manual():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["symbolic_engine"]
    result = engine.compute("solve_linear", expression="2*x + 4")
    assert result.success is True
    assert "-2" in result.result


def test_engine_solve_quadratic_manual():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["symbolic_engine"]
    result = engine.compute("solve_quadratic", expression="x**2 - 5*x + 6")
    assert result.success is True
    assert "2" in result.result
    assert "3" in result.result


def test_engine_trig_simplify_manual():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["symbolic_engine"]
    result = engine.compute("trig_simplify", expression="sin(x)**2 + cos(x)**2")
    assert result.success is True
    assert "1" in result.result


def test_verifier_solve_linear():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.start_all()
    verifier = ctx.plugins["math_verifier"]
    result = verifier.verify("solve_linear", "2*x + 4", "[-2]")
    assert result.verified is True


def test_verifier_solve_quadratic():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.start_all()
    verifier = ctx.plugins["math_verifier"]
    result = verifier.verify("solve_quadratic", "x**2 - 5*x + 6", "[2, 3]")
    assert result.verified is True


def test_verifier_trig_simplify():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(SymbolicEnginePlugin)
    reg.register_class(MathVerifierPlugin)
    reg.start_all()
    verifier = ctx.plugins["math_verifier"]
    result = verifier.verify("trig_simplify", "sin(x)**2 + cos(x)**2", "1")
    assert result.verified is True


def test_datetime_router_today():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(DateTimeRouterPlugin)
    reg.register_class(DateTimeEnginePlugin)
    reg.start_all()
    router = ctx.plugins["datetime_router"]
    result = router.route("today")
    assert result.success is True
    assert result.operation == "today"


def test_datetime_router_add_days():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(DateTimeRouterPlugin)
    reg.register_class(DateTimeEnginePlugin)
    reg.start_all()
    router = ctx.plugins["datetime_router"]
    result = router.route("add 5 days to 2024-01-01")
    assert result.success is True
    assert result.operation == "add_days"
    assert result.args == {"days": 5, "date": "2024-01-01"}


def test_datetime_engine_add_days():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(DateTimeEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["datetime_engine"]
    result = engine.compute("add_days", days=5, date="2024-01-01")
    assert result.success is True
    assert result.result == "2024-01-06"


def test_datetime_engine_days_between():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(DateTimeEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["datetime_engine"]
    result = engine.compute("days_between", start="2024-01-01", end="2024-01-10")
    assert result.success is True
    assert result.result == "9"


def test_datetime_engine_weekday():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(DateTimeEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["datetime_engine"]
    result = engine.compute("weekday", date="2024-01-01")
    assert result.success is True
    assert result.result == "Monday"


def test_units_router_convert():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(UnitsRouterPlugin)
    reg.register_class(UnitsEnginePlugin)
    reg.start_all()
    router = ctx.plugins["units_router"]
    result = router.route("convert 100 km to miles")
    assert result.success is True
    assert result.operation == "convert"
    assert result.args == {"value": 100.0, "from_unit": "km", "to_unit": "miles"}


def test_units_engine_convert():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(UnitsEnginePlugin)
    reg.start_all()
    engine = ctx.plugins["units_engine"]
    result = engine.compute("convert", value=100, from_unit="km", to_unit="miles")
    assert result.success is True
    assert "mile" in result.result


def test_units_router_in_format():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(UnitsRouterPlugin)
    reg.register_class(UnitsEnginePlugin)
    reg.start_all()
    router = ctx.plugins["units_router"]
    result = router.route("100 km in miles")
    assert result.success is True
    assert result.operation == "convert"
    assert result.args == {"value": 100.0, "from_unit": "km", "to_unit": "miles"}


def test_embedding_model_normalizes_vectors():
    from plugins.model.embedding import EmbeddingModel
    model = EmbeddingModel()
    model._cache = {}
    vector = [3.0, 4.0]
    normalized = model._normalize(vector)
    assert normalized == [0.6, 0.8]


def test_embedding_model_embed_batch_uses_cache():
    from plugins.model.embedding import EmbeddingModel
    model = EmbeddingModel()
    model._cache = {"hello": [1.0, 0.0]}
    model._hits = 0
    model._misses = 0
    results = model.embed_batch(["hello", "world"])
    assert results[0] == [1.0, 0.0]
    assert model._hits == 1
    assert model._misses == 1


def test_semantic_router_returns_none_without_embedder():
    from plugins.agent.semantic_router import SemanticRouter
    router = SemanticRouter()
    router._embedder = None
    router._routes = []
    assert router.route("derive x^2") is None


def test_semantic_router_precompute_populates_embeddings():
    from plugins.agent.semantic_router import SemanticRouter
    router = SemanticRouter()
    router._embedder = type("MockEmbedder", (), {
        "embed": lambda self, text: [0.0] * 4,
        "embed_batch": lambda self, texts: [[0.0] * 4 for _ in texts],
    })()
    router._routes = [
        {"id": "math_derivative", "examples": ["derivative of x^2"], "delegate": "math", "threshold": 0.7},
    ]
    router._embeddings = {}
    router._precompute()
    assert "math_derivative" in router._embeddings
    assert len(router._embeddings["math_derivative"]) == 4


def test_parameter_extractor_converts_natural_language_math():
    from plugins.agent.parameter_extractor import ParameterExtractor
    extractor = ParameterExtractor()
    assert "x**3" in extractor.extract_math_expression("x cubed")
    assert "sin(x)" in extractor.extract_math_expression("sine of x")
    assert "cos(x)" in extractor.extract_math_expression("cosine of x")
    assert "tan(x)" in extractor.extract_math_expression("tangent of x")
    assert "exp(2*x)" in extractor.extract_math_expression("e to the 2x")
    assert "exp(x+1)" in extractor.extract_math_expression("e to the x plus 1")
    assert "sqrt(x)" in extractor.extract_math_expression("square root of x")
    assert "pi" in extractor.extract_math_expression("pi")
    assert "log(x)" in extractor.extract_math_expression("log of x")
    assert "ln(x)" in extractor.extract_math_expression("ln of x")
    assert "x**2" in extractor.extract_math_expression("x squared")
    assert "x**3" in extractor.extract_math_expression("x cubed")


def test_parameter_extractor_handles_operators():
    from plugins.agent.parameter_extractor import ParameterExtractor
    extractor = ParameterExtractor()
    assert "x*y" in extractor.extract_math_expression("x times y")
    assert "x+y" in extractor.extract_math_expression("x plus y")
    assert "x-y" in extractor.extract_math_expression("x minus y")
    assert "x/y" in extractor.extract_math_expression("x over y")


def test_parameter_extractor_strips_filler_words():
    from plugins.agent.parameter_extractor import ParameterExtractor
    extractor = ParameterExtractor()
    result = extractor.extract_math_expression("what is the derivative of x squared")
    assert "derive" in result
    assert "x**2" in result
    assert "what" not in result
    assert "is" not in result
    assert "the" not in result


def test_parameter_extractor_evaluate_point():
    from plugins.agent.parameter_extractor import ParameterExtractor
    extractor = ParameterExtractor()
    var, point = extractor.extract_evaluate_point("evaluate at x = pi/2")
    assert var == "x"
    assert point == "pi/2"


def test_query_splitter_splits_on_sentence_boundaries():
    from plugins.agent.query_splitter import QuerySplitter
    splitter = QuerySplitter()
    text = "What is the derivative of x squared? And how is pizza made?"
    fragments = splitter.split(text)
    assert len(fragments) == 2
    assert fragments[0].domain == "math"
    assert fragments[1].domain == "general"
    assert "derivative" in fragments[0].text.lower()
    assert "pizza" in fragments[1].text.lower()


def test_query_splitter_single_domain():
    from plugins.agent.query_splitter import QuerySplitter
    splitter = QuerySplitter()
    fragments = splitter.split("derive x squared")
    assert len(fragments) == 1
    assert fragments[0].domain == "math"


def test_query_splitter_empty_input():
    from plugins.agent.query_splitter import QuerySplitter
    splitter = QuerySplitter()
    fragments = splitter.split("")
    assert len(fragments) == 1
    assert fragments[0].domain == "general"


def test_multi_domain_router_returns_none_for_single_domain():
    from plugins.agent.multi_domain_router import MultiDomainRouter
    from plugins.agent.query_splitter import QuerySplitter
    router = MultiDomainRouter()
    router._splitter = QuerySplitter()
    result = router.route_multi("derive x squared", None)
    assert result is None


def test_multi_domain_router_routes_fragments():
    from plugins.agent.multi_domain_router import MultiDomainRouter
    from plugins.agent.query_splitter import QuerySplitter
    router = MultiDomainRouter()
    router._splitter = QuerySplitter()
    text = "What is the derivative of x squared? And how is pizza made?"
    result = router.route_multi(text, None)
    assert result is not None
    assert len(result.results) == 2
    assert result.results[0].domain == "math"
    assert result.results[1].domain == "general"
    assert result.has_unresolved is True


def test_aggregate_response_single_result():
    from plugins.agent.aggregate_response import AggregateResponse
    from plugins.agent.multi_domain_router import DomainResult, Fragment
    agg = AggregateResponse()
    result = agg.aggregate([DomainResult(fragment=Fragment(text="test", domain="math"), domain="math", response="42")])
    assert result == "42"


def test_aggregate_response_multiple_results():
    from plugins.agent.aggregate_response import AggregateResponse
    from plugins.agent.multi_domain_router import DomainResult, Fragment
    agg = AggregateResponse()
    results = [
        DomainResult(fragment=Fragment(text="math", domain="math"), domain="math", response="42"),
        DomainResult(fragment=Fragment(text="pizza", domain="general"), domain="general", response="flour and water"),
    ]
    result = agg.aggregate(results)
    assert "[math] 42" in result
    assert "[general] flour and water" in result


def test_aggregate_response_empty_results():
    from plugins.agent.aggregate_response import AggregateResponse
    agg = AggregateResponse()
    assert agg.aggregate([]) == ""
