import discord
from discord.ext import commands
from discord import app_commands, ui
from discord.ext import tasks
import random
import math
import time

from utils.colors import Colors
from utils.views import StandardView

# Cache TTL
_CACHE_TTL = 300  # 5 minutes


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._settings_cache: dict[int, tuple[dict, float]] = {}  # guild_id -> (settings, expiry)
        # XP write buffer: (guild_id, user_id) -> xp_to_add
        # Flushed every 30s to avoid a DB write on every single message
        self._xp_buffer: dict[tuple[int, int], int] = {}
        self._cd = commands.CooldownMapping.from_cooldown(1, 60.0, commands.BucketType.member)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()
        if not self._flush_xp_buffer.is_running():
            self._flush_xp_buffer.start()

    def cog_unload(self):
        self._flush_xp_buffer.cancel()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    async def setup_database(self):
        if self.bot.user:
            pass  # avatar available if needed later

        try:
            if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
                print(f"{Colors.RED}[ERROR] Database pool not set.{Colors.RESET}")
                return

            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS levels (
                        guild_id BIGINT NOT NULL,
                        user_id  BIGINT NOT NULL,
                        xp       BIGINT DEFAULT 0,
                        level    INT DEFAULT 0,
                        last_msg BIGINT DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id)
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS leveling_settings (
                        guild_id           BIGINT PRIMARY KEY,
                        enabled            BOOLEAN DEFAULT FALSE,
                        xp_min             INT DEFAULT 15,
                        xp_max             INT DEFAULT 25,
                        cooldown           INT DEFAULT 60,
                        channel_blacklist  JSONB NULL,
                        role_blacklist     JSONB NULL,
                        levelup_channel_id BIGINT DEFAULT NULL
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS level_rewards (
                        guild_id BIGINT NOT NULL,
                        level    INT NOT NULL,
                        role_id  BIGINT NOT NULL,
                        PRIMARY KEY (guild_id, level)
                    )
                """)
            print(f"{Colors.GREEN}[SUCCESS] cogs.leveling.py initialized (Clean UI).{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to init leveling tables: {e}{Colors.RESET}")

    # ------------------------------------------------------------------
    # XP buffer flush (runs every 30 seconds)
    # ------------------------------------------------------------------

    @tasks.loop(seconds=30)
    async def _flush_xp_buffer(self):
        if not self._xp_buffer:
            return

        # Snapshot and clear the buffer atomically
        buffer, self._xp_buffer = self._xp_buffer, {}

        try:
            async with self.bot.db_pool.acquire() as conn:
                async with conn.transaction():
                    for (guild_id, user_id), xp_gain in buffer.items():
                        now_ts = int(time.time())
                        await conn.execute("""
                            INSERT INTO levels (guild_id, user_id, xp, level, last_msg)
                            VALUES ($1, $2, $3, 0, $4)
                            ON CONFLICT (guild_id, user_id) DO UPDATE
                                SET xp = levels.xp + $5, last_msg = $6
                        """, guild_id, user_id, xp_gain, now_ts, xp_gain, now_ts)

                        user_data = await conn.fetchrow(
                            "SELECT xp, level FROM levels WHERE guild_id = $1 AND user_id = $2",
                            guild_id, user_id
                        )
                        if not user_data:
                            continue

                        actual_level = self._get_level_from_xp(user_data['xp'])
                        if actual_level > user_data['level']:
                            await conn.execute(
                                "UPDATE levels SET level = $1 WHERE guild_id = $2 AND user_id = $3",
                                actual_level, guild_id, user_id
                            )

                            # Send level-up message
                            settings = await self._get_settings(guild_id)
                            if settings:
                                guild = self.bot.get_guild(guild_id)
                                if guild:
                                    member = guild.get_member(user_id)
                                    target_id = settings.get('levelup_channel_id')
                                    target_ch  = guild.get_channel(target_id) if target_id else None

                                    if member and target_ch:
                                        desc = f"Congratulations {member.mention}! You've reached Level {actual_level}!"
                                        view = self._view("Leveled Up!", desc, member.display_avatar.url)
                                        try:
                                            await target_ch.send(view=view)
                                        except discord.Forbidden:
                                            pass

                            # Assign role reward
                            reward = await conn.fetchrow(
                                "SELECT role_id FROM level_rewards WHERE guild_id = $1 AND level = $2",
                                guild_id, user_id
                            )
                            if reward:
                                guild = self.bot.get_guild(guild_id)
                                if guild:
                                    member = guild.get_member(user_id)
                                    role   = guild.get_role(reward['role_id'])
                                    if member and role:
                                        try:
                                            await member.add_roles(role)
                                        except discord.Forbidden:
                                            pass
        except Exception as e:
            print(f"{Colors.RED}[ERROR] XP flush failed: {e}{Colors.RESET}")
            # Merge failed entries back into the buffer
            for key, val in buffer.items():
                self._xp_buffer[key] = self._xp_buffer.get(key, 0) + val

    # ------------------------------------------------------------------
    # Settings cache (TTL-aware)
    # ------------------------------------------------------------------

    async def _get_settings(self, guild_id: int) -> dict | None:
        cached, expiry = self._settings_cache.get(guild_id, (None, 0))
        if cached and time.monotonic() < expiry:
            return cached

        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool:
            return None

        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO leveling_settings (guild_id, enabled)
                    VALUES ($1, FALSE)
                    ON CONFLICT (guild_id) DO NOTHING
                """, guild_id)
                settings = await conn.fetchrow(
                    "SELECT * FROM leveling_settings WHERE guild_id = $1", guild_id
                )
                if settings:
                    data = dict(settings)
                    self._settings_cache[guild_id] = (data, time.monotonic() + _CACHE_TTL)
                    return data
        except Exception as e:
            print(f"{Colors.RED}[ERROR] [Leveling] Failed to fetch settings for guild {guild_id}: {e}{Colors.RESET}")
        return None

    # ------------------------------------------------------------------
    # Math helpers
    # ------------------------------------------------------------------

    def _calculate_level_xp(self, level: int) -> int:
        return 50 * (level ** 2) + (50 * level)

    def _get_level_from_xp(self, xp: int) -> int:
        if xp <= 0:
            return 0
        return int((-50 + math.sqrt(50 ** 2 - 4 * 50 * (-xp))) / (2 * 50))

    def _make_progress_bar(self, current: int, total: int, length: int = 15) -> str:
        percent = min(1.0, current / total) if total > 0 else 0
        filled  = int(length * percent)
        bar     = '<:gained_xp:1454540588190924960>' * filled + '<:remaining_xp:1454540589541494956>' * (length - filled)
        return f"{bar} {int(percent * 100)}%"

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _view(title: str, description: str, avatar_url: str = None) -> StandardView:
        header = ui.TextDisplay(f"**{title}**")
        sep    = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body   = ui.TextDisplay(description)

        if avatar_url:
            thumbnail = ui.Thumbnail(media=avatar_url)
            section   = ui.Section(header, body, accessory=thumbnail)
            container = ui.Container(section)
        else:
            container = ui.Container(header, sep, body)

        return StandardView(container)

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        settings = await self._get_settings(message.guild.id)
        if not settings or not settings['enabled']:
            return

        bucket      = self._cd.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            return

        # asyncpg already returns JSONB as Python objects — no json.loads() needed
        channel_bl = settings.get('channel_blacklist') or []
        if message.channel.id in channel_bl:
            return

        role_bl = settings.get('role_blacklist') or []
        if role_bl and any(r.id in role_bl for r in message.author.roles):
            return

        xp_gain = random.randint(settings['xp_min'], settings['xp_max'])
        key = (message.guild.id, message.author.id)
        self._xp_buffer[key] = self._xp_buffer.get(key, 0) + xp_gain

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    level_group = app_commands.Group(name="level", description="Leveling system commands.")

    @level_group.command(name="rank", description="Check your or another user's rank card.")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        await interaction.response.defer()

        settings = await self._get_settings(interaction.guild.id)
        if not settings or not settings['enabled']:
            view = self._view("System Disabled", "The leveling system is currently disabled in this server.")
            return await interaction.followup.send(view=view)

        async with self.bot.db_pool.acquire() as conn:
            data = await conn.fetchrow(
                "SELECT xp, level FROM levels WHERE guild_id = $1 AND user_id = $2",
                interaction.guild.id, member.id
            )
            rank_str = "Unranked"
            if data:
                r_data = await conn.fetchrow(
                    "SELECT COUNT(*) + 1 AS rank FROM levels WHERE guild_id = $1 AND xp > $2",
                    interaction.guild.id, data['xp']
                )
                if r_data:
                    rank_str = f"#{r_data['rank']}"

        xp       = data['xp'] if data else 0
        level    = self._get_level_from_xp(xp)
        cur_start = self._calculate_level_xp(level)
        nxt_req   = self._calculate_level_xp(level + 1)
        bar       = self._make_progress_bar(xp - cur_start, nxt_req - cur_start)

        desc = (
            f"Rank: {rank_str}\n"
            f"Level: {level}\n"
            f"Total XP: {xp:,}\n\n"
            f"{bar}\n"
            f"{xp - cur_start:,} / {nxt_req - cur_start:,} XP to Level {level + 1}"
        )

        # Use Section + Thumbnail (embed_like.py pattern)
        view = self._view(f"{member.display_name}'s Progress", desc, member.display_avatar.url)
        await interaction.followup.send(view=view)

    @level_group.command(name="leaderboard", description="Displays the top 10 users.")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()

        settings = await self._get_settings(interaction.guild.id)
        if not settings or not settings['enabled']:
            view = self._view("System Disabled", "The leveling system is currently disabled in this server.")
            return await interaction.followup.send(view=view)

        async with self.bot.db_pool.acquire() as conn:
            top_users = await conn.fetch(
                "SELECT user_id, xp FROM levels WHERE guild_id = $1 ORDER BY xp DESC LIMIT 10",
                interaction.guild.id
            )

        if not top_users:
            view = self._view("Leaderboard Empty", "No one has earned experience points yet.")
            return await interaction.followup.send(view=view)

        lines = ["**Current Standings**"]
        for idx, u in enumerate(top_users, 1):
            m    = interaction.guild.get_member(u['user_id'])
            name = m.display_name if m else f"Unknown ({u['user_id']})"
            medal = '🥇' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else f'#{idx}'
            lvl   = self._get_level_from_xp(u['xp'])
            lines.append(f"{medal} {name} — Lvl {lvl} ({u['xp']:,} XP)")

        view = self._view("Competitive Leaderboard", "\n".join(lines))
        await interaction.followup.send(view=view)

    @level_group.command(name="config", description="Configure leveling settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config(
        self, interaction: discord.Interaction,
        enabled: bool = None,
        levelup_channel: discord.TextChannel = None,
        xp_min: int = None,
        xp_max: int = None,
    ):
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO leveling_settings (guild_id, enabled) VALUES ($1, FALSE) ON CONFLICT DO NOTHING",
                interaction.guild.id
            )
            updates: list[str] = []
            params: list       = []
            if enabled is not None:
                updates.append(f"enabled = ${len(params)+1}")
                params.append(enabled)
            if levelup_channel:
                updates.append(f"levelup_channel_id = ${len(params)+1}")
                params.append(levelup_channel.id)
            if xp_min is not None:
                updates.append(f"xp_min = ${len(params)+1}")
                params.append(xp_min)
            if xp_max is not None:
                updates.append(f"xp_max = ${len(params)+1}")
                params.append(xp_max)
            if updates:
                params.append(interaction.guild.id)
                await conn.execute(
                    f"UPDATE leveling_settings SET {', '.join(updates)} WHERE guild_id = ${len(params)}",
                    *params
                )
            new_settings = await conn.fetchrow(
                "SELECT * FROM leveling_settings WHERE guild_id = $1", interaction.guild.id
            )
            if new_settings:
                self._settings_cache[interaction.guild.id] = (dict(new_settings), time.monotonic() + _CACHE_TTL)

        view = self._view("Configuration Updated", "Settings updated successfully.")
        await interaction.followup.send(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))