from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def try_math_router(text: str, context: Any) -> Optional[str]:
    math_router = context.plugins.get("math_router") if context else None
    math_pipeline = context.plugins.get("math_pipeline") if context else None
    engine = context.plugins.get("symbolic_engine") if context else None
    verifier = context.plugins.get("math_verifier") if context else None
    logger = context.plugins.get("event_logger") if context else None
    if math_router is None:
        return None
    try:
        if text.strip().lower().startswith("/math "):
            query = text.strip()[6:]
            if engine is not None and verifier is not None:
                pipeline_result = math_pipeline.run(query) if math_pipeline is not None else math_router.route(query)
                if pipeline_result.success:
                    expression = pipeline_result.args.get("expression", query) if hasattr(pipeline_result, 'args') else query
                    verified = verifier.verify(pipeline_result.operation or "simplify", expression, pipeline_result.result)
                    if verified.verified:
                        if logger is not None:
                            logger.emit("math.solved", {
                                "route": pipeline_result.operation,
                                "query": query,
                                "result": pipeline_result.result,
                                "steps": pipeline_result.steps,
                                "verified": True,
                            })
                        formatted = "\n".join(pipeline_result.steps + [f"Result: {pipeline_result.result}"])
                        context.append_message("assistant", formatted)
                        return formatted
        else:
            if math_pipeline is not None:
                result = math_pipeline.run(text)
            else:
                result = math_router.route(text)
            if result.success:
                expression = result.args.get("expression", text) if hasattr(result, 'args') else text
                verified = verifier.verify(result.operation or "simplify", expression, result.result) if verifier is not None else None
                if verified is not None and verified.verified:
                    if logger is not None:
                        logger.emit("math.solved", {
                            "route": result.operation,
                            "query": text,
                            "result": result.result,
                            "steps": result.steps,
                        })
                    formatted = "\n".join(result.steps + [f"Result: {result.result}"])
                    context.append_message("assistant", formatted)
                    return formatted
    except Exception as exc:
        logger.debug("Math router failed: %s", exc)
    return None


def try_datetime_router(text: str, context: Any) -> Optional[str]:
    router = context.plugins.get("datetime_router") if context else None
    engine = context.plugins.get("datetime_engine") if context else None
    if router is None or engine is None:
        return None
    logger = context.plugins.get("event_logger") if context else None
    try:
        if text.strip().lower().startswith("/datetime "):
            query = text.strip()[10:]
        else:
            query = text.strip()
        result = router.route(query)
        if result.success:
            computed = engine.compute(result.operation, **result.args)
            if computed.success:
                if logger is not None:
                    logger.emit("datetime.solved", {
                        "route": result.operation,
                        "query": text,
                        "result": computed.result,
                        "steps": computed.steps,
                    })
                formatted = "\n".join(computed.steps + [f"Result: {computed.result}"])
                context.append_message("assistant", formatted)
                return formatted
    except Exception as exc:
        logger.debug("Math router failed: %s", exc)
    return None


def try_units_router(text: str, context: Any) -> Optional[str]:
    router = context.plugins.get("units_router") if context else None
    engine = context.plugins.get("units_engine") if context else None
    if router is None or engine is None:
        return None
    logger = context.plugins.get("event_logger") if context else None
    try:
        if text.strip().lower().startswith("/units "):
            query = text.strip()[7:]
        else:
            query = text.strip()
        result = router.route(query)
        if result.success:
            computed = engine.compute(result.operation, **result.args)
            if computed.success:
                if logger is not None:
                    logger.emit("units.solved", {
                        "route": result.operation,
                        "query": text,
                        "result": computed.result,
                        "steps": computed.steps,
                    })
                formatted = "\n".join(computed.steps + [f"Result: {computed.result}"])
                context.append_message("assistant", formatted)
                return formatted
    except Exception as exc:
        logger.debug("Math router failed: %s", exc)
    return None


def try_specialized_routers(text: str, context: Any) -> Optional[str]:
    for router in (try_math_router, try_datetime_router, try_units_router):
        result = router(text, context)
        if result is not None:
            return result
    return None
