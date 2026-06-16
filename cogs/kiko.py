import discord
from discord.ext import commands
from discord import app_commands
import asyncio

KIKO_ID = 465618379642896394

# Discord is comfortable with ~1 DM/sec. Use 1.5s to stay well under the limit.
_DM_INTERVAL = 1.5


class AnnounceStopView(discord.ui.View):
    """Persistent Stop button shown during an active announce."""

    def __init__(self, cog: "KikoTools"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Stop Announce", style=discord.ButtonStyle.danger, emoji="🛑")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != KIKO_ID:
            return await interaction.response.send_message("No.", ephemeral=True)

        self.cog._announce_cancelled = True
        button.disabled = True
        button.label = "Stopping…"
        await interaction.response.edit_message(view=self)


class KikoTools(commands.Cog):
    """Private developer tools — restricted to Kiko only."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._announce_running: bool = False
        self._announce_cancelled: bool = False

    kiko_group = app_commands.Group(name="kiko", description="Developer tools.")

    # ------------------------------------------------------------------
    # /kiko notify
    # ------------------------------------------------------------------

    @kiko_group.command(name="notify", description="Send a DM to any user through Clark.")
    @app_commands.describe(user_id="The user's ID to DM", message="Message to send")
    async def notify(self, interaction: discord.Interaction, user_id: str, message: str):
        if interaction.user.id != KIKO_ID:
            return await interaction.response.send_message("No permission.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.followup.send("Invalid user ID — must be a number.", ephemeral=True)

        try:
            user = await self.bot.fetch_user(uid)
        except discord.NotFound:
            return await interaction.followup.send(f"No user found with ID `{user_id}`.", ephemeral=True)
        except discord.HTTPException as e:
            return await interaction.followup.send(f"Failed to fetch user: {e}", ephemeral=True)

        try:
            await user.send(message)
            await interaction.followup.send(f"Sent to **{user}** (`{user.id}`).", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(
                f"Failed — **{user}** has DMs closed or has blocked the bot.", ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to send DM: {e}", ephemeral=True)

    # ------------------------------------------------------------------
    # /kiko announce
    # ------------------------------------------------------------------

    @kiko_group.command(name="announce", description="DM every unique server owner with a message.")
    @app_commands.describe(message="Message to send to all server owners")
    async def announce(self, interaction: discord.Interaction, message: str):
        if interaction.user.id != KIKO_ID:
            return await interaction.response.send_message("No permission.", ephemeral=True)

        if self._announce_running:
            return await interaction.response.send_message(
                "An announce is already running — press **Stop Announce** on the original message.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        # Collect unique owners (deduplicate — one owner may own multiple servers)
        owner_map: dict[int, str] = {}   # owner_id -> guild name (for context)
        for guild in self.bot.guilds:
            if guild.owner_id and guild.owner_id not in owner_map:
                owner_map[guild.owner_id] = guild.name

        total = len(owner_map)
        if total == 0:
            return await interaction.followup.send("No guilds found.", ephemeral=True)

        self._announce_running   = True
        self._announce_cancelled = False

        sent = failed = 0
        view = AnnounceStopView(self)

        def _status(i: int, done: bool = False) -> str:
            icon = "✅" if done and not self._announce_cancelled else ("🛑" if self._announce_cancelled else "📢")
            label = "Complete" if done and not self._announce_cancelled else ("Stopped" if self._announce_cancelled else "Announcing")
            return (
                f"{icon} **{label}**\n"
                f"Sent: **{sent}** | Failed: **{failed}** | Progress: **{i}/{total}**"
            )

        status_msg = await interaction.followup.send(
            f"📢 **Starting** — {total} unique server owners\nSent: **0** | Failed: **0** | Progress: **0/{total}**",
            view=view,
            ephemeral=True,
        )

        for i, (owner_id, guild_name) in enumerate(owner_map.items(), 1):
            if self._announce_cancelled:
                break

            try:
                owner = await self.bot.fetch_user(owner_id)
                await owner.send(message)
                sent += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException:
                failed += 1

            # Edit progress every 5 DMs (avoid hitting edit rate limits)
            if i % 5 == 0 or i == total:
                try:
                    await status_msg.edit(content=_status(i), view=view)
                except discord.HTTPException:
                    pass

            # Rate limit: one DM every 1.5 seconds
            await asyncio.sleep(_DM_INTERVAL)

        self._announce_running = False

        # Final update — remove Stop button
        try:
            await status_msg.edit(content=_status(total, done=True), view=None)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(KikoTools(bot))
