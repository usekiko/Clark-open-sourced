"""
utils/views.py
--------------
Shared UI helpers for Clark. All cogs import from here instead of
copy-pasting the same 6-line Container builder.
"""
from __future__ import annotations
import discord
from discord import ui


def styled_view(title: str, description: str, *, timeout: float | None = None) -> ui.LayoutView:
    """
    Build a standard LayoutView with a Container(TextDisplay, Separator, TextDisplay).
    
    This replaces the identical _create_styled_view / _create_container_view /
    _create_response_container helpers that existed in every cog.
    
    Args:
        title:       Bold header text.
        description: Body text (supports markdown).
        timeout:     View timeout. Defaults to None (no timeout).
    
    Returns:
        A ready-to-send ui.LayoutView.
    """
    header = ui.TextDisplay(f"**{title}**")
    sep    = ui.Separator(spacing=discord.SeparatorSpacing.small)
    body   = ui.TextDisplay(description)

    container = ui.Container(header, sep, body)
    view = ui.LayoutView(timeout=timeout)
    view.add_item(container)
    return view


def section_view(
    header_text: str,
    thumbnail_url: str | None = None,
    *,
    timeout: float | None = None,
) -> ui.LayoutView:
    """
    Build a LayoutView with a Section (optional Thumbnail accessory).
    Used for profile / rank cards that display an avatar alongside text.
    
    Args:
        header_text:   Markdown text for the TextDisplay inside the Section.
        thumbnail_url: Avatar/image URL for the Thumbnail accessory, or None.
        timeout:       View timeout. Defaults to None.
    
    Returns:
        A ready-to-send ui.LayoutView.
    """
    text = ui.TextDisplay(header_text)
    accessory = ui.Thumbnail(media=thumbnail_url) if thumbnail_url else None
    section = ui.Section(text, accessory=accessory)

    container = ui.Container(section)
    view = ui.LayoutView(timeout=timeout)
    view.add_item(container)
    return view
