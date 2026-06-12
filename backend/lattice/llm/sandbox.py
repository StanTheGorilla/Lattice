"""Sandboxed execution for AI-authored algorithms (Phase 2L-a).

Three public entry points:
- validate_code(code)        — AST check before saving; raises ValueError on violation
- execute_algorithm(code, data) — restricted exec with 5s thread timeout
- fetch_algorithm_data(session, requirements) — async data fetcher for data_requirements JSON
"""

from __future__ import annotations

import ast
import logging
import math
import statistics
import threading

logger = logging.getLogger(__name__)
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------- #
# Code validation
# --------------------------------------------------------------------------- #

_BLOCKED_CALLS = {
    "eval", "exec", "open", "compile", "__import__", "breakpoint",
    # P1-7: block reflection helpers that re-open the import door.
    "getattr", "setattr", "delattr", "vars", "globals", "locals", "input",
}

_REQUIRED_FUNC = "run"


def validate_code(code: str) -> None:
    """Raise ValueError if code contains forbidden constructs or missing run().

    P1-7: dunder attribute walks (``"".__class__.__mro__[1].__subclasses__()``)
    let restricted-exec code reach `os` / `subprocess` via Python's object
    graph. Since the research agent can pipe untrusted web text into the AI's
    code-generation path, prompt-injection → code execution is a real risk.
    Reject any ``ast.Attribute`` whose attribute starts with ``__``, plus the
    reflection helpers (`getattr`/`setattr`/`vars`/`globals`) that achieve
    the same thing without a literal dunder.

    Limitation (documented, not fixed here): `execute_algorithm` uses a
    daemon-thread join with a wall-clock timeout. Python cannot interrupt a
    running thread, so an infinite loop continues to burn a Pi core after
    `TimeoutError` is raised. Long-term we want a subprocess with
    ``resource`` limits; for now we at least warn-log timeout cases so the
    owner sees them.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError(
                "imports are not allowed in algorithm code — "
                "use the injected `data` dict and built-in math/statistics"
            )
        if isinstance(node, ast.Global):
            raise ValueError("global statements are not allowed")
        if isinstance(node, ast.Attribute):
            # Reject every dunder attribute access — `.__class__`,
            # `.__mro__`, `.__subclasses__`, `.__globals__`, etc. — which
            # are the standard sandbox-escape chains.
            if node.attr.startswith("__"):
                raise ValueError(
                    f"dunder attribute access ('.{node.attr}') is not allowed",
                )
        if isinstance(node, ast.Name) and node.id in _BLOCKED_CALLS:
            # Catches `g = getattr` then `g(x, '__class__')` etc.
            raise ValueError(f"reference to '{node.id}' is not allowed")
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _BLOCKED_CALLS:
                raise ValueError(f"call to '{name}' is not allowed")

    # Verify a top-level `def run(...)` exists
    top_level_funcs = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
        and isinstance(n, ast.FunctionDef)
    }
    # Only check top-level (direct children of module)
    module_func_names = {
        n.name for n in tree.body if isinstance(n, ast.FunctionDef)
    }
    if _REQUIRED_FUNC not in module_func_names:
        raise ValueError("algorithm must define a top-level `def run(data): ...` function")


# --------------------------------------------------------------------------- #
# Safe builtins
# --------------------------------------------------------------------------- #

_SAFE_BUILTINS: dict[str, Any] = {
    # type constructors
    "bool": bool, "int": int, "float": float, "str": str,
    "list": list, "dict": dict, "set": set, "tuple": tuple,
    "frozenset": frozenset, "bytes": bytes,
    # iteration & functional
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "range": range, "reversed": reversed, "sorted": sorted,
    "iter": iter, "next": next,
    # math & stats
    "abs": abs, "round": round, "sum": sum,
    "min": min, "max": max, "pow": pow, "divmod": divmod,
    # introspection (read-only)
    "len": len, "isinstance": isinstance, "issubclass": issubclass,
    "hasattr": hasattr, "type": type, "repr": repr, "format": format,
    "callable": callable,
    # logical
    "all": all, "any": any,
    # singletons
    "True": True, "False": False, "None": None,
    # safe exceptions
    "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError,
    "ZeroDivisionError": ZeroDivisionError,
    # stdlib modules injected as values
    "math": math,
    "statistics": statistics,
    # block everything else
    "__import__": None,
    "__builtins__": {},
}


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #

def execute_algorithm(code: str, data: dict[str, Any], timeout: float = 5.0) -> Any:
    """Execute algorithm code with injected data. Returns run(data) result.

    Runs in a daemon thread with a hard timeout so infinite loops can't block
    the event loop. Raises TimeoutError, or re-raises any exception from run().
    """
    namespace: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS, "data": data}
    result_box: list[Any] = [None]
    error_box: list[BaseException | None] = [None]

    def _target() -> None:
        try:
            exec(compile(code, "<algorithm>", "exec"), namespace)  # noqa: S102
            fn = namespace.get(_REQUIRED_FUNC)
            if fn is None or not callable(fn):
                error_box[0] = ValueError("run() not found after exec")
                return
            result_box[0] = fn(data)
        except Exception as exc:  # noqa: BLE001
            error_box[0] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # P1-7: daemon threads cannot be force-killed in CPython, so an
        # infinite-loop algorithm will keep burning a core after this
        # returns. Surfacing this at WARNING so the owner sees recurring
        # offenders in the log; the long-term fix is a subprocess sandbox
        # with `resource` limits (see module docstring).
        logger.warning(
            "algorithm thread exceeded %.1fs timeout — daemon thread leaks "
            "until process restart",
            timeout,
        )
        raise TimeoutError(f"algorithm exceeded {timeout}s timeout")
    if error_box[0] is not None:
        raise error_box[0]
    return result_box[0]


# --------------------------------------------------------------------------- #
# Data fetcher
# --------------------------------------------------------------------------- #

async def fetch_algorithm_data(
    session: AsyncSession,
    requirements: dict[str, Any],
) -> dict[str, Any]:
    """Fetch data declared in data_requirements and return as a plain dict.

    Keys produced:
      data["<metric_name>"]        — list of {timestamp, value} for each metric
      data["entries_<type>"]       — list of {timestamp, data} for each entry type
      data["calendar"]             — list of {title, start, end, is_all_day}
    Only keys that are requested are included.
    """
    # Import here to avoid circular deps at module load time
    from lattice.models import Entry, Metric  # noqa: PLC0415
    from lattice.sync.calendar_sync import cached_events_or_refresh  # noqa: PLC0415

    now = datetime.now(UTC)
    result: dict[str, Any] = {}

    # ---- metrics ----
    for req in requirements.get("metrics", []):
        metric_name: str = req["name"]
        days: int = int(req.get("days", 14))
        cutoff = (now - timedelta(days=days)).isoformat()
        stmt = (
            select(Metric)
            .where(Metric.metric_name == metric_name, Metric.timestamp >= cutoff)
            .order_by(Metric.timestamp.asc())
        )
        rows = list((await session.execute(stmt)).scalars().all())
        result[metric_name] = [
            {"timestamp": r.timestamp, "value": r.value} for r in rows
        ]

    # ---- entries ----
    for req in requirements.get("entries", []):
        entry_type: str = req["type"]
        days = int(req.get("days", 7))
        cutoff = (now - timedelta(days=days)).isoformat()
        stmt2 = (
            select(Entry)
            .where(Entry.type == entry_type, Entry.timestamp >= cutoff)
            .order_by(Entry.timestamp.asc())
        )
        rows2 = list((await session.execute(stmt2)).scalars().all())
        import json as _json  # noqa: PLC0415
        result[f"entries_{entry_type}"] = [
            {
                "timestamp": r.timestamp,
                "data": _json.loads(r.data) if isinstance(r.data, str) else r.data,
            }
            for r in rows2
        ]

    # ---- calendar ----
    if "calendar" in requirements:
        cal_days: int = int(requirements["calendar"].get("days", 7))
        time_min = now.isoformat()
        time_max = (now + timedelta(days=cal_days)).isoformat()
        try:
            events = await cached_events_or_refresh(session, time_min, time_max)
            result["calendar"] = [
                {
                    "title": e.title,
                    "start": e.start,
                    "end": e.end,
                    "is_all_day": e.is_all_day,
                }
                for e in events
            ]
        except Exception:  # noqa: BLE001 — calendar may be unconfigured
            result["calendar"] = []

    return result


__all__ = ["execute_algorithm", "fetch_algorithm_data", "validate_code"]
