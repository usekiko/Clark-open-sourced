import discord
from discord.ext import commands
from discord import app_commands

KIKO_ID = 465618379642896394


class KikoTools(commands.Cog):
    """Private developer tools — restricted to Kiko only."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    kiko_group = app_commands.Group(name="kiko", description="Developer tools.")

    @kiko_group.command(name="notify", description="Send a DM to any user through Clark.")
    @app_commands.describe(
        user_id="The user's ID to DM",
        message="Message to send",
    )
    async def notify(self, interaction: discord.Interaction, user_id: str, message: str):
        # Hard-locked to Kiko only
        if interaction.user.id != KIKO_ID:
            return await interaction.response.send_message(
                "You don't have permission to use this command.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.followup.send("Invalid user ID — must be a number.", ephemeral=True)

        try:
            user = await self.bot.fetch_user(uid)
        except discord.NotFound:
            return await interaction.followup.send(f"No user found with ID `{user_id}`.", ephemeral=True)
        except discord.HTTPException as e:
            return await interaction.followup.send(f"Failed to fetch user: {e}", ephemeral=True)

        try:
            await user.send(message)
            await interaction.followup.send(
                f"Sent to **{user}** (`{user.id}`).", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"Failed — **{user}** has DMs closed or has blocked the bot.", ephemeral=True
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"Failed to send DM: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(KikoTools(bot))
