import discord
from discord.ext import commands
from discord import app_commands, ui
import logging

logger = logging.getLogger("MessageSender")

class MessageSender(commands.GroupCog, name="message"):
    def __init__(self, bot):
        self.bot = bot

    def format_hex(self, hex_code: str):
        """Ensures hex code starts with # for Discord compatibility."""
        if not hex_code: return None
        hex_code = hex_code.strip()
        return hex_code if hex_code.startswith("#") else f"#{hex_code}"

    @app_commands.command(name="send", description="Send a Message Container or Plain Text")
    @app_commands.describe(
        channel="Where to send the message",
        mode="Message Container (v2) or Plain Text",
        content="The main message body",
        title="Title for the container",
        thumbnail_type="Add an accessory (Required for Section layout)",
        media_url="Add an image to the media gallery",
        button_name="Label for a link button",
        button_link="The URL for the button",
        accent_color="Hex color for the left border (leave empty for none)",
        show_separator="Add a thin line between text and media"
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Message Container", value="container"),
            app_commands.Choice(name="Plain Text", value="text")
        ],
        thumbnail_type=[
            app_commands.Choice(name="Server Icon", value="server"),
            app_commands.Choice(name="User Avatar", value="user"),
            app_commands.Choice(name="Invisible/None (Dummy Button)", value="none")
        ]
    )
    @commands.has_permissions(administrator=True)
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

            # 2. LayoutView Mode
            view = ui.LayoutView()

            # --- Forced Accessory Logic ---
            # Discord requires an accessory for the Section to render correctly.
            if thumbnail_type == "server" and itx.guild.icon:
                accessory = ui.Thumbnail(media=itx.guild.icon.url)
            elif thumbnail_type == "user":
                accessory = ui.Thumbnail(media=itx.user.display_avatar.url)
            else:
                # If 'None' is chosen, we use a URL button as a dummy accessory 
                # This satisfies the requirement while remaining functional.
                accessory = discord.ui.Button(label=" ", url="https://discord.com", disabled=True)

            # --- Section Construction ---
            display_text = f"## {title}\n{content}" if title else content
            # A Section must hold a TextDisplay object.
            section = ui.Section(ui.TextDisplay(display_text), accessory=accessory)

            # --- Container Construction ---
            container_items = [section]
            
            if show_separator:
                # Separators add visual spacing between items.
                container_items.append(ui.Separator(spacing=discord.SeparatorSpacing.small))

            if media_url:
                # MediaGallery can contain up to 10 MediaGalleryItems.
                gallery = ui.MediaGallery()
                gallery.add_item(media=media_url) 
                container_items.append(gallery)

            hex_val = self.format_hex(accent_color)
            clr = discord.Colour.from_str(hex_val) if hex_val else None
            
            # Container wraps items and adds the side accent colour.
            container = ui.Container(*container_items, accent_colour=clr)
            view.add_item(container)

            # --- Bottom Action Row ---
            if button_name and button_link:
                row = ui.ActionRow()
                row.add_item(discord.ui.Button(label=button_name, url=button_link))
                view.add_item(row)

            # Send via LayoutView.
            await channel.send(view=view)
            await itx.followup.send(f"Message container sent to {channel.mention}")

        except Exception as e:
            logger.error(f"Message Send Error: {e}")
            await itx.followup.send(f"An error occurred, contact bot developer (usekiko): {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MessageSender(bot))