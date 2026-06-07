import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import io
import base64

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

class AnalyticsView(ui.LayoutView):
    def __init__(self, container: ui.Container):
        super().__init__(timeout=None)
        self.add_item(container)

class Analytics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_cache: Dict[int, List[datetime]] = {}  # channel_id -> list of message times
        self.voice_sessions: Dict[int, dict] = {}  # user_id -> {channel_id, joined_at}
        
    async def setup_database(self):
        await self.bot.wait_until_ready()
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool: return
        try:
            async with self.bot.db_pool.acquire() as conn:
                # Message activity by hour
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS message_activity (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        hour_bucket TIMESTAMP NOT NULL,
                        message_count INT DEFAULT 1,
                        UNIQUE (guild_id, channel_id, user_id, hour_bucket)
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_hour ON message_activity (guild_id, hour_bucket)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_channel ON message_activity (channel_id)")
                
                # Voice activity
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS voice_activity (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        joined_at TIMESTAMP NOT NULL,
                        left_at TIMESTAMP NULL,
                        duration_seconds INT DEFAULT 0
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild ON voice_activity (guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON voice_activity (user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_time ON voice_activity (joined_at)")
                
                # Member join/leave tracking
                # Adding ENUM in postgres is a bit more manual, using VARCHAR constraint instead for simplicity
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS member_events (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        event_type VARCHAR(10) CHECK (event_type IN ('join', 'leave')) NOT NULL,
                        event_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        account_age_days INT
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_date ON member_events (guild_id, event_date)")
                
                # Daily guild snapshots
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS guild_snapshots (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        snapshot_date DATE NOT NULL,
                        total_members INT,
                        online_members INT,
                        new_members INT DEFAULT 0,
                        left_members INT DEFAULT 0,
                        total_messages INT DEFAULT 0,
                        active_users INT DEFAULT 0,
                        UNIQUE (guild_id, snapshot_date)
                    )
                """)
                
                # Command usage stats
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS command_usage (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        command_name VARCHAR(50) NOT NULL,
                        user_id BIGINT NOT NULL,
                        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        success BOOLEAN DEFAULT TRUE
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_cmd ON command_usage (guild_id, command_name)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON command_usage (used_at)")
                
            print(f"{Colors.GREEN}[SUCCESS]      Analytics tables initialized.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Failed to initialize analytics tables: {e}{Colors.RESET}")

    def _create_container_view(self, title: str, description: str) -> AnalyticsView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        container = ui.Container(header, sep, body)
        return AnalyticsView(container)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        # Record message activity
        hour_bucket = datetime.now().replace(minute=0, second=0, microsecond=0)
        
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool: return
        async with self.bot.db_pool.acquire() as conn:
            # Try to update existing record
            await conn.execute("""
                INSERT INTO message_activity (guild_id, channel_id, user_id, hour_bucket, message_count)
                VALUES ($1, $2, $3, $4, 1)
                ON CONFLICT (guild_id, channel_id, user_id, hour_bucket) DO UPDATE SET message_count = message_activity.message_count + 1
            """, message.guild.id, message.channel.id, message.author.id, hour_bucket)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        
        now = datetime.now()
        
        # User joined a voice channel
        if after.channel and (not before.channel or before.channel.id != after.channel.id):
            self.voice_sessions[member.id] = {
                'guild_id': member.guild.id,
                'channel_id': after.channel.id,
                'joined_at': now
            }
        
        # User left a voice channel
        if before.channel and (not after.channel or before.channel.id != after.channel.id):
            if member.id in self.voice_sessions:
                session = self.voice_sessions[member.id]
                duration = int((now - session['joined_at']).total_seconds())
                
                if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
                    async with self.bot.db_pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO voice_activity (guild_id, channel_id, user_id, joined_at, left_at, duration_seconds)
                            VALUES ($1, $2, $3, $4, $5, $6)
                        """, session['guild_id'], session['channel_id'], member.id, session['joined_at'], now, duration)
                
                del self.voice_sessions[member.id]

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        
        account_age = (datetime.now() - member.created_at.replace(tzinfo=None)).days
        
        if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO member_events (guild_id, user_id, event_type, account_age_days)
                    VALUES ($1, $2, 'join', $3)
                """, member.guild.id, member.id, account_age)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        
        if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO member_events (guild_id, user_id, event_type)
                    VALUES ($1, $2, 'leave')
                """, member.guild.id, member.id)

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: app_commands.Command):
        if not interaction.guild:
            return
        
        if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO command_usage (guild_id, command_name, user_id, success)
                    VALUES ($1, $2, $3, TRUE)
                """, interaction.guild.id, command.name, interaction.user.id)

    @app_commands.command(name="analytics", description="View server analytics and statistics.")
    @app_commands.describe(
        metric="The type of analytics to view",
        days="Number of days to analyze (default: 7)"
    )
    @app_commands.choices(metric=[
        app_commands.Choice(name="Overview", value="overview"),
        app_commands.Choice(name="Messages", value="messages"),
        app_commands.Choice(name="Voice", value="voice"),
        app_commands.Choice(name="Members", value="members"),
        app_commands.Choice(name="Commands", value="commands"),
        app_commands.Choice(name="Heatmap", value="heatmap")
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def analytics(self, interaction: discord.Interaction, metric: str, days: int = 7):
        await interaction.response.defer()
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool:
            return await interaction.followup.send("Database not configured.", ephemeral=True)
        
        if days > 90:
            view = self._create_container_view("Error", "Maximum analysis period is 90 days.")
            return await interaction.followup.send(view=view, ephemeral=True)
        
        if metric == "overview":
            await self.show_overview(interaction, days)
        elif metric == "messages":
            await self.show_message_stats(interaction, days)
        elif metric == "voice":
            await self.show_voice_stats(interaction, days)
        elif metric == "members":
            await self.show_member_stats(interaction, days)
        elif metric == "commands":
            await self.show_command_stats(interaction, days)
        elif metric == "heatmap":
            await self.show_heatmap(interaction, days)

    async def show_overview(self, interaction: discord.Interaction, days: int):
        async with self.bot.db_pool.acquire() as conn:
            # Total messages
            res = await conn.fetchrow("""
                SELECT SUM(message_count) as total FROM message_activity
                WHERE guild_id = $1 AND hour_bucket >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
            total_messages = res['total'] or 0
            
            # Unique active users
            res = await conn.fetchrow("""
                SELECT COUNT(DISTINCT user_id) as unique_users FROM message_activity
                WHERE guild_id = $1 AND hour_bucket >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
            active_users = res['unique_users'] or 0
            
            # Voice minutes
            res = await conn.fetchrow("""
                SELECT SUM(duration_seconds) / 60 as total_minutes FROM voice_activity
                WHERE guild_id = $1 AND joined_at >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
            voice_minutes = res['total_minutes'] or 0
            
            # Joins/leaves
            member_stats = await conn.fetchrow("""
                SELECT 
                    SUM(CASE WHEN event_type = 'join' THEN 1 ELSE 0 END) as joins,
                    SUM(CASE WHEN event_type = 'leave' THEN 1 ELSE 0 END) as leaves
                FROM member_events
                WHERE guild_id = $1 AND event_date >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
            joins = member_stats['joins'] or 0
            leaves = member_stats['leaves'] or 0
            
            # Command usage
            res = await conn.fetchrow("""
                SELECT COUNT(*) as total FROM command_usage
                WHERE guild_id = $1 AND used_at >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
            commands_used = res['total'] or 0
        
        description = f"""📊 **Server Overview (Last {days} days)**

💬 **Messages:** {total_messages:,}
👥 **Active Users:** {active_users:,}
🔊 **Voice Minutes:** {voice_minutes:,.0f}

📈 **Member Growth:**
> Joined: {joins} | Left: {leaves} | Net: {joins - leaves:+d}

⚡ **Commands Used:** {commands_used:,}

📉 **Current Population:** {interaction.guild.member_count} members
"""
        
        view = self._create_container_view("Server Analytics", description)
        await interaction.followup.send(view=view)

    async def show_message_stats(self, interaction: discord.Interaction, days: int):
        async with self.bot.db_pool.acquire() as conn:
            # Top channels
            top_channels = await conn.fetch("""
                SELECT channel_id, SUM(message_count) as total
                FROM message_activity
                WHERE guild_id = $1 AND hour_bucket >= NOW() - interval '1 day' * $2
                GROUP BY channel_id
                ORDER BY total DESC
                LIMIT 10
            """, interaction.guild.id, days)
            
            # Top users
            top_users = await conn.fetch("""
                SELECT user_id, SUM(message_count) as total
                FROM message_activity
                WHERE guild_id = $1 AND hour_bucket >= NOW() - interval '1 day' * $2
                GROUP BY user_id
                ORDER BY total DESC
                LIMIT 10
            """, interaction.guild.id, days)
            
            # Daily breakdown
            daily = await conn.fetch("""
                SELECT DATE(hour_bucket) as date, SUM(message_count) as total
                FROM message_activity
                WHERE guild_id = $1 AND hour_bucket >= NOW() - interval '1 day' * $2
                GROUP BY DATE(hour_bucket)
                ORDER BY date DESC
            """, interaction.guild.id, days)
        
        description = f"💬 **Message Statistics (Last {days} days)**\n\n"
        
        description += "**Top Channels:**\n"
        for ch in top_channels[:5]:
            channel = interaction.guild.get_channel(ch['channel_id'])
            name = channel.name if channel else "Deleted Channel"
            description += f"#{name}: {ch['total']:,} msgs\n"
        
        description += "\n**Top Users:**\n"
        for u in top_users[:5]:
            user = interaction.guild.get_member(u['user_id'])
            name = user.display_name if user else f"User {u['user_id']}"
            description += f"{name}: {u['total']:,} msgs\n"
        
        description += "\n**Daily Activity:**\n"
        for d in daily[:7]:
            description += f"{d['date']}: {d['total']:,} msgs\n"
        
        view = self._create_container_view("Message Analytics", description)
        await interaction.followup.send(view=view)

    async def show_voice_stats(self, interaction: discord.Interaction, days: int):
        async with self.bot.db_pool.acquire() as conn:
            # Top voice channels
            top_channels = await conn.fetch("""
                SELECT channel_id, SUM(duration_seconds) / 60 as minutes, COUNT(DISTINCT user_id) as users
                FROM voice_activity
                WHERE guild_id = $1 AND joined_at >= NOW() - interval '1 day' * $2
                GROUP BY channel_id
                ORDER BY minutes DESC
                LIMIT 10
            """, interaction.guild.id, days)
            
            # Top voice users
            top_users = await conn.fetch("""
                SELECT user_id, SUM(duration_seconds) / 60 as minutes, COUNT(*) as sessions
                FROM voice_activity
                WHERE guild_id = $1 AND joined_at >= NOW() - interval '1 day' * $2
                GROUP BY user_id
                ORDER BY minutes DESC
                LIMIT 10
            """, interaction.guild.id, days)
            
            # Total stats
            totals = await conn.fetchrow("""
                SELECT SUM(duration_seconds) / 60 / 60 as hours, COUNT(*) as sessions
                FROM voice_activity
                WHERE guild_id = $1 AND joined_at >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
        
        description = f"🔊 **Voice Statistics (Last {days} days)**\n\n"
        description += f"**Total:** {totals['hours'] or 0:,.1f} hours | {totals['sessions'] or 0:,} sessions\n\n"
        
        description += "**Top Channels:**\n"
        for ch in top_channels[:5]:
            channel = interaction.guild.get_channel(ch['channel_id'])
            name = channel.name if channel else "Deleted Channel"
            description += f"{name}: {ch['minutes']:,.0f} min ({ch['users']} users)\n"
        
        description += "\n**Top Users:**\n"
        for u in top_users[:5]:
            user = interaction.guild.get_member(u['user_id'])
            name = user.display_name if user else f"User {u['user_id']}"
            description += f"{name}: {u['minutes']:,.0f} min ({u['sessions']} sessions)\n"
        
        view = self._create_container_view("Voice Analytics", description)
        await interaction.followup.send(view=view)

    async def show_member_stats(self, interaction: discord.Interaction, days: int):
        async with self.bot.db_pool.acquire() as conn:
            # Daily joins/leaves
            daily_stats = await conn.fetch("""
                SELECT 
                    DATE(event_date) as date,
                    SUM(CASE WHEN event_type = 'join' THEN 1 ELSE 0 END) as joins,
                    SUM(CASE WHEN event_type = 'leave' THEN 1 ELSE 0 END) as leaves
                FROM member_events
                WHERE guild_id = $1 AND event_date >= NOW() - interval '1 day' * $2
                GROUP BY DATE(event_date)
                ORDER BY date DESC
            """, interaction.guild.id, days)
            
            # Account age distribution
            age_dist = await conn.fetch("""
                SELECT 
                    CASE 
                        WHEN account_age_days < 7 THEN 'Less than 1 week'
                        WHEN account_age_days < 30 THEN '1-4 weeks'
                        WHEN account_age_days < 90 THEN '1-3 months'
                        WHEN account_age_days < 365 THEN '3-12 months'
                        ELSE 'Over 1 year'
                    END as age_group,
                    COUNT(*) as count
                FROM member_events
                WHERE guild_id = $1 AND event_type = 'join' AND event_date >= NOW() - interval '1 day' * $2
                GROUP BY age_group
                ORDER BY count DESC
            """, interaction.guild.id, days)
        
        description = f"👥 **Member Statistics (Last {days} days)**\n\n"
        
        description += "**Daily Activity:**\n"
        for d in daily_stats[:10]:
            net = d['joins'] - d['leaves']
            description += f"{d['date']}: +{d['joins']} / -{d['leaves']} = {net:+d}\n"
        
        description += "\n**Account Age of New Members:**\n"
        for age in age_dist:
            description += f"{age['age_group']}: {age['count']}\n"
        
        # Calculate retention approximation
        total_joins = sum(d['joins'] for d in daily_stats)
        total_leaves = sum(d['leaves'] for d in daily_stats)
        retention = ((total_joins - total_leaves) / total_joins * 100) if total_joins > 0 else 0
        description += f"\n**Retention Rate:** {retention:.1f}%"
        
        view = self._create_container_view("Member Analytics", description)
        await interaction.followup.send(view=view)

    async def show_command_stats(self, interaction: discord.Interaction, days: int):
        async with self.bot.db_pool.acquire() as conn:
            # Top commands
            top_commands = await conn.fetch("""
                SELECT command_name, COUNT(*) as uses
                FROM command_usage
                WHERE guild_id = $1 AND used_at >= NOW() - interval '1 day' * $2
                GROUP BY command_name
                ORDER BY uses DESC
                LIMIT 15
            """, interaction.guild.id, days)
            
            # Total usage
            res = await conn.fetchrow("""
                SELECT COUNT(*) as total FROM command_usage
                WHERE guild_id = $1 AND used_at >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
            total = res['total']
            
            # Top command users
            top_users = await conn.fetch("""
                SELECT user_id, COUNT(*) as uses
                FROM command_usage
                WHERE guild_id = $1 AND used_at >= NOW() - interval '1 day' * $2
                GROUP BY user_id
                ORDER BY uses DESC
                LIMIT 10
            """, interaction.guild.id, days)
        
        description = f"⚡ **Command Statistics (Last {days} days)**\n\n"
        description += f"**Total Commands Used:** {total:,}\n\n"
        
        description += "**Most Used Commands:**\n"
        for cmd in top_commands[:10]:
            description += f"/{cmd['command_name']}: {cmd['uses']:,} uses\n"
        
        description += "\n**Power Users:**\n"
        for u in top_users[:5]:
            user = interaction.guild.get_member(u['user_id'])
            name = user.display_name if user else f"User {u['user_id']}"
            description += f"{name}: {u['uses']:,} commands\n"
        
        view = self._create_container_view("Command Analytics", description)
        await interaction.followup.send(view=view)

    async def show_heatmap(self, interaction: discord.Interaction, days: int):
        async with self.bot.db_pool.acquire() as conn:
            # Get hourly activity for the last week
            # DOW is 0-6 (Sunday-Saturday)
            hourly_data = await conn.fetch("""
                SELECT 
                    EXTRACT(HOUR FROM hour_bucket) as hour,
                    EXTRACT(DOW FROM hour_bucket) as day,
                    SUM(message_count) as total
                FROM message_activity
                WHERE guild_id = $1 AND hour_bucket >= NOW() - interval '1 day' * $2
                GROUP BY EXTRACT(HOUR FROM hour_bucket), EXTRACT(DOW FROM hour_bucket)
            """, interaction.guild.id, min(days, 30))
        
        # Build heatmap
        days_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        heatmap = [[0 for _ in range(24)] for _ in range(7)]
        
        max_val = 0
        for row in hourly_data:
            day_idx = int(row['day'])
            hour = int(row['hour'])
            heatmap[day_idx][hour] = row['total']
            max_val = max(max_val, row['total'])
        
        # Generate text-based heatmap
        blocks = ['⬛', '🟫', '🟨', '🟩', '🟦']
        
        description = "🔥 **Activity Heatmap** (Messages per hour, darker = more active)\n\n"
        description += "```\n     00  04  08  12  16  20\n"
        
        for day_idx in range(7):
            description += f"{days_names[day_idx]} "
            for hour in [0, 4, 8, 12, 16, 20]:
                val = heatmap[day_idx][hour]
                if max_val > 0:
                    intensity = min(int((val / max_val) * 4), 4)
                else:
                    intensity = 0
                description += blocks[intensity] + " "
            description += "\n"
        
        description += "```\n"
        description += f"Peak activity: {max_val:,} messages in one hour\n"
        
        # Find most active hour
        max_day, max_hour = 0, 0
        for d in range(7):
            for h in range(24):
                if heatmap[d][h] > heatmap[max_day][max_hour]:
                    max_day, max_hour = d, h
        
        description += f"Most active: {days_names[max_day]}s at {max_hour:02d}:00"
        
        view = self._create_container_view("Activity Heatmap", description)
        await interaction.followup.send(view=view)

    @app_commands.command(name="export-analytics", description="Export analytics data to CSV.")
    @app_commands.describe(
        data_type="Type of data to export",
        days="Days of data to include"
    )
    @app_commands.choices(data_type=[
        app_commands.Choice(name="Messages", value="messages"),
        app_commands.Choice(name="Members", value="members"),
        app_commands.Choice(name="Voice", value="voice"),
        app_commands.Choice(name="Commands", value="commands")
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def export_analytics(self, interaction: discord.Interaction, data_type: str, days: int = 30):
        await interaction.response.defer(ephemeral=True)
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool:
            return await interaction.followup.send("Database not configured.", ephemeral=True)
        
        csv_data = []
        
        async with self.bot.db_pool.acquire() as conn:
            if data_type == "messages":
                rows = await conn.fetch("""
                    SELECT DATE(hour_bucket) as date, SUM(message_count) as total
                    FROM message_activity
                    WHERE guild_id = $1 AND hour_bucket >= NOW() - interval '1 day' * $2
                    GROUP BY DATE(hour_bucket)
                    ORDER BY date
                """, interaction.guild.id, days)
                csv_data.append("Date,Message Count")
                for row in rows:
                    csv_data.append(f"{row['date']},{row['total']}")
            
            elif data_type == "members":
                rows = await conn.fetch("""
                    SELECT DATE(event_date) as date,
                        SUM(CASE WHEN event_type = 'join' THEN 1 ELSE 0 END) as joins,
                        SUM(CASE WHEN event_type = 'leave' THEN 1 ELSE 0 END) as leaves
                    FROM member_events
                    WHERE guild_id = $1 AND event_date >= NOW() - interval '1 day' * $2
                    GROUP BY DATE(event_date)
                    ORDER BY date
                """, interaction.guild.id, days)
                csv_data.append("Date,Joins,Leaves")
                for row in rows:
                    csv_data.append(f"{row['date']},{row['joins']},{row['leaves']}")
            
            elif data_type == "voice":
                rows = await conn.fetch("""
                    SELECT DATE(joined_at) as date, SUM(duration_seconds) / 60 as minutes
                    FROM voice_activity
                    WHERE guild_id = $1 AND joined_at >= NOW() - interval '1 day' * $2
                    GROUP BY DATE(joined_at)
                    ORDER BY date
                """, interaction.guild.id, days)
                csv_data.append("Date,Voice Minutes")
                for row in rows:
                    csv_data.append(f"{row['date']},{row['minutes']:.0f}")
            
            elif data_type == "commands":
                rows = await conn.fetch("""
                    SELECT DATE(used_at) as date, command_name, COUNT(*) as uses
                    FROM command_usage
                    WHERE guild_id = $1 AND used_at >= NOW() - interval '1 day' * $2
                    GROUP BY DATE(used_at), command_name
                    ORDER BY date
                """, interaction.guild.id, days)
                csv_data.append("Date,Command,Uses")
                for row in rows:
                    csv_data.append(f"{row['date']},{row['command_name']},{row['uses']}")
        
        csv_content = "\n".join(csv_data)
        file = discord.File(fp=io.BytesIO(csv_content.encode()), filename=f"{data_type}_analytics_{days}days.csv")
        
        await interaction.followup.send(f"📊 Here's your **{data_type}** analytics export:", file=file, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()

async def setup(bot: commands.Bot):
    await bot.add_cog(Analytics(bot))
