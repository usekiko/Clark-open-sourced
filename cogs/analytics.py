import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from utils import styled_view, Colors


_FLUSH_INTERVAL = 30   # seconds between DB flushes
_CACHE_TTL      = 300  # seconds — 5 min TTL (not currently used but available for future config)


class Analytics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # In-memory accumulators — flushed every _FLUSH_INTERVAL seconds
        # key: (guild_id, channel_id, user_id, hour_bucket_str) → count
        self._msg_buffer: Dict[Tuple, int] = defaultdict(int)
        # list of (guild_id, command_name, user_id) tuples
        self._cmd_buffer: List[Tuple] = []
        # voice sessions: user_id -> {guild_id, channel_id, joined_at}
        self.voice_sessions: Dict[int, dict] = {}

        self._flush_task: Optional[asyncio.Task] = None

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def cog_load(self) -> None:
        if not getattr(self.bot, "db_pool", None):
            print(f"{Colors.RED}[ERROR]        Analytics cog: db_pool not ready.{Colors.RESET}")
            return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS message_activity (
                        id            SERIAL    PRIMARY KEY,
                        guild_id      BIGINT    NOT NULL,
                        channel_id    BIGINT    NOT NULL,
                        user_id       BIGINT    NOT NULL,
                        hour_bucket   TIMESTAMP NOT NULL,
                        message_count INT       DEFAULT 1,
                        UNIQUE (guild_id, channel_id, user_id, hour_bucket)
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_hour ON message_activity (guild_id, hour_bucket)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_channel    ON message_activity (channel_id)")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS voice_activity (
                        id               SERIAL    PRIMARY KEY,
                        guild_id         BIGINT    NOT NULL,
                        channel_id       BIGINT    NOT NULL,
                        user_id          BIGINT    NOT NULL,
                        joined_at        TIMESTAMP NOT NULL,
                        left_at          TIMESTAMP,
                        duration_seconds INT       DEFAULT 0
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_va_guild ON voice_activity (guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_va_user  ON voice_activity (user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_va_time  ON voice_activity (joined_at)")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS member_events (
                        id               SERIAL     PRIMARY KEY,
                        guild_id         BIGINT     NOT NULL,
                        user_id          BIGINT     NOT NULL,
                        event_type       VARCHAR(10) CHECK (event_type IN ('join','leave')) NOT NULL,
                        event_date       TIMESTAMP  DEFAULT CURRENT_TIMESTAMP,
                        account_age_days INT
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_date ON member_events (guild_id, event_date)")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS guild_snapshots (
                        id             SERIAL  PRIMARY KEY,
                        guild_id       BIGINT  NOT NULL,
                        snapshot_date  DATE    NOT NULL,
                        total_members  INT,
                        online_members INT,
                        new_members    INT     DEFAULT 0,
                        left_members   INT     DEFAULT 0,
                        total_messages INT     DEFAULT 0,
                        active_users   INT     DEFAULT 0,
                        UNIQUE (guild_id, snapshot_date)
                    )
                """)

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS command_usage (
                        id           SERIAL    PRIMARY KEY,
                        guild_id     BIGINT    NOT NULL,
                        command_name VARCHAR(50) NOT NULL,
                        user_id      BIGINT    NOT NULL,
                        used_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        success      BOOLEAN   DEFAULT TRUE
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_cmd ON command_usage (guild_id, command_name)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_date  ON command_usage (used_at)")

            print(f"{Colors.GREEN}[SUCCESS]      Analytics tables initialized.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Analytics table init failed: {e}{Colors.RESET}")
            return

        # Start background flush loop
        self._flush_task = asyncio.create_task(self._flush_loop())

    def cog_unload(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()

    # -----------------------------------------------------------------------
    # Flush loop — batches DB writes
    # -----------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Every _FLUSH_INTERVAL seconds, flush both buffers to DB in one transaction."""
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL)
            await self._flush_buffers()

    async def _flush_buffers(self) -> None:
        if not getattr(self.bot, "db_pool", None):
            return
        if not self._msg_buffer and not self._cmd_buffer:
            return

        # Snapshot and clear
        msg_snapshot = dict(self._msg_buffer)
        cmd_snapshot = list(self._cmd_buffer)
        self._msg_buffer.clear()
        self._cmd_buffer.clear()

        try:
            async with self.bot.db_pool.acquire() as conn:
                async with conn.transaction():
                    if msg_snapshot:
                        await conn.executemany(
                            """
                            INSERT INTO message_activity
                                (guild_id, channel_id, user_id, hour_bucket, message_count)
                            VALUES ($1, $2, $3, $4, $5)
                            ON CONFLICT (guild_id, channel_id, user_id, hour_bucket)
                            DO UPDATE SET message_count = message_activity.message_count + EXCLUDED.message_count
                            """,
                            [(*k, v) for k, v in msg_snapshot.items()],
                        )
                    if cmd_snapshot:
                        await conn.executemany(
                            "INSERT INTO command_usage (guild_id, command_name, user_id, success) VALUES ($1, $2, $3, TRUE)",
                            cmd_snapshot,
                        )
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Analytics flush failed: {e}{Colors.RESET}")
            # Put data back so it isn't lost
            for k, v in msg_snapshot.items():
                self._msg_buffer[k] += v
            self._cmd_buffer.extend(cmd_snapshot)

    # -----------------------------------------------------------------------
    # Listeners — accumulate into buffers (no DB I/O)
    # -----------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        hour_bucket = datetime.now().replace(minute=0, second=0, microsecond=0)
        key = (message.guild.id, message.channel.id, message.author.id, hour_bucket)
        self._msg_buffer[key] += 1

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot:
            return
        now = datetime.now()

        # Joined or moved to a channel
        if after.channel and (not before.channel or before.channel.id != after.channel.id):
            self.voice_sessions[member.id] = {
                "guild_id":   member.guild.id,
                "channel_id": after.channel.id,
                "joined_at":  now,
            }

        # Left or moved from a channel
        if before.channel and (not after.channel or before.channel.id != after.channel.id):
            session = self.voice_sessions.pop(member.id, None)
            if session and getattr(self.bot, "db_pool", None):
                duration = int((now - session["joined_at"]).total_seconds())
                async with self.bot.db_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO voice_activity (guild_id, channel_id, user_id, joined_at, left_at, duration_seconds) VALUES ($1,$2,$3,$4,$5,$6)",
                        session["guild_id"], session["channel_id"], member.id,
                        session["joined_at"], now, duration,
                    )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot or not getattr(self.bot, "db_pool", None):
            return
        age = (datetime.now() - member.created_at.replace(tzinfo=None)).days
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO member_events (guild_id, user_id, event_type, account_age_days) VALUES ($1,$2,'join',$3)",
                member.guild.id, member.id, age,
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot or not getattr(self.bot, "db_pool", None):
            return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO member_events (guild_id, user_id, event_type) VALUES ($1,$2,'leave')",
                member.guild.id, member.id,
            )

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command
    ) -> None:
        if not interaction.guild:
            return
        # Accumulate — no DB write here
        self._cmd_buffer.append((interaction.guild.id, command.name, interaction.user.id))

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    @app_commands.command(name="analytics", description="View server analytics and statistics.")
    @app_commands.describe(metric="The type of analytics to view", days="Days to analyze (max 90)")
    @app_commands.choices(metric=[
        app_commands.Choice(name="Overview",  value="overview"),
        app_commands.Choice(name="Messages",  value="messages"),
        app_commands.Choice(name="Voice",     value="voice"),
        app_commands.Choice(name="Members",   value="members"),
        app_commands.Choice(name="Commands",  value="commands"),
        app_commands.Choice(name="Heatmap",   value="heatmap"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def analytics(self, interaction: discord.Interaction, metric: str, days: int = 7):
        await interaction.response.defer()
        if not getattr(self.bot, "db_pool", None):
            return await interaction.followup.send("Database not configured.", ephemeral=True)
        if days > 90:
            return await interaction.followup.send(
                view=styled_view("Error", "Maximum analysis period is 90 days."), ephemeral=True
            )
        dispatch = {
            "overview": self.show_overview,
            "messages": self.show_message_stats,
            "voice":    self.show_voice_stats,
            "members":  self.show_member_stats,
            "commands": self.show_command_stats,
            "heatmap":  self.show_heatmap,
        }
        await dispatch[metric](interaction, days)

    async def show_overview(self, interaction: discord.Interaction, days: int) -> None:
        async with self.bot.db_pool.acquire() as conn:
            msgs    = await conn.fetchrow(
                "SELECT SUM(message_count) AS total FROM message_activity WHERE guild_id=$1 AND hour_bucket>=NOW()-interval '1 day'*$2",
                interaction.guild.id, days,
            )
            users   = await conn.fetchrow(
                "SELECT COUNT(DISTINCT user_id) AS unique_users FROM message_activity WHERE guild_id=$1 AND hour_bucket>=NOW()-interval '1 day'*$2",
                interaction.guild.id, days,
            )
            voice   = await conn.fetchrow(
                "SELECT SUM(duration_seconds)/60 AS total_minutes FROM voice_activity WHERE guild_id=$1 AND joined_at>=NOW()-interval '1 day'*$2",
                interaction.guild.id, days,
            )
            members = await conn.fetchrow(
                "SELECT SUM(CASE WHEN event_type='join' THEN 1 ELSE 0 END) AS joins, SUM(CASE WHEN event_type='leave' THEN 1 ELSE 0 END) AS leaves FROM member_events WHERE guild_id=$1 AND event_date>=NOW()-interval '1 day'*$2",
                interaction.guild.id, days,
            )
            cmds    = await conn.fetchrow(
                "SELECT COUNT(*) AS total FROM command_usage WHERE guild_id=$1 AND used_at>=NOW()-interval '1 day'*$2",
                interaction.guild.id, days,
            )

        joins  = members["joins"]  or 0
        leaves = members["leaves"] or 0
        desc = (
            f"Messages: {msgs['total'] or 0:,}\n"
            f"Active Users: {users['unique_users'] or 0:,}\n"
            f"Voice Minutes: {voice['total_minutes'] or 0:,.0f}\n\n"
            f"Member Growth\n"
            f"Joined: {joins} | Left: {leaves} | Net: {joins - leaves:+d}\n\n"
            f"Commands Used: {cmds['total'] or 0:,}\n"
            f"Current Members: {interaction.guild.member_count}"
        )
        await interaction.followup.send(view=styled_view(f"Server Overview ({days}d)", desc))

    async def show_message_stats(self, interaction: discord.Interaction, days: int) -> None:
        async with self.bot.db_pool.acquire() as conn:
            top_channels = await conn.fetch(
                "SELECT channel_id, SUM(message_count) AS total FROM message_activity WHERE guild_id=$1 AND hour_bucket>=NOW()-interval '1 day'*$2 GROUP BY channel_id ORDER BY total DESC LIMIT 5",
                interaction.guild.id, days,
            )
            top_users = await conn.fetch(
                "SELECT user_id, SUM(message_count) AS total FROM message_activity WHERE guild_id=$1 AND hour_bucket>=NOW()-interval '1 day'*$2 GROUP BY user_id ORDER BY total DESC LIMIT 5",
                interaction.guild.id, days,
            )
            daily = await conn.fetch(
                "SELECT DATE(hour_bucket) AS date, SUM(message_count) AS total FROM message_activity WHERE guild_id=$1 AND hour_bucket>=NOW()-interval '1 day'*$2 GROUP BY DATE(hour_bucket) ORDER BY date DESC LIMIT 7",
                interaction.guild.id, days,
            )

        ch_lines = "\n".join(
            f"#{(interaction.guild.get_channel(r['channel_id']) or type('x', (), {'name': 'Deleted'})()).name}: {r['total']:,}"
            for r in top_channels
        )
        u_lines = "\n".join(
            f"{(interaction.guild.get_member(r['user_id']) or type('x', (), {'display_name': f'User {r[\"user_id\"]}'})()).display_name}: {r['total']:,}"
            for r in top_users
        )
        d_lines = "\n".join(f"{r['date']}: {r['total']:,}" for r in daily)

        desc = f"Top Channels\n{ch_lines}\n\nTop Users\n{u_lines}\n\nDaily Activity\n{d_lines}"
        await interaction.followup.send(view=styled_view(f"Message Analytics ({days}d)", desc))

    async def show_voice_stats(self, interaction: discord.Interaction, days: int) -> None:
        async with self.bot.db_pool.acquire() as conn:
            top_channels = await conn.fetch(
                "SELECT channel_id, SUM(duration_seconds)/60 AS minutes, COUNT(DISTINCT user_id) AS users FROM voice_activity WHERE guild_id=$1 AND joined_at>=NOW()-interval '1 day'*$2 GROUP BY channel_id ORDER BY minutes DESC LIMIT 5",
                interaction.guild.id, days,
            )
            top_users = await conn.fetch(
                "SELECT user_id, SUM(duration_seconds)/60 AS minutes, COUNT(*) AS sessions FROM voice_activity WHERE guild_id=$1 AND joined_at>=NOW()-interval '1 day'*$2 GROUP BY user_id ORDER BY minutes DESC LIMIT 5",
                interaction.guild.id, days,
            )
            totals = await conn.fetchrow(
                "SELECT SUM(duration_seconds)/3600 AS hours, COUNT(*) AS sessions FROM voice_activity WHERE guild_id=$1 AND joined_at>=NOW()-interval '1 day'*$2",
                interaction.guild.id, days,
            )

        ch_lines = "\n".join(
            f"{(interaction.guild.get_channel(r['channel_id']) or type('x', (), {'name': 'Deleted'})()).name}: {r['minutes']:,.0f} min ({r['users']} users)"
            for r in top_channels
        )
        u_lines = "\n".join(
            f"{(interaction.guild.get_member(r['user_id']) or type('x', (), {'display_name': f'User {r[\"user_id\"]}'})()).display_name}: {r['minutes']:,.0f} min ({r['sessions']} sessions)"
            for r in top_users
        )
        desc = (
            f"Total: {totals['hours'] or 0:,.1f} hours | {totals['sessions'] or 0:,} sessions\n\n"
            f"Top Channels\n{ch_lines}\n\nTop Users\n{u_lines}"
        )
        await interaction.followup.send(view=styled_view(f"Voice Analytics ({days}d)", desc))

    async def show_member_stats(self, interaction: discord.Interaction, days: int) -> None:
        async with self.bot.db_pool.acquire() as conn:
            daily = await conn.fetch(
                """
                SELECT DATE(event_date) AS date,
                    SUM(CASE WHEN event_type='join'  THEN 1 ELSE 0 END) AS joins,
                    SUM(CASE WHEN event_type='leave' THEN 1 ELSE 0 END) AS leaves
                FROM member_events
                WHERE guild_id=$1 AND event_date>=NOW()-interval '1 day'*$2
                GROUP BY DATE(event_date) ORDER BY date DESC LIMIT 10
                """,
                interaction.guild.id, days,
            )
            age_dist = await conn.fetch(
                """
                SELECT CASE
                    WHEN account_age_days < 7   THEN 'Less than 1 week'
                    WHEN account_age_days < 30  THEN '1-4 weeks'
                    WHEN account_age_days < 90  THEN '1-3 months'
                    WHEN account_age_days < 365 THEN '3-12 months'
                    ELSE 'Over 1 year'
                END AS age_group, COUNT(*) AS count
                FROM member_events
                WHERE guild_id=$1 AND event_type='join' AND event_date>=NOW()-interval '1 day'*$2
                GROUP BY age_group ORDER BY count DESC
                """,
                interaction.guild.id, days,
            )

        d_lines  = "\n".join(f"{d['date']}: +{d['joins']} / -{d['leaves']} = {d['joins']-d['leaves']:+d}" for d in daily)
        age_lines = "\n".join(f"{a['age_group']}: {a['count']}" for a in age_dist)

        total_j = sum(d["joins"]  for d in daily)
        total_l = sum(d["leaves"] for d in daily)
        retention = ((total_j - total_l) / total_j * 100) if total_j else 0

        desc = f"Daily Activity\n{d_lines}\n\nAccount Age of New Members\n{age_lines}\n\nRetention Rate: {retention:.1f}%"
        await interaction.followup.send(view=styled_view(f"Member Analytics ({days}d)", desc))

    async def show_command_stats(self, interaction: discord.Interaction, days: int) -> None:
        async with self.bot.db_pool.acquire() as conn:
            top_cmds = await conn.fetch(
                "SELECT command_name, COUNT(*) AS uses FROM command_usage WHERE guild_id=$1 AND used_at>=NOW()-interval '1 day'*$2 GROUP BY command_name ORDER BY uses DESC LIMIT 10",
                interaction.guild.id, days,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM command_usage WHERE guild_id=$1 AND used_at>=NOW()-interval '1 day'*$2",
                interaction.guild.id, days,
            )
            top_users = await conn.fetch(
                "SELECT user_id, COUNT(*) AS uses FROM command_usage WHERE guild_id=$1 AND used_at>=NOW()-interval '1 day'*$2 GROUP BY user_id ORDER BY uses DESC LIMIT 5",
                interaction.guild.id, days,
            )

        cmd_lines  = "\n".join(f"/{r['command_name']}: {r['uses']:,}" for r in top_cmds)
        user_lines = "\n".join(
            f"{(interaction.guild.get_member(r['user_id']) or type('x', (), {'display_name': f'User {r[\"user_id\"]}'})()).display_name}: {r['uses']:,}"
            for r in top_users
        )
        desc = f"Total Commands Used: {total:,}\n\nMost Used Commands\n{cmd_lines}\n\nPower Users\n{user_lines}"
        await interaction.followup.send(view=styled_view(f"Command Analytics ({days}d)", desc))

    async def show_heatmap(self, interaction: discord.Interaction, days: int) -> None:
        async with self.bot.db_pool.acquire() as conn:
            hourly = await conn.fetch(
                """
                SELECT EXTRACT(HOUR FROM hour_bucket) AS hour,
                       EXTRACT(DOW  FROM hour_bucket) AS day,
                       SUM(message_count) AS total
                FROM message_activity
                WHERE guild_id=$1 AND hour_bucket>=NOW()-interval '1 day'*$2
                GROUP BY EXTRACT(HOUR FROM hour_bucket), EXTRACT(DOW FROM hour_bucket)
                """,
                interaction.guild.id, min(days, 30),
            )

        days_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        heatmap    = [[0] * 24 for _ in range(7)]
        max_val    = 0
        for row in hourly:
            d = int(row["day"])
            h = int(row["hour"])
            heatmap[d][h] = row["total"]
            max_val = max(max_val, row["total"])

        blocks = ["⬛", "🟫", "🟨", "🟩", "🟦"]
        lines  = ["```", "     00  04  08  12  16  20"]
        for d in range(7):
            row_str = f"{days_names[d]} "
            for h in [0, 4, 8, 12, 16, 20]:
                val       = heatmap[d][h]
                intensity = min(int((val / max_val) * 4), 4) if max_val else 0
                row_str  += blocks[intensity] + " "
            lines.append(row_str)
        lines.append("```")
        lines.append(f"Peak activity: {max_val:,} messages in one hour")

        max_d, max_h = 0, 0
        for d in range(7):
            for h in range(24):
                if heatmap[d][h] > heatmap[max_d][max_h]:
                    max_d, max_h = d, h
        lines.append(f"Most active: {days_names[max_d]}s at {max_h:02d}:00")

        await interaction.followup.send(view=styled_view("Activity Heatmap", "\n".join(lines)))

    # -----------------------------------------------------------------------
    # Export
    # -----------------------------------------------------------------------

    @app_commands.command(name="export-analytics", description="Export analytics data as CSV.")
    @app_commands.describe(data_type="Type of data to export", days="Days to include")
    @app_commands.choices(data_type=[
        app_commands.Choice(name="Messages", value="messages"),
        app_commands.Choice(name="Members",  value="members"),
        app_commands.Choice(name="Voice",    value="voice"),
        app_commands.Choice(name="Commands", value="commands"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def export_analytics(self, interaction: discord.Interaction, data_type: str, days: int = 30):
        await interaction.response.defer(ephemeral=True)
        if not getattr(self.bot, "db_pool", None):
            return await interaction.followup.send("Database not configured.", ephemeral=True)

        import io as _io

        async with self.bot.db_pool.acquire() as conn:
            if data_type == "messages":
                rows = await conn.fetch(
                    "SELECT DATE(hour_bucket) AS date, SUM(message_count) AS total FROM message_activity WHERE guild_id=$1 AND hour_bucket>=NOW()-interval '1 day'*$2 GROUP BY DATE(hour_bucket) ORDER BY date",
                    interaction.guild.id, days,
                )
                header = "Date,Message Count"
                lines  = [f"{r['date']},{r['total']}" for r in rows]
            elif data_type == "members":
                rows = await conn.fetch(
                    "SELECT DATE(event_date) AS date, SUM(CASE WHEN event_type='join' THEN 1 ELSE 0 END) AS joins, SUM(CASE WHEN event_type='leave' THEN 1 ELSE 0 END) AS leaves FROM member_events WHERE guild_id=$1 AND event_date>=NOW()-interval '1 day'*$2 GROUP BY DATE(event_date) ORDER BY date",
                    interaction.guild.id, days,
                )
                header = "Date,Joins,Leaves"
                lines  = [f"{r['date']},{r['joins']},{r['leaves']}" for r in rows]
            elif data_type == "voice":
                rows = await conn.fetch(
                    "SELECT DATE(joined_at) AS date, SUM(duration_seconds)/60 AS minutes FROM voice_activity WHERE guild_id=$1 AND joined_at>=NOW()-interval '1 day'*$2 GROUP BY DATE(joined_at) ORDER BY date",
                    interaction.guild.id, days,
                )
                header = "Date,Voice Minutes"
                lines  = [f"{r['date']},{r['minutes']:.0f}" for r in rows]
            else:  # commands
                rows = await conn.fetch(
                    "SELECT DATE(used_at) AS date, command_name, COUNT(*) AS uses FROM command_usage WHERE guild_id=$1 AND used_at>=NOW()-interval '1 day'*$2 GROUP BY DATE(used_at), command_name ORDER BY date",
                    interaction.guild.id, days,
                )
                header = "Date,Command,Uses"
                lines  = [f"{r['date']},{r['command_name']},{r['uses']}" for r in rows]

        content = "\n".join([header] + lines)
        file    = discord.File(fp=_io.BytesIO(content.encode("utf-8")), filename=f"{data_type}_{days}d.csv")
        await interaction.followup.send(f"Analytics export for **{data_type}** ({days} days):", file=file, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Analytics(bot))
