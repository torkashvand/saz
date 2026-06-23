"""Safe boolean expression evaluator for workflow ``condition`` steps.

Evaluates expressions such as::

    $form.budget > 0 && $form.budget < 5000 && $step('x').risk == "high"
    !($form.dry_run) || $env('FORCE') == "1"

Operands: ``$form.*``, ``$step('id').path``, ``$env('NAME')``,
``$secret('NAME')`` references (resolved through an injected callback),
quoted string literals, numbers, and ``true``/``false``/``null``.
Operators: ``== != > >= < <= && || !`` and parentheses.

No Python ``eval``; expressions are tokenised and parsed with a
recursive-descent parser. Malformed expressions raise :class:`ConditionError`
so callers fail closed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)


class ConditionError(ValueError):
    """Raised when a condition expression is malformed."""


_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"\$form\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*"
    r"|\$step\(\s*(?:'[^']*'|\"[^\"]*\")\s*\)(?:\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)?"
    r"|\$env\(\s*(?:'[^']*'|\"[^\"]*\")\s*(?:,\s*(?:'[^']*'|\"[^\"]*\")\s*)?\)"
    r"|\$secret\(\s*(?:'[^']*'|\"[^\"]*\")\s*\)"
)

_TOKEN_SPECS: Final[list[tuple[str, re.Pattern[str]]]] = [
    ("WS", re.compile(r"\s+")),
    ("AND", re.compile(r"&&")),
    ("OR", re.compile(r"\|\|")),
    ("EQ", re.compile(r"==")),
    ("NE", re.compile(r"!=")),
    ("GE", re.compile(r">=")),
    ("LE", re.compile(r"<=")),
    ("GT", re.compile(r">")),
    ("LT", re.compile(r"<")),
    ("NOT", re.compile(r"!")),
    ("LP", re.compile(r"\(")),
    ("RP", re.compile(r"\)")),
    ("REF", _REF_RE),
    ("NUM", re.compile(r"-?\d+(?:\.\d+)?")),
    ("STR", re.compile(r"'[^']*'|\"[^\"]*\"")),
    ("KW", re.compile(r"(?:true|false|null)\b", re.IGNORECASE)),
]

_COMPARATORS: Final[frozenset[str]] = frozenset({"EQ", "NE", "GT", "GE", "LT", "LE"})


def _strip_braces(expr: str) -> str:
    expr = expr.strip()
    if expr.startswith("{{") and expr.endswith("}}"):
        return expr[2:-2].strip()
    return expr


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        for kind, pattern in _TOKEN_SPECS:
            m = pattern.match(expr, pos)
            if m:
                if kind != "WS":
                    tokens.append((kind, m.group(0)))
                pos = m.end()
                break
        else:
            raise ConditionError(f"Unexpected character at position {pos} in {expr!r}")
    return tokens


def coerce_bool(value: Any) -> bool:
    """Strict truthiness for the final result and ``&&``/``||`` operands."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "0", "null", "none")
    if isinstance(value, dict | list):
        return len(value) > 0
    return bool(value)


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _compare(left: Any, op: str, right: Any) -> bool:
    if op in ("EQ", "NE"):
        ln, rn = _to_number(left), _to_number(right)
        equal = (
            (ln == rn)
            if (ln is not None and rn is not None)
            else (_stringify(left) == _stringify(right))
        )
        return equal if op == "EQ" else not equal

    ln, rn = _to_number(left), _to_number(right)
    lhs: Any
    rhs: Any
    if ln is None or rn is None:
        lhs, rhs = _stringify(left), _stringify(right)
    else:
        lhs, rhs = ln, rn
    if op == "GT":
        return bool(lhs > rhs)
    if op == "GE":
        return bool(lhs >= rhs)
    if op == "LT":
        return bool(lhs < rhs)
    return bool(lhs <= rhs)


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], resolve_ref: Callable[[str], Any]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.resolve_ref = resolve_ref

    def _peek(self) -> str | None:
        return self.tokens[self.pos][0] if self.pos < len(self.tokens) else None

    def _advance(self) -> tuple[str, str]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self) -> Any:
        value = self._parse_or()
        if self.pos != len(self.tokens):
            raise ConditionError("Unexpected trailing tokens in condition")
        return value

    def _parse_or(self) -> Any:
        left = self._parse_and()
        while self._peek() == "OR":
            self._advance()
            right = self._parse_and()
            left = coerce_bool(left) or coerce_bool(right)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_not()
        while self._peek() == "AND":
            self._advance()
            right = self._parse_not()
            left = coerce_bool(left) and coerce_bool(right)
        return left

    def _parse_not(self) -> Any:
        if self._peek() == "NOT":
            self._advance()
            return not coerce_bool(self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self) -> Any:
        left = self._parse_primary()
        if self._peek() in _COMPARATORS:
            op, _ = self._advance()
            right = self._parse_primary()
            return _compare(left, op, right)
        return left

    def _parse_primary(self) -> Any:
        kind = self._peek()
        if kind is None:
            raise ConditionError("Unexpected end of condition")
        if kind == "LP":
            self._advance()
            value = self._parse_or()
            if self._peek() != "RP":
                raise ConditionError("Missing closing parenthesis")
            self._advance()
            return value
        kind, text = self._advance()
        if kind == "NUM":
            return float(text) if "." in text else int(text)
        if kind == "STR":
            return text[1:-1]
        if kind == "KW":
            lowered = text.lower()
            return True if lowered == "true" else (False if lowered == "false" else None)
        if kind == "REF":
            return self.resolve_ref(text)
        raise ConditionError(f"Unexpected token {text!r} in condition")


def validate_condition_syntax(expr: Any) -> None:
    """Validate a condition's grammar without resolving any variables.

    Reuses the tokenizer + parser with a no-op resolver, so structural errors
    (bad characters, unbalanced parens, trailing tokens) raise
    :class:`ConditionError` while undefined variables are ignored. Used by the
    flow linter to check conditions at authoring time.
    """
    evaluate_condition(expr, lambda _ref: None)


def extract_condition_refs(expr: str) -> list[str]:
    """Return the ``$form``/``$step``/``$env``/``$secret`` reference tokens in a
    condition expression (no validation)."""
    return _REF_RE.findall(_strip_braces(expr))


def evaluate_condition(expr: Any, resolve_ref: Callable[[str], Any]) -> bool:
    """Evaluate a boolean condition expression to a strict ``bool``.

    ``resolve_ref`` receives each ``$...`` reference token and returns its
    native value. Raises :class:`ConditionError` on malformed input.
    """
    if isinstance(expr, bool):
        return expr
    if expr is None:
        return False
    if not isinstance(expr, str):
        return coerce_bool(expr)

    stripped = _strip_braces(expr)
    tokens = _tokenize(stripped)
    if not tokens:
        raise ConditionError("Empty condition expression")
    value = _Parser(tokens, resolve_ref).parse()
    return coerce_bool(value)


def render_condition(expr: str, resolve_ref: Callable[[str], Any]) -> str:
    """Substitute reference tokens with resolved values for audit display."""
    return _REF_RE.sub(lambda m: _stringify(resolve_ref(m.group(0))), _strip_braces(expr))
