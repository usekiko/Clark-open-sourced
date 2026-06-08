import discord
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional

from utils import styled_view, Colors

BUTTON_COLORS = {
    "green": discord.ButtonStyle.success,
    "blue":  discord.ButtonStyle.primary,
    "grey":  discord.ButtonStyle.secondary,
    "red":   discord.ButtonStyle.danger,
}


class VerificationModal(ui.Modal):
    def __init__(self, title: str, question: str, correct_answer: int, log_channel_id: Optional[int], cog):
        super().__init__(title=title)
        self.question_text  = question
        self.correct_answer = correct_answer
        self.log_channel_id = log_channel_id
        self.cog            = cog

        self.answer_input = ui.TextInput(
            label=f"What is {self.question_text}?",
            placeholder="Type your answer here…",
            required=True,
            min_length=1,
        )
        self.add_item(self.answer_input)

    async def on_submit(self, interaction: discord.Interaction):
        user_input = self.answer_input.value.strip()
        try:
            is_correct = int(user_input) == self.correct_answer
        except ValueError:
            is_correct = False

        # Log to the configured log channel
        if self.log_channel_id:
            log_channel = interaction.guild.get_channel(self.log_channel_id)
            if log_channel:
                result_text = "Correct" if is_correct else "Incorrect"
                log_desc = (
                    f"User: {interaction.user.name} ({interaction.user.id})\n"
                    f"Question: {self.question_text}\n"
                    f"Answer Given: {user_input}\n"
                    f"Result: {result_text}"
                )
                try:
                    await log_channel.send(view=styled_view("Verification Log", log_desc))
                except Exception:
                    pass

        if is_correct:
            await self.cog.complete_verification(interaction)
        else:
            await interaction.response.send_message(
                view=styled_view("Verification Failed", "The answer you provided is incorrect. Please try again."),
                ephemeral=True,
            )


