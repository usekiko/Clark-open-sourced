import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import traceback
from dotenv import load_dotenv
import asyncpg
import json
import os
import sys


async def _init_connection(conn):
    """Make JSONB behave the way every cog already assumes it does.

    By default asyncpg hands JSON/JSONB back as a raw string and refuses to
    encode anything that isn't one. Three cogs were written against the opposite
    assumption — passing a Python list straight at a JSONB column and reading one
    back — so /log setup and /selfrole raised on every insert and silently saved
    nothing. Registering the codec here fixes all of them at once, and keeps the
    behaviour consistent for anything added later.
    """
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

# --- Initialization ---
load_dotenv()

print("[Clark] v1.0.0 starting up...")

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

    async def on_app_command_error(self, interaction: discord.Interaction, error):
        """Fallback handler for every slash command that doesn't define its own.

        A failed permission check raises before the callback body runs, so nothing
        has acknowledged the interaction yet. Without this the user just sees
        "application did not respond" and the log says nothing about why.
        """
        if isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
            body = f"You need the **{missing}** permission to use that."
        elif isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
            body = f"I'm missing the **{missing}** permission here."
        elif isinstance(error, app_commands.NoPrivateMessage):
            body = "That command only works inside a server."
        elif isinstance(error, app_commands.CommandOnCooldown):
            body = f"Slow down — try again in {error.retry_after:.0f}s."
        elif isinstance(error, app_commands.CheckFailure):
            body = "You can't use that command here."
        else:
            name = interaction.command.qualified_name if interaction.command else "unknown"
            print(f"[ERROR] /{name} failed: {type(error).__name__}: {error}")
            traceback.print_exception(type(error), error, error.__traceback__)
            body = "That command failed. The error has been logged."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(body, ephemeral=True)
            else:
                await interaction.response.send_message(body, ephemeral=True)
        except discord.HTTPException:
            pass

    async def setup_hook(self):
        # Cogs with their own cog_app_command_error still win; this catches the rest.
        self.tree.on_error = self.on_app_command_error

        # 1. Connect to Database first
        try:
            self.db_pool = await asyncpg.create_pool(
                host=os.getenv('PG_HOST', 'localhost'),
                user=os.getenv('PG_USER'),
                password=os.getenv('PG_PASSWORD'),
                database=os.getenv('PG_DATABASE'),
                port=int(os.getenv('PG_PORT', 5432)),
                min_size=5,
                max_size=20,
                init=_init_connection,
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
        try:
            print("[SYNC] Attempting to sync global commands...")
            synced = await self.tree.sync()
            print(f"[SUCCESS] Synced {len(synced)} global commands.")
        except Exception as e:
            print(f"[ERROR] Command sync failed: {e}")

    async def close(self):
        if self.db_pool:
            await self.db_pool.close()
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
