import discord
from discord.ext import commands
from discord import app_commands, ui
import logging
import asyncio
import aiohttp

logger = logging.getLogger("ThreadCog")

class ThreadGroup(commands.GroupCog, name="thread"):
    def __init__(self, bot):
        self.bot = bot
        self.active_channels = set()

    async def cog_load(self):
        """Create table then load active channels from DB on startup."""
        if not (hasattr(self.bot, 'db_pool') and self.bot.db_pool):
            return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS thread_channels (
                    id         SERIAL PRIMARY KEY,
                    guild_id   BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL UNIQUE
                )
            """)
            rows = await conn.fetch("SELECT channel_id FROM thread_channels")
            self.active_channels = {row[0] for row in rows}
        logger.info(f"Loaded {len(self.active_channels)} thread channels from database.")


    @app_commands.command(name="create", description="Enable auto-threads for images in a channel")
    @app_commands.describe(channel="The channel to enable threads for")
    @commands.has_permissions(administrator=True)
    async def create_thread_channel(self, itx: discord.Interaction, channel: discord.TextChannel):
        await itx.response.defer(ephemeral=True)
        
        try:
            query = "INSERT INTO thread_channels (guild_id, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(query, itx.guild.id, channel.id)
            
            self.active_channels.add(channel.id)
            await itx.followup.send(f"Successfully enabled auto-threads for {channel.mention}.")
        except Exception as e:
            logger.error(f"Thread Create Error: {e}")
            await itx.followup.send(f"Error: {e}")

    @app_commands.command(name="delete", description="Disable auto-threads for a channel")
    @app_commands.describe(channel="The channel to disable threads for")
    @commands.has_permissions(administrator=True)
    async def delete_thread_channel(self, itx: discord.Interaction, channel: discord.TextChannel):
        await itx.response.defer(ephemeral=True)
        
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("DELETE FROM thread_channels WHERE channel_id = $1", channel.id)
            
            self.active_channels.discard(channel.id)
            await itx.followup.send(f"Successfully disabled auto-threads for {channel.mention}.")
        except Exception as e:
            logger.error(f"Thread Delete Error: {e}")
            await itx.followup.send(f"Error: {e}")

    @app_commands.command(name="list", description="List all active thread channels in this server")
    @commands.has_permissions(administrator=True)
    async def list_threads(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        
        async with self.bot.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT channel_id FROM thread_channels WHERE guild_id = $1", itx.guild.id)

        if not rows:
            return await itx.followup.send("No thread channels are currently configured.")

        channels = [itx.guild.get_channel(row[0]) for row in rows]
        # Filter out any None values if channels were deleted
        mentions = [c.mention for c in channels if c]
        
        await itx.followup.send(f"**Active Thread Channels:**\n" + "\n".join(mentions))

    async def get_or_create_webhook(self, channel: discord.TextChannel, retries=3):
        """Ensures a webhook exists with retry logic for network issues."""
        for attempt in range(retries):
            try:
                webhooks = await channel.webhooks()
                webhook = discord.utils.get(webhooks, name="MediaThreadHook")
                if not webhook:
                    webhook = await channel.create_webhook(name="MediaThreadHook", reason="Auto-thread system")
                return webhook
            except (aiohttp.ClientConnectorError, discord.HTTPException) as e:
                if attempt == retries - 1:
                    logger.error(f"Webhook connection failed: {e}")
                    return None
                await asyncio.sleep(2)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id not in self.active_channels:
            return

        has_image = any(att.content_type and att.content_type.startswith('image/') for att in message.attachments)
        if not has_image:
            return

        try:
            webhook = await self.get_or_create_webhook(message.channel)
            if not webhook: return

            files = [await att.to_file() for att in message.attachments]
            await message.delete()

            webhook_msg = await webhook.send(
                content=message.content,
                username=message.author.display_name,
                avatar_url=message.author.display_avatar.url,
                files=files,
                wait=True
            )

            await webhook_msg.add_reaction("👍")
            await webhook_msg.add_reaction("👎")
            await webhook_msg.create_thread(name=f"Comments: {message.author.name}")

        except Exception as e:
            logger.error(f"Media Thread Error: {e}")

async def setup(bot):
    await bot.add_cog(ThreadGroup(bot))