"""Templating engine for Saz workflows (strict semantics).

Supported forms:
  - {{ $form.path.to.value }}
  - {{ $step('step_id') }} or {{ $step('step_id').deep.path[.index] }}
    * STRICT: reads ONLY step_results[step_id]['output']; no aliases or metadata.
  - {{ $env('NAME') }}                       -> returns None when missing or empty
  - {{ $env('NAME', 'fallback_value') }}     -> returns fallback when missing or empty
  - {{ $secret('NAME') }}                    -> raises ValueError when missing

Resolution rules:
  - If the whole string is a single template, return the native type.
  - In mixed strings, dicts, and lists, values are interpolated; unknown or None -> "".
  - Inside dict/list values that are a single template resolving to None, coerce to "".
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)


_SINGLE_EXPR_RE: Final[re.Pattern[str]] = re.compile(r'^\{\{\s*(.+?)\s*\}\}$')
_EXPR_RE: Final[re.Pattern[str]] = re.compile(r'\{\{\s*(.+?)\s*\}\}')


# Sentinel to distinguish "unknown expression" from a real None result
class _UNRESOLVED_T: ...


_UNRESOLVED = _UNRESOLVED_T()


class TemplateContext:
    def __init__(
        self,
        form_data: dict[str, Any],
        step_results: dict[str, Any],
        secret_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self.form_data = form_data or {}
        self.step_results = step_results or {}
        self.secret_resolver: Callable[[str], str | None] = secret_resolver or (lambda name: None)
        self.logger = logger.bind(component="templating")

    # ------------------------------- Public API -------------------------------

    def resolve(self, template: Any) -> Any:
        """Resolve a value (str, dict, list, or primitive)."""
        if isinstance(template, str):
            return self._resolve_string(template)

        if isinstance(template, dict):
            out: dict[str, Any] = {}
            for k, v in template.items():
                # For container values that are a single template resolving to None, coerce to ""
                if isinstance(v, str) and _SINGLE_EXPR_RE.match(v):
                    rv = self._resolve_string(v)
                    out[k] = "" if rv is None else rv
                else:
                    out[k] = self.resolve(v)
            return out

        if isinstance(template, list):
            out_list: list[Any] = []
            for item in template:
                if isinstance(item, str) and _SINGLE_EXPR_RE.match(item):
                    rv = self._resolve_string(item)
                    out_list.append("" if rv is None else rv)
                else:
                    out_list.append(self.resolve(item))
            return out_list

        # primitives
        return template

    # ------------------------------- Core string resolution -------------------

    def _resolve_string(self, template: str) -> Any:
        # Entire string is a single expression
        m = _SINGLE_EXPR_RE.match(template)
        if m:
            expr = m.group(1)
            val = self._evaluate_expression(expr)
            # Unknown expression stays literal in single-expr case
            if val is _UNRESOLVED:
                return "{{ " + expr + " }}"
            return val  # may be None (allowed at top-level)

        # Mixed/interpolated string
        def _replacer(mm: re.Match[str]) -> str:
            expr = mm.group(1).strip()
            val = self._evaluate_expression(expr)
            # Unknown or None -> empty in mixed strings
            if val is _UNRESOLVED or val is None:
                return ""
            if isinstance(val, dict | list):
                return json.dumps(val, ensure_ascii=False)
            return str(val)

        return _EXPR_RE.sub(_replacer, template)

    # ------------------------------- Expression evaluation --------------------

    def _evaluate_expression(self, expr: str) -> Any:
        expr = expr.strip()

        # $form.path
        if expr.startswith("$form."):
            return self._resolve_form(expr[6:])

        # $step('id')[.path]
        step_match = re.match(r"\$step\(['\"](.+?)['\"]\)(?:\.(.+))?", expr)
        if step_match:
            step_id = step_match.group(1)
            prop_path = step_match.group(2)
            return self._resolve_step_output(step_id, prop_path)

        # $env('NAME')  or  $env('NAME', 'fallback')
        # The optional second argument is returned verbatim when the env
        # var is missing or empty, so demos can ship with safe defaults
        # while still letting operators override via the environment.
        env_match = re.match(
            r"\$env\(['\"](.+?)['\"](?:\s*,\s*['\"](.*?)['\"])?\)",
            expr,
        )
        if env_match:
            name = env_match.group(1)
            default = env_match.group(2)  # None when no default was given
            return self._resolve_env(name, default)

        # $secret('NAME')
        sec_match = re.match(r"\$secret\(['\"](.+?)['\"]\)", expr)
        if sec_match:
            name = sec_match.group(1)
            return self._resolve_secret(name)

        self.logger.warning("unresolved_expression", expr=expr)
        return _UNRESOLVED

    # ------------------------------- Resolvers --------------------------------

    def _resolve_form(self, path: str) -> Any:
        return self._walk_path(self.form_data, path, on_missing=lambda: self._warn_form(path))

    def _resolve_step_output(self, step_id: str, prop_path: str | None) -> Any:
        # Contract: ``WorkflowExecutor`` stores every step result as
        # ``step_results[id] = {"output": <step result dict>}`` (see the
        # writers in ``saz/engine/executor.py``). We always read through
        # the ``["output"]`` wrapper — flat-dict storage would silently
        # resolve ``$step('x').field`` to ``None`` and break audit blobs.
        if step_id not in self.step_results or not isinstance(self.step_results[step_id], dict):
            self.logger.warning(
                "step_result_not_found",
                step_id=step_id,
                available=list(self.step_results.keys()),
            )
            return None

        step_obj = self.step_results[step_id]
        if "output" not in step_obj:
            self.logger.warning("step_output_missing", step_id=step_id, keys=list(step_obj.keys()))
            return None

        output = step_obj["output"]
        if prop_path is None or prop_path == "":
            return output

        return self._walk_path(
            output,
            prop_path,
            on_missing=lambda: self._warn_step_prop(step_id, prop_path),
        )

    def _resolve_env(self, name: str, default: str | None = None) -> Any:
        val = os.getenv(name)
        if not val:  # missing or empty -> default (or None)
            if default is not None:
                self.logger.debug("env_var_default_used", var=name)
                return default
            self.logger.warning("env_var_not_found", var=name)
            return None
        return val

    def _resolve_secret(self, name: str) -> str:
        val = self.secret_resolver(name)
        if val is None:
            self.logger.error("secret_not_found", secret_name=name)
            raise ValueError(f"Secret '{name}' not found. Please configure credential.")
        return val

    # ------------------------------- Helpers ----------------------------------

    def _walk_path(self, obj: Any, dotted: str, *, on_missing: Callable[[], None]) -> Any:
        """
        Walk a dotted path through dicts and lists. Numeric segments index lists.
        Returns None on any miss (and calls on_missing()).
        """
        cur = obj
        for seg in dotted.split("."):
            if isinstance(cur, dict) and seg in cur:
                cur = cur[seg]
                continue
            if isinstance(cur, list) and seg.isdigit():
                idx = int(seg)
                if 0 <= idx < len(cur):
                    cur = cur[idx]
                    continue
            on_missing()
            return None
        return cur

    def _warn_form(self, path: str) -> None:
        self.logger.warning(
            "form_field_not_found", field_path=path, available=list(self.form_data.keys())
        )

    def _warn_step_prop(self, step_id: str, prop: str) -> None:
        self.logger.warning("step_output_property_not_found", step_id=step_id, prop_path=prop)


def resolve_template(
    template: Any,
    form_data: dict[str, Any],
    step_results: dict[str, Any],
    secret_resolver: Callable[[str], str | None] | None = None,
) -> Any:
    return TemplateContext(form_data, step_results, secret_resolver).resolve(template)
