import discord
from discord.ext import commands
from discord import app_commands, ui

from utils import embed

# Cog name -> the category it shows up under in the dropdown.
# Anything not listed lands in "Other".
CATEGORIES = {
    "Moderation":  ("Moderation",),
    "AutoMod":     ("AutoMod",),
    "Logging":     ("Logging",),
    "AI":          ("Settings",),
    "Economy":     ("Economy",),
    "Fun":         ("Funny",),
    "Welcome":     ("Welcome", "Goodbye"),
    "Utility":     ("BotInfo", "MessageSender", "Utilities"),
}
FALLBACK = "Other"


class HelpSelect(ui.Select):
    def __init__(self, cog: "Utilities"):
        self.help_cog = cog
        options = [discord.SelectOption(label=c) for c in cog.categories()]
        super().__init__(placeholder="Pick a category", options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        await interaction.response.edit_message(
            embed=self.help_cog.category_embed(category), view=self.view
        )


class HelpView(ui.View):
    def __init__(self, cog: "Utilities"):
        super().__init__(timeout=180)
        self.add_item(HelpSelect(cog))


class Utilities(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _category_of(self, cog_name: str) -> str:
        for category, names in CATEGORIES.items():
            if cog_name in names:
                return category
        return FALLBACK

    def _walk(self) -> dict[str, list[app_commands.Command]]:
        """Groups every command by category. Built from the live tree so it can't
        go stale when a cog gets added or removed."""
        grouped: dict[str, list] = {}
        for cmd in self.bot.tree.walk_commands():
            if isinstance(cmd, app_commands.Group):
                continue
            cog_name = cmd.binding.__class__.__name__ if cmd.binding else ""
            # Kiko's dev tools aren't for anyone else.
            if cog_name == "KikoTools":
                continue
            grouped.setdefault(self._category_of(cog_name), []).append(cmd)
        return grouped

    def categories(self) -> list[str]:
        return sorted(self._walk().keys())

    def category_embed(self, category: str) -> discord.Embed:
        cmds = sorted(self._walk().get(category, []), key=lambda c: c.qualified_name)
        if not cmds:
            return embed(f"{category} commands", "Nothing here.")
        lines = [f"**/{c.qualified_name}** — {c.description or 'No description.'}" for c in cmds]
        return embed(f"{category} commands", "\n".join(lines))

    @app_commands.command(name="help", description="Show every command Clark has.")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        grouped = self._walk()
        total = sum(len(v) for v in grouped.values())
        e = embed(
            f"{self.bot.user.name} help",
            f"{total} commands across {len(grouped)} categories.\n"
            "Pick a category below to see what's in it.",
        )
        if self.bot.user:
            e.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.followup.send(embed=e, view=HelpView(self), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utilities(bot))
