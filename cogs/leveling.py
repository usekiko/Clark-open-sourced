import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import random
import math
import datetime
import time
import traceback

class Colors:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'

# Keep for backward compatibility with existing code

class ResponseView(ui.LayoutView):
    def __init__(self, container: ui.Container, ephemeral: bool = False):
        super().__init__(timeout=None if not ephemeral else 300)
        self.add_item(container)

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.EMOJIS = {
            'SUCCESS':  '<:goodconnection:1454536158208983051> ›  ',
            'ERROR':    '<:lowconnection:1454536160545214527> ›  ',
            'INFO':     '<:mediumconnection:1454536162189512734> ›  ',
            'LEVELUP':  '<:goodconnection:1454536158208983051> ›  ',
            'TROPHY':   '🏆'
        }
        self.response_thumbnail_accessory = None
        self._cd = commands.CooldownMapping.from_cooldown(1, 60.0, commands.BucketType.member)
        self._settings_cache = {}
        self._cache_hits = 0
        self._cache_misses = 0

    async def setup_database(self):
        if self.bot.user:
            self.response_thumbnail_accessory = ui.Thumbnail(media=self.bot.user.display_avatar.url)

        try:
            if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
                print(f"{Colors.RED}[ERROR] Database pool not set.{Colors.RESET}")
                return


            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS levels (
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        xp BIGINT DEFAULT 0,
                        level INT DEFAULT 0,
                        last_msg BIGINT DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id)
                    )
                """)
                
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS leveling_settings (
                        guild_id BIGINT PRIMARY KEY,
                        enabled BOOLEAN DEFAULT FALSE,
                        xp_min INT DEFAULT 15,
                        xp_max INT DEFAULT 25,
                        cooldown INT DEFAULT 60,
                        channel_blacklist JSONB NULL,
                        role_blacklist JSONB NULL,
                        levelup_channel_id BIGINT DEFAULT NULL
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS level_rewards (
                        guild_id BIGINT NOT NULL,
                        level INT NOT NULL,
                        role_id BIGINT NOT NULL,
                        PRIMARY KEY (guild_id, level)
                    )
                """)
            print(f"{Colors.GREEN}[SUCCESS] cogs.leveling.py initialized (Clean UI).{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to init leveling tables: {e}{Colors.RESET}")

    def _create_response_container(self, title: str, description: str, status: str = 'SUCCESS') -> ResponseView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        container = ui.Container(header, sep, body)
        return ResponseView(container)

    def _calculate_level_xp(self, level: int) -> int:
        return 50 * (level ** 2) + (50 * level)

    def _get_level_from_xp(self, xp: int) -> int:
        if xp <= 0: return 0
        level = int((-50 + math.sqrt(50**2 - 4 * 50 * (-xp))) / (2 * 50))
        return level

    def _make_progress_bar(self, current: int, total: int, length: int = 15) -> str:
        percent = min(1.0, current / total) if total > 0 else 0
        filled = int(length * percent)
        bar = '<:gained_xp:1454540588190924960>' * filled + '<:remaining_xp:1454540589541494956>' * (length - filled)
        return f"{bar} {int(percent * 100)}%"

    async def _get_settings(self, guild_id: int) -> dict:
        """Fetch settings from cache or database with proper TTL caching."""
        # Check cache first
        cached = self._settings_cache.get(guild_id)
        if cached:
            self._cache_hits += 1
            return cached
        
        self._cache_misses += 1
        
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool:
            return None
            
        try:
            async with self.bot.db_pool.acquire() as conn:
                # Ensure row exists
                await conn.execute("""
                    INSERT INTO leveling_settings (guild_id, enabled) 
                    VALUES ($1, FALSE) 
                    ON CONFLICT (guild_id) DO NOTHING
                """, guild_id)
                
                # Fetch fresh data
                settings = await conn.fetchrow("SELECT * FROM leveling_settings WHERE guild_id = $1", guild_id)
                if settings:
                    settings_dict = dict(settings)
                    self._settings_cache[guild_id] = settings_dict
                    return settings_dict
        except Exception as e:
            print(f"{Colors.RED}[ERROR] [Leveling] Failed to fetch settings for guild {guild_id}: {e}{Colors.RESET}")
            return None
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        settings = await self._get_settings(message.guild.id)
        if not settings or not settings['enabled']:
            return

        bucket = self._cd.get_bucket(message)
        retry_after = bucket.update_rate_limit()
        if retry_after: return

        if settings['channel_blacklist']:
            ignored = json.loads(settings['channel_blacklist'])
            if message.channel.id in ignored: return
        
        if settings['role_blacklist']:
            ignored_roles = json.loads(settings['role_blacklist'])
            if any(r.id in ignored_roles for r in message.author.roles): return

        if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
            try:
                async with self.bot.db_pool.acquire() as conn:
                    xp_gain = random.randint(settings['xp_min'], settings['xp_max'])
                    now_ts = int(time.time())

                    await conn.execute("""
                        INSERT INTO levels (guild_id, user_id, xp, level, last_msg) 
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (guild_id, user_id) DO UPDATE SET xp = levels.xp + $6, last_msg = $7
                    """, message.guild.id, message.author.id, xp_gain, 0, now_ts, xp_gain, now_ts)
                    
                    user_data = await conn.fetchrow("SELECT xp, level FROM levels WHERE guild_id = $1 AND user_id = $2", message.guild.id, message.author.id)
                    
                    actual_level = self._get_level_from_xp(user_data['xp'])

                    if actual_level > user_data['level']:
                        await conn.execute("UPDATE levels SET level = $1 WHERE guild_id = $2 AND user_id = $3", actual_level, message.guild.id, message.author.id)
                        
                        target_id = settings['levelup_channel_id']
                        target_channel = message.guild.get_channel(target_id) if target_id else message.channel

                        if target_channel:
                            desc = f"Congratulations {message.author.mention}! You've reached Level {actual_level}!"
                            view = self._create_response_container("Leveled Up!", desc, "LEVELUP")
                            try: await target_channel.send(view=view)
                            except discord.Forbidden: pass

                        reward = await conn.fetchrow("SELECT role_id FROM level_rewards WHERE guild_id = $1 AND level = $2", message.guild.id, actual_level)
                        if reward:
                            role = message.guild.get_role(reward['role_id'])
                            if role:
                                try: await message.author.add_roles(role)
                                except discord.Forbidden: pass
            except Exception as e:
                print(f"{Colors.RED}[ERROR] Leveling on_message: {e}{Colors.RESET}")

    level_group = app_commands.Group(name="level", description="Leveling system commands.")

    @level_group.command(name="rank", description="Check your or another user's rank card.")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        await interaction.response.defer()
        
        settings = await self._get_settings(interaction.guild.id)

        if not settings or not settings['enabled']:
            desc = "The leveling system is currently disabled in this server."
            view = self._create_response_container("System Disabled", desc, "INFO")
            return await interaction.followup.send(view=view)

        async with self.bot.db_pool.acquire() as conn:
            data = await conn.fetchrow("SELECT xp, level FROM levels WHERE guild_id = $1 AND user_id = $2", interaction.guild.id, member.id)
            
            rank_str = "Unranked"
            if data:
                r_data = await conn.fetchrow("SELECT COUNT(*) + 1 as rank FROM levels WHERE guild_id = $1 AND xp > $2", interaction.guild.id, data['xp'])
                if r_data: rank_str = f"#{r_data['rank']}"
            
        xp = data['xp'] if data else 0
        level = self._get_level_from_xp(xp)
        cur_start = self._calculate_level_xp(level)
        nxt_req = self._calculate_level_xp(level + 1)
        progress_bar = self._make_progress_bar(xp - cur_start, nxt_req - cur_start)
        
        desc = (
            f"Rank: {rank_str}\n"
            f"Level: {level}\n"
            f"Total XP: {xp:,}\n\n"
            f"{progress_bar}\n"
            f"{xp - cur_start:,} / {nxt_req - cur_start:,} XP to Level {level + 1}"
        )
        
        view = self._create_response_container(f"{member.display_name}'s Progress", desc, "SUCCESS")
        await interaction.followup.send(view=view)

    @level_group.command(name="leaderboard", description="Displays the top 10 users.")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        settings = await self._get_settings(interaction.guild.id)

        if not settings or not settings['enabled']:
            desc = "The leveling system is currently disabled in this server."
            view = self._create_response_container("System Disabled", desc, "INFO")
            return await interaction.followup.send(view=view)

        async with self.bot.db_pool.acquire() as conn:
            top_users = await conn.fetch("SELECT user_id, xp FROM levels WHERE guild_id = $1 ORDER BY xp DESC LIMIT 10", interaction.guild.id)

        if not top_users:
            desc = "No one has earned experience points yet."
            view = self._create_response_container("Leaderboard Empty", desc, "INFO")
            return await interaction.followup.send(view=view)

        lines = ["**Current Standings**"]
        for idx, u in enumerate(top_users, 1):
            user_id = u['user_id']
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"Unknown ({user_id})"

            medal = '🥇' if idx==1 else '🥈' if idx==2 else '🥉' if idx==3 else f'#{idx}'
            lvl = self._get_level_from_xp(u['xp'])
            lines.append(f"{medal} {name} — Lvl {lvl} ({u['xp']:,} XP)")
        
        desc = "\n".join(lines)
        view = self._create_response_container("Competitive Leaderboard", desc, "TROPHY")
        await interaction.followup.send(view=view)

    @level_group.command(name="config", description="Configure leveling settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config(self, interaction: discord.Interaction, enabled: bool = None, levelup_channel: discord.TextChannel = None, xp_min: int = None, xp_max: int = None):
        await interaction.response.defer(ephemeral=True)
        
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("INSERT INTO leveling_settings (guild_id, enabled) VALUES ($1, FALSE) ON CONFLICT (guild_id) DO NOTHING", interaction.guild.id)
            updates, params = [], []
            if enabled is not None: updates.append(f"enabled = ${len(params)+1}"); params.append(enabled)
            if levelup_channel: updates.append(f"levelup_channel_id = ${len(params)+1}"); params.append(levelup_channel.id)
            if xp_min: updates.append(f"xp_min = ${len(params)+1}"); params.append(xp_min)
            if xp_max: updates.append(f"xp_max = ${len(params)+1}"); params.append(xp_max)
            if updates:
                params.append(interaction.guild.id)
                await conn.execute(f"UPDATE leveling_settings SET {', '.join(updates)} WHERE guild_id = ${len(params)}", *params)
            
            new_settings = await conn.fetchrow("SELECT * FROM leveling_settings WHERE guild_id = $1", interaction.guild.id)
            if new_settings:
                self._settings_cache[interaction.guild.id] = dict(new_settings)

        desc = "Settings updated successfully."
        view = self._create_response_container("Configuration Updated", desc, "SUCCESS")
        await interaction.followup.send(view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))