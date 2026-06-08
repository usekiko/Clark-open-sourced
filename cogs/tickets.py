import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import io
from datetime import datetime
from typing import Optional, Dict
from groq import AsyncGroq
import os

from utils import styled_view, Colors


# ---------------------------------------------------------------------------
# Persistent Views & Modals
# ---------------------------------------------------------------------------

class TicketPanelView(ui.View):
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog      = cog
        self.guild_id = guild_id

    @ui.button(label="Create Ticket", style=discord.ButtonStyle.primary, emoji="🎫")
    async def create_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(TicketCategoryModal(self.cog))

    @ui.button(label="View My Tickets", style=discord.ButtonStyle.secondary, emoji="📋")
    async def view_tickets(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.show_user_tickets(interaction)


class TicketCategoryModal(ui.Modal, title="Create Support Ticket"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    category = ui.TextInput(
        label="Category",
        placeholder="Support, Report, Appeal, Billing, or Other",
        required=True, max_length=50,
    )
    subject = ui.TextInput(
        label="Subject",
        placeholder="Brief summary of your issue",
        required=True, max_length=100,
    )
    description = ui.TextInput(
        label="Description",
        placeholder="Describe your issue in detail...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket(
            interaction,
            str(self.category),
            str(self.subject),
            str(self.description),
        )


class TicketActionView(ui.View):
    def __init__(self, cog, ticket_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.cog       = cog
        self.ticket_id = ticket_id
        self.channel_id = channel_id

    @ui.button(label="Close Ticket",   style=discord.ButtonStyle.danger,    emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CloseTicketModal(self.cog, self.ticket_id, self.channel_id))

    @ui.button(label="Claim Ticket",   style=discord.ButtonStyle.success,   emoji="👤")
    async def claim_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.claim_ticket(interaction, self.ticket_id)

    @ui.button(label="AI Suggestions", style=discord.ButtonStyle.primary,   emoji="🤖")
    async def ai_suggest(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.generate_ai_suggestions(interaction, self.ticket_id)

    @ui.button(label="Escalate",       style=discord.ButtonStyle.secondary, emoji="⚡")
    async def escalate_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(EscalateTicketModal(self.cog, self.ticket_id))


class CloseTicketModal(ui.Modal, title="Close Ticket"):
    def __init__(self, cog, ticket_id: int, channel_id: int):
        super().__init__()
        self.cog        = cog
        self.ticket_id  = ticket_id
        self.channel_id = channel_id

    resolution = ui.TextInput(
        label="Resolution Notes",
        placeholder="How was this issue resolved?",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.close_ticket(interaction, self.ticket_id, self.channel_id, str(self.resolution))


class EscalateTicketModal(ui.Modal, title="Escalate Ticket"):
    def __init__(self, cog, ticket_id: int):
        super().__init__()
        self.cog       = cog
        self.ticket_id = ticket_id

    reason = ui.TextInput(
        label="Escalation Reason",
        placeholder="Why does this need escalation?",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.escalate_ticket(interaction, self.ticket_id, str(self.reason))


class TicketConfigModal(ui.Modal, title="Ticket Configuration"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    category_name = ui.TextInput(label="Category Name",  placeholder="e.g., Support, Billing", required=True)
    category_desc = ui.TextInput(label="Description",     placeholder="What is this category for?", required=True)
    support_role  = ui.TextInput(label="Support Role ID", placeholder="Role ID (optional)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        raw_role = self.support_role.value.strip()
        role_id  = int(raw_role) if raw_role.isdigit() else None

        async with self.cog.bot.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ticket_categories (guild_id, name, description, support_role_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, name) DO UPDATE
                    SET description     = EXCLUDED.description,
                        support_role_id = EXCLUDED.support_role_id
                """,
                interaction.guild.id,
                str(self.category_name),
                str(self.category_desc),
                role_id,
            )
        await interaction.response.send_message(
            f"Category '{self.category_name}' configured.", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot          = bot
        self.groq_client  = AsyncGroq(api_key=os.getenv("GROQ_API_KEY")) if os.getenv("GROQ_API_KEY") else None
        # channel_id -> {ticket_id, user_id, started_at}
        self.active_tickets: Dict[int, dict] = {}

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def cog_load(self) -> None:
        if not getattr(self.bot, "db_pool", None):
            print(f"{Colors.RED}[ERROR]        Tickets cog: db_pool not ready.{Colors.RESET}")
            return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_categories (
                        category_id     SERIAL      PRIMARY KEY,
                        guild_id        BIGINT      NOT NULL,
                        name            VARCHAR(50) NOT NULL,
                        description     VARCHAR(255),
                        emoji           VARCHAR(10),
                        support_role_id BIGINT,
                        priority        INT         DEFAULT 0,
                        created_at      TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (guild_id, name)
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cat_guild ON ticket_categories (guild_id)")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS tickets (
                        ticket_id           SERIAL      PRIMARY KEY,
                        guild_ticket_number INT         NOT NULL,
                        guild_id            BIGINT      NOT NULL,
                        user_id             BIGINT      NOT NULL,
                        channel_id          BIGINT,
                        category            VARCHAR(50),
                        subject             VARCHAR(100),
                        description         TEXT,
                        status              VARCHAR(20) CHECK (status IN ('open','claimed','escalated','closed')) DEFAULT 'open',
                        claimed_by          BIGINT,
                        priority            VARCHAR(20) CHECK (priority IN ('low','medium','high','urgent'))     DEFAULT 'medium',
                        created_at          TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                        closed_at           TIMESTAMP,
                        resolution_notes    TEXT,
                        satisfaction_rating INT,
                        UNIQUE (guild_id, guild_ticket_number)
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_tick_user   ON tickets (user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_tick_status ON tickets (status)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_tick_channel ON tickets (channel_id)")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_messages (
                        message_id  SERIAL       PRIMARY KEY,
                        ticket_id   INT          NOT NULL,
                        user_id     BIGINT       NOT NULL,
                        username    VARCHAR(100),
                        content     TEXT,
                        attachments TEXT,
                        timestamp   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_ticket ON ticket_messages (ticket_id)")

                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_analytics (
                        id                  SERIAL   PRIMARY KEY,
                        guild_id            BIGINT   NOT NULL,
                        date                DATE     NOT NULL,
                        tickets_created     INT      DEFAULT 0,
                        tickets_closed      INT      DEFAULT 0,
                        avg_response_time   INT,
                        avg_resolution_time INT,
                        satisfaction_avg    DECIMAL(3,2),
                        UNIQUE (guild_id, date)
                    )
                """)

                # Populate active_tickets so transcript logging works after restart
                rows = await conn.fetch(
                    "SELECT ticket_id, channel_id, user_id, created_at FROM tickets WHERE status != 'closed' AND channel_id IS NOT NULL"
                )
                for row in rows:
                    self.active_tickets[row["channel_id"]] = {
                        "ticket_id":  row["ticket_id"],
                        "user_id":    row["user_id"],
                        "started_at": row["created_at"],
                    }

            print(f"{Colors.GREEN}[SUCCESS]      Ticket system tables initialized.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Failed to initialize ticket tables: {e}{Colors.RESET}")

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    @app_commands.command(name="ticket-panel", description="Post the ticket panel in this channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        panel = ui.LayoutView()
        header = ui.TextDisplay("## 🎫 Support Center\nNeed help? Create a ticket and our team will assist you!\n\n**How it works:**\n1. Click Create Ticket below\n2. Select a category\n3. Describe your issue\n4. Wait for a staff member")
        container = ui.Container(header)
        panel.add_item(container)

        buttons = ui.ActionRow()
        buttons.add_item(discord.ui.Button(label="Create Ticket",  style=discord.ButtonStyle.primary,   emoji="🎫", custom_id=f"tp_create:{interaction.guild.id}"))
        buttons.add_item(discord.ui.Button(label="View My Tickets",style=discord.ButtonStyle.secondary,            custom_id=f"tp_view:{interaction.guild.id}"))
        panel.add_item(buttons)

        # Use a persistent view that can handle the buttons
        view = TicketPanelView(self, interaction.guild.id)
        await interaction.channel.send(view=view)
        await interaction.followup.send(view=styled_view("Panel Created", "Ticket panel posted successfully."), ephemeral=True)

    @app_commands.command(name="ticket-config", description="Configure ticket categories and settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_config(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketConfigModal(self))

    # -----------------------------------------------------------------------
    # Core ticket logic
    # -----------------------------------------------------------------------

    async def create_ticket(
        self,
        interaction: discord.Interaction,
        category:    str,
        subject:     str,
        description: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user  = interaction.user

        async with self.bot.db_pool.acquire() as conn:
            async with conn.transaction():
                # Atomic next ticket number
                result = await conn.fetchrow(
                    "SELECT COALESCE(MAX(guild_ticket_number), 0) + 1 AS next FROM tickets WHERE guild_id = $1",
                    guild.id,
                )
                ticket_number = result["next"]

                ticket_id = await conn.fetchval(
                    """
                    INSERT INTO tickets (guild_ticket_number, guild_id, user_id, category, subject, description)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING ticket_id
                    """,
                    ticket_number, guild.id, user.id, category, subject, description,
                )

                # Support role for this category (still in same connection, avoids extra acquire)
                role_row = await conn.fetchrow(
                    "SELECT support_role_id FROM ticket_categories WHERE guild_id = $1 AND name = $2",
                    guild.id, category,
                )

        # Create the channel (outside transaction — Discord API call)
        overwrites: dict = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user:               discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        if role_row and role_row["support_role_id"]:
            role = guild.get_role(role_row["support_role_id"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        tickets_cat = discord.utils.get(guild.categories, name="Tickets") or await guild.create_category("Tickets")
        channel_name   = f"ticket-{ticket_number:04d}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=tickets_cat,
            overwrites=overwrites,
            topic=f"Ticket #{ticket_number:04d} | {category} | {subject}",
        )

        # Update channel_id in DB
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET channel_id = $1 WHERE ticket_id = $2",
                ticket_channel.id, ticket_id,
            )

        # Build ticket welcome message (LayoutView instead of embed)
        ticket_view = ui.LayoutView()
        header_text = (
            f"## 🎫 Ticket #{ticket_number:04d}\n"
            f"**Category:** {category}\n"
            f"**Subject:** {subject}\n\n"
            f"**Description:**\n{description}"
        )
        section = ui.Section(
            ui.TextDisplay(header_text),
            accessory=ui.Thumbnail(media=user.display_avatar.url),
        )
        container = ui.Container(section)
        ticket_view.add_item(container)

        action_view = TicketActionView(self, ticket_id, ticket_channel.id)
        msg = await ticket_channel.send(content=user.mention, view=action_view)

        # Pin info card separately so it's visible
        info_view = ui.LayoutView()
        info_view.add_item(container)
        info_msg = await ticket_channel.send(view=info_view)
        try:
            await info_msg.pin()
        except discord.Forbidden:
            pass

        self.active_tickets[ticket_channel.id] = {
            "ticket_id":  ticket_id,
            "user_id":    user.id,
            "started_at": datetime.now(),
        }

        await interaction.followup.send(
            view=styled_view(
                "Ticket Created",
                f"Your ticket **#{ticket_number:04d}** has been created.\nChannel: {ticket_channel.mention}",
            ),
            ephemeral=True,
        )
        await self._log_ticket(guild, f"Ticket #{ticket_number:04d} created by {user.mention} in category '{category}'")

    async def claim_ticket(self, interaction: discord.Interaction, ticket_id: int) -> None:
        async with self.bot.db_pool.acquire() as conn:
            ticket = await conn.fetchrow("SELECT claimed_by FROM tickets WHERE ticket_id = $1", ticket_id)
            if not ticket:
                return await interaction.response.send_message("Ticket not found.", ephemeral=True)
            if ticket["claimed_by"]:
                existing = interaction.guild.get_member(ticket["claimed_by"])
                name = existing.mention if existing else "Unknown"
                return await interaction.response.send_message(
                    f"This ticket is already claimed by {name}.", ephemeral=True
                )
            await conn.execute(
                "UPDATE tickets SET claimed_by = $1, status = 'claimed' WHERE ticket_id = $2",
                interaction.user.id, ticket_id,
            )
        await interaction.response.send_message(
            f"Ticket claimed by {interaction.user.mention}. They will handle this issue."
        )

    async def close_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id:   int,
        channel_id:  int,
        resolution:  str,
    ) -> None:
        await interaction.response.defer()

        transcript = await self._generate_transcript(ticket_id, channel_id)

        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET status = 'closed', closed_at = NOW(), resolution_notes = $1 WHERE ticket_id = $2",
                resolution, ticket_id,
            )
            result = await conn.fetchrow("SELECT user_id FROM tickets WHERE ticket_id = $1", ticket_id)

        guild = interaction.guild

        # Send transcript to log channel
        log_channel = discord.utils.get(guild.text_channels, name="ticket-logs")
        if log_channel:
            log_view = styled_view(
                "Ticket Closed",
                f"**Ticket ID:** #{ticket_id}\n**Closed by:** {interaction.user.mention}\n\n**Resolution:**\n{resolution}",
            )
            file = discord.File(fp=io.BytesIO(transcript.encode("utf-8")), filename=f"ticket_{ticket_id}_transcript.txt")
            await log_channel.send(view=log_view, file=file)

        # DM the original user
        if result:
            user_obj = self.bot.get_user(result["user_id"])
            if user_obj:
                try:
                    await user_obj.send(
                        view=styled_view(
                            "Your Ticket Has Been Closed",
                            f"**Ticket ID:** #{ticket_id}\n**Resolution:**\n{resolution}\n\nThank you for contacting support!",
                        )
                    )
                except discord.Forbidden:
                    pass

        await interaction.followup.send(view=styled_view("Ticket Closed", "Transcript saved. Channel will be deleted in 5 seconds."))

        await asyncio.sleep(5)
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                await channel.delete()
            except discord.Forbidden:
                pass

        self.active_tickets.pop(channel_id, None)

    async def escalate_ticket(self, interaction: discord.Interaction, ticket_id: int, reason: str) -> None:
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET status = 'escalated', priority = 'high' WHERE ticket_id = $1",
                ticket_id,
            )
        owner = interaction.guild.owner
        await interaction.response.send_message(
            f"Ticket escalated!\n**Reason:** {reason}\n\n{owner.mention} — This ticket requires immediate attention!"
        )

    async def generate_ai_suggestions(self, interaction: discord.Interaction, ticket_id: int) -> None:
        if not self.groq_client:
            return await interaction.response.send_message("AI features are not configured.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db_pool.acquire() as conn:
            ticket = await conn.fetchrow(
                "SELECT category, subject, description FROM tickets WHERE ticket_id = $1", ticket_id
            )
        if not ticket:
            return await interaction.followup.send("Ticket not found.", ephemeral=True)
        try:
            prompt = (
                f"You are a helpful support assistant. Based on this ticket, provide 3 suggested responses:\n\n"
                f"Category: {ticket['category']}\nSubject: {ticket['subject']}\nDescription: {ticket['description']}\n\n"
                "Format each as: [Tone]: [Response]"
            )
            chat = await self.groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="openai/gpt-oss-120b",
                temperature=0.7,
                max_tokens=500,
            )
            suggestions = chat.choices[0].message.content
            await interaction.followup.send(
                view=styled_view("AI Response Suggestions", suggestions[:3900]),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"AI generation failed: {e}", ephemeral=True)

    async def _generate_transcript(self, ticket_id: int, channel_id: int) -> str:
        async with self.bot.db_pool.acquire() as conn:
            messages = await conn.fetch(
                "SELECT * FROM ticket_messages WHERE ticket_id = $1 ORDER BY timestamp", ticket_id
            )
            ticket = await conn.fetchrow("SELECT * FROM tickets WHERE ticket_id = $1", ticket_id)

        lines = [
            "========================================",
            "TICKET TRANSCRIPT",
            "========================================",
            f"Ticket ID:  #{ticket['guild_ticket_number']:04d}",
            f"Category:   {ticket['category']}",
            f"Subject:    {ticket['subject']}",
            f"Status:     {ticket['status']}",
            f"Created:    {ticket['created_at']}",
            f"Closed:     {ticket['closed_at'] or 'N/A'}",
            f"Resolution: {ticket['resolution_notes'] or 'N/A'}",
            "========================================",
            "",
            "MESSAGES:",
            "",
        ]
        for msg in messages:
            ts = msg["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"[{ts}] {msg['username']}: {msg['content']}")
            if msg["attachments"]:
                lines.append(f"  [Attachments: {msg['attachments']}]")
            lines.append("")

        lines += ["", "========================================", "END OF TRANSCRIPT", "========================================"]
        return "\n".join(lines)

    async def show_user_tickets(self, interaction: discord.Interaction) -> None:
        async with self.bot.db_pool.acquire() as conn:
            tickets = await conn.fetch(
                """
                SELECT ticket_id, guild_ticket_number, category, subject, status, created_at
                FROM tickets
                WHERE user_id = $1 AND guild_id = $2 AND status != 'closed'
                ORDER BY created_at DESC
                """,
                interaction.user.id, interaction.guild.id,
            )

        if not tickets:
            return await interaction.response.send_message(
                view=styled_view("No Active Tickets", "You don't have any open tickets."), ephemeral=True
            )

        status_emoji = {"open": "🟢", "claimed": "🔵", "escalated": "🔴"}
        lines = []
        for t in tickets:
            emoji = status_emoji.get(t["status"], "⚪")
            lines.append(
                f"{emoji} **#{t['guild_ticket_number']:04d}** — {t['category']}\n"
                f"{t['subject'][:50]}\n"
                f"Created: <t:{int(t['created_at'].timestamp())}:R>\n"
            )
        await interaction.response.send_message(
            view=styled_view("Your Tickets", "\n".join(lines)), ephemeral=True
        )

    async def _log_ticket(self, guild: discord.Guild, message: str) -> None:
        log_channel = discord.utils.get(guild.text_channels, name="ticket-logs")
        if log_channel:
            await log_channel.send(view=styled_view("Ticket Event", message))

    # -----------------------------------------------------------------------
    # Message listener — record transcript lines
    # -----------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        info = self.active_tickets.get(message.channel.id)
        if not info:
            return
        if not getattr(self.bot, "db_pool", None):
            return
        attachments = [a.url for a in message.attachments] if message.attachments else []
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ticket_messages (ticket_id, user_id, username, content, attachments)
                VALUES ($1, $2, $3, $4, $5)
                """,
                info["ticket_id"],
                message.author.id,
                str(message.author),
                message.content,
                str(attachments) if attachments else None,
            )

    # -----------------------------------------------------------------------
    # Stats command
    # -----------------------------------------------------------------------

    @app_commands.command(name="ticket-stats", description="View ticket statistics for the server.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_stats(self, interaction: discord.Interaction, days: int = 7):
        await interaction.response.defer()
        if not getattr(self.bot, "db_pool", None):
            return await interaction.followup.send("Database not configured.", ephemeral=True)

        async with self.bot.db_pool.acquire() as conn:
            res = await conn.fetchrow(
                "SELECT COUNT(*) AS total FROM tickets WHERE guild_id = $1 AND created_at >= NOW() - interval '1 day' * $2",
                interaction.guild.id, days,
            )
            status_rows = await conn.fetch(
                "SELECT status, COUNT(*) AS count FROM tickets WHERE guild_id = $1 AND created_at >= NOW() - interval '1 day' * $2 GROUP BY status",
                interaction.guild.id, days,
            )
            cat_rows = await conn.fetch(
                "SELECT category, COUNT(*) AS count FROM tickets WHERE guild_id = $1 AND created_at >= NOW() - interval '1 day' * $2 GROUP BY category ORDER BY count DESC",
                interaction.guild.id, days,
            )

        status_counts = {r["status"]: r["count"] for r in status_rows}
        cat_lines = "\n".join(f"{r['category']}: {r['count']}" for r in cat_rows[:5])

        desc = (
            f"Total Tickets: {res['total']}\n"
            f"Open: {status_counts.get('open', 0)} | Claimed: {status_counts.get('claimed', 0)} | Closed: {status_counts.get('closed', 0)}\n\n"
            f"**By Category:**\n{cat_lines}"
        )
        await interaction.followup.send(view=styled_view(f"Ticket Analytics ({days}d)", desc))


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
