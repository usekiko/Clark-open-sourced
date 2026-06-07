import discord
from discord.ext import commands
from discord import app_commands, ui
import json
from datetime import datetime
from typing import Optional, Dict, List

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

class FormsView(ui.LayoutView):
    def __init__(self, container: ui.Container):
        super().__init__(timeout=None)
        self.add_item(container)

class FormBuilderModal(ui.Modal, title="Form Builder"):
    def __init__(self, cog, form_id: Optional[int] = None):
        super().__init__()
        self.cog = cog
        self.form_id = form_id

    form_name = ui.TextInput(label="Form Name", placeholder="e.g., Staff Application", required=True, max_length=50)
    description = ui.TextInput(label="Description", placeholder="What is this form for?", required=True, max_length=200)
    role_id = ui.TextInput(label="Role ID (Optional)", placeholder="Role to assign on approval", required=False)
    questions = ui.TextInput(
        label="Questions (JSON format)",
        placeholder='[{"q": "Question 1?", "type": "short"}, {"q": "Question 2?", "type": "long"}]',
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            questions = json.loads(str(self.questions))
            if not isinstance(questions, list):
                raise ValueError("Questions must be a list")
        except json.JSONDecodeError:
            return await interaction.response.send_message("Invalid JSON format for questions.", ephemeral=True)
        
        role_id = int(str(self.role_id)) if str(self.role_id) else None
        
        async with self.cog.bot.db_pool.acquire() as conn:
            if self.form_id:
                await conn.execute("""
                    UPDATE forms SET name = $1, description = $2, questions = $3, role_id = $4
                    WHERE form_id = $5 AND guild_id = $6
                """, str(self.form_name), str(self.description), json.dumps(questions), role_id, self.form_id, interaction.guild.id)
            else:
                await conn.execute("""
                    INSERT INTO forms (guild_id, name, description, questions, role_id, created_by)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, interaction.guild.id, str(self.form_name), str(self.description), json.dumps(questions), role_id, interaction.user.id)
        
        action = "updated" if self.form_id else "created"
        await interaction.response.send_message(f"✅ Form '{self.form_name}' {action} successfully!", ephemeral=True)

class FormSubmissionModal(ui.Modal):
    def __init__(self, cog, form_id: int, questions: List[dict]):
        title = "Application Form"
        super().__init__(title=title[:45])
        self.cog = cog
        self.form_id = form_id
        self.questions = questions
        self.answers = {}
        
        # Add up to 5 questions (Discord limit)
        for i, q in enumerate(questions[:5]):
            style = discord.TextStyle.paragraph if q.get('type') == 'long' else discord.TextStyle.short
            setattr(self, f'q{i}', ui.TextInput(
                label=q['q'][:45],
                required=True,
                style=style,
                max_length=1000
            ))

    async def on_submit(self, interaction: discord.Interaction):
        # Collect answers
        answers = []
        for i, q in enumerate(self.questions[:5]):
            field = getattr(self, f'q{i}', None)
            if field:
                answers.append({
                    'question': q['q'],
                    'answer': str(field)
                })
        
        await self.cog.submit_form(interaction, self.form_id, answers)

class ApplicationActionView(ui.View):
    def __init__(self, cog, submission_id: int, user_id: int, form_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.submission_id = submission_id
        self.user_id = user_id
        self.form_id = form_id

    @ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.process_application(interaction, self.submission_id, self.user_id, self.form_id, "approved")

    @ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RejectionModal(self.cog, self.submission_id, self.user_id, self.form_id))

    @ui.button(label="View Profile", style=discord.ButtonStyle.secondary, emoji="👤")
    async def view_profile(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.show_applicant_profile(interaction, self.user_id)

class RejectionModal(ui.Modal, title="Reject Application"):
    def __init__(self, cog, submission_id: int, user_id: int, form_id: int):
        super().__init__()
        self.cog = cog
        self.submission_id = submission_id
        self.user_id = user_id
        self.form_id = form_id

    reason = ui.TextInput(
        label="Rejection Reason",
        placeholder="Why is this application being rejected?",
        required=True,
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.process_application(interaction, self.submission_id, self.user_id, self.form_id, "rejected", str(self.reason))

class Forms(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def setup_database(self):
        await self.bot.wait_until_ready()
        if not hasattr(self.bot, 'db_pool') or not self.bot.db_pool: return
        try:
            async with self.bot.db_pool.acquire() as conn:
                # Forms definitions
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS forms (
                        form_id SERIAL PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        name VARCHAR(50) NOT NULL,
                        description VARCHAR(255),
                        questions JSONB NOT NULL,
                        role_id BIGINT,
                        approval_channel_id BIGINT,
                        created_by BIGINT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_form_guild ON forms (guild_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_form_active ON forms (is_active)")
                
                # Form submissions
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS form_submissions (
                        submission_id SERIAL PRIMARY KEY,
                        form_id INT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        answers JSONB NOT NULL,
                        status VARCHAR(20) CHECK (status IN ('pending', 'approved', 'rejected')) DEFAULT 'pending',
                        reviewed_by BIGINT,
                        review_notes TEXT,
                        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        reviewed_at TIMESTAMP NULL
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_fsub_form ON form_submissions (form_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_fsub_user ON form_submissions (user_id)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_fsub_status ON form_submissions (status)")
                
                # Form submission logs
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS form_logs (
                        log_id SERIAL PRIMARY KEY,
                        submission_id INT NOT NULL,
                        action VARCHAR(50) NOT NULL,
                        performed_by BIGINT NOT NULL,
                        details TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
            print(f"{Colors.GREEN}[SUCCESS]      Forms system tables initialized.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Failed to initialize forms tables: {e}{Colors.RESET}")

    def _create_container_view(self, title: str, description: str) -> FormsView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        container = ui.Container(header, sep, body)
        return FormsView(container)

    @app_commands.command(name="form-create", description="Create a new application form.")
    @app_commands.checks.has_permissions(administrator=True)
    async def form_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(FormBuilderModal(self))

    @app_commands.command(name="form-edit", description="Edit an existing form.")
    @app_commands.checks.has_permissions(administrator=True)
    async def form_edit(self, interaction: discord.Interaction, form_id: int):
        async with self.bot.db_pool.acquire() as conn:
            form = await conn.fetchrow(
                "SELECT * FROM forms WHERE form_id = $1 AND guild_id = $2",
                form_id, interaction.guild.id
            )
        
        if not form:
            view = self._create_container_view("Error", "Form not found.")
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        modal = FormBuilderModal(self, form_id)
        modal.form_name.default = form['name']
        modal.description.default = form['description']
        modal.role_id.default = str(form['role_id']) if form['role_id'] else ""
        
        # Ensure questions JSON is loaded then dumped so it formats cleanly if stringified
        if isinstance(form['questions'], str):
            modal.questions.default = form['questions']
        else:
            modal.questions.default = json.dumps(form['questions'])
        
        await interaction.response.send_modal(modal)

    @app_commands.command(name="form-delete", description="Delete a form.")
    @app_commands.checks.has_permissions(administrator=True)
    async def form_delete(self, interaction: discord.Interaction, form_id: int):
        async with self.bot.db_pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM forms WHERE form_id = $1 AND guild_id = $2",
                form_id, interaction.guild.id
            )
            rows_affected = int(status.split()[-1])
            
            if rows_affected == 0:
                view = self._create_container_view("Error", "Form not found.")
                return await interaction.response.send_message(view=view, ephemeral=True)
        
        view = self._create_container_view("Success", f"Form #{form_id} has been deleted.")
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="form-list", description="List all forms in this server.")
    async def form_list(self, interaction: discord.Interaction):
        async with self.bot.db_pool.acquire() as conn:
            forms = await conn.fetch(
                "SELECT form_id, name, description, is_active FROM forms WHERE guild_id = $1",
                interaction.guild.id
            )
        
        if not forms:
            view = self._create_container_view("No Forms", "No forms have been created yet.")
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        description = "**Available Forms:**\n\n"
        for form in forms:
            status = "🟢" if form['is_active'] else "🔴"
            description += f"{status} **#{form['form_id']}** - {form['name']}\n"
            description += f"{form['description']}\n\n"
        
        view = self._create_container_view("Forms", description)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="form-submit", description="Submit an application form.")
    async def form_submit(self, interaction: discord.Interaction, form_id: int):
        async with self.bot.db_pool.acquire() as conn:
            form = await conn.fetchrow(
                "SELECT * FROM forms WHERE form_id = $1 AND guild_id = $2 AND is_active = TRUE",
                form_id, interaction.guild.id
            )
        
        if not form:
            view = self._create_container_view("Error", "Form not found or inactive.")
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        # Check for existing pending submission
        async with self.bot.db_pool.acquire() as conn:
            existing = await conn.fetchrow("""
                SELECT submission_id FROM form_submissions
                WHERE form_id = $1 AND user_id = $2 AND status = 'pending'
            """, form_id, interaction.user.id)
        
        if existing:
            view = self._create_container_view("Error", "You already have a pending application for this form.")
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        if isinstance(form['questions'], str):
            questions = json.loads(form['questions'])
        else:
            questions = form['questions'] # already list/dict from asyncpg jsonb

        await interaction.response.send_modal(FormSubmissionModal(self, form_id, questions))

    async def submit_form(self, interaction: discord.Interaction, form_id: int, answers: List[dict]):
        async with self.bot.db_pool.acquire() as conn:
            submission_id = await conn.fetchval("""
                INSERT INTO form_submissions (form_id, guild_id, user_id, answers)
                VALUES ($1, $2, $3, $4)
                RETURNING submission_id
            """, form_id, interaction.guild.id, interaction.user.id, json.dumps(answers))
            
            # Get form info
            form_info = await conn.fetchrow(
                "SELECT name, approval_channel_id FROM forms WHERE form_id = $1",
                form_id
            )
        
        # Notify user
        view = self._create_container_view(
            "Application Submitted",
            f"Your application for **{form_info['name']}** has been submitted!\n\nSubmission ID: #{submission_id}\n\nYou will be notified when it's reviewed."
        )
        await interaction.response.send_message(view=view, ephemeral=True)
        
        # Send to approval channel
        if form_info['approval_channel_id']:
            channel = interaction.guild.get_channel(form_info['approval_channel_id'])
            if channel:
                embed = discord.Embed(
                    title=f"📋 New Application: {form_info['name']}",
                    description=f"**Applicant:** {interaction.user.mention} ({interaction.user.id})\n**Submitted:** <t:{int(datetime.now().timestamp())}:R>",
                    color=0x5a63f7,
                    timestamp=datetime.now()
                )
                
                for ans in answers:
                    embed.add_field(name=ans['question'][:256], value=ans['answer'][:1024], inline=False)
                
                action_view = ApplicationActionView(self, submission_id, interaction.user.id, form_id)
                await channel.send(embed=embed, view=action_view)

    @app_commands.command(name="form-panel", description="Post a form submission panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def form_panel(self, interaction: discord.Interaction, form_id: int, channel: discord.TextChannel):
        async with self.bot.db_pool.acquire() as conn:
            form = await conn.fetchrow(
                "SELECT * FROM forms WHERE form_id = $1 AND guild_id = $2",
                form_id, interaction.guild.id
            )
        
        if not form:
            view = self._create_container_view("Error", "Form not found.")
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        # Update approval channel
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE forms SET approval_channel_id = $1 WHERE form_id = $2",
                channel.id, form_id
            )
        
        # Create panel
        embed = discord.Embed(
            title=f"📋 {form['name']}",
            description=f"{form['description']}\n\nClick below to submit your application!",
            color=0x5a63f7
        )
        
        panel_view = FormSubmitView(self, form_id)
        await interaction.channel.send(embed=embed, view=panel_view)
        
        view = self._create_container_view("Panel Posted", f"Form panel posted! Applications will be sent to {channel.mention}")
        await interaction.response.send_message(view=view, ephemeral=True)

    async def process_application(self, interaction: discord.Interaction, submission_id: int, user_id: int, form_id: int, decision: str, reason: str = None):
        async with self.bot.db_pool.acquire() as conn:
            # Get form info
            form = await conn.fetchrow(
                "SELECT name, role_id FROM forms WHERE form_id = $1",
                form_id
            )
            
            # Update submission
            await conn.execute("""
                UPDATE form_submissions 
                SET status = $1, reviewed_by = $2, review_notes = $3, reviewed_at = NOW()
                WHERE submission_id = $4
            """, decision, interaction.user.id, reason, submission_id)
            
            # Log action
            await conn.execute("""
                INSERT INTO form_logs (submission_id, action, performed_by, details)
                VALUES ($1, $2, $3, $4)
            """, submission_id, decision, interaction.user.id, reason)
        
        # Get user
        user = interaction.guild.get_member(user_id)
        
        if decision == "approved":
            # Assign role if configured
            if form['role_id'] and user:
                role = interaction.guild.get_role(form['role_id'])
                if role:
                    try:
                        await user.add_roles(role, reason=f"Approved for {form['name']}")
                    except:
                        pass
            
            # DM user
            if user:
                try:
                    embed = discord.Embed(
                        title=f"✅ Application Approved",
                        description=f"Your application for **{form['name']}** has been approved!\n\nReviewed by: {interaction.user.mention}",
                        color=0x00ff00
                    )
                    await user.send(embed=embed)
                except:
                    pass
            
            await interaction.response.send_message(f"✅ Application #{submission_id} approved!", ephemeral=True)
        
        else:  # rejected
            # DM user
            if user:
                try:
                    embed = discord.Embed(
                        title=f"❌ Application Rejected",
                        description=f"Your application for **{form['name']}** has been rejected.\n\n**Reason:** {reason or 'No reason provided'}",
                        color=0xff0000
                    )
                    await user.send(embed=embed)
                except:
                    pass
            
            await interaction.response.send_message(f"❌ Application #{submission_id} rejected.", ephemeral=True)

    async def show_applicant_profile(self, interaction: discord.Interaction, user_id: int):
        user = interaction.guild.get_member(user_id)
        if not user:
            return await interaction.response.send_message("User not found in server.", ephemeral=True)
        
        # Get user's application history
        async with self.bot.db_pool.acquire() as conn:
            history = await conn.fetch("""
                SELECT fs.status, fs.submitted_at, f.name as form_name
                FROM form_submissions fs
                JOIN forms f ON fs.form_id = f.form_id
                WHERE fs.user_id = $1 AND fs.guild_id = $2
                ORDER BY fs.submitted_at DESC
                LIMIT 5
            """, user_id, interaction.guild.id)
        
        embed = discord.Embed(
            title=f"👤 Applicant Profile: {user.display_name}",
            description=f"**Account Created:** <t:{int(user.created_at.timestamp())}:D>\n**Joined Server:** <t:{int(user.joined_at.timestamp())}:R>",
            color=0x5a63f7
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        
        if history:
            history_text = ""
            for h in history:
                emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(h['status'], "⚪")
                history_text += f"{emoji} **{h['form_name']}** - {h['status'].title()} (<t:{int(h['submitted_at'].timestamp())}:R>)\n"
            embed.add_field(name="Application History", value=history_text, inline=False)
        else:
            embed.add_field(name="Application History", value="No previous applications.", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="my-applications", description="View your application history.")
    async def my_applications(self, interaction: discord.Interaction):
        async with self.bot.db_pool.acquire() as conn:
            applications = await conn.fetch("""
                SELECT fs.submission_id, fs.status, fs.submitted_at, fs.reviewed_at, f.name as form_name
                FROM form_submissions fs
                JOIN forms f ON fs.form_id = f.form_id
                WHERE fs.user_id = $1 AND fs.guild_id = $2
                ORDER BY fs.submitted_at DESC
            """, interaction.user.id, interaction.guild.id)
        
        if not applications:
            view = self._create_container_view("No Applications", "You haven't submitted any applications yet.")
            return await interaction.response.send_message(view=view, ephemeral=True)
        
        description = "**Your Applications:**\n\n"
        for app in applications:
            emoji = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(app['status'], "⚪")
            description += f"{emoji} **#{app['submission_id']}** - {app['form_name']}\n"
            description += f"Status: {app['status'].title()}\n"
            description += f"Submitted: <t:{int(app['submitted_at'].timestamp())}:R>\n"
            if app['reviewed_at']:
                description += f"Reviewed: <t:{int(app['reviewed_at'].timestamp())}:R>\n"
            description += "\n"
        
        view = self._create_container_view("Your Applications", description)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="applications-review", description="Review pending applications.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def applications_review(self, interaction: discord.Interaction, status: str = "pending"):
        await interaction.response.defer()
        
        async with self.bot.db_pool.acquire() as conn:
            applications = await conn.fetch("""
                SELECT fs.submission_id, fs.user_id, fs.submitted_at, f.name as form_name
                FROM form_submissions fs
                JOIN forms f ON fs.form_id = f.form_id
                WHERE fs.guild_id = $1 AND fs.status = $2
                ORDER BY fs.submitted_at ASC
                LIMIT 10
            """, interaction.guild.id, status)
        
        if not applications:
            view = self._create_container_view("No Applications", f"No {status} applications found.")
            return await interaction.followup.send(view=view)
        
        description = f"**{status.title()} Applications:**\n\n"
        for app in applications:
            user = interaction.guild.get_member(app['user_id'])
            user_mention = user.mention if user else f"User {app['user_id']}"
            description += f"**#{app['submission_id']}** - {app['form_name']}\n"
            description += f"By: {user_mention}\n"
            description += f"Submitted: <t:{int(app['submitted_at'].timestamp())}:R>\n\n"
        
        view = self._create_container_view("Application Queue", description)
        await interaction.followup.send(view=view)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()

class FormSubmitView(ui.View):
    def __init__(self, cog, form_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.form_id = form_id

    @ui.button(label="Submit Application", style=discord.ButtonStyle.primary, emoji="📝")
    async def submit(self, interaction: discord.Interaction, button: ui.Button):
        # Reuse the form-submit command logic
        async with self.cog.bot.db_pool.acquire() as conn:
            form = await conn.fetchrow(
                "SELECT * FROM forms WHERE form_id = $1 AND guild_id = $2 AND is_active = TRUE",
                self.form_id, interaction.guild.id
            )
        
        if not form:
            return await interaction.response.send_message("This form is no longer available.", ephemeral=True)
        
        if isinstance(form['questions'], str):
            questions = json.loads(form['questions'])
        else:
            questions = form['questions']
            
        await interaction.response.send_modal(FormSubmissionModal(self.cog, self.form_id, questions))

async def setup(bot: commands.Bot):
    await bot.add_cog(Forms(bot))
