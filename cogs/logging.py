import discord
from discord.ext import commands
from discord import app_commands
from discord import ui
import asyncio
import time
from typing import Dict, List, Optional, Literal, Tuple

from utils import styled_view, Colors

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOGGABLE_EVENTS = {
    "message_delete":   "Message Deleted",
    "message_edit":     "Message Edited",
    "member_join":      "Member Joined",
    "member_remove":    "Member Left / Kicked",
    "member_ban":       "Member Banned",
    "member_unban":     "Member Unbanned",
    "member_update":    "Member Roles/Nick Changed",
    "channel_create":   "Channel Created",
    "channel_delete":   "Channel Deleted",
    "channel_update":   "Channel Updated",
    "role_create":      "Role Created",
    "role_delete":      "Role Deleted",
    "role_update":      "Role Updated",
    "voice_state_update": "Voice Channel Activity",
}

_CACHE_TTL = 300  # seconds — 5 minutes


class Logging(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # TTL cache: guild_id -> (channel_id, [event_keys], expires_at)
        self._config_cache: Dict[int, Tuple[int, List[str], float]] = {}

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def cog_load(self) -> None:
        """Create tables once at load time, not on every shard ready."""
        if not getattr(self.bot, "db_pool", None):
            print(f"{Colors.RED}[ERROR]        Logging cog: db_pool not ready at cog_load.{Colors.RESET}")
            return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS logging_config (
                    guild_id         BIGINT PRIMARY KEY,
                    log_channel_id   BIGINT NOT NULL,
                    enabled_events   JSONB  NOT NULL DEFAULT '[]'
                )
            """)
        print(f"{Colors.GREEN}[SUCCESS]      Logging cog initialized tables.{Colors.RESET}")

    # -----------------------------------------------------------------------
    # Config helpers
    # -----------------------------------------------------------------------

    async def _get_log_config(self, guild_id: int) -> Optional[Tuple[int, List[str]]]:
        """Return (channel_id, [event_keys]) from a 5-minute TTL cache."""
        now = time.monotonic()
        cached = self._config_cache.get(guild_id)
        if cached and now < cached[2]:
            return cached[0], cached[1]

        async with self.bot.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT log_channel_id, enabled_events FROM logging_config WHERE guild_id = $1",
                guild_id,
            )
        if not row:
            return None

        channel_id     = row["log_channel_id"]
        # enabled_events is JSONB → asyncpg returns a Python list directly
        enabled_events = row["enabled_events"] or []
        self._config_cache[guild_id] = (channel_id, enabled_events, now + _CACHE_TTL)
        return channel_id, enabled_events

    def _invalidate_cache(self, guild_id: int) -> None:
        self._config_cache.pop(guild_id, None)

    async def _send_log(
        self,
        guild_id:   int,
        event_type: str,
        title:      str,
        description: str,
    ) -> None:
        """Check config + send a styled log message to the guild's log channel."""
        config = await self._get_log_config(guild_id)
        if not config:
            return
        channel_id, enabled_events = config
        if event_type not in enabled_events:
            return

        log_channel = self.bot.get_channel(channel_id)
        if not log_channel or not isinstance(log_channel, discord.TextChannel):
            return

        view = styled_view(title, description)
        try:
            await log_channel.send(view=view)
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Logging send failed (guild={guild_id}): {e}{Colors.RESET}")

    async def _get_audit_actor(
        self,
        guild:  discord.Guild,
        target: discord.abc.Snowflake,
        action: discord.AuditLogAction,
    ) -> Optional[discord.User]:
        """Fetch the responsible actor from audit logs (waits 0.5s for Discord to populate)."""
        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(action=action, limit=5):
                if entry.target and entry.target.id == target.id:
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                        return entry.user
        except discord.Forbidden:
            pass
        return None

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    log = app_commands.Group(name="log", description="Configure server logging.")

    @log.command(name="setup", description="Set the logging channel and events to capture.")
    @app_commands.describe(log_channel="Channel where logs will be sent.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_setup(self, interaction: discord.Interaction, log_channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        options = [discord.SelectOption(label=label, value=key) for key, label in LOGGABLE_EVENTS.items()]
        select_menu = ui.Select(
            placeholder="Select events to log…",
            min_values=1,
            max_values=len(options),
            options=options,
        )

        async def select_callback(itx: discord.Interaction):
            selected = itx.data.get("values", [])
            try:
                async with self.bot.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO logging_config (guild_id, log_channel_id, enabled_events)
                        VALUES ($1, $2, $3::jsonb)
                        ON CONFLICT (guild_id) DO UPDATE
                            SET log_channel_id   = EXCLUDED.log_channel_id,
                                enabled_events   = EXCLUDED.enabled_events
                        """,
                        itx.guild_id,
                        log_channel.id,
                        selected,          # asyncpg serialises list → JSONB
                    )
                self._invalidate_cache(itx.guild_id)

                events_str = "\n".join(LOGGABLE_EVENTS[e] for e in selected)
                desc = f"Channel: {log_channel.mention}\n\nEnabled Events\n{events_str}"
                await itx.response.edit_message(content=None, view=styled_view("Logging Configured", desc))
            except Exception as e:
                print(f"{Colors.RED}[ERROR]        log_setup callback: {e}{Colors.RESET}")
                await itx.response.edit_message(
                    content=None, view=styled_view("Configuration Failed", "A database error occurred.")
                )

        select_menu.callback = select_callback

        header    = ui.TextDisplay("**Configure Logging**")
        sep       = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body      = ui.TextDisplay("Select which events to log from the dropdown below.")
        container = ui.Container(header, sep, body)
        action_row = ui.ActionRow(select_menu)

        prompt_view = ui.LayoutView()
        prompt_view.add_item(container)
        prompt_view.add_item(action_row)
        await interaction.followup.send(view=prompt_view, ephemeral=True)

    @log.command(name="disable", description="Disable logging for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_disable(self, interaction: discord.Interaction):
        async with self.bot.db_pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM logging_config WHERE guild_id = $1", interaction.guild_id
            )
        self._invalidate_cache(interaction.guild_id)
        rows = int(status.split()[-1])
        if rows == 0:
            view = styled_view("Not Configured", "Logging is not enabled on this server.")
        else:
            view = styled_view("Logging Disabled", "Event logging has been turned off.")
        await interaction.response.send_message(view=view, ephemeral=True)

    @log_setup.error
    @log_disable.error
    async def _on_log_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            view = styled_view("Access Denied", "Manage Guild permission required.")
        else:
            print(f"{Colors.RED}[ERROR]        log command error: {error}{Colors.RESET}")
            view = styled_view("Error", "An unexpected error occurred.")
        if not interaction.response.is_done():
            await interaction.response.send_message(view=view, ephemeral=True)
        else:
            await interaction.followup.send(view=view, ephemeral=True)

    # -----------------------------------------------------------------------
    # Event listeners
    # -----------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        actor = await self._get_audit_actor(
            message.guild, message.author, discord.AuditLogAction.message_delete
        )
        actor_str = actor.mention if actor else "Unknown"

        content = message.content or "*(no text content)*"
        if len(content) > 1000:
            content = content[:1000] + "\n*(truncated)*"
        if message.attachments:
            content += f"\n*(+ {len(message.attachments)} attachment(s))*"

        desc = (
            f"**Author:** {message.author.mention}\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Deleted by:** {actor_str}\n\n"
            f"{content}"
        )
        await self._send_log(message.guild.id, "message_delete", "Message Deleted", desc)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or after.author.bot or before.content == after.content:
            return

        before_content = (before.content or "*(empty)*")[:500]
        after_content  = (after.content  or "*(empty)*")[:500]

        desc = (
            f"**Author:** {after.author.mention}\n"
            f"**Channel:** {after.channel.mention}\n"
            f"**Link:** [Jump to message]({after.jump_url})\n\n"
            f"**Before**\n{before_content}\n\n"
            f"**After**\n{after_content}"
        )
        await self._send_log(after.guild.id, "message_edit", "Message Edited", desc)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        created_at = discord.utils.format_dt(member.created_at, style="f")
        relative   = discord.utils.format_dt(member.created_at, style="R")
        desc = (
            f"**User:** {member.mention}\n"
            f"**Account Created:** {created_at} ({relative})\n\n"
            f"Server Members: {member.guild.member_count}"
        )
        await self._send_log(member.guild.id, "member_join", "Member Joined", desc)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        actor      = await self._get_audit_actor(member.guild, member, discord.AuditLogAction.kick)
        action_str = f"Kicked by {actor.mention}" if actor else "Left the server"
        desc = (
            f"**User:** {member.mention}\n"
            f"**ID:** {member.id}\n"
            f"**Action:** {action_str}\n\n"
            f"Server Members: {member.guild.member_count}"
        )
        await self._send_log(member.guild.id, "member_remove", "Member Left", desc)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        actor     = await self._get_audit_actor(guild, user, discord.AuditLogAction.ban)
        actor_str = actor.mention if actor else "Unknown"
        desc = (
            f"**User:** {user.mention}\n"
            f"**ID:** {user.id}\n"
            f"**Banned by:** {actor_str}"
        )
        await self._send_log(guild.id, "member_ban", "Member Banned", desc)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        actor     = await self._get_audit_actor(guild, user, discord.AuditLogAction.unban)
        actor_str = actor.mention if actor else "Unknown"
        desc = (
            f"**User:** {user.mention}\n"
            f"**ID:** {user.id}\n"
            f"**Unbanned by:** {actor_str}"
        )
        await self._send_log(guild.id, "member_unban", "Member Unbanned", desc)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Nickname change
        if before.nick != after.nick:
            actor     = await self._get_audit_actor(after.guild, after, discord.AuditLogAction.member_update)
            actor_str = f"by {actor.mention}" if actor else ""
            desc = (
                f"**Member:** {after.mention}\n"
                f"**Action:** Nickname changed {actor_str}\n\n"
                f"Old: `{before.nick or 'None'}`\n"
                f"New: `{after.nick or 'None'}`"
            )
            await self._send_log(after.guild.id, "member_update", "Nickname Changed", desc)

        # Role change
        if before.roles != after.roles:
            actor  = await self._get_audit_actor(after.guild, after, discord.AuditLogAction.member_role_update)
            actor_str = f"by {actor.mention}" if actor else ""
            added   = [r.mention for r in after.roles  if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            if not added and not removed:
                return
            desc = f"**Member:** {after.mention}\n**Action:** Roles updated {actor_str}\n\n"
            if added:   desc += f"Added: {', '.join(added)}\n"
            if removed: desc += f"Removed: {', '.join(removed)}"
            await self._send_log(after.guild.id, "member_update", "Roles Updated", desc)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        actor     = await self._get_audit_actor(channel.guild, channel, discord.AuditLogAction.channel_create)
        actor_str = actor.mention if actor else "Unknown"
        desc = (
            f"**Channel:** {channel.mention}\n"
            f"**Type:** {channel.type}\n"
            f"**Created by:** {actor_str}"
        )
        await self._send_log(channel.guild.id, "channel_create", "Channel Created", desc)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        actor     = await self._get_audit_actor(channel.guild, channel, discord.AuditLogAction.channel_delete)
        actor_str = actor.mention if actor else "Unknown"
        desc = (
            f"**Channel:** #{channel.name}\n"
            f"**Type:** {channel.type}\n"
            f"**Deleted by:** {actor_str}"
        )
        await self._send_log(channel.guild.id, "channel_delete", "Channel Deleted", desc)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if isinstance(after, discord.TextChannel) and before.topic != after.topic:
            changes.append("Topic: changed")
        if not changes:
            return
        actor     = await self._get_audit_actor(after.guild, after, discord.AuditLogAction.channel_update)
        actor_str = f"by {actor.mention}" if actor else ""
        desc = (
            f"**Channel:** {after.mention}\n"
            f"**Action:** Updated {actor_str}\n\n"
            + "\n".join(changes)
        )
        await self._send_log(after.guild.id, "channel_update", "Channel Updated", desc)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        actor     = await self._get_audit_actor(role.guild, role, discord.AuditLogAction.role_create)
        actor_str = actor.mention if actor else "Unknown"
        desc = (
            f"**Role:** {role.mention}\n"
            f"**Color:** {role.color}\n"
            f"**Created by:** {actor_str}"
        )
        await self._send_log(role.guild.id, "role_create", "Role Created", desc)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        actor     = await self._get_audit_actor(role.guild, role, discord.AuditLogAction.role_delete)
        actor_str = actor.mention if actor else "Unknown"
        desc = (
            f"**Role:** {role.name}\n"
            f"**Deleted by:** {actor_str}"
        )
        await self._send_log(role.guild.id, "role_delete", "Role Deleted", desc)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name        != after.name:        changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.color       != after.color:       changes.append(f"Color: `{before.color}` → `{after.color}`")
        if before.permissions != after.permissions: changes.append("Permissions: updated")
        if not changes:
            return
        actor     = await self._get_audit_actor(after.guild, after, discord.AuditLogAction.role_update)
        actor_str = f"by {actor.mention}" if actor else ""
        desc = (
            f"**Role:** {after.mention}\n"
            f"**Action:** Updated {actor_str}\n\n"
            + "\n".join(changes)
        )
        await self._send_log(after.guild.id, "role_update", "Role Updated", desc)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if before.channel == after.channel:
            return

        if not before.channel and after.channel:
            title = "Voice Channel Joined"
            desc  = f"**Member:** {member.mention}\nJoined {after.channel.mention}"
        elif before.channel and not after.channel:
            title = "Voice Channel Left"
            desc  = f"**Member:** {member.mention}\nLeft {before.channel.mention}"
        else:
            title = "Voice Channel Moved"
            desc  = f"**Member:** {member.mention}\nMoved from {before.channel.mention} to {after.channel.mention}"

        await self._send_log(member.guild.id, "voice_state_update", title, desc)


async def setup(bot: commands.Bot):
    await bot.add_cog(Logging(bot))