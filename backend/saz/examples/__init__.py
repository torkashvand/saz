"""
Flow templates and examples module.

Loads curated unified DSL YAML templates, validates them through the compiler,
and exposes them via the API.
"""

from .manager import FlowTemplate, TemplateManager, get_template_manager

__all__ = ['TemplateManager', 'FlowTemplate', 'get_template_manager']
