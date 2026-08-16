import discord
from discord.ext import commands
from discord import app_commands, ui
import logging

from utils import CLARK_COLOUR

logger = logging.getLogger("MessageSender")

@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
class MessageSender(commands.GroupCog, name="message"):
    def __init__(self, bot):
        self.bot = bot

    def format_hex(self, hex_code: str):
        """Ensures hex code starts with # for Discord compatibility."""
        if not hex_code: return None
        hex_code = hex_code.strip()
        return hex_code if hex_code.startswith("#") else f"#{hex_code}"

    @app_commands.command(name="send", description="Send an embed or plain text to a channel")
    @app_commands.describe(
        channel="Where to send the message",
        mode="Embed or Plain Text",
        content="The main message body",
        title="Embed title",
        thumbnail_type="Thumbnail shown in the top right",
        media_url="Large image shown at the bottom",
        button_name="Label for a link button",
        button_link="The URL for the button",
        accent_color="Hex colour for the left bar",
        show_separator="Add a divider under the text"
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Embed", value="container"),
            app_commands.Choice(name="Plain Text", value="text")
        ],
        thumbnail_type=[
            app_commands.Choice(name="Server Icon", value="server"),
            app_commands.Choice(name="User Avatar", value="user"),
            app_commands.Choice(name="None", value="none")
        ]
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def send_message(
        self, 
        itx: discord.Interaction, 
        channel: discord.TextChannel,
        mode: str,
        content: str,
        title: str = None,
        thumbnail_type: str = "none",
        media_url: str = None,
        button_name: str = None,
        button_link: str = None,
        accent_color: str = None, 
        show_separator: bool = False
    ):
        await itx.response.defer(ephemeral=True)

        try:
            # 1. Plain Text Mode
            if mode == "text":
                await channel.send(content=content)
                return await itx.followup.send("Plain text message sent.")

            # 2. Embed mode
            hex_val = self.format_hex(accent_color)
            clr = discord.Colour.from_str(hex_val) if hex_val else discord.Colour(CLARK_COLOUR)

            e = discord.Embed(title=title, description=content, colour=clr)

            if thumbnail_type == "server" and itx.guild.icon:
                e.set_thumbnail(url=itx.guild.icon.url)
            elif thumbnail_type == "user":
                e.set_thumbnail(url=itx.user.display_avatar.url)

            if media_url:
                e.set_image(url=media_url)

            # Used to space out container items. Embeds do that themselves, so
            # it's a divider line now.
            if show_separator and content:
                e.description = f"{content}\n\n───────────────"

            # Embeds can't hold buttons, so a link button still needs a View.
            view = None
            if button_name and button_link:
                view = ui.View(timeout=None)
                view.add_item(discord.ui.Button(label=button_name, url=button_link))

            await channel.send(embed=e, view=view)
            await itx.followup.send(f"Message sent to {channel.mention}")

        except Exception as e:
            logger.error(f"Message Send Error: {e}")
            await itx.followup.send(f"An error occurred, contact bot developer (usekiko): {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MessageSender(bot))