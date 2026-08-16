import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger("GoodbyeCog")

@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class Goodbye(commands.GroupCog, name="goodbye"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
            async with self.bot.db_pool.acquire() as conn:
                try:
                    await conn.execute("ALTER TABLE goodbye_config RENAME TO old_goodbye_config")
                except:
                    pass
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS goodbye_config (
                        guild_id BIGINT PRIMARY KEY,
                        channel_id BIGINT,
                        custom_text TEXT
                    )
                """)

    def format_goodbye(self, text, member: discord.Member):
        if not text: return ""
        # {user} on goodbye shows name (pings don't work for users who left)
        return text.replace("{user}", f"**{member.name}**") \
                   .replace("{servername}", member.guild.name) \
                   .replace("\\n", "\n")

    @app_commands.command(name="setup", description="Configure text-only goodbye messages")
    @app_commands.describe(
        channel="Where to send the message",
        message="Tags: {user} (name), {servername}. Use \\n for new lines."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, itx: discord.Interaction, channel: discord.TextChannel, *, message: str):
        await itx.response.defer(ephemeral=True)
        try:
            query = """
            INSERT INTO goodbye_config (guild_id, channel_id, custom_text)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE SET channel_id = EXCLUDED.channel_id, custom_text = EXCLUDED.custom_text
            """
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(query, itx.guild.id, channel.id, message)
            
            preview = self.format_goodbye(message, itx.user)
            await itx.followup.send(f"**Goodbye Configured!**\n<:preview:1454536798402383952> **Preview:**\n{preview}", ephemeral=True)
        except Exception as e:
            await itx.followup.send(f"Error: {e}", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not self.bot.db_pool: return
        async with self.bot.db_pool.acquire() as conn:
            cfg = await conn.fetchrow("SELECT channel_id, custom_text FROM goodbye_config WHERE guild_id = $1", member.guild.id)

        if cfg and cfg['channel_id']:
            channel = self.bot.get_channel(cfg['channel_id']) or await self.bot.fetch_channel(cfg['channel_id'])
            if channel:
                try:
                    await channel.send(self.format_goodbye(cfg['custom_text'], member))
                except discord.Forbidden:
                    pass

async def setup(bot):
    await bot.add_cog(Goodbye(bot))