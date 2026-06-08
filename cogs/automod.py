import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import asyncio
import logging

from utils import styled_view

logger = logging.getLogger("AutoModCog")

class AutoMod(commands.GroupCog, name="automod"):
    def __init__(self, bot):
        self.bot = bot
        # Default bad words list with wildcards
        self.default_bad_words = [
            "fuck*", "shit*", "bitch*", "nigger*", "nigga*", "cunt*", "pussy*", 
            "faggot*", "retard*", "kys", "suicide", "porn*", "nude*"
        ]
        self.gif_patterns = ["*.gif", "*tenor.com*", "*giphy.com*"]


    async def get_rule_by_name(self, guild: discord.Guild, name: str):
        """Finds an existing AutoMod rule by name."""
        try:
            rules = await guild.fetch_automod_rules()
            return discord.utils.get(rules, name=name)
        except Exception:
            return None

    @app_commands.command(name="configure", description="Configure AutoMod safety settings")
    @app_commands.describe(
        block_bad_words="Enable or disable the bad words filter",
        custom_words="Comma-separated list of extra words to block",
        block_gifs="Enable or disable GIF blocking",
        mention_limit="Max mentions allowed per message (0 to disable)",
        timeout_duration="Minutes to timeout offenders (0 for none)",
        log_channel="Channel where AutoMod alerts should be sent"
    )
    @commands.has_permissions(administrator=True)
    async def configure(
        self, 
        itx: discord.Interaction, 
        block_bad_words: bool = None,
        custom_words: str = None,
        block_gifs: bool = None,
        mention_limit: int = None,
        timeout_duration: int = 0,
        log_channel: discord.TextChannel = None
    ):
        await itx.response.defer(ephemeral=True)
        guild = itx.guild
        
        # Define actions
        primary_actions = [discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message)]
        
        # Add alert channel if specified
        if log_channel:
            primary_actions.append(discord.AutoModRuleAction(
                type=discord.AutoModRuleActionType.send_alert_message,
                channel_id=log_channel.id
            ))

        # Add timeout if specified
        if timeout_duration > 0:
            primary_actions.append(discord.AutoModRuleAction(
                type=discord.AutoModRuleActionType.timeout,
                duration=datetime.timedelta(minutes=timeout_duration)
            ))

        log_changes = []

        try:
            # --- Bad Words Rule ---
            if block_bad_words is not None or custom_words:
                rule_name = "Safety: Bad Words"
                existing = await self.get_rule_by_name(guild, rule_name)
                
                word_list = self.default_bad_words
                if custom_words:
                    word_list += [w.strip() for w in custom_words.split(",")]

                if block_bad_words is False and existing:
                    await existing.delete(reason="AutoMod Reset")
                    log_changes.append("Disabled Bad Words filter (Rule Removed)")
                else:
                    trigger = discord.AutoModTrigger(
                        type=discord.AutoModRuleTriggerType.keyword,
                        keyword_filter=word_list
                    )
                    if existing:
                        await existing.edit(trigger=trigger, actions=primary_actions, enabled=True)
                    else:
                        await guild.create_automod_rule(
                            name=rule_name,
                            event_type=discord.AutoModRuleEventType.message_send,
                            trigger=trigger,
                            actions=primary_actions,
                            enabled=True
                        )
                    log_changes.append("Updated Bad Words filter")

            # --- GIF Blocking Rule ---
            if block_gifs is not None:
                rule_name = "Safety: Block GIFs"
                existing = await self.get_rule_by_name(guild, rule_name)

                if block_gifs is False and existing:
                    await existing.delete(reason="AutoMod Reset")
                    log_changes.append("Disabled GIF blocking (Rule Removed)")
                elif block_gifs is True:
                    trigger = discord.AutoModTrigger(
                        type=discord.AutoModRuleTriggerType.keyword,
                        keyword_filter=self.gif_patterns
                    )
                    if existing:
                        await existing.edit(trigger=trigger, actions=primary_actions, enabled=True)
                    else:
                        await guild.create_automod_rule(
                            name=rule_name,
                            event_type=discord.AutoModRuleEventType.message_send,
                            trigger=trigger,
                            actions=primary_actions,
                            enabled=True
                        )
                    log_changes.append("Enabled GIF blocking")

            # --- Mention Spam Rule ---
            if mention_limit is not None:
                rule_name = "Safety: Mention Spam"
                existing = await self.get_rule_by_name(guild, rule_name)

                if mention_limit <= 0 and existing:
                    await existing.delete(reason="AutoMod Reset")
                    log_changes.append("Disabled Mention Spam filter (Rule Removed)")
                elif mention_limit > 0:
                    trigger = discord.AutoModTrigger(
                        type=discord.AutoModRuleTriggerType.mention_spam,
                        mention_limit=mention_limit
                    )
                    if existing:
                        await existing.edit(trigger=trigger, actions=primary_actions, enabled=True)
                    else:
                        await guild.create_automod_rule(
                            name=rule_name,
                            event_type=discord.AutoModRuleEventType.message_send,
                            trigger=trigger,
                            actions=primary_actions,
                            enabled=True
                        )
                    log_changes.append(f"Set Mention Limit to {mention_limit}")

            if not log_changes:
                return await itx.followup.send(view=styled_view("No Changes", "No changes were specified."))

            summary = "\n".join(log_changes)
            await itx.followup.send(view=styled_view("AutoMod Configuration", summary))

        except discord.Forbidden:
            await itx.followup.send(view=styled_view("Error", "Insufficient permissions. Administrator access required."))
        except Exception as e:
            logger.error(f"AutoMod Config Error: {e}")
            await itx.followup.send(view=styled_view("Error", str(e)))

async def setup(bot):
    await bot.add_cog(AutoMod(bot))