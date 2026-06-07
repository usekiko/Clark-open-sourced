import discord
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional
import random

# Mapping for button color customization
BUTTON_COLORS = {
    "green": discord.ButtonStyle.success,
    "blue": discord.ButtonStyle.primary,
    "grey": discord.ButtonStyle.secondary,
    "red": discord.ButtonStyle.danger
}

class VerificationModal(ui.Modal):
    def __init__(self, title: str, question: str, correct_answer: int, log_channel_id: Optional[int], cog):
        super().__init__(title=title)
        self.question_text = question
        self.correct_answer = correct_answer
        self.log_channel_id = log_channel_id
        self.cog = cog

        self.answer_input = ui.TextInput(
            label=f"What is {self.question_text}?",
            placeholder="Type your answer here...",
            required=True,
            min_length=1
        )
        self.add_item(self.answer_input)

    async def on_submit(self, interaction: discord.Interaction):
        user_input = self.answer_input.value.strip()
        
        is_correct = False
        try:
            is_correct = int(user_input) == self.correct_answer
        except ValueError:
            is_correct = False

        # Handle Logging using Message Container (UI v2)
        if self.log_channel_id:
            log_channel = interaction.guild.get_channel(self.log_channel_id)
            if log_channel:
                status_key = "SUCCESS" if is_correct else "ERROR"
                result_text = "Correct" if is_correct else "Incorrect"
                
                log_desc = (
                    f"User: {interaction.user.name} ({interaction.user.id})\n"
                    f"Question: {self.question_text}\n"
                    f"Answer Given: {user_input}\n"
                    f"Result: {result_text}"
                )
                
                # Using the styled container for the log message
                log_view = self.cog._create_styled_view(status_key, "Verification Log", log_desc)
                try:
                    await log_channel.send(view=log_view)
                except:
                    pass

        if is_correct:
            await self.cog.complete_verification(interaction)
        else:
            response_view = self.cog._create_styled_view('ERROR', "Verification Failed", "The answer you provided is incorrect. Please try again.")
            await interaction.response.send_message(view=response_view, ephemeral=True)

class VerifyButton(ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle):
        super().__init__(
            label=label,
            style=style,
            custom_id="verify_button"
        )
    
    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog('Verification')
        if cog:
            await cog.handle_verification(interaction)

