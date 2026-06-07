import discord
from discord.ext import commands
from discord import app_commands, ui
import aiomysql
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

    async def setup_database(self):
        if self.bot.user:
            self.response_thumbnail_accessory = ui.Thumbnail(media=self.bot.user.display_avatar.url)

        try:
            if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
                print(f"{Colors.RED}[ERROR] Database pool not set.{Colors.RESET}")
                return


            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS levels (
                            guild_id BIGINT NOT NULL,
                            user_id BIGINT NOT NULL,
                            xp BIGINT DEFAULT 0,
                            level INT DEFAULT 0,
                            last_msg BIGINT DEFAULT 0,
                            PRIMARY KEY (guild_id, user_id)
                        )
                    """)
                    
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS leveling_settings (
                            guild_id BIGINT PRIMARY KEY,
                            enabled BOOLEAN DEFAULT FALSE,
                            xp_min INT DEFAULT 15,
                            xp_max INT DEFAULT 25,
                            cooldown INT DEFAULT 60,
                            channel_blacklist JSON NULL,
                            role_blacklist JSON NULL,
                            levelup_channel_id BIGINT DEFAULT NULL
                        )
                    """)

                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS level_rewards (
                            guild_id BIGINT NOT NULL,
                            level INT NOT NULL,
                            role_id BIGINT NOT NULL,
                            PRIMARY KEY (guild_id, level)
                        )
                    """)
                    await conn.commit()
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
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Ensure row exists
                    await cursor.execute("""
                        INSERT INTO leveling_settings (guild_id, enabled) 
                        VALUES (%s, 0) 
                        ON DUPLICATE KEY UPDATE guild_id=guild_id
                    """, (guild_id,))
                    await conn.commit()
                    # Fetch fresh data
                    await cursor.execute("SELECT * FROM leveling_settings WHERE guild_id = %s", (guild_id,))
                    settings = await cursor.fetchone()
                    if settings:
                        self._settings_cache[guild_id] = settings
                    return settings
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
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        xp_gain = random.randint(settings['xp_min'], settings['xp_max'])
                        now_ts = int(time.time())

                        await cursor.execute("""
                            INSERT INTO levels (guild_id, user_id, xp, level, last_msg) 
                            VALUES (%s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE xp = xp + %s, last_msg = %s
                        """, (message.guild.id, message.author.id, xp_gain, 0, now_ts, xp_gain, now_ts))
                        
                        await cursor.execute("SELECT xp, level FROM levels WHERE guild_id = %s AND user_id = %s", (message.guild.id, message.author.id))
                        user_data = await cursor.fetchone()
                        
                        actual_level = self._get_level_from_xp(user_data['xp'])

                        if actual_level > user_data['level']:
                            await cursor.execute("UPDATE levels SET level = %s WHERE guild_id = %s AND user_id = %s", (actual_level, message.guild.id, message.author.id))
                            await conn.commit()
                            
                            target_id = settings['levelup_channel_id']
                            target_channel = message.guild.get_channel(target_id) if target_id else message.channel

                            if target_channel:
                                desc = f"> **Congratulations {message.author.mention}! You've reached Level {actual_level}!**"
                                view = self._create_response_container("Leveled Up!", desc, "LEVELUP")
                                try: await target_channel.send(view=view)
                                except discord.Forbidden: pass

                            await cursor.execute("SELECT role_id FROM level_rewards WHERE guild_id = %s AND level = %s", (message.guild.id, actual_level))
                            reward = await cursor.fetchone()
                            if reward:
                                role = message.guild.get_role(reward['role_id'])
                                if role:
                                    try: await message.author.add_roles(role)
                                    except discord.Forbidden: pass
                        else:
                            await conn.commit()
            except Exception as e:
                print(f"{Colors.RED}[ERROR] Leveling on_message: {e}{Colors.RESET}")

    level_group = app_commands.Group(name="level", description="Leveling system commands.")

    @level_group.command(name="rank", description="Check your or another user's rank card.")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        await interaction.response.defer()
        


        settings = await self._get_settings(interaction.guild.id)

        if not settings or not settings['enabled']:
            desc = "> **The leveling system is currently disabled in this server.**"
            view = self._create_response_container("System Disabled", desc, "INFO")
            return await interaction.followup.send(view=view)

        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT xp, level FROM levels WHERE guild_id = %s AND user_id = %s", (interaction.guild.id, member.id))
                data = await cursor.fetchone()
                
                rank_str = "Unranked"
                if data:
                    await cursor.execute("SELECT COUNT(*) + 1 as `rank` FROM levels WHERE guild_id = %s AND xp > %s", (interaction.guild.id, data['xp']))
                    r_data = await cursor.fetchone()
                    if r_data: rank_str = f"#{r_data['rank']}"
            
        xp = data['xp'] if data else 0
        level = self._get_level_from_xp(xp)
        cur_start = self._calculate_level_xp(level)
        nxt_req = self._calculate_level_xp(level + 1)
        progress_bar = self._make_progress_bar(xp - cur_start, nxt_req - cur_start)
        
        desc = (
            f"**Member Statistics**\n"
            f"> **Rank:** {rank_str}\n"
            f"> **Level:** {level}\n"
            f"> **Total Experience:** {xp:,} XP\n\n"
            f"**Level Progress**\n"
            f"> {progress_bar}\n"
            f"**{xp - cur_start:,} / {nxt_req - cur_start:,} XP to Level {level + 1}**"
        )
        
        view = self._create_response_container(f"{member.display_name}'s Progress", desc, "SUCCESS")
        await interaction.followup.send(view=view)

    @level_group.command(name="leaderboard", description="Displays the top 10 users.")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        

        
        settings = await self._get_settings(interaction.guild.id)

        if not settings or not settings['enabled']:
            desc = "> **The leveling system is currently disabled in this server.**"
            view = self._create_response_container("System Disabled", desc, "INFO")
            return await interaction.followup.send(view=view)

        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT user_id, xp FROM levels WHERE guild_id = %s ORDER BY xp DESC LIMIT 10", (interaction.guild.id,))
                top_users = await cursor.fetchall()

        if not top_users:
            desc = "> **No one has earned experience points yet.**"
            view = self._create_response_container("Leaderboard Empty", desc, "INFO")
            return await interaction.followup.send(view=view)

        lines = ["**Current Standings**"]
        for idx, u in enumerate(top_users, 1):
            user_id = u['user_id']
            member = interaction.guild.get_member(user_id)
            name = member.display_name if member else f"Unknown ({user_id})"

            medal = '🥇' if idx==1 else '🥈' if idx==2 else '🥉' if idx==3 else f'#{idx}'
            lvl = self._get_level_from_xp(u['xp'])
            lines.append(f"> **{medal}** — {name} • Lvl {lvl} (`{u['xp']:,} XP`)")
        
        desc = "\n".join(lines)
        view = self._create_response_container("Competitive Leaderboard", desc, "TROPHY")
        await interaction.followup.send(view=view)

    @level_group.command(name="config", description="Configure leveling settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config(self, interaction: discord.Interaction, enabled: bool = None, levelup_channel: discord.TextChannel = None, xp_min: int = None, xp_max: int = None):
        await interaction.response.defer(ephemeral=True)
        
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("INSERT INTO leveling_settings (guild_id, enabled) VALUES (%s, 0) ON DUPLICATE KEY UPDATE guild_id=guild_id", (interaction.guild.id,))
                updates, params = [], []
                if enabled is not None: updates.append("enabled = %s"); params.append(int(enabled))
                if levelup_channel: updates.append("levelup_channel_id = %s"); params.append(levelup_channel.id)
                if xp_min: updates.append("xp_min = %s"); params.append(xp_min)
                if xp_max: updates.append("xp_max = %s"); params.append(xp_max)
                if updates:
                    params.append(interaction.guild.id)
                    await cursor.execute(f"UPDATE leveling_settings SET {', '.join(updates)} WHERE guild_id = %s", tuple(params))
                    await conn.commit()
                await cursor.execute("SELECT * FROM leveling_settings WHERE guild_id = %s", (interaction.guild.id,))
                new_settings = await cursor.fetchone()
                self._settings_cache[interaction.guild.id] = new_settings

        desc = "> **Server leveling parameters successfully updated and cached.**"
        view = self._create_response_container("Configuration Updated", desc, "SUCCESS")
        await interaction.followup.send(view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))