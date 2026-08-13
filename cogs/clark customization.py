import discord
from discord.ext import commands
from discord import app_commands, ui

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
        self.embed_color = 0x5a63f7
        self.response_thumbnail_accessory = None 
        # Task to initialize the profile accessory
        self.bot.loop.create_task(self.setup_bot_profile())

    async def setup_bot_profile(self):
        """Initializes the accessory with the Bot/Server avatar."""
        await self.bot.wait_until_ready()
        if self.bot.user:
            self.response_thumbnail_accessory = ui.Thumbnail(media=self.bot.user.display_avatar.url)

    def _create_styled_view(self, status: str, title: str, description: str, interaction: discord.Interaction) -> ui.LayoutView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        container = ui.Container(header, sep, body)
        
        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view
    
    clark_group = app_commands.Group(name="clark", description="Clark's bot-specific settings.")
    
    async def _check_db_ready(self, interaction: discord.Interaction) -> bool:
        if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
            view = self._create_styled_view('ERROR', "Database Not Ready", "The database connection is not yet established.", interaction)
            await interaction.response.send_message(view=view, ephemeral=True)
            return False
        return True

    async def _clear_server_history(self, guild_id: str):
        """Clark's context is shared per channel, so a persona change resets the
        whole server's conversation, not just the staff member who ran the command.
        Rows are archived rather than deleted so analytics keep their data."""
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE chat_messages SET archived = TRUE WHERE guild_id = $1 AND archived = FALSE",
                    guild_id,
                )
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Error clearing history: {e}{Colors.RESET}")

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
                    str(interaction.guild.id), interaction.guild.name, mode
                )
            
            await self._clear_server_history(str(interaction.guild.id))
            view = self._create_styled_view('SUCCESS', "AI Behaviour Updated", f"Personality set to: {mode.capitalize()}\nConversation history cleared.", interaction)
            await interaction.response.send_message(view=view, ephemeral=True)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Mode command error: {e}{Colors.RESET}")
            await interaction.response.send_message("Database error occurred.", ephemeral=True)

    @clark_group.command(name="instruction", description="Set a custom instruction (Overrides mode).")
    @app_commands.describe(instruction="Bot's new instructions (Max 400 chars).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_instruction(self, interaction: discord.Interaction, instruction: str):
        if len(instruction) > 400:
            view = self._create_styled_view('INFO', "Character Limit Exceeded", "Maximum instruction length is 400 characters.", interaction)
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        if not await self._check_db_ready(interaction): return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO servers (guild_id, guild_name, custom_instruction, clark_mode) "
                    "VALUES ($1, $2, $3, NULL) ON CONFLICT (guild_id) DO UPDATE SET custom_instruction=$3, clark_mode=NULL",
                    str(interaction.guild.id), interaction.guild.name, instruction
                )
            
            await self._clear_server_history(str(interaction.guild.id))
            
            view = self._create_styled_view('SUCCESS', "Custom Instruction Set", "New instruction configured.\nConversation history cleared.", interaction)
            await interaction.response.send_message(view=view, ephemeral=True)
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
                    str(interaction.guild.id)
                )
            
            await self._clear_server_history(str(interaction.guild.id))
            view = self._create_styled_view('SUCCESS', "Settings Reset", "Custom instructions removed.\nDefault behaviour restored.\nConversation history cleared.", interaction)
            await interaction.response.send_message(view=view, ephemeral=True)
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Reset error: {e}{Colors.RESET}")

    @clark_group.command(name="on", description="Turns the mention chatbot feature on.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def chatbot_on(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("INSERT INTO servers (guild_id, guild_name, chatbot_enabled) VALUES ($1, $2, TRUE) ON CONFLICT (guild_id) DO UPDATE SET chatbot_enabled=TRUE", str(interaction.guild.id), interaction.guild.name)
        view = self._create_styled_view('SUCCESS', "AI Responses Enabled", "Clark will now respond to mentions.", interaction)
        await interaction.response.send_message(view=view, ephemeral=True)

    @clark_group.command(name="off", description="Turns the mention chatbot feature off.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def chatbot_off(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("INSERT INTO servers (guild_id, guild_name, chatbot_enabled) VALUES ($1, $2, FALSE) ON CONFLICT (guild_id) DO UPDATE SET chatbot_enabled=FALSE", str(interaction.guild.id), interaction.guild.name)
        view = self._create_styled_view('SUCCESS', "AI Responses Disabled", "Clark will no longer respond to mentions.", interaction)
        await interaction.response.send_message(view=view, ephemeral=True)

    @clark_group.command(name="add_channel", description="Whitelist a channel for Clark.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("INSERT INTO allowed_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", str(interaction.guild.id), channel.id)
        view = self._create_styled_view('SUCCESS', "Channel Whitelisted", f"{channel.mention} added to allowed channels.", interaction)
        await interaction.response.send_message(view=view, ephemeral=True)

    @clark_group.command(name="remove_channel", description="Remove a channel whitelist.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM allowed_channels WHERE guild_id = $1 AND channel_id = $2", str(interaction.guild.id), channel.id)
        view = self._create_styled_view('SUCCESS', "Channel Removed", f"{channel.mention} removed from allowed channels.", interaction)
        await interaction.response.send_message(view=view, ephemeral=True)

    @clark_group.command(name="clear_channels", description="Respond in all channels.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def clear_channels(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM allowed_channels WHERE guild_id = $1", str(interaction.guild.id))
        view = self._create_styled_view('SUCCESS', "Channel Restrictions Cleared", "Clark will respond in all channels.", interaction)
        await interaction.response.send_message(view=view, ephemeral=True)

    @clark_group.command(name="list_channels", description="List allowed channels.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_channels(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            res = await conn.fetch("SELECT channel_id FROM allowed_channels WHERE guild_id = $1", str(interaction.guild.id))
        
        if not res: 
            view = self._create_styled_view('SUCCESS', "Channel Access", "No restrictions configured. Clark responds in all channels.", interaction)
        else:
            mentions = [interaction.guild.get_channel(int(r['channel_id'])).mention for r in res if interaction.guild.get_channel(int(r['channel_id']))]
            view = self._create_styled_view('SUCCESS', "Allowed Channels", "\n".join(mentions), interaction)
        await interaction.response.send_message(view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Settings(bot))