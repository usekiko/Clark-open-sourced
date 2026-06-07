import discord
from discord.ext import commands
from discord import app_commands, ui

class LayoutDemo(commands.Cog):
    """
    Gold Standard Cog for Discord.py Components V2 (Message Containers).
    This serves as a template for the 'Clean & Native' UI style:
    - Level 3 Heading titles
    - ui.Separator for visual distinction
    - Quoted and Bold field values
    - Omitted accent_colour for no sidebar
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Example Help Banner URL
        self.banner_url = "https://cdn.discordapp.com/attachments/1454528236607242423/1460661734263230556/polish_save.png"

    def build_container_layout(self, title: str, description: str, show_banner: bool = False) -> ui.LayoutView:
        """
        Helper method to construct the requested UI style.
        
        Style Rules:
        1. Title must be a Level 3 Header (###).
        2. A ui.Separator follows the title.
        3. The description body uses custom manual formatting (e.g., > **Field:** Value).
        4. ui.Container MUST omit accent_colour to remove the sidebar.
        """
        
        # --- 1. Title Component ---
        # Using ### for the native 'Section Header' look
        header_item = ui.TextDisplay(content=f"### {title}")

        # --- 2. Separator Component ---
        # Adds the thin horizontal line between header and body
        separator = ui.Separator(spacing=discord.SeparatorSpacing.small)

        # --- 3. Description Component ---
        # Description is passed as a pre-formatted string to allow per-line control
        body_item = ui.TextDisplay(content=description)

        # --- 4. Container Assembly ---
        # We wrap items in a list. Note: Section is avoided to bypass accessory requirements.
        container_items = [header_item, separator, body_item]

        # --- 5. Optional Media Gallery ---
        # If a banner is requested, we add it to the bottom of the container children
        if show_banner:
            gallery = ui.MediaGallery()
            gallery.add_item(media=self.banner_url)
            container_items.append(gallery)

        # --- 6. Final Container ---
        # OMITTING accent_colour is what removes the vertical side bar.
        container = ui.Container(*container_items)

        # --- 7. Final View ---
        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        
        return view

    @app_commands.command(name="layout-test", description="Demonstrates the clean native UI style.")
    @app_commands.describe(banner="Whether to include the bottom media banner.")
    async def layout_test(self, interaction: discord.Interaction, banner: bool = True):
        # Always defer for complex V2 Layouts
        await interaction.response.defer(ephemeral=True)

        # --- Example Data Presentation ---
        # This matches the requested style: Bold Header -> Quoted Fields -> Bold Footer
        title = "Financial Profile Audit"
        
        body = (
            "**Portfolio Analysis**\n"
            "> **Wallet:** 1,250 ✦\n"
            "> **Bank:** 45,000 ✦\n\n"
            "**Total Balance:** 46,250 Credits"
        )
        
        # Build and Send
        my_view = self.build_container_layout(
            title=title, 
            description=body, 
            show_banner=banner
        )

        await interaction.followup.send(view=my_view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(LayoutDemo(bot))