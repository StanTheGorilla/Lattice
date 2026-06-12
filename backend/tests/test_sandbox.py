"""Tests for the AI-authored-algorithm sandbox (P2-2).

Covers `validate_code` accept/reject (including dunder-walk and reflection
escape attempts), and `execute_algorithm` happy path + timeout.
"""

from __future__ import annotations

import pytest

from lattice.llm.sandbox import execute_algorithm, validate_code


def test_validate_accepts_minimal_run() -> None:
    validate_code("def run(data):\n    return data.get('x', 0) + 1\n")


def test_validate_accepts_math_and_statistics() -> None:
    validate_code(
        "def run(data):\n"
        "    xs = data['xs']\n"
        "    return math.sqrt(statistics.mean(xs))\n"
    )


def test_validate_rejects_missing_run() -> None:
    with pytest.raises(ValueError, match="run"):
        validate_code("def helper(data):\n    return 1\n")


def test_validate_rejects_imports() -> None:
    with pytest.raises(ValueError, match="imports"):
        validate_code("import os\ndef run(data):\n    return 1\n")
    with pytest.raises(ValueError, match="imports"):
        validate_code("from os import system\ndef run(data):\n    return 1\n")


def test_validate_rejects_eval_exec_open() -> None:
    for bad in ("eval", "exec", "open", "compile", "__import__"):
        with pytest.raises(ValueError):
            validate_code(f"def run(data):\n    return {bad}('x')\n")


def test_validate_rejects_dunder_attribute_walk() -> None:
    # The canonical sandbox escape: reach `os` through the object graph.
    escape = (
        "def run(data):\n"
        "    return ''.__class__.__mro__[1].__subclasses__()\n"
    )
    with pytest.raises(ValueError, match="dunder"):
        validate_code(escape)


def test_validate_rejects_reflection_helpers() -> None:
    for helper in ("getattr", "setattr", "vars", "globals", "locals", "delattr"):
        with pytest.raises(ValueError):
            validate_code(f"def run(data):\n    g = {helper}\n    return g\n")


def test_validate_rejects_global_statement() -> None:
    with pytest.raises(ValueError, match="global"):
        validate_code("def run(data):\n    global x\n    return 1\n")


def test_validate_rejects_syntax_error() -> None:
    with pytest.raises(ValueError, match="syntax"):
        validate_code("def run(data) return 1")


def test_execute_happy_path() -> None:
    result = execute_algorithm(
        "def run(data):\n    return sum(data['xs']) / len(data['xs'])\n",
        {"xs": [2, 4, 6]},
    )
    assert result == 4


def test_execute_propagates_run_exception() -> None:
    with pytest.raises(ZeroDivisionError):
        execute_algorithm(
            "def run(data):\n    return 1 / 0\n",
            {},
        )


def test_execute_timeout() -> None:
    with pytest.raises(TimeoutError):
        execute_algorithm(
            "def run(data):\n    while True:\n        pass\n",
            {},
            timeout=0.3,
        )
