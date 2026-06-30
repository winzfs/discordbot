from __future__ import annotations

import discord


def _ow_footer(embed: discord.Embed) -> discord.Embed:
    """Apply the shared Overwatch community footer and return the embed."""
    embed.set_footer(text="도파민 터지는 옵치")
    return embed
