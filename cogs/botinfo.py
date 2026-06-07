import discord
from discord.ext import commands
from discord import app_commands, ui
import time
import os

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
            
            header = ui.TextDisplay("**Clark information**")
            sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
            subtitle = ui.TextDisplay("**Global bot statistics and performance metrics**")
            
            dev_section = ui.TextDisplay(
                f"**Developer**\n"
                f"> [usekiko](https://usekiko.com)"
            )
            
            server_section = ui.TextDisplay(
                f"**Server Statistics**\n"
                f"> Servers: {server_count:,}\n"
                f"> Total Users: {total_users:,}"
            )
            
            shard_section = ui.TextDisplay(
                f"**Shard Information**\n"
                f"> Shards: {shard_count}\n"
                f"> API Latency: {latency}ms"
            )
            
            perf_section = ui.TextDisplay(
                f"**Performance**\n"
                f"> Memory Usage: {memory}\n"
                f"> Uptime: {uptime}"
            )
            
            container = ui.Container(
                header,
                sep,
                subtitle,
                dev_section,
                server_section,
                shard_section,
                perf_section
            )
            
            view = ui.LayoutView()
            view.add_item(container)
            
            await interaction.followup.send(view=view)
        except Exception as e:
            print(f"[ERROR] Botinfo command failed: {e}")
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(BotInfo(bot))
