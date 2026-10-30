"""Application package exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .container import Application

__all__ = ["Application"]


def __getattr__(name: str):
    # API/domain helpers must not import the composition root as a side effect.
    if name == "Application":
        from .container import Application

        return Application
    raise AttributeError(name)
