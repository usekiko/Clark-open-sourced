import discord
from discord.ext import commands
from discord import app_commands, ui
import aiomysql
import json
import random
import math
import datetime
import time
import traceback

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

class ResponseView(ui.LayoutView):
    def __init__(self, container: ui.Container, ephemeral: bool = False):
        super().__init__(timeout=None if not ephemeral else 300)
        self.add_item(container)

class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.EMOJIS = {
            'SUCCESS':  '<:excellent:1444475037938876427> ›  ',
            'ERROR':    '<:badconnection:1444475034482511872> ›  ',
            'INFO':     '<:unstableping:1444474533724684459> ›  ',
            'GAMBLE':   '<a:dice:1470523499021074543> '
        }
        self._settings_cache = {}
        self.response_thumbnail_accessory = None

    async def setup_database(self):
        await self.bot.wait_until_ready()
        if self.bot.user:
            self.response_thumbnail_accessory = ui.Thumbnail(media=self.bot.user.display_avatar.url)

        try:
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS economy_users (
                            guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
                            wallet BIGINT DEFAULT 0, bank BIGINT DEFAULT 0,
                            last_work BIGINT DEFAULT 0, last_slut BIGINT DEFAULT 0,
                            last_rob BIGINT DEFAULT 0, last_daily BIGINT DEFAULT 0,
                            last_stream BIGINT DEFAULT 0, last_hunt BIGINT DEFAULT 0,
                            last_scavenge BIGINT DEFAULT 0,
                            PRIMARY KEY (guild_id, user_id)
                        )
                    """)
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS economy_settings (
                            guild_id BIGINT PRIMARY KEY,
                            currency_name VARCHAR(32) DEFAULT 'Credits',
                            currency_symbol VARCHAR(32) DEFAULT '⌽',
                            daily_amount INT DEFAULT 2000,
                            work_min INT DEFAULT 100, work_max INT DEFAULT 500, work_cooldown INT DEFAULT 5,
                            stream_min INT DEFAULT 150, stream_max INT DEFAULT 800, stream_cooldown INT DEFAULT 15,
                            hunt_min INT DEFAULT 300, hunt_max INT DEFAULT 1200, hunt_cooldown INT DEFAULT 45,
                            scavenge_min INT DEFAULT 50, scavenge_max INT DEFAULT 300, scavenge_cooldown INT DEFAULT 5,
                            slut_min INT DEFAULT 200, slut_max INT DEFAULT 1000, slut_fail_rate INT DEFAULT 45, slut_cooldown INT DEFAULT 10,
                            rob_fail_rate INT DEFAULT 60, rob_min_wallet INT DEFAULT 500, rob_cooldown INT DEFAULT 30,
                            slots_fail_rate INT DEFAULT 35
                        )
                    """)
                    await conn.commit()
            print(f"{Colors.GREEN}[SUCCESS]      Economy synchronized. All systems active.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Failed to initialize economy tables: {e}{Colors.RESET}")

    async def get_config(self, guild_id: int):
        if guild_id in self._settings_cache:
            return self._settings_cache[guild_id]
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("INSERT INTO economy_settings (guild_id) VALUES (%s) ON DUPLICATE KEY UPDATE guild_id=guild_id", (guild_id,))
                await conn.commit()
                await cursor.execute("SELECT * FROM economy_settings WHERE guild_id = %s", (guild_id,))
                config = await cursor.fetchone()
                self._settings_cache[guild_id] = config
                return config

    def _create_styled_container(self, status: str, title: str, description: str, user: discord.User = None) -> ResponseView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        container = ui.Container(header, sep, body)
        return ResponseView(container)

    async def _get_user_data(self, guild_id: int, user_id: int):
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("INSERT INTO economy_users (guild_id, user_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE guild_id=guild_id", (guild_id, user_id))
                await conn.commit()
                await cursor.execute("SELECT * FROM economy_users WHERE guild_id = %s AND user_id = %s", (guild_id, user_id))
                return await cursor.fetchone()

    @app_commands.command(name="balance", description="Detailed audit of your wallet and vault liquidity.")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        user = member or interaction.user
        data = await self._get_user_data(interaction.guild.id, user.id)
        cfg = await self.get_config(interaction.guild.id)
        
        desc = (
            f"**Portfolio Analysis**\n"
            f"> **Wallet:** {data['wallet']:,} {cfg['currency_symbol']}\n"
            f"> **Bank:** {data['bank']:,} {cfg['currency_symbol']}\n\n"
            f"**Total Balance:** {data['wallet'] + data['bank']:,} {cfg['currency_name']}"
        )
        
        view = self._create_styled_container("SUCCESS", f"{user.display_name}'s Financial Profile", desc, user=user)
        await interaction.followup.send(view=view)

    @app_commands.command(name="daily", description="Claim your server-authorized daily stipend.")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild_id)
        data = await self._get_user_data(interaction.guild_id, interaction.user.id)
        
        now = int(time.time())
        if now < data['last_daily'] + 86400:
            rem = (data['last_daily'] + 86400) - now
            desc = f"> **The treasury is closed. Available in {rem//3600}h {(rem%3600)//60}m.**"
            view = self._create_styled_container("INFO", "Stipend Locked", desc)
            return await interaction.followup.send(view=view)

        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, last_daily = %s WHERE guild_id = %s AND user_id = %s", (cfg['daily_amount'], now, interaction.guild.id, interaction.user.id))
                await conn.commit()
        
        desc = f"> **Withdrew {cfg['daily_amount']:,} {cfg['currency_symbol']} from the treasury.**"
        view = self._create_styled_container("SUCCESS", "Daily Stipend", desc)
        await interaction.followup.send(view=view)

    @app_commands.command(name="work", description="Engage in professional labor for guaranteed income.")
    async def work(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cfg = await self.get_config(interaction.guild_id)
            data = await self._get_user_data(interaction.guild_id, interaction.user.id)
            
            now = int(time.time())
            cooldown_sec = (cfg['work_cooldown'] or 5) * 60  # Default 5 min if NULL
            last_work = data['last_work'] or 0
            
            if now < last_work + cooldown_sec:
                rem = (last_work + cooldown_sec) - now
                desc = f"> **Wait {rem//60}m {rem%60}s before your next shift.**"
                view = self._create_styled_container("INFO", "Exhausted", desc)
                return await interaction.followup.send(view=view)

            gain = random.randint(cfg['work_min'] or 100, cfg['work_max'] or 500)
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, last_work = %s WHERE guild_id = %s AND user_id = %s", (gain, now, interaction.guild.id, interaction.user.id))
                    await conn.commit()
            
            jobs = ["Virtual Real Estate Agent", "AI Ethicist", "Professional Meme Curator", "Lead Developer"]
            desc = f"> **Worked as a {random.choice(jobs)} and earned {gain:,} {cfg['currency_symbol']}.**"
            view = self._create_styled_container("SUCCESS", "Shift Ended", desc)
            await interaction.followup.send(view=view)
        except Exception as e:
            print(f"[ERROR] Work command failed: {e}")
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    @app_commands.command(name="stream", description="Host a livestream for viewer donations.")
    async def stream(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild_id)
        data = await self._get_user_data(interaction.guild_id, interaction.user.id)
        
        now = int(time.time())
        cooldown_sec = cfg['stream_cooldown'] * 60
        if now < data['last_stream'] + cooldown_sec:
            rem = (data['last_stream'] + cooldown_sec) - now
            desc = f"> **Wait {rem//60}m {rem%60}s to stream again.**"
            view = self._create_styled_container("INFO", "Offline", desc)
            return await interaction.followup.send(view=view)

        gain = random.randint(cfg['stream_min'], cfg['stream_max'])
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, last_stream = %s WHERE guild_id = %s AND user_id = %s", (gain, now, interaction.guild.id, interaction.user.id))
                await conn.commit()
        desc = f"> **Your stream was successful! Earned {gain:,} {cfg['currency_symbol']} in donations.**"
        view = self._create_styled_container("SUCCESS", "Stream Ended", desc)
        await interaction.followup.send(view=view)

    @app_commands.command(name="hunt", description="Venturing into the forest for resources.")
    async def hunt(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild_id)
        data = await self._get_user_data(interaction.guild_id, interaction.user.id)
        
        now = int(time.time())
        cooldown_sec = cfg['hunt_cooldown'] * 60
        if now < data['last_hunt'] + cooldown_sec:
            rem = (data['last_hunt'] + cooldown_sec) - now
            desc = f"> **The forest is empty. Wait {rem//60}m {rem%60}s.**"
            view = self._create_styled_container("INFO", "Forest Restock", desc)
            return await interaction.followup.send(view=view)

        gain = random.randint(cfg['hunt_min'], cfg['hunt_max'])
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, last_hunt = %s WHERE guild_id = %s AND user_id = %s", (gain, now, interaction.guild.id, interaction.user.id))
                await conn.commit()
        desc = f"> **Sold your trophy catch for {gain:,} {cfg['currency_symbol']}!**"
        view = self._create_styled_container("SUCCESS", "Hunt Conclusion", desc)
        await interaction.followup.send(view=view)

    @app_commands.command(name="scavenge", description="Exploring for high-quality scrap metal.")
    async def scavenge(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild_id)
        data = await self._get_user_data(interaction.guild_id, interaction.user.id)
        
        now = int(time.time())
        cooldown_sec = cfg['scavenge_cooldown'] * 60
        if now < data['last_scavenge'] + cooldown_sec:
            rem = (data['last_scavenge'] + cooldown_sec) - now
            desc = f"> **Wait {rem//60}m {rem%60}s for new salvage.**"
            view = self._create_styled_container("INFO", "Yard Empty", desc)
            return await interaction.followup.send(view=view)

        gain = random.randint(cfg['scavenge_min'], cfg['scavenge_max'])
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, last_scavenge = %s WHERE guild_id = %s AND user_id = %s", (gain, now, interaction.guild.id, interaction.user.id))
                await conn.commit()
        desc = f"> **Found high-quality salvage worth {gain:,} {cfg['currency_symbol']}!**"
        view = self._create_styled_container("SUCCESS", "Scavenge Results", desc)
        await interaction.followup.send(view=view)

    @app_commands.command(name="slut", description="Illegal Job: High-risk street hustle for fast cash.")
    async def slut(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild_id)
        data = await self._get_user_data(interaction.guild_id, interaction.user.id)
        
        now = int(time.time())
        cooldown_sec = cfg['slut_cooldown'] * 60
        if now < data['last_slut'] + cooldown_sec:
            rem = (data['last_slut'] + cooldown_sec) - now
            desc = f"> **Wait {rem//60}m {rem%60}s for the heat to die down.**"
            view = self._create_styled_container("INFO", "Street Heat", desc)
            return await interaction.followup.send(view=view)

        if random.randint(1, 100) <= cfg['slut_fail_rate']:
            loss = random.randint(200, 600)
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("UPDATE economy_users SET wallet = wallet - %s, last_slut = %s WHERE guild_id = %s AND user_id = %s", (loss, now, interaction.guild.id, interaction.user.id))
                    await conn.commit()
            desc = f"> **Authorities intercepted the hustle. Fined {loss:,} {cfg['currency_symbol']}.**"
            view = self._create_styled_container("ERROR", "Intercepted", desc)
        else:
            gain = random.randint(cfg['slut_min'], cfg['slut_max'])
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, last_slut = %s WHERE guild_id = %s AND user_id = %s", (gain, now, interaction.guild.id, interaction.user.id))
                    await conn.commit()
            desc = f"> **The hustle was successful. Earned {gain:,} {cfg['currency_symbol']}!**"
            view = self._create_styled_container("SUCCESS", "Hustle Paid", desc)
        await interaction.followup.send(view=view)

    @app_commands.command(name="rob", description="Heist another user for a percentage of their wallet.")
    async def rob(self, interaction: discord.Interaction, target: discord.Member):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)
        if target.id == interaction.user.id: 
            desc = "> **Self-robbery is prohibited.**"
            view = self._create_styled_container("ERROR", "Constraint Error", desc)
            return await interaction.followup.send(view=view)
            
        data, now = await self._get_user_data(interaction.guild.id, interaction.user.id), int(time.time())
        cooldown_sec = cfg['rob_cooldown'] * 60
        if now < data['last_rob'] + cooldown_sec:
            rem = (data['last_rob'] + cooldown_sec) - now
            desc = f"> **Wait {rem//60}m {rem%60}s before your next attempt.**"
            view = self._create_styled_container("INFO", "Surveillance", desc)
            return await interaction.followup.send(view=view)

        vic = await self._get_user_data(interaction.guild.id, target.id)
        if vic['wallet'] < cfg['rob_min_wallet']: 
            desc = f"> **Target wallet is below the threshold (Min {cfg['rob_min_wallet']} required).**"
            view = self._create_styled_container("INFO", "Poor Target", desc)
            return await interaction.followup.send(view=view)

        if random.randint(1, 100) <= cfg['rob_fail_rate']:
            fine = random.randint(400, 1000)
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("UPDATE economy_users SET wallet = wallet - %s, last_rob = %s WHERE guild_id = %s AND user_id = %s", (fine, now, interaction.guild.id, interaction.user.id))
                    await conn.commit()
            desc = f"> **Heist blown! You were caught and paid {fine} {cfg['currency_symbol']} in legal fees.**"
            view = self._create_styled_container("ERROR", "Heist Failed", desc)
        else:
            stolen = random.randint(100, int(vic['wallet'] * 0.45))
            async with self.bot.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, last_rob = %s WHERE guild_id = %s AND user_id = %s", (stolen, now, interaction.guild.id, interaction.user.id))
                    await cursor.execute("UPDATE economy_users SET wallet = wallet - %s WHERE guild_id = %s AND user_id = %s", (stolen, interaction.guild.id, target.id))
                    await conn.commit()
            desc = f"> **Successful heist! Snatched {stolen:,} {cfg['currency_symbol']} from {target.mention}!**"
            view = self._create_styled_container("SUCCESS", "Clean Job", desc)
        await interaction.followup.send(view=view)

    @app_commands.command(name="deposit", description="Transfer cash to vault.")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)
        data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        try: amt = data['wallet'] if amount.lower() == 'all' else int(amount)
        except: 
            view = self._create_styled_container("ERROR", "Input Error", "> **Numeric input or 'all' is required.**")
            return await interaction.followup.send(view=view)
            
        if amt <= 0 or data['wallet'] < amt: 
            view = self._create_styled_container("ERROR", "Insufficient Funds", "> **You do not have enough liquid funds to deposit.**")
            return await interaction.followup.send(view=view)
            
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE economy_users SET wallet = wallet - %s, bank = bank + %s WHERE guild_id = %s AND user_id = %s", (amt, amt, interaction.guild.id, interaction.user.id))
                await conn.commit()
        desc = f"> **Stored {amt:,} {cfg['currency_symbol']} in the vault security system.**"
        await interaction.followup.send(view=self._create_styled_container("SUCCESS", "Vault Deposit", desc))

    @app_commands.command(name="withdraw", description="Release currency from vault.")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)
        data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        try: amt = data['bank'] if amount.lower() == 'all' else int(amount)
        except: 
            view = self._create_styled_container("ERROR", "Input Error", "> **Numeric input or 'all' is required.**")
            return await interaction.followup.send(view=view)
            
        if amt <= 0 or data['bank'] < amt: 
            view = self._create_styled_container("ERROR", "Insufficient Funds", "> **You do not have enough vault balance to withdraw.**")
            return await interaction.followup.send(view=view)
            
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE economy_users SET wallet = wallet + %s, bank = bank - %s WHERE guild_id = %s AND user_id = %s", (amt, amt, interaction.guild.id, interaction.user.id))
                await conn.commit()
        desc = f"> **Released {amt:,} {cfg['currency_symbol']} into your active wallet.**"
        await interaction.followup.send(view=self._create_styled_container("SUCCESS", "Vault Withdrawal", desc))

    @app_commands.command(name="pay", description="Transfer currency to another user.")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)
        
        if member.id == interaction.user.id:
            desc = "> **You cannot transfer currency to yourself.**"
            view = self._create_styled_container("ERROR", "Invalid Transfer", desc)
            return await interaction.followup.send(view=view)
        
        if member.bot:
            desc = "> **You cannot transfer currency to bots.**"
            view = self._create_styled_container("ERROR", "Invalid Recipient", desc)
            return await interaction.followup.send(view=view)
        
        if amount <= 0:
            desc = "> **Amount must be greater than 0.**"
            view = self._create_styled_container("ERROR", "Invalid Amount", desc)
            return await interaction.followup.send(view=view)
        
        sender_data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        
        if sender_data['wallet'] < amount:
            desc = f"> **You do not have enough {cfg['currency_name']} in your wallet.**"
            view = self._create_styled_container("ERROR", "Insufficient Funds", desc)
            return await interaction.followup.send(view=view)
        
        # Get or create recipient data
        recipient_data = await self._get_user_data(interaction.guild.id, member.id)
        
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Deduct from sender
                await cursor.execute(
                    "UPDATE economy_users SET wallet = wallet - %s WHERE guild_id = %s AND user_id = %s",
                    (amount, interaction.guild.id, interaction.user.id)
                )
                # Add to recipient
                await cursor.execute(
                    "UPDATE economy_users SET wallet = wallet + %s WHERE guild_id = %s AND user_id = %s",
                    (amount, interaction.guild.id, member.id)
                )
                await conn.commit()
        
        desc = f"> **Transferred {amount:,} {cfg['currency_symbol']} to {member.mention}.**"
        view = self._create_styled_container("SUCCESS", "Transfer Complete", desc)
        await interaction.followup.send(view=view)

    @app_commands.command(name="slots", description="Risk your currency on the high-end slot machine.")
    async def slots(self, interaction: discord.Interaction, bet: int):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)
        if bet < 50: 
            return await interaction.followup.send(view=self._create_styled_container("ERROR", "Min Bet", f"> **Minimum bet is 50 {cfg['currency_name']}.**"))
            
        data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        if data['wallet'] < bet: 
            return await interaction.followup.send(view=self._create_styled_container("ERROR", "Insufficient Funds", "> **Wallet balance too low for this bet.**"))
        
        icons = ["<:diamond:1470522339958460591>", "<:cherry:1470522699364171879>", "<:ticket:1470523139229483151>", "<:gold:1470522343267766373>", "<:emerald:1470522362003718348>", "<:quartz:1470522360212750572>"]
        fail_rate = cfg.get('slots_fail_rate', 35)

        if random.randint(1, 100) <= fail_rate:
            r = random.sample(icons, 3)
        else:
            if random.random() < 0.5:
                icon = random.choice(icons)
                r = [icon, icon, icon]
            else:
                match_icon = random.choice(icons)
                other_icon = random.choice([i for i in icons if i != match_icon])
                r = [match_icon, match_icon, other_icon]
                random.shuffle(r)

        if r[0] == r[1] == r[2]:
            win = bet * (15 if r[0] == "<:quartz:1470522360212750572>" else 10)
            status, msg = "SUCCESS", f"JACKPOT! You won {win:,}!"
        elif r[0] == r[1] or r[1] == r[2] or r[0] == r[2]:
            win = int(bet * 1.5)
            status, msg = "INFO", f"Match! You won {win:,}."
        else: 
            win = -bet
            status, msg = "ERROR", f"No Luck. Lost {bet:,}."
        
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE economy_users SET wallet = wallet + %s WHERE guild_id = %s AND user_id = %s", (win, interaction.guild.id, interaction.user.id))
                await conn.commit()
        
        desc = (
            f"**Spin Results**\n"
            f"> **[ {r[0]} | {r[1]} | {r[2]} ]**\n\n"
            f"**{msg}**"
        )
        await interaction.followup.send(view=self._create_styled_container(status, "Slot Machine", desc, user=interaction.user))

    @app_commands.command(name="economy-config", description="Admin: Configure all economy variables.")
    @app_commands.describe(slots_fail_rate="Percentage (1-100) of spins that will be forced losses.")
    @app_commands.checks.has_permissions(administrator=True)
    async def econ_config(self, interaction: discord.Interaction, 
                         currency_name: str = None, symbol: str = None, daily_amount: int = None,
                         work_min: int = None, work_max: int = None, work_cooldown: int = None,
                         stream_min: int = None, stream_max: int = None, stream_cooldown: int = None,
                         hunt_min: int = None, hunt_max: int = None, hunt_cooldown: int = None,
                         scavenge_min: int = None, scavenge_max: int = None, scavenge_cooldown: int = None,
                         slut_min: int = None, slut_max: int = None, slut_cooldown: int = None,
                         rob_cooldown: int = None, rob_min_wallet: int = None, slut_fail_rate: int = None, 
                         rob_fail_rate: int = None, slots_fail_rate: int = None):
        await interaction.response.defer(ephemeral=True)
        
        # Whitelist of allowed columns to prevent SQL injection
        ALLOWED_COLUMNS = {
            "currency_name", "currency_symbol", "daily_amount",
            "work_min", "work_max", "work_cooldown",
            "stream_min", "stream_max", "stream_cooldown",
            "hunt_min", "hunt_max", "hunt_cooldown",
            "scavenge_min", "scavenge_max", "scavenge_cooldown",
            "slut_min", "slut_max", "slut_cooldown", "slut_fail_rate",
            "rob_cooldown", "rob_min_wallet", "rob_fail_rate", "slots_fail_rate"
        }
        
        updates, params = [], []
        mappings = {
            "currency_name": currency_name, "currency_symbol": symbol, "daily_amount": daily_amount,
            "work_min": work_min, "work_max": work_max, "work_cooldown": work_cooldown,
            "stream_min": stream_min, "stream_max": stream_max, "stream_cooldown": stream_cooldown,
            "hunt_min": hunt_min, "hunt_max": hunt_max, "hunt_cooldown": hunt_cooldown,
            "scavenge_min": scavenge_min, "scavenge_max": scavenge_max, "scavenge_cooldown": scavenge_cooldown,
            "slut_min": slut_min, "slut_max": slut_max, "slut_cooldown": slut_cooldown, "slut_fail_rate": slut_fail_rate,
            "rob_cooldown": rob_cooldown, "rob_min_wallet": rob_min_wallet, "rob_fail_rate": rob_fail_rate,
            "slots_fail_rate": slots_fail_rate
        }
        for col, val in mappings.items():
            if val is not None and col in ALLOWED_COLUMNS:
                updates.append(f"{col} = %s")
                params.append(val)
        
        async with self.bot.db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT INTO economy_settings (guild_id) VALUES (%s) ON DUPLICATE KEY UPDATE guild_id=guild_id", (interaction.guild.id,))
                if updates:
                    params.append(interaction.guild.id)
                    await cursor.execute(f"UPDATE economy_settings SET {', '.join(updates)} WHERE guild_id = %s", tuple(params))
                await conn.commit()
                
        self._settings_cache.pop(interaction.guild.id, None)
        desc = "> **Changes applied!**"
        view = self._create_styled_container("SUCCESS", "System Configured", desc)
        await interaction.followup.send(view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        desc = f"> **{str(error)}**"
        view = self._create_styled_container("ERROR", "Constraint Error", desc)
        if not interaction.response.is_done(): 
            await interaction.response.send_message(view=view, ephemeral=True)
        else: 
            await interaction.followup.send(view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))