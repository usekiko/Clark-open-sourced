"""
Shared UI view helpers so they don't need to be copy-pasted in every cog.
"""

from __future__ import annotations
from typing import Optional
import discord
from discord import ui

__all__ = ('StandardView', 'make_view')


class StandardView(ui.LayoutView):
    """A basic LayoutView that wraps a single Container.
    
    Usage::
    
        view = make_view("Title", "Some description text")
        await interaction.followup.send(view=view)
    """
    def __init__(self, container: ui.Container, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.add_item(container)


def make_view(title: str, description: str, *, accent_colour: Optional[discord.Colour] = None) -> StandardView:
    """Build a standard **Title** / separator / description LayoutView."""
    header    = ui.TextDisplay(f"**{title}**")
    sep       = ui.Separator(spacing=discord.SeparatorSpacing.small)
    body      = ui.TextDisplay(description)
    container = ui.Container(header, sep, body, accent_colour=accent_colour)
    return StandardView(container)


def make_section_view(
    title: str,
    description: str,
    thumbnail_url: Optional[str] = None,
    *,
    accent_colour: Optional[discord.Colour] = None,
) -> StandardView:
    """Build a LayoutView with a Section + optional Thumbnail accessory (like embed_like.py).

    If *thumbnail_url* is provided the section will render the image as a thumbnail
    accessory on the right side, matching the discord.py embed_like example layout::

        +---Container---+
        | +--Section--+ |
        | | TextDisplay|  Thumbnail|
        | +-----------+ |
        +---------------+
    """
    header = ui.TextDisplay(f"**{title}**")
    body   = ui.TextDisplay(description)

    if thumbnail_url:
        thumbnail = ui.Thumbnail(media=thumbnail_url)
        section   = ui.Section(header, body, accessory=thumbnail)
        container = ui.Container(section, accent_colour=accent_colour)
    else:
        sep       = ui.Separator(spacing=discord.SeparatorSpacing.small)
        container = ui.Container(header, sep, body, accent_colour=accent_colour)

    return StandardView(container)
