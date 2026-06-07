import discord
from discord.ext import commands
from discord import app_commands
from discord import ui
import json
import asyncio
from typing import List, Optional, Literal

class Colors:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'

LOGGABLE_EVENTS = {
    "message_delete": "Message Deleted",
    "message_edit": "Message Edited",
    "member_join": "Member Joined",
    "member_remove": "Member Left / Kicked",
    "member_ban": "Member Banned",
    "member_unban": "Member Unbanned",
    "member_update": "Member Roles/Nick Changed",
    "channel_create": "Channel Created",
    "channel_delete": "Channel Deleted",
    "channel_update": "Channel Updated",
    "role_create": "Role Created",
    "role_delete": "Role Deleted",
    "role_update": "Role Updated",
    "voice_state_update": "Voice Channel Activity"
}

EMOJI_SUCCESS = "<:goodconnection:1454536158208983051>"
EMOJI_ERROR = "<:lowconnection:1454536160545214527>"
EMOJI_INFO = "<:mediumconnection:1454536162189512734>"

class Logging(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.response_thumbnail_accessory: Optional[ui.Thumbnail] = None
        self.bot.loop.create_task(self.setup_bot_profile())

    async def setup_bot_profile(self):
        await self.bot.wait_until_ready()
        if self.bot.user and self.bot.user.display_avatar:
            self.response_thumbnail_accessory = ui.Thumbnail(media=self.bot.user.display_avatar.url)
        else:
            print(f"{Colors.YELLOW}[WARN]        Could not load bot avatar for logging thumbnail.{Colors.RESET}")

    @commands.Cog.listener()
    async def on_ready(self):
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS logging_config (
                    guild_id BIGINT PRIMARY KEY,
                    log_channel_id BIGINT NOT NULL,
                    enabled_events TEXT NOT NULL
                );
            """)

    def _create_styled_view(self, status: Literal["SUCCESS", "ERROR", "INFO"], title: str, description: str) -> ui.LayoutView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        container = ui.Container(header, sep, body)
        
        view = ui.LayoutView()
        view.add_item(container)
        return view

    async def _get_log_config(self, guild_id: int) -> Optional[tuple[int, List[str]]]:
        async with self.bot.db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT log_channel_id, enabled_events FROM logging_config WHERE guild_id = $1", guild_id)
            if row:
                log_channel_id = row['log_channel_id']
                enabled_events_json = row['enabled_events']
                enabled_events = json.loads(enabled_events_json)
                return log_channel_id, enabled_events
        return None

    async def _send_log_message(self, guild_id: int, event_type: str, status: Literal["SUCCESS", "ERROR", "INFO"], title: str, description: str):
        config = await self._get_log_config(guild_id)
        if not config: return
        
        log_channel_id, enabled_events = config
        if event_type not in enabled_events: return
            
        log_channel = self.bot.get_channel(log_channel_id)
        if not log_channel or not isinstance(log_channel, discord.TextChannel): return
            
        log_view = self._create_styled_view(status=status, title=title, description=description)
        
        try:
            await log_channel.send(view=log_view)
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Error sending log message to guild {guild_id} (channel {log_channel_id}). [Error]: {e}{Colors.RESET}")

    async def _get_audit_log_entry(self, guild: discord.Guild, target: discord.abc.Snowflake, action: discord.AuditLogAction) -> Optional[discord.User]:
        await asyncio.sleep(0.5)
        try:
            async for entry in guild.audit_logs(action=action, limit=5):
                if entry.target and entry.target.id == target.id:
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                        return entry.user
        except discord.Forbidden:
            return None
        return None

    log = app_commands.Group(name="log", description="Configure server logging.")

    @log.command(name="setup", description="Set up the logging channel and events to log.")
    @app_commands.describe(log_channel="The channel where logs will be sent.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_setup(self, interaction: discord.Interaction, log_channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        
        options = [discord.SelectOption(label=label, value=key) for key, label in LOGGABLE_EVENTS.items()]
        
        select_menu = ui.Select(placeholder="Select events to log...", min_values=1, max_values=len(options), options=options)

        async def select_callback(interaction: discord.Interaction):
            try:
                selected_events = interaction.data.get('values', [])
                
                async with self.bot.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO logging_config (guild_id, log_channel_id, enabled_events)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (guild_id) DO UPDATE SET
                        log_channel_id = EXCLUDED.log_channel_id, enabled_events = EXCLUDED.enabled_events;
                    """, interaction.guild_id, log_channel.id, json.dumps(selected_events))
                
                enabled_events_str = "\n".join([f"{LOGGABLE_EVENTS[e]}" for e in selected_events])
                description = (
                    f"Channel: {log_channel.mention}\n\n"
                    f"**Enabled Events**\n"
                    f"{enabled_events_str}"
                )
                
                response_view = self._create_styled_view("SUCCESS", "Logging Configured", description)
                await interaction.response.edit_message(content=None, view=response_view)
            except Exception as e:
                print(f"{Colors.RED}[ERROR]        Error in logging select_callback. [Error]: {e}{Colors.RESET}")
                error_view = self._create_styled_view("ERROR", "Configuration Failed", "Database error occurred.")
                await interaction.response.edit_message(content=None, view=error_view)


        select_menu.callback = select_callback
        
        header = ui.TextDisplay("**Configure Logging**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay("Select which events to log from the dropdown below.")
        container = ui.Container(header, sep, body)
        
        action_row = ui.ActionRow(select_menu)
        
        prompt_view = ui.LayoutView()
        prompt_view.add_item(container)
        prompt_view.add_item(action_row)
        
        await interaction.followup.send(view=prompt_view, ephemeral=True)

    @log.command(name="disable", description="Disable logging for this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_disable(self, interaction: discord.Interaction):
        rows_affected = 0
        async with self.bot.db_pool.acquire() as conn:
            status = await conn.execute("DELETE FROM logging_config WHERE guild_id = $1", interaction.guild_id)
            # DELETE n where n is rows_affected. e.g. 'DELETE 1'
            rows_affected = int(status.split()[-1])

        if rows_affected == 0:
            response_view = self._create_styled_view("ERROR", "Not Configured", "Logging is not enabled on this server.")
        else:
            response_view = self._create_styled_view("SUCCESS", "Logging Disabled", "Event logging has been turned off.")
        
        await interaction.response.send_message(view=response_view, ephemeral=True)

    @log_setup.error
    @log_disable.error
    async def on_log_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            description = "Manage Guild permission required."
            title = "Access Denied"
        else:
            print(f"{Colors.RED}[ERROR]        Error in logging app command. [Error]: {error}{Colors.RESET}")
            description = "An unexpected error occurred."
            title = "Error"
        
        error_view = self._create_styled_view("ERROR", title, description)
        if not interaction.response.is_done():
            await interaction.response.send_message(view=error_view, ephemeral=True)
        else:
            await interaction.followup.send(view=error_view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot: return
        actor = await self._get_audit_log_entry(message.guild, message.author, discord.AuditLogAction.message_delete)
        actor_str = actor.mention if actor else "Unknown"
        
        content = message.content if message.content else "*(Message had no text content)*"
        if len(content) > 1000: content = content[:1000] + "...\n*(Message truncated)*"
        if message.attachments: content += f"\n*(+ {len(message.attachments)} attachment(s))*"
        
        description = (
            f"Author:** {message.author.mention}\n"
            f"Channel:** {message.channel.mention}\n"
            f"Deleted by:** {actor_str}\n\n"
            f"{content}"
        )
        await self._send_log_message(message.guild.id, "message_delete", "SUCCESS", "Message Deleted", description)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or after.author.bot or before.content == after.content: return
        
        before_content = before.content if before.content else "*(Empty)*"
        after_content = after.content if after.content else "*(Empty)*"
        
        if len(before_content) > 500: before_content = before_content[:500] + "..."
        if len(after_content) > 500: after_content = after_content[:500] + "..."
        
        description = (
            f"Author:** {after.author.mention}\n"
            f"Channel:** {after.channel.mention}\n"
            f"Link:** [Jump to Message]({after.jump_url})\n\n"
            f"**Before**\n{before_content}\n\n"
            f"**After**\n{after_content}"
        )
        await self._send_log_message(after.guild.id, "message_edit", "SUCCESS", "Message Edited", description)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        created_at_ts = discord.utils.format_dt(member.created_at, style='f')
        relative = discord.utils.format_dt(member.created_at, style='R')
        
        description = (
            f"User:** {member.mention}\n"
            f"Created:** {created_at_ts} ({relative})\n\n"
            f"Server Members: {member.guild.member_count}"
        )
        await self._send_log_message(member.guild.id, "member_join", "SUCCESS", "Member Joined", description)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        actor = await self._get_audit_log_entry(member.guild, member, discord.AuditLogAction.kick)
        action_str = f"Kicked by {actor.mention}" if actor else "Left the server"
        
        description = (
            f"User:** {member.mention}\n"
            f"ID:** {member.id}\n"
            f"Action:** {action_str}\n\n"
            f"Server Members: {member.guild.member_count}"
        )
        await self._send_log_message(member.guild.id, "member_remove", "SUCCESS", "Member Left", description)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        actor = await self._get_audit_log_entry(guild, user, discord.AuditLogAction.ban)
        actor_str = actor.mention if actor else "Unknown"
        
        description = (
            f"User:** {user.mention}\n"
            f"ID:** {user.id}\n"
            f"Banned by:** {actor_str}"
        )
        await self._send_log_message(guild.id, "member_ban", "SUCCESS", "Member Banned", description)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        actor = await self._get_audit_log_entry(guild, user, discord.AuditLogAction.unban)
        actor_str = actor.mention if actor else "Unknown"
        
        description = (
            f"User:** {user.mention}\n"
            f"ID:** {user.id}\n"
            f"Unbanned by:** {actor_str}"
        )
        await self._send_log_message(guild.id, "member_unban", "SUCCESS", "Member Unbanned", description)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            actor = await self._get_audit_log_entry(after.guild, after, discord.AuditLogAction.member_update)
            actor_str = f"by {actor.mention}" if actor else ""
            
            description = (
                f"Member:** {after.mention}\n"
                f"Action:** Nickname Changed {actor_str}\n\n"
                f"Old: `{before.nick or 'None'}`\n"
                f"New: `{after.nick or 'None'}`"
            )
            await self._send_log_message(after.guild.id, "member_update", "SUCCESS", "Nickname Changed", description)
        
        if before.roles != after.roles:
            actor = await self._get_audit_log_entry(after.guild, after, discord.AuditLogAction.member_role_update)
            actor_str = f"by {actor.mention}" if actor else ""
            
            added = [r.mention for r in after.roles if r not in before.roles]
            removed = [r.mention for r in before.roles if r not in after.roles]
            
            if not added and not removed: return
            
            description = f"Member:** {after.mention}\n> **Action:** Roles Updated {actor_str}\n\n"
            
            if added: description += f"Added: {', '.join(added)}\n"
            if removed: description += f"Removed: {', '.join(removed)}"
            
            await self._send_log_message(after.guild.id, "member_update", "SUCCESS", "Roles Updated", description)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        actor = await self._get_audit_log_entry(channel.guild, channel, discord.AuditLogAction.channel_create)
        actor_str = actor.mention if actor else "Unknown"
        
        description = (
            f"Channel:** {channel.mention}\n"
            f"Type:** {channel.type}\n"
            f"Created by:** {actor_str}"
        )
        await self._send_log_message(channel.guild.id, "channel_create", "SUCCESS", "Channel Created", description)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        actor = await self._get_audit_log_entry(channel.guild, channel, discord.AuditLogAction.channel_delete)
        actor_str = actor.mention if actor else "Unknown"
        
        description = (
            f"Channel:** {channel.name}\n"
            f"Type:** {channel.type}\n"
            f"Deleted by:** {actor_str}"
        )
        await self._send_log_message(channel.guild.id, "channel_delete", "SUCCESS", "Channel Deleted", description)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        actor = await self._get_audit_log_entry(after.guild, after, discord.AuditLogAction.channel_update)
        actor_str = f"by {actor.mention}" if actor else ""
        
        changes = []
        if before.name != after.name: changes.append(f"- **Before & After:** `{before.name}` › `{after.name}`")
        if isinstance(after, discord.TextChannel) and before.topic != after.topic: changes.append(f"Topic: Changed")
        
        if not changes: return
        
        description = (
            f"Channel:** {after.mention}\n"
            f"Action:** Updated {actor_str}\n\n"
            + "\n".join(changes)
        )
        await self._send_log_message(after.guild.id, "channel_update", "SUCCESS", "Channel Updated", description)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        actor = await self._get_audit_log_entry(role.guild, role, discord.AuditLogAction.role_create)
        actor_str = actor.mention if actor else "Unknown"
        
        description = (
            f"Role:** {role.mention}\n"
            f"Color:** {role.color}\n"
            f"Created by:** {actor_str}"
        )
        await self._send_log_message(role.guild.id, "role_create", "SUCCESS", "Role Created", description)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        actor = await self._get_audit_log_entry(role.guild, role, discord.AuditLogAction.role_delete)
        actor_str = actor.mention if actor else "Unknown"
        
        description = (
            f"Role:** {role.name}\n"
            f"Deleted by:** {actor_str}"
        )
        await self._send_log_message(role.guild.id, "role_delete", "SUCCESS", "Role Deleted", description)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        actor = await self._get_audit_log_entry(after.guild, after, discord.AuditLogAction.role_update)
        actor_str = f"by {actor.mention}" if actor else ""
        
        changes = []
        if before.name != after.name: changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.color != after.color: changes.append(f"Color: `{before.color}` → `{after.color}`")
        if before.permissions != after.permissions: changes.append(f"Permissions: Updated")
        
        if not changes: return
        
        description = (
            f"Role:** {after.mention}\n"
            f"Action:** Updated {actor_str}\n\n"
            + "\n".join(changes)
        )
        await self._send_log_message(after.guild.id, "role_update", "SUCCESS", "Role Updated", description)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if before.channel == after.channel: return
        
        description = f"Member:** {member.mention}\n"
        title = "Voice Activity"
        
        if not before.channel and after.channel:
            title = "Voice Channel Joined"
            description += f"Joined {after.channel.mention}"
        elif before.channel and not after.channel:
            title = "Voice Channel Left"
            description += f"Left {before.channel.mention}"
        else:
            title = "Voice Channel Moved"
            description += f"Moved from {before.channel.mention} to {after.channel.mention}"
            
        await self._send_log_message(member.guild.id, "voice_state_update", "SUCCESS", title, description)

async def setup(bot: commands.Bot):
    await bot.add_cog(Logging(bot))