import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import re
import os
from dotenv import load_dotenv

load_dotenv()

class ReminderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_reminders.start()

    async def cog_load(self):
        await self.init_db()

    def cog_unload(self):
        self.check_reminders.cancel()

    async def init_db(self):
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool:
            return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders_set (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    reminder_text TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL
                )
            """)

    def parse_time(self, time_str):
        regex = r"(\d+)([wdhms])"
        matches = re.findall(regex, time_str.lower())
        if not matches:
            return None
        total_seconds = 0
        units = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
        for amount, unit in matches:
            total_seconds += int(amount) * units[unit]
        return total_seconds

    @app_commands.command(name="reminder")
    @app_commands.describe(time="Format: 1d12h", message="What to remind", channel="Where to send")
    async def reminder(self, interaction: discord.Interaction, time: str, message: str, channel: discord.TextChannel):
        seconds = self.parse_time(time)
        if seconds is None:
            await interaction.response.send_message("Invalid time format.", ephemeral=True)
            return
        expiration = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
        expiration = expiration.replace(tzinfo=None)
        
        if not self.bot.db_pool:
            await interaction.response.send_message("Database connection error.", ephemeral=True)
            return
            
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO reminders_set (user_id, channel_id, reminder_text, expires_at) VALUES ($1, $2, $3, $4)",
                interaction.user.id, channel.id, message, expiration
            )
        await interaction.response.send_message(f"Reminder set for {time} in {channel.mention}.")

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        now = datetime.datetime.utcnow()
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool:
            return
        async with self.bot.db_pool.acquire() as conn:
            expired = await conn.fetch("SELECT * FROM reminders_set WHERE expires_at <= $1", now)
            if not expired:
                return
            for row in expired:
                target_channel = self.bot.get_channel(row["channel_id"])
                if target_channel:
                    user_mention = f"<@{row['user_id']}>"
                    try:
                        await target_channel.send(f"Reminder for {user_mention}: {row['reminder_text']}")
                    except discord.Forbidden:
                        pass
                await conn.execute("DELETE FROM reminders_set WHERE id = $1", row["id"])

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(ReminderCog(bot))
