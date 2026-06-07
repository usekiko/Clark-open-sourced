import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger("WelcomeCog")

class Welcome(commands.GroupCog, name="welcome"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Forces the database to update without needing HeidiSQL."""
        if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Rename old table if it exists to avoid conflicts, then create fresh
                    try:
                        await cur.execute("ALTER TABLE welcome_config RENAME TO old_welcome_config")
                    except:
                        pass # Table might not exist or already renamed
                    
                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS welcome_config (
                            guild_id BIGINT PRIMARY KEY,
                            channel_id BIGINT,
                            custom_text TEXT
                        )
                    """)
                    await conn.commit()

    def format_welcome(self, text, member: discord.Member):
        """Handles pings, server names, and manual newlines."""
        if not text: return ""
        # {user} = Mention/Ping, {servername} = Server Name, \\n = Actual New Line
        return text.replace("{user}", member.mention) \
                   .replace("{user.name}", member.name) \
                   .replace("{servername}", member.guild.name) \
                   .replace("\\n", "\n")

    @app_commands.command(name="setup", description="Configure text-only welcome messages")
    @app_commands.describe(
        channel="Where to send the message",
        message="Tags: {user} (ping), {servername}. Use \\n for new lines."
    )
    @commands.has_permissions(administrator=True)
    async def setup(self, itx: discord.Interaction, channel: discord.TextChannel, *, message: str):
        await itx.response.defer(ephemeral=True)
        try:
            query = """
            INSERT INTO welcome_config (guild_id, channel_id, custom_text)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE channel_id = VALUES(channel_id), custom_text = VALUES(custom_text)
            """
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (itx.guild.id, channel.id, message))
                    await conn.commit()
            
            preview = self.format_welcome(message, itx.user)
            await itx.followup.send(f"**Welcome Configured!**\n**Channel:** {channel.mention}\n**Preview:**\n{preview}", ephemeral=True)
        except Exception as e:
            await itx.followup.send(f"Error: {e}", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not self.bot.db_pool: return
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT channel_id, custom_text FROM welcome_config WHERE guild_id = %s", (member.guild.id,))
                cfg = await cur.fetchone()

        if cfg and cfg[0]:
            channel = self.bot.get_channel(cfg[0]) or await self.bot.fetch_channel(cfg[0])
            if channel:
                try:
                    await channel.send(self.format_welcome(cfg[1], member))
                except discord.Forbidden:
                    logger.warning(f"No permission to send welcome in {member.guild.name}")

async def setup(bot):
    await bot.add_cog(Welcome(bot))