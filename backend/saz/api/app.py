"""ASGI entrypoint.

This module exists so that `saz.api.__init__` stays side-effect-free —
importing ``saz.api.errors`` or any other submodule must not trigger
``create_app()`` (which transitively imports services that import errors,
producing a circular import seen by the create_user CLI).

ASGI servers point here: ``uvicorn saz.api.app:app``.
"""

from saz.api import create_app

app = create_app()
