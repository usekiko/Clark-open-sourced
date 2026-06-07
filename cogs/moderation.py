import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import aiomysql

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

class DurationTransformer(app_commands.Transformer):
    async def transform(self, interaction: discord.Interaction, value: str) -> datetime.timedelta:
        units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
        try:
            amount = int(value[:-1])
            unit = value[-1].lower()
            if unit not in units:
                raise ValueError("Invalid time unit.")
            return datetime.timedelta(seconds=amount * units[unit])
        except (ValueError, TypeError):
            raise app_commands.AppCommandError("Invalid duration format. Example: '10m', '2h', '1d'.")

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.embed_color = 0x5a63f7
        
        self.EMOJIS = {
            'SUCCESS':  '<:goodconnection:1454536158208983051>',
            'ERROR':    '<:lowconnection:1454536160545214527>',
            'INFO':     '<:mediumconnection:1454536162189512734>'
        }
        
        self.response_thumbnail_accessory = None 
        # Initialize the bot profile task to prepare DB and accessories
        self.bot.loop.create_task(self.setup_database())

    # --- Command Group Definitions ---
    ban_group = app_commands.Group(name="ban", description="Permanent ban management.")
    tempban_group = app_commands.Group(name="tempban", description="Temporary ban management.")
    mute_group = app_commands.Group(name="mute", description="Mute (timeout) management.")
    warn_group = app_commands.Group(name="warn", description="Warning management.")
    slowmode_group = app_commands.Group(name="slowmode", description="Channel slowmode management.")
    lock_group = app_commands.Group(name="lock", description="Channel lock management.")
    role_group = app_commands.Group(name="role", description="User role management.")

    def _create_styled_view(self, status: str, title: str, description: str) -> ui.LayoutView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        container = ui.Container(header, sep, body)
        
        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view

    async def _send_dm_container(self, user: discord.User, title: str, description: str):
        try:
            dm_view = self._create_styled_view('INFO', title, description)
            await user.send(view=dm_view)
        except (discord.Forbidden, Exception) as e:
            print(f"{Colors.RED}[ERROR]         Failed to send moderation DM to {user.name} ({user.id}): {e}{Colors.RESET}")

    async def setup_database(self):
        await self.bot.wait_until_ready()
        if self.bot.user:
            self.response_thumbnail_accessory = ui.Thumbnail(
                media=self.bot.user.display_avatar.url
            )

        try:
            if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
                print(f"{Colors.RED}[ERROR]         Database pool not set on bot object.{Colors.RESET}")
                return

            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS mod_logs (
                            log_id INT AUTO_INCREMENT PRIMARY KEY, guild_case_id INT NOT NULL, guild_id VARCHAR(255) NOT NULL,
                            moderator_id VARCHAR(255) NOT NULL, user_id VARCHAR(255) NOT NULL, action_type VARCHAR(50) NOT NULL,
                            reason TEXT, timestamp BIGINT NOT NULL, expires_at BIGINT NULL,
                            UNIQUE KEY idx_guild_case (guild_id, guild_case_id), INDEX idx_guild_user (guild_id, user_id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """)
            print(f"{Colors.GREEN}[SUCCESS]      cogs.moderation.py has successfully created all tables{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]         Failed to initialize moderation logs table: {e}{Colors.RESET}")

    async def log_case(self, interaction: discord.Interaction, action_type: str, user: discord.User, reason: str, expires_at=None) -> int:
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await conn.begin()
                try:
                    await cursor.execute("SELECT MAX(guild_case_id) as max_id FROM mod_logs WHERE guild_id = %s FOR UPDATE", (str(interaction.guild.id),))
                    result = await cursor.fetchone()
                    next_case_id = (result['max_id'] or 0) + 1
                    await cursor.execute(
                        "INSERT INTO mod_logs (guild_case_id, guild_id, moderator_id, user_id, action_type, reason, timestamp, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (next_case_id, str(interaction.guild.id), str(interaction.user.id), str(user.id), action_type, reason, int(datetime.datetime.now().timestamp()), expires_at)
                    )
                    await conn.commit()
                    return next_case_id
                except Exception as e:
                    await conn.rollback()
                    print(f"{Colors.RED}[ERROR]         Error logging case: {e}{Colors.RESET}")
                    raise

    # --- Moderation Commands ---

    @app_commands.command(name="kick", description="Removes a user from the server.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, *, reason: str = "No reason provided."):
        if member == self.bot.user or member == interaction.guild.owner or member == interaction.user:
            response_view = self._create_styled_view("ERROR", "Access Denied", "> Insufficient permissions to moderate this user.")
            return await interaction.response.send_message(view=response_view, ephemeral=True) 
        if member.top_role >= interaction.guild.me.top_role:
            response_view = self._create_styled_view("ERROR", "Hierarchy Error", "> Cannot moderate user with higher role position.")
            return await interaction.response.send_message(view=response_view, ephemeral=True) 
        try:
            case_id = await self.log_case(interaction, "KICK", member, reason)
            
            dm_title = f"You were Kicked from {interaction.guild.name}"
            dm_description = (
                f"### Details\n"
                f"- **Moderator:** {interaction.user.mention}\n"
                f"- **Reason:** {reason}\n"
                f"- **Case ID:** #{case_id}\n\n"
                "You may be able to rejoin with a new invite link."
            )
            await self._send_dm_container(member, dm_title, dm_description)

            await member.kick(reason=f"Case #{case_id}: {reason} (Kicked by {interaction.user.name})")
            
            response_view = self._create_styled_view("SUCCESS", "Member Kicked", f"> User: {member.name}\n> Reason: {reason}\n> Case ID: #{case_id}")
            await interaction.response.send_message(view=response_view) 
        except discord.Forbidden:
            response_view = self._create_styled_view("ERROR", "Missing Permissions", "> 'Kick Members' permission required.")
            await interaction.response.send_message(view=response_view, ephemeral=True) 

    @ban_group.command(name="add", description="Permanently removes a user from the server.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_add(self, interaction: discord.Interaction, user: discord.User, reason: str, delete_days: app_commands.Range[int, 0, 7] = 0):
        if user == self.bot.user or user == interaction.guild.owner or user == interaction.user:
            response_view = self._create_styled_view("ERROR", "Protected User", "> Cannot moderate administrator or server owner.")
            return await interaction.response.send_message(view=response_view, ephemeral=True)
        member = interaction.guild.get_member(user.id)
        if member and member.top_role >= interaction.guild.me.top_role:
            response_view = self._create_styled_view("ERROR", "Hierarchy Error", "> Cannot moderate user with higher role position.")
            return await interaction.response.send_message(view=response_view, ephemeral=True)
        try:
            case_id = await self.log_case(interaction, "BAN", user, reason)
            
            dm_title = f"You were Banned from {interaction.guild.name}"
            dm_description = (
                f"### Details\n"
                f"- **Moderator:** {interaction.user.mention}\n"
                f"- **Reason:** {reason}\n"
                f"- **Case ID:** #{case_id}\n\n"
                "This action is permanent."
            )
            await self._send_dm_container(user, dm_title, dm_description)

            await interaction.guild.ban(user, reason=f"Case #{case_id}: {reason} (Banned by {interaction.user.name})", delete_message_days=delete_days)
            
            response_view = self._create_styled_view("SUCCESS", "Member Banned", f"> User: {user.name}\n> Reason: {reason}\n> Case ID: #{case_id}")
            await interaction.response.send_message(view=response_view)
        except discord.Forbidden:
            response_view = self._create_styled_view("ERROR", "Missing Permissions", "> 'Ban Members' permission required.")
            await interaction.response.send_message(view=response_view, ephemeral=True)

    @ban_group.command(name="remove", description="Removes a ban from a user.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_remove(self, interaction: discord.Interaction, user_id: str, *, reason: str = "Reversal of ban."):
        if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
            response_view = self._create_styled_view("ERROR", "Database Error", "> Database connection unavailable.")
            return await interaction.response.send_message(view=response_view, ephemeral=True)
        
        try:
            user = await self.bot.fetch_user(int(user_id))
            case_id = await self.log_case(interaction, "UNBAN", user, reason)
            await interaction.guild.unban(user, reason=f"Case #{case_id}: {reason} (Unbanned by {interaction.user.name})")
            
            dm_title = f"Your Ban was Removed from {interaction.guild.name}"
            dm_description = (
                f"### Details\n"
                f"- **Moderator:** {interaction.user.mention}\n"
                f"- **Reason:** {reason}\n"
                f"- **Case ID:** #{case_id}\n\n"
                "You can now rejoin the server."
            )
            await self._send_dm_container(user, dm_title, dm_description)
            
            response_view = self._create_styled_view("SUCCESS", "Member Unbanned", f"> User: {user.name}\n> Reason: {reason}\n> Case ID: #{case_id}")
            await interaction.response.send_message(view=response_view)
        except discord.NotFound:
            response_view = self._create_styled_view("ERROR", "Not Banned", "> User is not currently banned.")
            await interaction.response.send_message(view=response_view, ephemeral=True)
        except Exception as e:
             response_view = self._create_styled_view("ERROR", "Error", f"> {e}")
             await interaction.response.send_message(view=response_view, ephemeral=True)

    @tempban_group.command(name="add", description="Temporarily removes a user.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempban_add(self, interaction: discord.Interaction, user: discord.User, duration: app_commands.Transform[datetime.timedelta, DurationTransformer], reason: str):
        if user == self.bot.user or user == interaction.guild.owner or user == interaction.user:
            response_view = self._create_styled_view("ERROR", "Protected User", "> Cannot moderate administrator or server owner.")
            return await interaction.response.send_message(view=response_view, ephemeral=True)
        try:
            end_time = discord.utils.utcnow() + duration
            expires_at_ts = int(end_time.timestamp())
            case_id = await self.log_case(interaction, "TEMPBAN", user, reason, expires_at=expires_at_ts)

            dm_title = f"You were Temporarily Banned from {interaction.guild.name}"
            dm_description = (
                f"### Details\n"
                f"- **Moderator:** {interaction.user.mention}\n"
                f"- **Reason:** {reason}\n"
                f"- **Duration:** {str(duration).split('.')[0]}\n"
                f"- **Expires:** <t:{expires_at_ts}:F>\n"
                f"- **Case ID:** #{case_id}"
            )
            await self._send_dm_container(user, dm_title, dm_description)
            await interaction.guild.ban(user, reason=f"Case #{case_id} (Temporary): {reason}")
            
            response_view = self._create_styled_view("SUCCESS", "Temporary Ban Applied", f"> User: {user.name}\n> Expires: <t:{expires_at_ts}:F>\n> Case ID: #{case_id}")
            await interaction.response.send_message(view=response_view)
        except Exception as e:
            response_view = self._create_styled_view("ERROR", "Error", f"> {e}")
            await interaction.response.send_message(view=response_view, ephemeral=True)

    @tempban_group.command(name="remove", description="Removes a temporary ban.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def tempban_remove(self, interaction: discord.Interaction, user_id: str, *, reason: str = "Reversal of temporary ban."):
        await self.ban_remove.callback(self, interaction, user_id, reason=reason)

    @mute_group.command(name="add", description="Prevents a user from sending messages.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute_add(self, interaction: discord.Interaction, member: discord.Member, duration: app_commands.Transform[datetime.timedelta, DurationTransformer], *, reason: str):
        if member == self.bot.user or member == interaction.guild.owner or member == interaction.user:
            response_view = self._create_styled_view("ERROR", "Protected User", "> Cannot moderate administrator or server owner.")
            return await interaction.response.send_message(view=response_view, ephemeral=True)
        try:
            end_time = discord.utils.utcnow() + duration
            expires_at_ts = int(end_time.timestamp())
            case_id = await self.log_case(interaction, "MUTE", member, reason, expires_at=expires_at_ts)

            dm_title = f"You have been Timed Out in {interaction.guild.name}"
            dm_description = (
                f"### Details\n"
                f"- **Moderator:** {interaction.user.mention}\n"
                f"- **Reason:** {reason}\n"
                f"- **Expires:** <t:{expires_at_ts}:F>\n"
                f"- **Case ID:** #{case_id}"
            )
            await self._send_dm_container(member, dm_title, dm_description)
            await member.timeout(duration, reason=f"Case #{case_id}: {reason}")
            
            response_view = self._create_styled_view("SUCCESS", "Member Muted", f"> User: {member.name}\n> Expires: <t:{expires_at_ts}:F>\n> Case ID: #{case_id}")
            await interaction.response.send_message(view=response_view)
        except Exception as e:
            response_view = self._create_styled_view("ERROR", "Error", f"> {e}")
            await interaction.response.send_message(view=response_view, ephemeral=True)

    @mute_group.command(name="remove", description="Removes a user's timeout.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def mute_remove(self, interaction: discord.Interaction, member: discord.Member, *, reason: str = "Reversal of mute."):
        if not member.is_timed_out():
            response_view = self._create_styled_view("ERROR", "Not Muted", "> User does not have an active timeout.")
            return await interaction.response.send_message(view=response_view, ephemeral=True)
        try:
            case_id = await self.log_case(interaction, "UNMUTE", member, reason)
            await member.timeout(None, reason=f"Case #{case_id}: {reason}")
            
            response_view = self._create_styled_view("SUCCESS", "Member Unmuted", f"> User: {member.name}\n> Case ID: #{case_id}")
            await interaction.response.send_message(view=response_view)
        except Exception as e:
            response_view = self._create_styled_view("ERROR", "Error", f"> {e}")
            await interaction.response.send_message(view=response_view, ephemeral=True)

    @warn_group.command(name="add", description="Gives a user a warning.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_add(self, interaction: discord.Interaction, member: discord.Member, *, reason: str):
        if member.bot or member == interaction.guild.owner or member == interaction.user:
            response_view = self._create_styled_view("ERROR", "Invalid Target", "> Cannot moderate this user.")
            return await interaction.response.send_message(view=response_view, ephemeral=True)
        case_id = await self.log_case(interaction, "WARN", member, reason)
        
        dm_title = f"You received a Warning in {interaction.guild.name}"
        dm_description = f"### Details\n- **Reason:** {reason}\n- **Case ID:** #{case_id}"
        await self._send_dm_container(member, dm_title, dm_description)
        
        response_view = self._create_styled_view("SUCCESS", "Warning Issued", f"> User: {member.name}\n> Reason: {reason}\n> Case ID: #{case_id}")
        await interaction.response.send_message(view=response_view)

    @warn_group.command(name="remove", description="Deletes a warning by Case ID.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn_remove(self, interaction: discord.Interaction, case_id: int):
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT log_id, action_type, user_id FROM mod_logs WHERE guild_case_id = %s AND guild_id = %s", (case_id, str(interaction.guild.id)))
                record = await cursor.fetchone()
                if not record or record.get('action_type') != 'WARN':
                    response_view = self._create_styled_view("ERROR", "Not Found", "> Warning case does not exist.")
                    return await interaction.response.send_message(view=response_view, ephemeral=True)
                
                await cursor.execute("DELETE FROM mod_logs WHERE log_id = %s", (record['log_id'],))
                await conn.commit()
        
        response_view = self._create_styled_view("SUCCESS", "Warning Removed", f"> Case #{case_id} removed from record.")
        await interaction.response.send_message(view=response_view)

    @app_commands.command(name="purge", description="Deletes messages.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        response_view = self._create_styled_view("SUCCESS", "Messages Purged", f"> {len(deleted)} messages deleted.")
        await interaction.followup.send(view=response_view, ephemeral=True)

    @slowmode_group.command(name="apply", description="Sets channel slowmode.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode_apply(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        response_view = self._create_styled_view("SUCCESS", "Slowmode Configured", f"> Rate limit set to {seconds} seconds.")
        await interaction.response.send_message(view=response_view)

    @lock_group.command(name="apply", description="Locks the channel.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock_apply(self, interaction: discord.Interaction):
        target = interaction.guild.default_role
        overwrite = interaction.channel.overwrites_for(target)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(target, overwrite=overwrite)
        response_view = self._create_styled_view("SUCCESS", "Channel Locked", f"> Send messages permission revoked for {target.name}.")
        await interaction.response.send_message(view=response_view)

    @role_group.command(name="add", description="Adds a role.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def role_add(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        try:
            await member.add_roles(role)
            response_view = self._create_styled_view("SUCCESS", "Role Assigned", f"> {role.name} assigned to {member.name}.")
            await interaction.response.send_message(view=response_view)
        except Exception as e:
            response_view = self._create_styled_view("ERROR", "Error", f"> {e}")
            await interaction.response.send_message(view=response_view, ephemeral=True)

    @app_commands.command(name="history", description="Displays moderation history.")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def history(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        
        main_text = ui.TextDisplay(f"**{self.EMOJIS['SUCCESS']} ›  Moderation History for {member.name}**\n\n_Showing last 10 cases._")
        
        items = [main_text]
        items.append(ui.Separator(spacing=discord.SeparatorSpacing.large, visible=True))

        history_content = ""
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT guild_case_id, action_type, reason, timestamp, moderator_id FROM mod_logs WHERE guild_id = %s AND user_id = %s ORDER BY timestamp DESC LIMIT 10",
                    (str(interaction.guild.id), str(member.id))
                )
                records = await cursor.fetchall()
                if records:
                    for record in records:
                        mod_id = int(record['moderator_id'])
                        mod = interaction.guild.get_member(mod_id) or f"ID: {mod_id}"
                        action_time = f"<t:{record['timestamp']}:f>"
                        history_content += (
                            f"**Case #{record['guild_case_id']} — {record['action_type']}**\n"
                            f"- Reason: {record['reason']}\n"
                            f"- Moderator: {mod}\n"
                            f"- Date: {action_time}\n\n"
                        )
                    items.append(ui.TextDisplay(history_content))

        if not history_content:
            items.append(ui.TextDisplay("No moderation history found for this user."))
        
        container = ui.Container(*items)
        view = ui.LayoutView()
        view.add_item(container)
        await interaction.followup.send(view=view)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        title = "Operation Failed"
        description = str(error)
        
        if isinstance(error, app_commands.errors.MissingPermissions):
            description = "You do not have the required permissions."
        
        response_view = self._create_styled_view("ERROR", title, description)
        if not interaction.response.is_done():
            await interaction.response.send_message(view=response_view, ephemeral=True)
        else:
            await interaction.followup.send(view=response_view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))