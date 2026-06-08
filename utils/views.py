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

    Replaces the identical _create_styled_view / _create_container_view /
    _create_response_container helpers that existed in every cog.
    """
    header    = ui.TextDisplay(f"**{title}**")
    sep       = ui.Separator(spacing=discord.SeparatorSpacing.small)
    body      = ui.TextDisplay(description)
    container = ui.Container(header, sep, body)
    view      = ui.LayoutView(timeout=timeout)
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
    """
    text      = ui.TextDisplay(header_text)
    accessory = ui.Thumbnail(media=thumbnail_url) if thumbnail_url else None
    section   = ui.Section(text, accessory=accessory)
    container = ui.Container(section)
    view      = ui.LayoutView(timeout=timeout)
    view.add_item(container)
    return view


class StandardView(ui.LayoutView):
    """
    Backward-compatible LayoutView subclass used by economy-underwork.py and leveling.py.

    Usage (as originally written in those cogs):
        container = ui.Container(header, sep, body)
        return StandardView(container)
    """

    def __init__(self, *items: ui.Item, timeout: float | None = None):
        super().__init__(timeout=timeout)
        for item in items:
            self.add_item(item)
