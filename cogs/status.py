import discord
from discord.ext import commands, tasks

class Description(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.update_status.start()
    
    @tasks.loop(minutes=120) 
    async def update_status(self):
        if self.bot.is_ready():
            total_users = sum(g.member_count or 0 for g in self.bot.guilds)
            activity = discord.Streaming(
                name=f"{total_users:,} users",
                url="https://www.youtube.com/@Kikodev_23"
            )
            await self.bot.change_presence(activity=activity)
            print(f"[Status Update] Status set to: Streaming {total_users:,} users")
        else:
            print("[Status Update] Bot is not ready, skipping status update.")

    @update_status.before_loop
    async def before_update_status(self):
        print("[Status Update] Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        print("[Status Update] Bot is ready. Loop starting.")

    def cog_unload(self):
        self.update_status.cancel()
        print("[Status Update] Cog unloaded, loop cancelled.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        print(f"[Guild Join] Added to server: {guild.name} (ID: {guild.id})")
        if self.update_status.is_running():
            self.update_status.restart()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        print(f"[Guild Remove] Removed from server: {guild.name} (ID: {guild.id})")
        if self.update_status.is_running():
            self.update_status.restart()

async def setup(bot):
    await bot.add_cog(Description(bot))