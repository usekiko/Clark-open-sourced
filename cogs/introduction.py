import discord
from discord.ext import commands
from discord import ui
import discord.app_commands as app_commands

from utils import Colors, embed

LINKS = {
    "Website": "https://clarklabs.cc/",
    "Privacy Policy": "https://clarklabs.cc/privacy-policy",
    "Terms of Service": "https://clarklabs.cc/terms-of-service",
    "Command List": "https://clarklabs.cc/commands",
}
SUPPORT_SERVER = "https://discord.gg/V3DBj8fXzu"
TOPGG = "https://top.gg/bot/1422636332454514779"


def link_row(**links) -> ui.View:
    """Row of link buttons. Embeds can't hold buttons so this rides alongside."""
    view = ui.View(timeout=None)
    for label, url in links.items():
        view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=url))
    return view


class ExampleCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def welcome_embed(self) -> discord.Embed:
        """Posted in the server when Clark is added."""
        e = embed(
            "Hi, I am Clark!",
            "I need the right permissions to work properly - moderation and the rest "
            "rely on them.",
        )
        e.add_field(
            name="Commands",
            value=f"Use `/help` to see everything, or visit [clarklabs.cc]({LINKS['Command List']}).",
            inline=False,
        )
        e.add_field(
            name="Purpose",
            value="AI chatbot plus moderation, automod, logging, economy and welcome messages.",
            inline=False,
        )
        e.add_field(
            name="Data Storage",
            value=f"Only what's needed to run. See the [Privacy Policy]({LINKS['Privacy Policy']}).",
            inline=False,
        )
        e.set_footer(text="Restarts mean feature updates.")
        return e

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
            e = embed(
                f"Thanks for adding {self.bot.user.name}!",
                f"Hi {inviter.name}! I'm ready to help run **{guild.name}**.",
            )
            e.add_field(
                name="Quick Start",
                value="`/clark mode` to change the AI personality\n"
                      "`/automod configure` to set up filtering\n"
                      "`/help` to see everything",
                inline=False,
            )
            e.add_field(
                name="Important",
                value="Give me a role **above** the roles you want me to manage.",
                inline=False,
            )
            e.add_field(name="Need Help?", value="Run `/help`, or join the support server.", inline=False)

            await inviter.send(embed=e, view=link_row(**{'Support Server': SUPPORT_SERVER, 'Vote on Top.gg': TOPGG}))
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
        
        e = self.welcome_embed()
        
        try:
            await channel.send(embed=e, view=link_row(**LINKS))
            print(f"{Colors.GREEN}[SUCCESS]       Sent welcome message to {guild.name} (ID: {guild.id}){Colors.RESET}")
        except discord.Forbidden:
            print(f"{Colors.RED}[ERROR]         Missing permissions to send welcome message in {guild.name}{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]         Error sending welcome message to {guild.name}: {e}{Colors.RESET}")


async def setup(bot):
    await bot.add_cog(ExampleCog(bot))