import discord
import traceback
from discord.ext import commands
from discord import app_commands

from utils import embed, error_embed


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

class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _embed(self, status: str, title: str, description: str) -> discord.Embed:
        """status is ERROR/SUCCESS/INFO - only ERROR changes the colour."""
        return error_embed(title, description) if status == "ERROR" else embed(title, description)
    
    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        """Without this, a failed permission check or an exception raised before the
        callback body leaves the interaction unacknowledged, and Discord shows the
        user "application did not respond" with nothing in the logs to explain it."""
        if isinstance(error, app_commands.MissingPermissions):
            title = "Missing Permissions"
            body = "You need the **Manage Server** permission to change Clark's settings."
        elif isinstance(error, app_commands.BotMissingPermissions):
            title = "I'm Missing Permissions"
            body = f"I need: {', '.join(error.missing_permissions)}"
        elif isinstance(error, app_commands.CheckFailure):
            title, body = "Not Allowed", "You can't use that command here."
        else:
            title = "Something Broke"
            body = "That command failed. The error has been logged."
            name = interaction.command.qualified_name if interaction.command else "unknown"
            print(f"{Colors.RED}[ERROR] /{name} failed: {type(error).__name__}: {error}{Colors.RESET}")
            traceback.print_exception(type(error), error, error.__traceback__)

        try:
            e = self._embed('ERROR', title, body)
            if interaction.response.is_done():
                await interaction.followup.send(embed=e, ephemeral=True)
            else:
                await interaction.response.send_message(embed=e, ephemeral=True)
        except discord.HTTPException:
            pass

    clark_group = app_commands.Group(name="clark", description="Clark's bot-specific settings.")
    
    async def _check_db_ready(self, interaction: discord.Interaction) -> bool:
        if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
            e = self._embed('ERROR', "Database Not Ready", "The database connection is not yet established.")
            await interaction.response.send_message(embed=e, ephemeral=True)
            return False
        return True

    def _invalidate_ai_gate(self, guild_id: int):
        """Drops just the cached on/off + whitelist + persona lookup, so an on,
        off or channel change lands straight away. Leaves the conversation alone -
        toggling the chatbot shouldn't wipe what he remembers."""
        cog = self.bot.get_cog("AIChatbot")
        if cog is not None and hasattr(cog, "invalidate_config"):
            cog.invalidate_config(guild_id)

    def _invalidate_ai_cache(self, guild_id: int):
        """The AI cog caches persona settings for a minute; drop it so a staff
        change applies to the very next message instead of a minute later."""
        cog = self.bot.get_cog("AIChatbot")
        if cog is None:
            return
        if hasattr(cog, "invalidate_config"):
            cog.invalidate_config(guild_id)
        # Context also lives in RAM now, so archiving the rows is not enough.
        if hasattr(cog, "invalidate_conversations"):
            cog.invalidate_conversations(guild_id)

    async def _clear_server_history(self, guild_id: int) -> int:
        """Clark's context is shared per channel, so a persona change resets the
        whole server's conversation, not just the staff member who ran the command.
        Rows are archived rather than deleted so analytics keep their data.
        Returns how many exchanges were retired."""
        try:
            async with self.bot.db_pool.acquire() as conn:
                status = await conn.execute(
                    "UPDATE chat_messages SET archived = TRUE WHERE guild_id = $1 AND archived = FALSE",
                    guild_id,
                )
            # asyncpg hands back a tag like "UPDATE 12".
            return int(status.split()[-1]) if status else 0
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Error clearing history: {e}{Colors.RESET}")
            return 0

    @clark_group.command(name="mode", description="Changes Clark's personality mode.")
    @app_commands.describe(mode="Choose between friendly, strict, or rude.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Friendly (Default)", value="friendly"),
        app_commands.Choice(name="Strict", value="strict"),
        app_commands.Choice(name="Rude", value="rude")
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_mode(self, interaction: discord.Interaction, mode: str):
        if not await self._check_db_ready(interaction): return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO servers (guild_id, guild_name, clark_mode, custom_instruction) "
                    "VALUES ($1, $2, $3, NULL) ON CONFLICT (guild_id) DO UPDATE SET clark_mode=$3, custom_instruction=NULL",
                    interaction.guild.id, interaction.guild.name, mode
                )
            
            await self._clear_server_history(interaction.guild.id)
            self._invalidate_ai_cache(interaction.guild.id)
            e = self._embed('SUCCESS', "AI Behaviour Updated", f"Personality set to: {mode.capitalize()}\nConversation history cleared.")
            await interaction.response.send_message(embed=e, ephemeral=True)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Mode command error: {e}{Colors.RESET}")
            await interaction.response.send_message("Database error occurred.", ephemeral=True)

    @clark_group.command(name="instruction", description="Set a custom instruction (Overrides mode).")
    @app_commands.describe(instruction="Bot's new instructions (Max 400 chars).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_instruction(self, interaction: discord.Interaction, instruction: str):
        if len(instruction) > 400:
            e = self._embed('INFO', "Character Limit Exceeded", "Maximum instruction length is 400 characters.")
            return await interaction.response.send_message(embed=e, ephemeral=True)
        
        if not await self._check_db_ready(interaction): return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO servers (guild_id, guild_name, custom_instruction, clark_mode) "
                    "VALUES ($1, $2, $3, NULL) ON CONFLICT (guild_id) DO UPDATE SET custom_instruction=$3, clark_mode=NULL",
                    interaction.guild.id, interaction.guild.name, instruction
                )
            
            await self._clear_server_history(interaction.guild.id)
            self._invalidate_ai_cache(interaction.guild.id)
            
            e = self._embed('SUCCESS', "Custom Instruction Set", "New instruction configured.\nConversation history cleared.")
            await interaction.response.send_message(embed=e, ephemeral=True)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Instruction command error: {e}{Colors.RESET}")

    @clark_group.command(name="reset_instruction", description="Resets instruction and defaults mode.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reset_instruction(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE servers SET custom_instruction = NULL, clark_mode = 'friendly' WHERE guild_id = $1",
                    interaction.guild.id
                )
            
            await self._clear_server_history(interaction.guild.id)
            self._invalidate_ai_cache(interaction.guild.id)
            e = self._embed('SUCCESS', "Settings Reset", "Custom instructions removed.\nDefault behaviour restored.\nConversation history cleared.")
            await interaction.response.send_message(embed=e, ephemeral=True)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Reset error: {e}{Colors.RESET}")

    @clark_group.command(name="clear_context", description="Wipes Clark's memory of every conversation on this server.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clear_context(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        await interaction.response.defer(ephemeral=True)
        try:
            cleared = await self._clear_server_history(interaction.guild.id)
            # Context also lives in RAM, so archiving rows alone would leave
            # Clark still remembering everything until the cache turned over.
            self._invalidate_ai_cache(interaction.guild.id)

            body = (
                f"Forgot {cleared} exchange{'' if cleared == 1 else 's'} across every channel.\n"
                "Clark now starts fresh with everyone here."
            ) if cleared else "There was nothing left to forget."
            e = self._embed('SUCCESS', "Context Cleared", body)
            await interaction.followup.send(embed=e, ephemeral=True)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Clear context error: {e}{Colors.RESET}")
            await interaction.followup.send("Database error occurred.", ephemeral=True)

    @clark_group.command(name="on", description="Turns the mention chatbot feature on.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def chatbot_on(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("INSERT INTO servers (guild_id, guild_name, chatbot_enabled) VALUES ($1, $2, TRUE) ON CONFLICT (guild_id) DO UPDATE SET chatbot_enabled=TRUE", interaction.guild.id, interaction.guild.name)
        self._invalidate_ai_gate(interaction.guild.id)
        e = self._embed('SUCCESS', "AI Responses Enabled", "Clark will now respond to mentions.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @clark_group.command(name="off", description="Turns the mention chatbot feature off.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def chatbot_off(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("INSERT INTO servers (guild_id, guild_name, chatbot_enabled) VALUES ($1, $2, FALSE) ON CONFLICT (guild_id) DO UPDATE SET chatbot_enabled=FALSE", interaction.guild.id, interaction.guild.name)
        self._invalidate_ai_gate(interaction.guild.id)
        e = self._embed('SUCCESS', "AI Responses Disabled", "Clark will no longer respond to mentions.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @clark_group.command(name="add_channel", description="Whitelist a channel for Clark.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("INSERT INTO allowed_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", interaction.guild.id, channel.id)
        self._invalidate_ai_gate(interaction.guild.id)
        e = self._embed('SUCCESS', "Channel Whitelisted", f"{channel.mention} added to allowed channels.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @clark_group.command(name="remove_channel", description="Remove a channel whitelist.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM allowed_channels WHERE guild_id = $1 AND channel_id = $2", interaction.guild.id, channel.id)
        self._invalidate_ai_gate(interaction.guild.id)
        e = self._embed('SUCCESS', "Channel Removed", f"{channel.mention} removed from allowed channels.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @clark_group.command(name="clear_channels", description="Respond in all channels.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clear_channels(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM allowed_channels WHERE guild_id = $1", interaction.guild.id)
        self._invalidate_ai_gate(interaction.guild.id)
        e = self._embed('SUCCESS', "Channel Restrictions Cleared", "Clark will respond in all channels.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @clark_group.command(name="list_channels", description="List allowed channels.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_channels(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            res = await conn.fetch("SELECT channel_id FROM allowed_channels WHERE guild_id = $1", interaction.guild.id)
        
        if not res: 
            e = self._embed('SUCCESS', "Channel Access", "No restrictions configured. Clark responds in all channels.")
        else:
            mentions = [interaction.guild.get_channel(int(r['channel_id'])).mention for r in res if interaction.guild.get_channel(int(r['channel_id']))]
            e = self._embed('SUCCESS', "Allowed Channels", "\n".join(mentions))
        await interaction.response.send_message(embed=e, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Settings(bot))