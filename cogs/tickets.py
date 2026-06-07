import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import json
import os
from groq import AsyncGroq

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

class TicketView(ui.LayoutView):
    def __init__(self, container: ui.Container):
        super().__init__(timeout=None)
        self.add_item(container)

class TicketPanelView(ui.View):
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
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
        placeholder="Select: Support, Report, Appeal, Billing, Other",
        required=True,
        max_length=50
    )
    
    subject = ui.TextInput(
        label="Subject",
        placeholder="Brief summary of your issue",
        required=True,
        max_length=100
    )
    
    description = ui.TextInput(
        label="Description",
        placeholder="Describe your issue in detail...",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_ticket(
            interaction, 
            str(self.category), 
            str(self.subject), 
            str(self.description)
        )

class TicketActionView(ui.View):
    def __init__(self, cog, ticket_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_id = ticket_id
        self.channel_id = channel_id

    @ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(CloseTicketModal(self.cog, self.ticket_id, self.channel_id))

    @ui.button(label="Claim Ticket", style=discord.ButtonStyle.success, emoji="👤")
    async def claim_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.claim_ticket(interaction, self.ticket_id)

    @ui.button(label="AI Suggestions", style=discord.ButtonStyle.primary, emoji="🤖")
    async def ai_suggest(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.generate_ai_suggestions(interaction, self.ticket_id)

    @ui.button(label="Escalate", style=discord.ButtonStyle.secondary, emoji="⚡")
    async def escalate_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(EscalateTicketModal(self.cog, self.ticket_id))

class CloseTicketModal(ui.Modal, title="Close Ticket"):
    def __init__(self, cog, ticket_id: int, channel_id: int):
        super().__init__()
        self.cog = cog
        self.ticket_id = ticket_id
        self.channel_id = channel_id

    resolution = ui.TextInput(
        label="Resolution Notes",
        placeholder="How was this issue resolved?",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.close_ticket(interaction, self.ticket_id, self.channel_id, str(self.resolution))

class EscalateTicketModal(ui.Modal, title="Escalate Ticket"):
    def __init__(self, cog, ticket_id: int):
        super().__init__()
        self.cog = cog
        self.ticket_id = ticket_id

    reason = ui.TextInput(
        label="Escalation Reason",
        placeholder="Why does this need escalation?",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.escalate_ticket(interaction, self.ticket_id, str(self.reason))

class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.groq_client = AsyncGroq(api_key=os.getenv('GROQ_API_KEY')) if os.getenv('GROQ_API_KEY') else None
        self.active_tickets: Dict[int, dict] = {}  # channel_id -> ticket info

    async def setup_database(self):
        await self.bot.wait_until_ready()
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool: return
        try:
            async with self.bot.db_pool.acquire() as conn:
                # Ticket categories
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_categories (
                        category_id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        name VARCHAR(50) NOT NULL,
                        description VARCHAR(255),
                        emoji VARCHAR(10),
                        support_role_id BIGINT,
                        priority INT DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (guild_id, name)
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_cat_guild ON ticket_categories (guild_id)")
                
                # Tickets
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS tickets (
                        ticket_id SERIAL PRIMARY KEY,
                        guild_ticket_number INT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        channel_id BIGINT,
                        category VARCHAR(50),
                        subject VARCHAR(100),
                        description TEXT,
                        status VARCHAR(20) CHECK (status IN ('open', 'claimed', 'escalated', 'closed')) DEFAULT 'open',
                        claimed_by BIGINT,
                        priority VARCHAR(20) CHECK (priority IN ('low', 'medium', 'high', 'urgent')) DEFAULT 'medium',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        closed_at TIMESTAMP NULL,
                        resolution_notes TEXT,
                        satisfaction_rating INT,
                        transcript_url VARCHAR(255),
                        UNIQUE (guild_id, guild_ticket_number)
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_tick_user ON tickets (user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_tick_status ON tickets (status)")
                
                # Ticket messages for transcript
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_messages (
                        message_id SERIAL PRIMARY KEY,
                        ticket_id INT NOT NULL,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(100),
                        content TEXT,
                        attachments TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_ticket ON ticket_messages (ticket_id)")
                
                # Ticket analytics
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS ticket_analytics (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        date DATE NOT NULL,
                        tickets_created INT DEFAULT 0,
                        tickets_closed INT DEFAULT 0,
                        avg_response_time INT,
                        avg_resolution_time INT,
                        satisfaction_avg DECIMAL(3,2),
                        UNIQUE (guild_id, date)
                    )
                """)
                
            print(f"{Colors.GREEN}[SUCCESS]      Ticket system tables initialized.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Failed to initialize ticket tables: {e}{Colors.RESET}")

    def _create_container_view(self, title: str, description: str, color: str = "INFO") -> TicketView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        container = ui.Container(header, sep, body)
        return TicketView(container)

    @app_commands.command(name="ticket-panel", description="Create a ticket panel in the current channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title="🎫 Support Center",
            description="Need help? Create a ticket and our team will assist you!\n\n**How it works:**\n1. Click 'Create Ticket' below\n2. Select a category\n3. Describe your issue\n4. Wait for a staff member to respond",
            color=0x5a63f7,
            timestamp=datetime.now()
        )
        embed.set_footer(text="Average response time: Usually within 1 hour")
        
        view = TicketPanelView(self, interaction.guild.id)
        await interaction.channel.send(embed=embed, view=view)
        
        view_response = self._create_container_view("Panel Created", "Ticket panel has been posted successfully.")
        await interaction.followup.send(view=view_response, ephemeral=True)

    @app_commands.command(name="ticket-config", description="Configure ticket categories and settings.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_config(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketConfigModal(self))

    async def create_ticket(self, interaction: discord.Interaction, category: str, subject: str, description: str):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        user = interaction.user
        
        # Get next ticket number for this guild
        async with self.bot.db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT MAX(guild_ticket_number) as max_num FROM tickets WHERE guild_id = $1",
                guild.id
            )
            ticket_number = (result['max_num'] or 0) + 1
            
            # Create ticket in database
            ticket_id = await conn.fetchval("""
                INSERT INTO tickets (guild_ticket_number, guild_id, user_id, category, subject, description, status)
                VALUES ($1, $2, $3, $4, $5, $6, 'open')
                RETURNING ticket_id
            """, ticket_number, guild.id, user.id, category, subject, description)

        # Create ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        # Add support roles
        async with self.bot.db_pool.acquire() as conn:
            role_result = await conn.fetchrow(
                "SELECT support_role_id FROM ticket_categories WHERE guild_id = $1 AND name = $2",
                guild.id, category
            )
            if role_result and role_result['support_role_id']:
                role = guild.get_role(role_result['support_role_id'])
                if role:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category_channel = discord.utils.get(guild.categories, name="Tickets")
        if not category_channel:
            category_channel = await guild.create_category("Tickets")
        
        channel_name = f"ticket-{ticket_number:04d}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category_channel,
            overwrites=overwrites,
            topic=f"Ticket #{ticket_number:04d} | {category} | {subject}"
        )
        
        # Update ticket with channel_id
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET channel_id = $1 WHERE ticket_id = $2",
                ticket_channel.id, ticket_id
            )

        # Send ticket info in channel
        ticket_embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_number:04d}",
            description=f"**Category:** {category}\n**Subject:** {subject}\n\n**Description:**\n{description}",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        ticket_embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        ticket_embed.set_footer(text=f"User ID: {user.id}")
        
        view = TicketActionView(self, ticket_id, ticket_channel.id)
        msg = await ticket_channel.send(content=f"{user.mention}", embed=ticket_embed, view=view)
        await msg.pin()
        
        # Store in active tickets
        self.active_tickets[ticket_channel.id] = {
            'ticket_id': ticket_id,
            'user_id': user.id,
            'started_at': datetime.now()
        }
        
        # Send confirmation to user
        view_response = self._create_container_view(
            "Ticket Created", 
            f"Your ticket **#{ticket_number:04d}** has been created.\nChannel: {ticket_channel.mention}"
        )
        await interaction.followup.send(view=view_response, ephemeral=True)
        
        # Log ticket creation
        await self.log_ticket_event(guild, f"Ticket #{ticket_number:04d} created by {user.mention} in category '{category}'")

    async def claim_ticket(self, interaction: discord.Interaction, ticket_id: int):
        async with self.bot.db_pool.acquire() as conn:
            ticket = await conn.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1",
                ticket_id
            )
            
            if not ticket:
                return await interaction.response.send_message("Ticket not found.", ephemeral=True)
            
            if ticket['claimed_by']:
                claimed_by = interaction.guild.get_member(ticket['claimed_by'])
                return await interaction.response.send_message(
                    f"This ticket is already claimed by {claimed_by.mention if claimed_by else 'Unknown'}.", 
                    ephemeral=True
                )
            
            await conn.execute(
                "UPDATE tickets SET claimed_by = $1, status = 'claimed' WHERE ticket_id = $2",
                interaction.user.id, ticket_id
            )
        
        await interaction.response.send_message(
            f"✅ Ticket claimed by {interaction.user.mention}. They will handle this issue.",
            ephemeral=False
        )

    async def close_ticket(self, interaction: discord.Interaction, ticket_id: int, channel_id: int, resolution: str):
        await interaction.response.defer(ephemeral=False)
        
        # Generate transcript
        transcript = await self.generate_transcript(ticket_id, channel_id)
        
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE tickets 
                SET status = 'closed', closed_at = NOW(), resolution_notes = $1
                WHERE ticket_id = $2
            """, resolution, ticket_id)
        
        # Send transcript to log channel
        guild = interaction.guild
        user = interaction.user
        
        log_embed = discord.Embed(
            title=f"🎫 Ticket Closed",
            description=f"**Ticket ID:** #{ticket_id}\n**Closed by:** {user.mention}\n\n**Resolution:**\n{resolution}",
            color=0xff0000,
            timestamp=datetime.now()
        )
        
        # Find log channel
        log_channel = discord.utils.get(guild.text_channels, name="ticket-logs")
        if log_channel:
            file = discord.File(fp=transcript.encode(), filename=f"ticket_{ticket_id}_transcript.txt")
            await log_channel.send(embed=log_embed, file=file)
        
        # Send to user
        async with self.bot.db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT user_id FROM tickets WHERE ticket_id = $1",
                ticket_id
            )
            if result:
                user_obj = self.bot.get_user(result['user_id'])
                if user_obj:
                    try:
                        dm_embed = discord.Embed(
                            title="Your Ticket Has Been Closed",
                            description=f"**Ticket ID:** #{ticket_id}\n**Resolution:**\n{resolution}\n\nThank you for contacting support!",
                            color=0x5a63f7
                        )
                        await user_obj.send(embed=dm_embed)
                    except:
                        pass

        await interaction.followup.send(f"✅ Ticket closed. Transcript saved.")
        
        # Delete channel after delay
        channel = guild.get_channel(channel_id)
        if channel:
            await asyncio.sleep(5)
            await channel.delete()
        
        if channel_id in self.active_tickets:
            del self.active_tickets[channel_id]

    async def escalate_ticket(self, interaction: discord.Interaction, ticket_id: int, reason: str):
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE tickets SET status = 'escalated', priority = 'high' WHERE ticket_id = $1",
                ticket_id
            )
        
        await interaction.response.send_message(
            f"⚡ Ticket escalated!\n**Reason:** {reason}\n\n<@&{interaction.guild.owner_id}> - This ticket requires immediate attention!",
            ephemeral=False
        )

    async def generate_ai_suggestions(self, interaction: discord.Interaction, ticket_id: int):
        if not self.groq_client:
            return await interaction.response.send_message("AI features are not configured.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        async with self.bot.db_pool.acquire() as conn:
            ticket = await conn.fetchrow(
                "SELECT category, subject, description FROM tickets WHERE ticket_id = $1",
                ticket_id
            )
            
            if not ticket:
                return await interaction.followup.send("Ticket not found.", ephemeral=True)

        try:
            prompt = f"""You are a helpful support assistant. Based on this support ticket, provide 3 suggested responses:

Category: {ticket['category']}
Subject: {ticket['subject']}
Description: {ticket['description']}

Provide 3 professional responses of varying tone:
1. Formal/professional
2. Friendly/casual  
3. Brief/direct

Format each as: [Tone]: [Response]"""

            chat_completion = await self.groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="openai/gpt-oss-120b",
                temperature=0.7,
                max_tokens=500
            )
            
            suggestions = chat_completion.choices[0].message.content
            
            embed = discord.Embed(
                title="🤖 AI Response Suggestions",
                description=suggestions[:4000],
                color=0x00ff00
            )
            embed.set_footer(text="These are AI-generated suggestions. Review before sending.")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"AI generation failed: {e}", ephemeral=True)

    async def generate_transcript(self, ticket_id: int, channel_id: int) -> str:
        async with self.bot.db_pool.acquire() as conn:
            messages = await conn.fetch(
                "SELECT * FROM ticket_messages WHERE ticket_id = $1 ORDER BY timestamp",
                ticket_id
            )
            
            ticket = await conn.fetchrow(
                "SELECT * FROM tickets WHERE ticket_id = $1",
                ticket_id
            )
        
        transcript = f"""
========================================
TICKET TRANSCRIPT
========================================
Ticket ID: #{ticket['guild_ticket_number']:04d}
Category: {ticket['category']}
Subject: {ticket['subject']}
Status: {ticket['status']}
Created: {ticket['created_at']}
Closed: {ticket['closed_at'] or 'N/A'}
Resolution: {ticket['resolution_notes'] or 'N/A'}
========================================

MESSAGES:

"""
        
        for msg in messages:
            timestamp = msg['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
            transcript += f"[{timestamp}] {msg['username']}: {msg['content']}\n"
            if msg['attachments']:
                transcript += f"  [Attachments: {msg['attachments']}]\n"
            transcript += "\n"
        
        transcript += "\n========================================\nEND OF TRANSCRIPT\n========================================"
        
        return transcript

    async def show_user_tickets(self, interaction: discord.Interaction):
        async with self.bot.db_pool.acquire() as conn:
            tickets = await conn.fetch("""
                SELECT ticket_id, guild_ticket_number, category, subject, status, created_at
                FROM tickets 
                WHERE user_id = $1 AND guild_id = $2 AND status != 'closed'
                ORDER BY created_at DESC
            """, interaction.user.id, interaction.guild.id)
        
        if not tickets:
            view = self._create_container_view("No Active Tickets", "You don't have any open tickets.")
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        content = "**Your Active Tickets:**\n\n"
        for t in tickets:
            status_emoji = {"open": "🟢", "claimed": "🔵", "escalated": "🔴"}.get(t['status'], "⚪")
            content += f"{status_emoji} **#{t['guild_ticket_number']:04d}** - {t['category']}\n"
            content += f"{t['subject'][:50]}...\n"
            content += f"Created: <t:{int(t['created_at'].timestamp())}:R>\n\n"
        
        view = self._create_container_view("Your Tickets", content)
        await interaction.response.send_message(view=view, ephemeral=True)

    async def log_ticket_event(self, guild: discord.Guild, message: str):
        log_channel = discord.utils.get(guild.text_channels, name="ticket-logs")
        if log_channel:
            embed = discord.Embed(description=message, color=0x5a63f7, timestamp=datetime.now())
            await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        
        # Check if this is a ticket channel
        if message.channel.id in self.active_tickets:
            ticket_info = self.active_tickets[message.channel.id]
            
            attachments = []
            if message.attachments:
                attachments = [a.url for a in message.attachments]
            
            if hasattr(self.bot, 'db_pool') and self.bot.db_pool:
                async with self.bot.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO ticket_messages (ticket_id, user_id, username, content, attachments)
                        VALUES ($1, $2, $3, $4, $5)
                    """, 
                        ticket_info['ticket_id'],
                        message.author.id,
                        str(message.author),
                        message.content,
                        json.dumps(attachments) if attachments else None
                    )

    @app_commands.command(name="ticket-stats", description="View ticket statistics for the server.")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_stats(self, interaction: discord.Interaction, days: int = 7):
        await interaction.response.defer()
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool:
            return await interaction.followup.send("Database not configured.", ephemeral=True)
            
        async with self.bot.db_pool.acquire() as conn:
            # Total tickets
            res = await conn.fetchrow("""
                SELECT COUNT(*) as total FROM tickets 
                WHERE guild_id = $1 AND created_at >= NOW() - interval '1 day' * $2
            """, interaction.guild.id, days)
            total = res['total']
            
            # By status
            status_rows = await conn.fetch("""
                SELECT status, COUNT(*) as count FROM tickets 
                WHERE guild_id = $1 AND created_at >= NOW() - interval '1 day' * $2
                GROUP BY status
            """, interaction.guild.id, days)
            status_counts = {row['status']: row['count'] for row in status_rows}
            
            # By category
            category_counts = await conn.fetch("""
                SELECT category, COUNT(*) as count FROM tickets 
                WHERE guild_id = $1 AND created_at >= NOW() - interval '1 day' * $2
                GROUP BY category
                ORDER BY count DESC
            """, interaction.guild.id, days)
        
        content = f"**Ticket Statistics (Last {days} days)**\n\n"
        content += f"**Total Tickets:** {total}\n"
        content += f"**Open:** {status_counts.get('open', 0)} | **Claimed:** {status_counts.get('claimed', 0)} | **Closed:** {status_counts.get('closed', 0)}\n\n"
        content += "**By Category:**\n"
        for cat in category_counts[:5]:
            content += f"{cat['category']}: {cat['count']}\n"
        
        view = self._create_container_view("Ticket Analytics", content)
        await interaction.followup.send(view=view)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()

class TicketConfigModal(ui.Modal, title="Ticket Configuration"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    category_name = ui.TextInput(label="Category Name", placeholder="e.g., Support, Billing", required=True)
    category_desc = ui.TextInput(label="Description", placeholder="What is this category for?", required=True)
    support_role = ui.TextInput(label="Support Role ID", placeholder="Role ID for this category (optional)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        async with self.cog.bot.db_pool.acquire() as conn:
            role_id = int(str(self.support_role)) if str(self.support_role) else None
            await conn.execute("""
                INSERT INTO ticket_categories (guild_id, name, description, support_role_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, name) DO UPDATE SET description = $5, support_role_id = $6
            """, 
                interaction.guild.id,
                str(self.category_name),
                str(self.category_desc),
                role_id,
                str(self.category_desc),
                role_id
            )
        
        await interaction.response.send_message(
            f"✅ Category '{self.category_name}' configured successfully!",
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
