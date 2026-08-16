import discord
from discord.ext import commands
from discord import app_commands
import time
import os

from utils import embed

class BotInfo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    def format_uptime(self) -> str:
        """Format uptime as 'Xd Xh Xm'."""
        delta = int(time.time() - self.start_time)
        days = delta // 86400
        hours = (delta % 86400) // 3600
        minutes = (delta % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        
        return " ".join(parts) if parts else "0m"

    def get_memory_usage(self) -> str:
        """Get memory usage if psutil is available."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_mb = process.memory_info().rss // 1024 // 1024
            return f"{mem_mb}MB"
        except ImportError:
            return "N/A"

    @app_commands.command(name="botinfo", description="Display bot statistics and information.")
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        try:
            # Calculate statistics
            server_count = len(self.bot.guilds)
            total_users = sum(g.member_count or 0 for g in self.bot.guilds)
            shard_count = self.bot.shard_count or 1
            latency = round(self.bot.latency * 1000)
            memory = self.get_memory_usage()
            uptime = self.format_uptime()
            
            e = embed("Clark information", "Global bot statistics and performance metrics")
            if self.bot.user:
                e.set_thumbnail(url=self.bot.user.display_avatar.url)
            e.add_field(name="Developer", value="[usekiko](https://usekiko.com)", inline=False)
            e.add_field(name="Servers", value=f"{server_count:,}")
            e.add_field(name="Total Users", value=f"{total_users:,}")
            e.add_field(name="Shards", value=str(shard_count))
            e.add_field(name="API Latency", value=f"{latency}ms")
            e.add_field(name="Memory", value=memory)
            e.add_field(name="Uptime", value=uptime)

            await interaction.followup.send(embed=e)
        except Exception as e:
            print(f"[ERROR] Botinfo command failed: {e}")
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(BotInfo(bot))
