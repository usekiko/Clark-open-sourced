import discord
from discord.ext import commands
from discord import ui
import discord.app_commands as app_commands

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

class ExampleCog(commands.Cog):
    
    BOT_OWNER_ID = 465618379642896394 
    
    def __init__(self, bot):
        self.bot = bot
        self.synced_commands_cache = {}

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.wait_until_ready()
        
        self.synced_commands_cache = {}
        
        for command in self.bot.tree.walk_commands():
            cmd_id = getattr(command, 'id', None)
            
            if cmd_id:
                if not command.parent:
                    self.synced_commands_cache[command.name] = cmd_id
                else:
                    self.synced_commands_cache[command.parent.name] = cmd_id
        
        print(f"{Colors.CYAN}[OTHER]         [WelcomeMsgs] Cached {len(self.synced_commands_cache)} unique command IDs.{Colors.RESET}")

    def create_welcome_view(self):
        header = ui.TextDisplay("**Hi, I am Clark!**")
        sep1 = ui.Separator(spacing=discord.SeparatorSpacing.small)
        intro = ui.TextDisplay(
            "I require appropriate permissions to function properly. "
            "These are essential for moderation and other features to work effectively."
        )
        
        commands_header = ui.TextDisplay("**Commands**")
        sep2 = ui.Separator(spacing=discord.SeparatorSpacing.small)
        commands_body = ui.TextDisplay(
            "Use </help:0> to see all available commands, or visit [clarklabs.cc/commands](https://clarklabs.cc/commands)"
        )
        
        purpose_header = ui.TextDisplay("**Purpose**")
        sep3 = ui.Separator(spacing=discord.SeparatorSpacing.small)
        purpose_body = ui.TextDisplay(
            "AI-powered assistant for server management, including moderation, leveling, economy, and automation features."
        )
        
        data_header = ui.TextDisplay("**Data Storage**")
        sep4 = ui.Separator(spacing=discord.SeparatorSpacing.small)
        data_body = ui.TextDisplay(
            "View our [Privacy Policy](https://clarklabs.cc/privacy-policy). "
            "Only essential operational data is stored."
        )
        
        footer = ui.TextDisplay(
            "Restarts indicate feature updates. "
            "Join the [Support Server](https://discord.gg/V3DBj8fXzu) for assistance."
        )
        
        container = ui.Container(
            header, sep1, intro,
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            commands_header, sep2, commands_body,
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            purpose_header, sep3, purpose_body,
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            data_header, sep4, data_body,
            ui.Separator(spacing=discord.SeparatorSpacing.large),
            footer
        )
        
        action_row = ui.ActionRow().add_item(
            discord.ui.Button(
                label="Website",
                style=discord.ButtonStyle.link,
                url="https://clarklabs.cc/"
            )
        ).add_item(
            discord.ui.Button(
                label="Privacy Policy",
                style=discord.ButtonStyle.link,
                url="https://clarklabs.cc/privacy-policy"
            )
        ).add_item(
            discord.ui.Button(
                label="Terms of Service",
                style=discord.ButtonStyle.link,
                url="https://clarklabs.cc/terms-of-service"
            )
        ).add_item(
            discord.ui.Button(
                label="Command List",
                style=discord.ButtonStyle.link,
                url="https://clarklabs.cc/commands"
            )
        )
        
        view = ui.LayoutView()
        view.add_item(container)
        view.add_item(action_row)
        return view

    async def get_inviter(self, guild: discord.Guild) -> discord.Member | None:
        """Find who invited the bot using audit logs."""
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=10):
                if entry.target.id == self.bot.user.id:
                    return entry.user
        except Exception:
            pass
        return None
    
    async def send_dm_to_inviter(self, inviter: discord.User, guild: discord.Guild):
        """Send professional welcome DM to the person who invited the bot."""
        try:
            # Build the DM content
            header = ui.TextDisplay(f"**Thanks for adding {self.bot.user.name}!**")
            sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
            greeting = ui.TextDisplay(f"Hi {inviter.name}! I'm ready to help manage your server **{guild.name}** with AI-powered moderation, leveling, economy and more.")
            
            quick_start_header = ui.TextDisplay("**Quick Start**")
            quick_start_body = ui.TextDisplay(
                "Use </clark mode:0> to change AI personality\n"
                "Use </level config:0> to enable leveling\n"
                "Use </help:0> to see all commands"
            )
            
            important_header = ui.TextDisplay("**Important**")
            important_body = ui.TextDisplay("Make sure I have a role **higher** than the roles you want me to manage!")
            
            help_header = ui.TextDisplay("**Need Help?**")
            help_body = ui.TextDisplay("Use </help:0> in your server or join our support server.")
            
            container = ui.Container(
                header, sep, greeting, 
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                quick_start_header, quick_start_body,
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                important_header, important_body,
                ui.Separator(spacing=discord.SeparatorSpacing.large),
                help_header, help_body
            )
            
            action_row = ui.ActionRow().add_item(
                discord.ui.Button(
                    label="Support Server",
                    style=discord.ButtonStyle.link,
                    url="https://discord.gg/V3DBj8fXzu"
                )
            ).add_item(
                discord.ui.Button(
                    label="Vote on Top.gg",
                    style=discord.ButtonStyle.link,
                    url="https://top.gg/bot/1422636332454514779"
                )
            )
            
            view = ui.LayoutView()
            view.add_item(container)
            view.add_item(action_row)
            
            await inviter.send(view=view)
            print(f"{Colors.GREEN}[SUCCESS]       Sent welcome DM to {inviter.name} ({inviter.id}){Colors.RESET}")
        except discord.Forbidden:
            print(f"{Colors.YELLOW}[WARN]          Could not send DM to {inviter.name} - DMs disabled{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]         Failed to send DM to {inviter.name}: {e}{Colors.RESET}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        # Send DM to inviter
        inviter = await self.get_inviter(guild)
        if inviter:
            await self.send_dm_to_inviter(inviter, guild)
        
        # Send channel welcome message
        channel = None
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            channel = guild.system_channel
        else:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
        
        if channel is None:
            print(f"{Colors.RED}[ERROR]         Could not find a suitable channel in {guild.name} to send welcome message{Colors.RESET}")
            return
        
        view = self.create_welcome_view()
        
        try:
            await channel.send(view=view)
            print(f"{Colors.GREEN}[SUCCESS]       Sent welcome message to {guild.name} (ID: {guild.id}){Colors.RESET}")
        except discord.Forbidden:
            print(f"{Colors.RED}[ERROR]         Missing permissions to send welcome message in {guild.name}{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]         Error sending welcome message to {guild.name}: {e}{Colors.RESET}")


async def setup(bot):
    await bot.add_cog(ExampleCog(bot))