class VerifyButton(ui.Button):
    def __init__(self, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id="verify_button")

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Verification")
        if cog:
            await cog.handle_verification(interaction)


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def cog_load(self) -> None:
        if not getattr(self.bot, "db_pool", None):
            print(f"{Colors.RED}[ERROR]        Verification cog: db_pool not ready.{Colors.RESET}")
            return
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS verification_config (
                        guild_id          BIGINT       PRIMARY KEY,
                        channel_id        BIGINT,
                        unverified_role_id BIGINT,
                        verified_role_id  BIGINT,
                        message_id        BIGINT,
                        custom_message    TEXT,
                        log_channel_id    BIGINT,
                        button_label      VARCHAR(100),
                        button_style      VARCHAR(20),
                        panel_title       VARCHAR(100)
                    )
                """)
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Verification table creation failed: {e}{Colors.RESET}")
            return

        # Restore persistent verification views on every startup
        try:
            async with self.bot.db_pool.acquire() as conn:
                configs = await conn.fetch("SELECT * FROM verification_config")
            for config in configs:
                guild = self.bot.get_guild(config["guild_id"])
                if not guild:
                    continue
                channel = guild.get_channel(config["channel_id"])
                if not channel:
                    continue
                try:
                    message = await channel.fetch_message(config["message_id"])
                    style   = BUTTON_COLORS.get(config["button_style"], discord.ButtonStyle.success)
                    view    = self._create_panel(config["panel_title"], config["custom_message"], config["button_label"], style)
                    await message.edit(view=view)
                except Exception:
                    continue
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Verification restore failed: {e}{Colors.RESET}")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _create_panel(
        self,
        title:     str,
        message:   str,
        btn_label: str,
        btn_style: discord.ButtonStyle,
    ) -> ui.LayoutView:
        header    = ui.TextDisplay(f"### <:goodconnection:1454536158208983051> ›  {title}")
        separator = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body      = ui.TextDisplay(message)
        button    = VerifyButton(label=btn_label, style=btn_style)

        container  = ui.Container(header, separator, body)
        view       = ui.LayoutView(timeout=None)
        view.add_item(container)
        view.add_item(ui.ActionRow(button))
        return view

    async def _check_db(self, interaction: discord.Interaction) -> bool:
        if not getattr(self.bot, "db_pool", None):
            await interaction.response.send_message(
                view=styled_view("Database Not Ready", "The database connection is not established."),
                ephemeral=True,
            )
            return False
        return True

    async def _get_config(self, guild_id: int):
        try:
            async with self.bot.db_pool.acquire() as conn:
                return await conn.fetchrow(
                    "SELECT * FROM verification_config WHERE guild_id = $1", guild_id
                )
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Verification config fetch: {e}{Colors.RESET}")
            return None

    # -----------------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------------

    verification_group = app_commands.Group(name="verification", description="Verification system settings.")

    @verification_group.command(name="setup", description="Set up the verification system.")
    @app_commands.describe(
        channel="Channel where the verification panel will be sent",
        unverified_role="Role given to unverified members",
        verified_role="Role given after successful verification",
        message="Message shown in the verification panel",
        log_channel="Channel where verification attempts are logged",
        button_label="Text on the button",
        button_color="Button color",
        panel_title="Title shown in the panel header",
    )
    @app_commands.choices(button_color=[
        app_commands.Choice(name="Green", value="green"),
        app_commands.Choice(name="Blue",  value="blue"),
        app_commands.Choice(name="Grey",  value="grey"),
        app_commands.Choice(name="Red",   value="red"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verification_setup(
        self,
        interaction: discord.Interaction,
        channel:         discord.TextChannel,
        unverified_role: discord.Role,
        verified_role:   discord.Role,
        message:         str,
        log_channel:     Optional[discord.TextChannel] = None,
        button_label:    str = "I accept the rules",
        button_color:    str = "green",
        panel_title:     str = "Verification Required",
    ):
        if not await self._check_db(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        try:
            style        = BUTTON_COLORS.get(button_color, discord.ButtonStyle.success)
            view         = self._create_panel(panel_title, message, button_label, style)
            sent_message = await channel.send(view=view)

            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO verification_config
                        (guild_id, channel_id, unverified_role_id, verified_role_id, message_id,
                         custom_message, log_channel_id, button_label, button_style, panel_title)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (guild_id) DO UPDATE SET
                        channel_id         = EXCLUDED.channel_id,
                        unverified_role_id = EXCLUDED.unverified_role_id,
                        verified_role_id   = EXCLUDED.verified_role_id,
                        message_id         = EXCLUDED.message_id,
                        custom_message     = EXCLUDED.custom_message,
                        log_channel_id     = EXCLUDED.log_channel_id,
                        button_label       = EXCLUDED.button_label,
                        button_style       = EXCLUDED.button_style,
                        panel_title        = EXCLUDED.panel_title
                    """,
                    interaction.guild.id, channel.id, unverified_role.id, verified_role.id,
                    sent_message.id, message,
                    log_channel.id if log_channel else None,
                    button_label, button_color, panel_title,
                )

            await interaction.followup.send(
                view=styled_view("Verification Setup", f"Panel sent to {channel.mention}."), ephemeral=True
            )
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Verification setup: {e}{Colors.RESET}")
            await interaction.followup.send(
                view=styled_view("Setup Failed", "An error occurred. Check bot permissions."), ephemeral=True
            )

    @verification_group.command(name="disable", description="Disable the verification system.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verification_disable(self, interaction: discord.Interaction):
        if not await self._check_db(interaction):
            return
        async with self.bot.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM verification_config WHERE guild_id = $1", interaction.guild.id)
        await interaction.response.send_message(
            view=styled_view("Verification Disabled", "The verification system has been disabled."), ephemeral=True
        )

    # -----------------------------------------------------------------------
    # Events
    # -----------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        config = await self._get_config(member.guild.id)
        if not config or not config["unverified_role_id"]:
            return
        role = member.guild.get_role(config["unverified_role_id"])
        if role:
            try:
                await member.add_roles(role)
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Verification flow
    # -----------------------------------------------------------------------

    async def handle_verification(self, interaction: discord.Interaction) -> None:
        config = await self._get_config(interaction.guild.id)
        if not config:
            return

        v_role = interaction.guild.get_role(config["verified_role_id"])
        if v_role and v_role in interaction.user.roles:
            await interaction.response.send_message(
                view=styled_view("Already Verified", "You are already verified."), ephemeral=True
            )
            return

        import random
        num1 = random.randint(1, 20)
        num2 = random.randint(1, 20)
        op   = random.choice(["+", "-"])
        if op == "+":
            answer = num1 + num2
        else:
            num1, num2 = max(num1, num2), min(num1, num2)
            answer = num1 - num2

        question_str = f"{num1} {op} {num2}"
        modal_title  = config["panel_title"] or "Verification — Solve the Task"
        await interaction.response.send_modal(
            VerificationModal(modal_title, question_str, answer, config["log_channel_id"], self)
        )

    async def complete_verification(self, interaction: discord.Interaction) -> None:
        config = await self._get_config(interaction.guild.id)
        if not config:
            return
        u_role = interaction.guild.get_role(config["unverified_role_id"])
        v_role = interaction.guild.get_role(config["verified_role_id"])
        try:
            if u_role and u_role in interaction.user.roles:
                await interaction.user.remove_roles(u_role)
            if v_role:
                await interaction.user.add_roles(v_role)
            await interaction.response.send_message(
                view=styled_view("Verification Successful", "You have been verified!"), ephemeral=True
            )
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Complete verification: {e}{Colors.RESET}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))