class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.embed_color = 0x5a63f7 
        self.response_thumbnail_accessory = None 
        self.dummy_accessory = ui.TextDisplay('.') 
        self.bot.loop.create_task(self.setup_bot_profile())
        self.bot.loop.create_task(self._restore_persistent_views())
        
    async def setup_bot_profile(self):
        await self.bot.wait_until_ready()
        if self.bot.user:
            self.response_thumbnail_accessory = ui.Thumbnail(media=self.bot.user.display_avatar.url)
        else:
            self.response_thumbnail_accessory = None

    def _create_styled_view(self, status: str, title: str, description: str) -> ui.LayoutView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        container = ui.Container(header, sep, body)
        
        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        return view

    def _create_verification_container(self, title: str, message: str, btn_label: str, btn_style: discord.ButtonStyle) -> ui.LayoutView:
        # Standardized format for verification panel
        header = ui.TextDisplay(f"### <:goodconnection:1454536158208983051> ›  {title}")
        separator = ui.Separator(spacing=discord.SeparatorSpacing.small)
        
        # Format message with blockquotes
        lines = message.split('\n')
        formatted_lines = [f"> **{line.strip()}**" if line.strip() else "" for line in lines]
        body = ui.TextDisplay('\n'.join(formatted_lines))
        
        button = VerifyButton(label=btn_label, style=btn_style)

        container = ui.Container(header, separator, body)
        
        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        view.add_item(ui.ActionRow(button))
        return view

    async def _check_db_ready(self, interaction: discord.Interaction) -> bool:
        if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
            response_view = self._create_styled_view('ERROR', "›  Database Not Ready", "The database connection is not established.")
            await interaction.response.send_message(view=response_view, ephemeral=True)
            return False
        return True

    async def _get_verification_config(self, guild_id: str):
        try:
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT * FROM verification_config WHERE guild_id = %s", (guild_id,))
                    return await cursor.fetchone()
        except Exception as e:
            print(f"Error fetching verification config: {e}")
            return None

    async def _create_verification_tables(self):
        await self.bot.wait_until_ready()
        if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None: return
        try:
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS verification_config (
                            guild_id VARCHAR(20) PRIMARY KEY,
                            channel_id BIGINT,
                            unverified_role_id BIGINT,
                            verified_role_id BIGINT,
                            message_id BIGINT,
                            custom_message TEXT,
                            log_channel_id BIGINT,
                            button_label VARCHAR(100),
                            button_style VARCHAR(20),
                            panel_title VARCHAR(100)
                        )
                    """)
                    await conn.commit()
        except Exception as e:
            print(f"Error creating verification tables: {e}")

    async def _restore_persistent_views(self):
        await self.bot.wait_until_ready()
        if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None: return
        try:
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT * FROM verification_config")
                    configs = await cursor.fetchall()
                    for config in configs:
                        guild = self.bot.get_guild(int(config[0]))
                        if not guild: continue
                        channel = guild.get_channel(config[1])
                        if not channel: continue
                        try:
                            message = await channel.fetch_message(config[4])
                            style = BUTTON_COLORS.get(config[8], discord.ButtonStyle.success)
                            view = self._create_verification_container(config[9], config[5], config[7], style)
                            await message.edit(view=view)
                        except: continue
        except Exception as e:
            print(f"Error restoring persistent views: {e}")

    async def cog_load(self):
        self.bot.loop.create_task(self._initialize_verification())
    
    async def _initialize_verification(self):
        await self.bot.wait_until_ready()
        await self._create_verification_tables()

    verification_group = app_commands.Group(name="verification", description="Verification system settings.")

    @verification_group.command(name="setup", description="Set up the verification system.")
    @app_commands.describe(
        channel="Channel where the verification message will be sent",
        unverified_role="Role given to unverified members",
        verified_role="Role given to verified members",
        message="Message content for the verification panel",
        log_channel="Channel where verification results are logged",
        button_label="Text displayed on the button",
        button_color="Color of the button",
        panel_title="The title header in the container"
    )
    @app_commands.choices(button_color=[
        app_commands.Choice(name="Green", value="green"),
        app_commands.Choice(name="Blue", value="blue"),
        app_commands.Choice(name="Grey", value="grey"),
        app_commands.Choice(name="Red", value="red")
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verification_setup(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
        unverified_role: discord.Role, verified_role: discord.Role,
        message: str, log_channel: Optional[discord.TextChannel] = None,
        button_label: str = "I accept the rules", button_color: str = "green",
        panel_title: str = "Verification Required"
    ):
        if not await self._check_db_ready(interaction): return
        await interaction.response.defer(ephemeral=True)

        try:
            style = BUTTON_COLORS.get(button_color, discord.ButtonStyle.success)
            view = self._create_verification_container(panel_title, message, button_label, style)
            sent_message = await channel.send(view=view)

            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        INSERT INTO verification_config 
                        (guild_id, channel_id, unverified_role_id, verified_role_id, message_id, custom_message, 
                        log_channel_id, button_label, button_style, panel_title) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                        channel_id=%s, unverified_role_id=%s, verified_role_id=%s, message_id=%s, custom_message=%s,
                        log_channel_id=%s, button_label=%s, button_style=%s, panel_title=%s
                    """, (
                        str(interaction.guild.id), channel.id, unverified_role.id, verified_role.id, sent_message.id, message,
                        log_channel.id if log_channel else None, button_label, button_color, panel_title,
                        channel.id, unverified_role.id, verified_role.id, sent_message.id, message,
                        log_channel.id if log_channel else None, button_label, button_color, panel_title
                    ))
                    await conn.commit()
            
            res_view = self._create_styled_view('SUCCESS', "Verification setup successful!", f"Message sent to {channel.mention}.")
            await interaction.followup.send(view=res_view, ephemeral=True)
        except Exception as e:
            print(f"Setup Error: {e}")

    @verification_group.command(name="disable", description="Disable the verification system.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verification_disable(self, interaction: discord.Interaction):
        if not await self._check_db_ready(interaction): return
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM verification_config WHERE guild_id = %s", (str(interaction.guild.id),))
                await conn.commit()
        await interaction.response.send_message(view=self._create_styled_view('SUCCESS', "Verification Disabled", "System is disabled!."), ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        config = await self._get_verification_config(str(member.guild.id))
        if not config or not config[2]: return
        role = member.guild.get_role(config[2])
        if role:
            try: await member.add_roles(role)
            except: pass

    async def handle_verification(self, interaction: discord.Interaction):
        config = await self._get_verification_config(str(interaction.guild.id))
        if not config: return

        v_role = interaction.guild.get_role(config[3])
        if v_role in interaction.user.roles:
            await interaction.response.send_message(view=self._create_styled_view('INFO', "Already verified.", "You no longer need to verify."), ephemeral=True)
            return

        num1 = random.randint(1, 20)
        num2 = random.randint(1, 20)
        operation = random.choice(['+', '-'])
        
        if operation == '+':
            answer = num1 + num2
        else:
            num1, num2 = max(num1, num2), min(num1, num2)
            answer = num1 - num2
            
        question_str = f"{num1} {operation} {num2}"
        modal_title = config[9] if config[9] else "Verification - Solve the Task"
        
        await interaction.response.send_modal(VerificationModal(modal_title, question_str, answer, config[6], self))

    async def complete_verification(self, interaction: discord.Interaction):
        config = await self._get_verification_config(str(interaction.guild.id))
        if not config: return
        u_role = interaction.guild.get_role(config[2])
        v_role = interaction.guild.get_role(config[3])

        try:
            if u_role and u_role in interaction.user.roles:
                await interaction.user.remove_roles(u_role)
            if v_role:
                await interaction.user.add_roles(v_role)
            await interaction.response.send_message(view=self._create_styled_view('SUCCESS', "Verification Successful", "You have been verified!"), ephemeral=True)
        except Exception as e:
            print(f"Role Error: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))