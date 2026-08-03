"""Tool-calling mechanics: the base tool shape and the registry that dispatches them."""

from .base import BaseTool
from .registry import ToolRegistry

__all__ = [
    "BaseTool",
    "ToolRegistry",
]
