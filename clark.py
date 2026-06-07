import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv
import aiomysql
import os
import sys

# --- Initialization ---
load_dotenv()

class MyBot(commands.AutoShardedBot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.invites = True
        intents.voice_states = True
        intents.bans = True
        intents.auto_moderation = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            chunk_guilds_at_startup=False
        )
        self.db_pool = None

    async def setup_hook(self):
        # 1. Connect to Database first
        try:
            self.db_pool = await aiomysql.create_pool(
                host=os.getenv('MYSQL_HOST'),
                user=os.getenv('MYSQL_USER'),
                password=os.getenv('MYSQL_PASSWORD'),
                db=os.getenv('MYSQL_DATABASE'),
                port=int(os.getenv('MYSQL_PORT', 3306)),
                minsize=5, 
                maxsize=20 
            )
            print("[SUCCESS] Database connection pool created.")
        except Exception as e:
            print(f"[ERROR] Could not connect to DB: {e}")
            await self.close()
            return

        # 2. Load Cogs
        if os.path.exists('./cogs'):
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py') and filename != '__init__.py':
                    try:
                        await self.load_extension(f'cogs.{filename[:-3]}')
                        print(f'[COGS] Loaded: {filename}')
                    except Exception as e:
                        print(f'[FAIL] Failed to load {filename}: {e}')

        # 3. Sync Commands Globally
        # This sends your commands to Discord so they appear in the slash command menu
        try:
            print("[SYNC] Attempting to sync global commands...")
            synced = await self.tree.sync()
            print(f"[SUCCESS] Synced {len(synced)} global commands.")
        except Exception as e:
            print(f"[ERROR] Command sync failed: {e}")

    async def close(self):
        if self.db_pool:
            self.db_pool.close()
            await self.db_pool.wait_closed()
            print("[POOL] Database pool closed.")
        await super().close()

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("[ERROR] DISCORD_TOKEN not found in .env")
        return

    bot = MyBot()
    try:
        async with bot:
            await bot.start(token)
    except discord.errors.HTTPException as e:
        if e.status == 429:
            print("[CRITICAL] Rate limited (429). Wait 15 mins before restarting.")
        else:
            print(f"[ERROR] HTTP Error: {e}")
    except Exception as e:
        print(f"[ERROR] Fatal error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Manual shutdown initiated.")
