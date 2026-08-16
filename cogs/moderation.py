import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime

from utils import styled_view, Colors, ensure_bigint_columns


class DurationTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> datetime.timedelta:
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        try:
            amount = int(value[:-1])
            unit   = value[-1].lower()
            if unit not in units:
                raise ValueError
            return datetime.timedelta(seconds=amount * units[unit])
        except (ValueError, TypeError):
            raise app_commands.AppCommandError(
                "Invalid duration format. Examples: `10m`, `2h`, `1d`."
            )


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # Command groups
    # -----------------------------------------------------------------------
    ban_group     = app_commands.Group(name="ban",      description="Permanent ban management.")
    tempban_group = app_commands.Group(name="tempban",  description="Temporary ban management.")
    mute_group    = app_commands.Group(name="mute",     description="Mute (timeout) management.")
    warn_group    = app_commands.Group(name="warn",     description="Warning management.")
    slowmode_group = app_commands.Group(name="slowmode", description="Channel slowmode management.")
    lock_group    = app_commands.Group(name="lock",     description="Channel lock management.")
    role_group    = app_commands.Group(name="role",     description="User role management.")

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def cog_load(self) -> None:
        if not getattr(self.bot, "db_pool", None):
            print(f"{Colors.RED}[ERROR]         Moderation cog: db_pool not ready.{Colors.RESET}")
            return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS mod_logs (
                        log_id          SERIAL      PRIMARY KEY,
                        guild_case_id   INT         NOT NULL,
                        guild_id        BIGINT      NOT NULL,
                        moderator_id    BIGINT      NOT NULL,
                        user_id         BIGINT      NOT NULL,
                        action_type     VARCHAR(50) NOT NULL,
                        reason          TEXT,
                        timestamp       BIGINT      NOT NULL,
                        expires_at      BIGINT,
                        UNIQUE (guild_id, guild_case_id)
                    )
                """)
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_guild_user ON mod_logs (guild_id, user_id)"
                )
                # Per-guild case-number sequence generator
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS mod_case_counters (
                        guild_id BIGINT PRIMARY KEY,
                        counter  INT    NOT NULL DEFAULT 0
                    )
                """)

                # Installs predating the BIGINT schema still have these as VARCHAR,
                # and CREATE TABLE IF NOT EXISTS above will never fix that. Snowflakes
                # are passed as ints, so every command routed through log_case dies
                # with "expected str, got int" until the columns are converted.
                for table, columns in (
                    ("mod_logs",          ("guild_id", "moderator_id", "user_id")),
                    ("mod_case_counters", ("guild_id",)),
                ):
                    migrated = await ensure_bigint_columns(conn, table, columns)
                    if migrated:
                        print(
                            f"{Colors.YELLOW}[MIGRATE]      {table}: "
                            f"{', '.join(migrated)} → BIGINT{Colors.RESET}"
                        )
            print(f"{Colors.GREEN}[SUCCESS]      cogs.moderation.py has successfully created all tables{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]         Moderation table creation failed: {e}{Colors.RESET}")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def log_case(
        self,
        interaction: discord.Interaction,
        action_type: str,
        user: discord.User,
        reason: str,
        expires_at: int | None = None,
    ) -> int:
        """
        Atomically increment the per-guild case counter and insert a mod log.
        Uses an UPSERT on mod_case_counters so concurrent calls can't race.
        """
        async with self.bot.db_pool.acquire() as conn:
            async with conn.transaction():
                # Atomic increment — safe under concurrency
                next_id = await conn.fetchval(
                    """
                    INSERT INTO mod_case_counters (guild_id, counter)
                    VALUES ($1, 1)
                    ON CONFLICT (guild_id) DO UPDATE
                        SET counter = mod_case_counters.counter + 1
                    RETURNING counter
                    """,
                    interaction.guild.id,
                )
                await conn.execute(
                    """
                    INSERT INTO mod_logs
                        (guild_case_id, guild_id, moderator_id, user_id,
                         action_type, reason, timestamp, expires_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    next_id,
                    interaction.guild.id,
                    interaction.user.id,
                    user.id,
                    action_type,
                    reason,
                    int(datetime.datetime.now().timestamp()),
                    expires_at,
                )
                return next_id

    async def _send_dm(self, user: discord.User, title: str, description: str) -> None:
        try:
            await user.send(view=styled_view(title, description))
        except (discord.Forbidden, Exception) as e:
            print(f"{Colors.RED}[ERROR]         DM to {user} failed: {e}{Colors.RESET}")

    @staticmethod
    def _check_target(
        member: discord.Member | discord.User,
        interaction: discord.Interaction,
        bot_user: discord.ClientUser,
    ) -> str | None:
        """Return an error string if the target cannot be moderated, else None."""
        if member == bot_user:
            return "I cannot moderate myself."
        if member == interaction.guild.owner:
            return "I cannot moderate the server owner."
        if member == interaction.user:
            return "You cannot moderate yourself."
        if isinstance(member, discord.Member) and member.top_role >= interaction.guild.me.top_role:
            return "Cannot moderate a user with a higher or equal role."
        return None

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    @app_commands.command(name="kick", description="Removes a user from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        *,
        reason: str = "No reason provided.",
    ):
        err = self._check_target(member, interaction, self.bot.user)
        if err:
            return await interaction.response.send_message(
                view=styled_view("Access Denied", err), ephemeral=True
            )
        try:
            case_id = await self.log_case(interaction, "KICK", member, reason)
            await self._send_dm(
                member,
                f"You were Kicked from {interaction.guild.name}",
                f"**Moderator:** {interaction.user.mention}\n**Reason:** {reason}\n**Case ID:** #{case_id}\n\nYou may rejoin with a new invite.",
            )
            await member.kick(reason=f"Case #{case_id}: {reason}")
            await interaction.response.send_message(
                view=styled_view("Member Kicked", f"User: {member.name}\nReason: {reason}\nCase ID: #{case_id}")
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                view=styled_view("Missing Permissions", "'Kick Members' permission required."), ephemeral=True
            )

    @ban_group.command(name="add", description="Permanently bans a user.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_add(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str,
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ):
        member = interaction.guild.get_member(user.id)
        err    = self._check_target(member or user, interaction, self.bot.user)
        if err:
            return await interaction.response.send_message(
                view=styled_view("Protected User", err), ephemeral=True
            )
        try:
            case_id = await self.log_case(interaction, "BAN", user, reason)
            await self._send_dm(
                user,
                f"You were Banned from {interaction.guild.name}",
                f"**Moderator:** {interaction.user.mention}\n**Reason:** {reason}\n**Case ID:** #{case_id}\n\nThis action is permanent.",
            )
            await interaction.guild.ban(user, reason=f"Case #{case_id}: {reason}", delete_message_days=delete_days)
            await interaction.response.send_message(
                view=styled_view("Member Banned", f"User: {user.name}\nReason: {reason}\nCase ID: #{case_id}")
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                view=styled_view("Missing Permissions", "'Ban Members' permission required."), ephemeral=True
            )

    @ban_group.command(name="remove", description="Removes a ban from a user.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_remove(self, interaction: discord.Interaction, user_id: str, *, reason: str = "Reversal of ban."):
        try:
            user    = await self.bot.fetch_user(int(user_id))
            case_id = await self.log_case(interaction, "UNBAN", user, reason)
            await interaction.guild.unban(user, reason=f"Case #{case_id}: {reason}")
            await self._send_dm(
                user,
                f"Your Ban was Removed from {interaction.guild.name}",
                f"**Moderator:** {interaction.user.mention}\n**Reason:** {reason}\n**Case ID:** #{case_id}\n\nYou can now rejoin.",
            )
            await interaction.response.send_message(
                view=styled_view("Member Unbanned", f"User: {user.name}\nReason: {reason}\nCase ID: #{case_id}")
            )
        except discord.NotFound:
            await interaction.response.send_message(
                view=styled_view("Not Banned", "User is not currently banned."), ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                view=styled_view("Error", str(e)), ephemeral=True
            )

    @tempban_group.command(name="add", description="Temporarily bans a user.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempban_add(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        duration: app_commands.Transform[datetime.timedelta, DurationTransformer],
        reason: str,
    ):
        err = self._check_target(user, interaction, self.bot.user)
        if err:
            return await interaction.response.send_message(
                view=styled_view("Protected User", err), ephemeral=True
            )
        try:
            end_time      = discord.utils.utcnow() + duration
            expires_at_ts = int(end_time.timestamp())
            case_id       = await self.log_case(interaction, "TEMPBAN", user, reason, expires_at=expires_at_ts)
            await self._send_dm(
                user,
                f"You were Temporarily Banned from {interaction.guild.name}",
                (
                    f"**Moderator:** {interaction.user.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Expires:** <t:{expires_at_ts}:F>\n"
                    f"**Case ID:** #{case_id}"
                ),
            )
            await interaction.guild.ban(user, reason=f"Case #{case_id} (Temp): {reason}")
            await interaction.response.send_message(
                view=styled_view(
                    "Temporary Ban Applied",
                    f"User: {user.name}\nExpires: <t:{expires_at_ts}:F>\nCase ID: #{case_id}",
                )
            )
        except Exception as e:
            await interaction.response.send_message(view=styled_view("Error", str(e)), ephemeral=True)

    @tempban_group.command(name="remove", description="Removes a temporary ban.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempban_remove(
        self, interaction: discord.Interaction, user_id: str, *, reason: str = "Reversal of temporary ban."
    ):
        await self.ban_remove.callback(self, interaction, user_id, reason=reason)

    @mute_group.command(name="add", description="Times out a user.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: app_commands.Transform[datetime.timedelta, DurationTransformer],
        *,
        reason: str,
    ):
        err = self._check_target(member, interaction, self.bot.user)
        if err:
            return await interaction.response.send_message(
                view=styled_view("Protected User", err), ephemeral=True
            )
        try:
            end_time      = discord.utils.utcnow() + duration
            expires_at_ts = int(end_time.timestamp())
            case_id       = await self.log_case(interaction, "MUTE", member, reason, expires_at=expires_at_ts)
            await self._send_dm(
                member,
                f"You have been Timed Out in {interaction.guild.name}",
                (
                    f"**Moderator:** {interaction.user.mention}\n"
                    f"**Reason:** {reason}\n"
                    f"**Expires:** <t:{expires_at_ts}:F>\n"
                    f"**Case ID:** #{case_id}"
                ),
            )
            await member.timeout(duration, reason=f"Case #{case_id}: {reason}")
            await interaction.response.send_message(
                view=styled_view(
                    "Member Muted",
                    f"User: {member.name}\nExpires: <t:{expires_at_ts}:F>\nCase ID: #{case_id}",
                )
            )
        except Exception as e:
            await interaction.response.send_message(view=styled_view("Error", str(e)), ephemeral=True)

    @mute_group.command(name="remove", description="Removes a user's timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute_remove(
        self, interaction: discord.Interaction, member: discord.Member, *, reason: str = "Reversal of mute."
    ):
        if not member.is_timed_out():
            return await interaction.response.send_message(
                view=styled_view("Not Muted", "User does not have an active timeout."), ephemeral=True
            )
        try:
            case_id = await self.log_case(interaction, "UNMUTE", member, reason)
            await member.timeout(None, reason=f"Case #{case_id}: {reason}")
            await interaction.response.send_message(
                view=styled_view("Member Unmuted", f"User: {member.name}\nCase ID: #{case_id}")
            )
        except Exception as e:
            await interaction.response.send_message(view=styled_view("Error", str(e)), ephemeral=True)

    @warn_group.command(name="add", description="Issues a warning to a user.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_add(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        if member.bot or member == interaction.guild.owner or member == interaction.user:
            return await interaction.response.send_message(
                view=styled_view("Invalid Target", "Cannot moderate this user."), ephemeral=True
            )
        case_id = await self.log_case(interaction, "WARN", member, reason)
        await self._send_dm(
            member,
            f"You received a Warning in {interaction.guild.name}",
            f"**Reason:** {reason}\n**Case ID:** #{case_id}",
        )
        await interaction.response.send_message(
            view=styled_view("Warning Issued", f"User: {member.name}\nReason: {reason}\nCase ID: #{case_id}")
        )

    @warn_group.command(name="remove", description="Deletes a warning by Case ID.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_remove(self, interaction: discord.Interaction, case_id: int):
        async with self.bot.db_pool.acquire() as conn:
            record = await conn.fetchrow(
                "SELECT log_id, action_type FROM mod_logs WHERE guild_case_id = $1 AND guild_id = $2",
                case_id, interaction.guild.id,
            )
            if not record or record["action_type"] != "WARN":
                return await interaction.response.send_message(
                    view=styled_view("Not Found", "Warning case does not exist."), ephemeral=True
                )
            await conn.execute("DELETE FROM mod_logs WHERE log_id = $1", record["log_id"])
        await interaction.response.send_message(
            view=styled_view("Warning Removed", f"Case #{case_id} removed from record.")
        )

    @app_commands.command(name="purge", description="Deletes messages in the current channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(
            view=styled_view("Messages Purged", f"{len(deleted)} messages deleted."), ephemeral=True
        )

    @slowmode_group.command(name="apply", description="Sets channel slowmode.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_apply(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        await interaction.response.send_message(
            view=styled_view("Slowmode Configured", f"Rate limit set to {seconds}s.")
        )

    @lock_group.command(name="apply", description="Locks the current channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_apply(self, interaction: discord.Interaction):
        target    = interaction.guild.default_role
        overwrite = interaction.channel.overwrites_for(target)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(target, overwrite=overwrite)
        await interaction.response.send_message(
            view=styled_view("Channel Locked", f"Send messages revoked for {target.name}.")
        )

    @lock_group.command(name="remove", description="Unlocks the current channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_remove(self, interaction: discord.Interaction):
        target    = interaction.guild.default_role
        overwrite = interaction.channel.overwrites_for(target)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(target, overwrite=overwrite)
        await interaction.response.send_message(
            view=styled_view("Channel Unlocked", f"Send messages restored for {target.name}.")
        )

    @role_group.command(name="add", description="Adds a role to a user.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                view=styled_view("Hierarchy Error", "Cannot assign a role equal or above my highest role."),
                ephemeral=True,
            )
        try:
            await member.add_roles(role)
            await interaction.response.send_message(
                view=styled_view("Role Assigned", f"{role.name} assigned to {member.name}.")
            )
        except Exception as e:
            await interaction.response.send_message(view=styled_view("Error", str(e)), ephemeral=True)

    @role_group.command(name="remove", description="Removes a role from a user.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_remove(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        if role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                view=styled_view("Hierarchy Error", "Cannot remove a role equal or above my highest role."),
                ephemeral=True,
            )
        try:
            await member.remove_roles(role)
            await interaction.response.send_message(
                view=styled_view("Role Removed", f"{role.name} removed from {member.name}.")
            )
        except Exception as e:
            await interaction.response.send_message(view=styled_view("Error", str(e)), ephemeral=True)

    @app_commands.command(name="history", description="Displays moderation history for a member.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def history(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        async with self.bot.db_pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT guild_case_id, action_type, reason, timestamp, moderator_id
                FROM mod_logs
                WHERE guild_id = $1 AND user_id = $2
                ORDER BY timestamp DESC
                LIMIT 10
                """,
                interaction.guild.id, member.id,
            )

        if not records:
            history_content = "No moderation history found for this user."
        else:
            lines = []
            for r in records:
                mod = interaction.guild.get_member(r["moderator_id"]) or f"ID: {r['moderator_id']}"
                lines.append(
                    f"**Case #{r['guild_case_id']} — {r['action_type']}**\n"
                    f"Reason: {r['reason']}\n"
                    f"Moderator: {mod}\n"
                    f"Date: <t:{r['timestamp']}:f>\n"
                )
            history_content = "\n".join(lines)

        main_text  = ui.TextDisplay(f"**Moderation History for {member.name}**\n\nShowing last 10 cases.")
        sep        = ui.Separator(spacing=discord.SeparatorSpacing.large, visible=True)
        body       = ui.TextDisplay(history_content)
        container  = ui.Container(main_text, sep, body)
        view       = ui.LayoutView()
        view.add_item(container)
        await interaction.followup.send(view=view)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            description = "You do not have the required permissions."
        else:
            description = str(error)
        view = styled_view("Operation Failed", description)
        if not interaction.response.is_done():
            await interaction.response.send_message(view=view, ephemeral=True)
        else:
            await interaction.followup.send(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))