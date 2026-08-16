"""
utils/embeds.py
---------------
One place to build Clark's embeds so every cog looks the same.
"""
from __future__ import annotations
import discord

__all__ = ("CLARK_COLOUR", "embed", "error_embed")

CLARK_COLOUR = 0x5a63f7


def embed(title: str, description: str = "", *, colour: int = CLARK_COLOUR,
          thumbnail: str | None = None) -> discord.Embed:
    """Standard Clark embed. Pass a thumbnail url for rank/profile style cards."""
    e = discord.Embed(title=title, description=description, colour=colour)
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    return e


def error_embed(title: str, description: str = "") -> discord.Embed:
    """Same thing in red, for anything that failed."""
    return discord.Embed(title=title, description=description, colour=0xED4245)
