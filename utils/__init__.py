"""
utils/__init__.py
-----------------
Central export point for Clark shared utilities.
"""
from .colors import Colors
from .views  import styled_view, section_view

__all__ = [
    "Colors",
    "styled_view",
    "section_view",
]
