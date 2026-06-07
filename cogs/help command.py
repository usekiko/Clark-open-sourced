import discord
from discord.ext import commands
from discord import app_commands, ui
from typing import Optional, Dict, List, Any

# --- Configuration & Emojis ---
HELP_BANNER_URL = "https://cdn.discordapp.com/attachments/1454528236607242423/1460661734263230556/polish_save.png?ex=6967babf&is=6966693f&hm=9acfab060e1bebb39129d2b9710d4d1610cb49cb4632bc1615515e0e4d663702&"
EMOJI_INFO = "<:goodconnection:1454536158208983051> ›  "
CAT_EMOJI = "<:help:1444474517324828788>"

class HelpSelect(ui.Select):
    def __init__(self, cog: 'Utilities'):
        self.help_cog = cog
        options = [
            discord.SelectOption(label=category, emoji=data["emoji"])
            for category, data in self.help_cog.commands_info.items()
        ]
        super().__init__(placeholder="View all command categories", options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        category_data = self.help_cog.commands_info[category]

        description = ""
        for cmd in category_data["commands"]:
            description += f"**`{cmd['name']}`**\n{cmd['description']}\n\n"

        new_view = self.help_cog.create_help_view(
            title=f"{category} Category\n", 
            description=description, 
            guild=interaction.guild
        )
        await interaction.response.edit_message(view=new_view)

class Utilities(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        self.commands_info: Dict[str, Dict[str, Any]] = {
            "Fun": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/joke", "description": "Tells a random joke/meme"},
                    {"name": "/meme", "description": "Sends a random meme/tiktok"},
                    {"name": "/funny", "description": "Sends a funny TikTok/roast"},
                    {"name": "/roast [optional mention]", "description": "Roast someone/fact"},
                    {"name": "/fact", "description": "Learn a random fact/help"},
                ]
            },
            "Music": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/music play", "description": "Play a song"},
                    {"name": "/music pause", "description": "Pause the song"},
                    {"name": "/music skip", "description": "Skip the current song"},
                    {"name": "/music disconnect", "description": "Disconnect the bot from voice."},
                ]
            },
            "Moderation": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/ban add", "description": "Permanently removes a user from the server."},
                    {"name": "/ban remove", "description": "Removes a ban from a user."},
                    {"name": "/tempban add", "description": "Temporarily removes a user."},
                    {"name": "/mute add", "description": "Prevents a user from sending messages."},
                    {"name": "/mute remove", "description": "Re-enables messaging for a user."},
                    {"name": "/warn add", "description": "Gives a user a warning."},
                    {"name": "/warn remove", "description": "Deletes a warning by Case ID."},
                    {"name": "/kick", "description": "Removes a user from the server."},
                    {"name": "/purge", "description": "Deletes specified messages."},
                    {"name": "/history", "description": "Displays moderation history."},
                    {"name": "/slowmode apply", "description": "Sets message cooldown."},
                    {"name": "/slowmode remove", "description": "Removes message cooldown."},
                    {"name": "/lock apply", "description": "Locks the channel for everyone."},
                    {"name": "/lock remove", "description": "Removes the lock from channel for everyone."},
                ]
            },
            "AI Settings": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/clark on", "description": "Turns the mention chatbot feature ON."},
                    {"name": "/clark off", "description": "Turns the mention chatbot feature OFF."},
                    {"name": "/clark mode", "description": "Changes Clark's personality mode."},
                    {"name": "/clark instruction", "description": "Set a custom system instruction."},
                    {"name": "/clark add_channel", "description": "Whitelist a channel for Clark."},
                    {"name": "/clark list_channels", "description": "List allowed channels."},
                    {"name": "/clark clear_channels", "description": "Respond in all channels."},
                    {"name": "/clark reset_instruction", "description": "Resets the current custom instruction (if any)."},
                ]
            },
            "Leveling": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/level rank", "description": "Check your or another user's rank card."},
                    {"name": "/level leaderboard", "description": "Displays the top 10 users."},
                    {"name": "/level config", "description": "Configure leveling settings."},
                ]
            },
            "Economy": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/economy-config", "description": "Higly customizable configuration of the economy."},
                    {"name": "/work", "description": "Work, get paid."},
                    {"name": "/scavenge", "description": "Scavenge, ged paid."},
                    {"name": "/hunt", "description": "Hunting, get paid."},
                    {"name": "/stream", "description": "Streaming, get donations."},
                    {"name": "/slut", "description": "High-risk street hustle for fast cash."},
                    {"name": "/slots", "description": "Risk your currency on the slot machine."},
                ]
            },
            "Verification": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/verification setup", "description": "Set up the verification system."},
                    {"name": "/verification message", "description": "Set up the custom verification message."},
                    {"name": "/verification disable", "description": "Disable the verification system."},
                    {"name": "/verification status", "description": "View verification configuration."},
                ]
            },
            "Roles": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/selfrole", "description": "Creates a persistent self-role menu."},
                    {"name": "/role add", "description": "Adds a role to a user."},
                    {"name": "/role remove", "description": "Removes a role from a user."},
                ]
            },
            "Automod": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/automod configure", "description": "Configure AutoMod safety settings."},
                ]
            },
            "Logging": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/log setup", "description": "Set up the logging channel."},
                    {"name": "/log disable", "description": "Disable the logging channel."},
                ]
            },
            "Other": {
                "emoji": CAT_EMOJI,
                "commands": [
                    {"name": "/thread create", "description": "Enable auto-threads for images."},
                    {"name": "/thread delete", "description": "Delete auto-threads for images."},
                    {"name": "/thread list", "description": "List all current enabled threads."},
                    {"name": "/message send", "description": "Send a Message Container or Plain Text (Highly customizable)."},
                    {"name": "/reminder", "description": "Set a reminder for yourself."},
                    {"name": "/sticky & /unsticky", "description": "Stick a message to the bottom of a channel, or remove the sticky message."},
                ]
            }
        }

    def create_help_view(self, title: str, description: str, guild: discord.Guild) -> ui.LayoutView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        gallery = ui.MediaGallery()
        gallery.add_item(media=HELP_BANNER_URL)

        container = ui.Container(header, sep, body, gallery)

        view = ui.LayoutView(timeout=None)
        view.add_item(container)
        view.add_item(ui.ActionRow(HelpSelect(self)))
        return view

    @app_commands.command(name="help", description="Displays a full list of commands.")
    async def help_command(self, interaction: discord.Interaction):
        # Acknowledge the interaction to stop the 'thinking' timeout
        await interaction.response.defer(ephemeral=True)
        
        try:
            initial_description = (
                "Welcome to the help panel! Please select a category from the dropdown menu below "
                "to see a detailed list of related commands."
            )
            
            # Build the layout
            help_view = self.create_help_view(
                title=f"{self.bot.user.name} Help Panel", 
                description=initial_description,
                guild=interaction.guild
            )

            # Finalize the interaction to remove the 'thinking' status
            await interaction.followup.send(view=help_view, ephemeral=True)
            
        except Exception as e:
            # Captures any remaining UI-specific initialization errors
            print(f"CRASH LOG: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Utilities(bot))