import discord
from discord.ext import commands
from discord import app_commands
import random
import time

from utils import Colors, embed

# Cache TTL in seconds
_CACHE_TTL = 300  # 5 minutes


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._settings_cache: dict[int, tuple[dict, float]] = {}  # guild_id -> (data, expiry_ts)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def setup_database(self):
        await self.bot.wait_until_ready()
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS economy_users (
                        guild_id BIGINT NOT NULL,
                        user_id  BIGINT NOT NULL,
                        wallet   BIGINT DEFAULT 0,
                        bank     BIGINT DEFAULT 0,
                        last_work     BIGINT DEFAULT 0,
                        last_slut     BIGINT DEFAULT 0,
                        last_rob      BIGINT DEFAULT 0,
                        last_daily    BIGINT DEFAULT 0,
                        last_stream   BIGINT DEFAULT 0,
                        last_hunt     BIGINT DEFAULT 0,
                        last_scavenge BIGINT DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id)
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS economy_settings (
                        guild_id       BIGINT PRIMARY KEY,
                        currency_name  VARCHAR(32) DEFAULT 'Credits',
                        currency_symbol VARCHAR(32) DEFAULT '💵',
                        daily_amount   INT DEFAULT 2000,
                        work_min       INT DEFAULT 100,
                        work_max       INT DEFAULT 500,
                        work_cooldown  INT DEFAULT 5,
                        stream_min     INT DEFAULT 150,
                        stream_max     INT DEFAULT 800,
                        stream_cooldown INT DEFAULT 15,
                        hunt_min       INT DEFAULT 300,
                        hunt_max       INT DEFAULT 1200,
                        hunt_cooldown  INT DEFAULT 45,
                        scavenge_min   INT DEFAULT 50,
                        scavenge_max   INT DEFAULT 300,
                        scavenge_cooldown INT DEFAULT 5,
                        slut_min       INT DEFAULT 200,
                        slut_max       INT DEFAULT 1000,
                        slut_fail_rate INT DEFAULT 45,
                        slut_cooldown  INT DEFAULT 10,
                        rob_fail_rate  INT DEFAULT 60,
                        rob_min_wallet INT DEFAULT 500,
                        rob_cooldown   INT DEFAULT 30,
                        slots_fail_rate INT DEFAULT 35
                    )
                """)
                # Migrate any legacy ⌽ symbols in existing rows
                await conn.execute(
                    "UPDATE economy_settings SET currency_symbol = '💵' WHERE currency_symbol = '⌽'"
                )
            print(f"{Colors.GREEN}[SUCCESS]      Economy synchronized. All systems active.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR]        Failed to initialize economy tables: {e}{Colors.RESET}")

    async def get_config(self, guild_id: int):
        """Return economy settings for a guild. Cached with 5-minute TTL."""
        cached, expiry = self._settings_cache.get(guild_id, (None, 0))
        if cached and time.monotonic() < expiry:
            return cached
        async with self.bot.db_pool.acquire() as conn:
            # Single query: insert if missing, then return the row
            config = await conn.fetchrow("""
                INSERT INTO economy_settings (guild_id)
                VALUES ($1)
                ON CONFLICT (guild_id) DO UPDATE SET guild_id = EXCLUDED.guild_id
                RETURNING *
            """, guild_id)
        config = dict(config)
        self._settings_cache[guild_id] = (config, time.monotonic() + _CACHE_TTL)
        return config

    async def _get_user_data(self, guild_id: int, user_id: int):
        """Upsert and return user economy row in a single query."""
        async with self.bot.db_pool.acquire() as conn:
            return await conn.fetchrow("""
                INSERT INTO economy_users (guild_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET guild_id = EXCLUDED.guild_id
                RETURNING *
            """, guild_id, user_id)

    # ------------------------------------------------------------------
    # UI factory
    # ------------------------------------------------------------------

    @staticmethod
    def _embed(title: str, description: str) -> discord.Embed:
        return embed(title, description)

    @staticmethod
    def _card(title: str, description: str, avatar_url: str) -> discord.Embed:
        """Balance card - same as _embed but with the user's avatar on the right."""
        return embed(title, description, thumbnail=avatar_url)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @app_commands.command(name="balance", description="Detailed audit of your wallet and vault liquidity.")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        try:
            user = member or interaction.user
            data = await self._get_user_data(interaction.guild.id, user.id)
            cfg  = await self.get_config(interaction.guild.id)

            sym = cfg['currency_symbol']
            desc = (
                f"Wallet: {data['wallet']:,} {sym}\n"
                f"Bank: {data['bank']:,} {sym}\n\n"
                f"Total Balance: {data['wallet'] + data['bank']:,} {cfg['currency_name']}"
            )
            e = self._card(f"{user.display_name}'s Financial Profile", desc, user.display_avatar.url)
            await interaction.followup.send(embed=e)
        except Exception as e:
            print(f"[ERROR] Balance command failed: {e}")
            await interaction.followup.send(embed=self._embed("Error", f"Something went wrong: {e}"), ephemeral=True)

    @app_commands.command(name="daily", description="Claim your server-authorized daily stipend.")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cfg  = await self.get_config(interaction.guild_id)
            data = await self._get_user_data(interaction.guild_id, interaction.user.id)

            now = int(time.time())
            if now < data['last_daily'] + 86400:
                rem  = (data['last_daily'] + 86400) - now
                e = self._embed("Stipend Locked", f"The treasury is closed. Available in {rem//3600}h {(rem%3600)//60}m.")
                return await interaction.followup.send(embed=e)

            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet + $1, last_daily = $2 WHERE guild_id = $3 AND user_id = $4",
                    cfg['daily_amount'], now, interaction.guild.id, interaction.user.id
                )

            e = self._embed("Daily Stipend", f"Withdrew {cfg['daily_amount']:,} {cfg['currency_symbol']} from the treasury.")
            await interaction.followup.send(embed=e)
        except Exception as e:
            print(f"[ERROR] Daily command failed: {e}")
            await interaction.followup.send(embed=self._embed("Error", str(e)), ephemeral=True)

    @app_commands.command(name="work", description="Engage in professional labor for guaranteed income.")
    async def work(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cfg  = await self.get_config(interaction.guild_id)
            data = await self._get_user_data(interaction.guild_id, interaction.user.id)

            now          = int(time.time())
            cooldown_sec = (cfg['work_cooldown'] or 5) * 60
            last_work    = data['last_work'] or 0

            if now < last_work + cooldown_sec:
                rem  = (last_work + cooldown_sec) - now
                e = self._embed("Exhausted", f"Wait {rem//60}m {rem%60}s before your next shift.")
                return await interaction.followup.send(embed=e)

            gain = random.randint(cfg['work_min'] or 100, cfg['work_max'] or 500)
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet + $1, last_work = $2 WHERE guild_id = $3 AND user_id = $4",
                    gain, now, interaction.guild.id, interaction.user.id
                )

            jobs = ["Virtual Real Estate Agent", "AI Ethicist", "Professional Meme Curator", "Lead Developer"]
            e = self._embed("Shift Ended", f"Worked as a {random.choice(jobs)} and earned {gain:,} {cfg['currency_symbol']}.")
            await interaction.followup.send(embed=e)
        except Exception as e:
            print(f"[ERROR] Work command failed: {e}")
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    @app_commands.command(name="stream", description="Host a livestream for viewer donations.")
    async def stream(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cfg  = await self.get_config(interaction.guild_id)
            data = await self._get_user_data(interaction.guild_id, interaction.user.id)

            now          = int(time.time())
            cooldown_sec = cfg['stream_cooldown'] * 60
            if now < data['last_stream'] + cooldown_sec:
                rem  = (data['last_stream'] + cooldown_sec) - now
                e = self._embed("Offline", f"Wait {rem//60}m {rem%60}s to stream again.")
                return await interaction.followup.send(embed=e)

            gain = random.randint(cfg['stream_min'], cfg['stream_max'])
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet + $1, last_stream = $2 WHERE guild_id = $3 AND user_id = $4",
                    gain, now, interaction.guild.id, interaction.user.id
                )
            e = self._embed("Stream Ended", f"Your stream was successful! Earned {gain:,} {cfg['currency_symbol']} in donations.")
            await interaction.followup.send(embed=e)
        except Exception as e:
            print(f"[ERROR] Stream command failed: {e}")
            await interaction.followup.send(embed=self._embed("Error", str(e)), ephemeral=True)

    @app_commands.command(name="hunt", description="Venture into the forest for resources.")
    async def hunt(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cfg  = await self.get_config(interaction.guild_id)
            data = await self._get_user_data(interaction.guild_id, interaction.user.id)

            now          = int(time.time())
            cooldown_sec = cfg['hunt_cooldown'] * 60
            if now < data['last_hunt'] + cooldown_sec:
                rem  = (data['last_hunt'] + cooldown_sec) - now
                e = self._embed("Forest Restock", f"The forest is empty. Wait {rem//60}m {rem%60}s.")
                return await interaction.followup.send(embed=e)

            gain = random.randint(cfg['hunt_min'], cfg['hunt_max'])
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet + $1, last_hunt = $2 WHERE guild_id = $3 AND user_id = $4",
                    gain, now, interaction.guild.id, interaction.user.id
                )
            e = self._embed("Hunt Conclusion", f"Sold your trophy catch for {gain:,} {cfg['currency_symbol']}!")
            await interaction.followup.send(embed=e)
        except Exception as e:
            print(f"[ERROR] Hunt command failed: {e}")
            await interaction.followup.send(embed=self._embed("Error", str(e)), ephemeral=True)

    @app_commands.command(name="scavenge", description="Explore for high-quality scrap metal.")
    async def scavenge(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            cfg  = await self.get_config(interaction.guild_id)
            data = await self._get_user_data(interaction.guild_id, interaction.user.id)

            now          = int(time.time())
            cooldown_sec = cfg['scavenge_cooldown'] * 60
            if now < data['last_scavenge'] + cooldown_sec:
                rem  = (data['last_scavenge'] + cooldown_sec) - now
                e = self._embed("Yard Empty", f"Wait {rem//60}m {rem%60}s for new salvage.")
                return await interaction.followup.send(embed=e)

            gain = random.randint(cfg['scavenge_min'], cfg['scavenge_max'])
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet + $1, last_scavenge = $2 WHERE guild_id = $3 AND user_id = $4",
                    gain, now, interaction.guild.id, interaction.user.id
                )
            e = self._embed("Scavenge Results", f"Found high-quality salvage worth {gain:,} {cfg['currency_symbol']}!")
            await interaction.followup.send(embed=e)
        except Exception as e:
            print(f"[ERROR] Scavenge command failed: {e}")
            await interaction.followup.send(embed=self._embed("Error", str(e)), ephemeral=True)

    @app_commands.command(name="slut", description="Illegal Job: High-risk street hustle for fast cash.")
    async def slut(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cfg  = await self.get_config(interaction.guild_id)
        data = await self._get_user_data(interaction.guild_id, interaction.user.id)

        now          = int(time.time())
        cooldown_sec = cfg['slut_cooldown'] * 60
        if now < data['last_slut'] + cooldown_sec:
            rem  = (data['last_slut'] + cooldown_sec) - now
            e = self._embed("Street Heat", f"Wait {rem//60}m {rem%60}s for the heat to die down.")
            return await interaction.followup.send(embed=e)

        if random.randint(1, 100) <= cfg['slut_fail_rate']:
            loss = random.randint(200, 600)
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet - $1, last_slut = $2 WHERE guild_id = $3 AND user_id = $4",
                    loss, now, interaction.guild.id, interaction.user.id
                )
            e = self._embed("Intercepted", f"Authorities intercepted the hustle. Fined {loss:,} {cfg['currency_symbol']}.")
        else:
            gain = random.randint(cfg['slut_min'], cfg['slut_max'])
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet + $1, last_slut = $2 WHERE guild_id = $3 AND user_id = $4",
                    gain, now, interaction.guild.id, interaction.user.id
                )
            e = self._embed("Hustle Paid", f"The hustle was successful. Earned {gain:,} {cfg['currency_symbol']}!")
        await interaction.followup.send(embed=e)

    @app_commands.command(name="rob", description="Heist another user for a percentage of their wallet.")
    async def rob(self, interaction: discord.Interaction, target: discord.Member):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)
        if target.id == interaction.user.id:
            return await interaction.followup.send(embed=self._embed("Constraint Error", "Self-robbery is prohibited."))

        now          = int(time.time())
        data         = await self._get_user_data(interaction.guild.id, interaction.user.id)
        cooldown_sec = cfg['rob_cooldown'] * 60
        if now < data['last_rob'] + cooldown_sec:
            rem  = (data['last_rob'] + cooldown_sec) - now
            e = self._embed("Surveillance", f"Wait {rem//60}m {rem%60}s before your next attempt.")
            return await interaction.followup.send(embed=e)

        vic = await self._get_user_data(interaction.guild.id, target.id)
        if vic['wallet'] < cfg['rob_min_wallet']:
            e = self._embed("Poor Target", f"Target wallet is below the threshold (Min {cfg['rob_min_wallet']} required).")
            return await interaction.followup.send(embed=e)

        if random.randint(1, 100) <= cfg['rob_fail_rate']:
            fine = random.randint(400, 1000)
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet - $1, last_rob = $2 WHERE guild_id = $3 AND user_id = $4",
                    fine, now, interaction.guild.id, interaction.user.id
                )
            e = self._embed("Heist Failed", f"Heist blown! You were caught and paid {fine} {cfg['currency_symbol']} in legal fees.")
        else:
            stolen = random.randint(100, max(100, int(vic['wallet'] * 0.45)))
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet + $1, last_rob = $2 WHERE guild_id = $3 AND user_id = $4",
                    stolen, now, interaction.guild.id, interaction.user.id
                )
                await conn.execute(
                    "UPDATE economy_users SET wallet = wallet - $1 WHERE guild_id = $2 AND user_id = $3",
                    stolen, interaction.guild.id, target.id
                )
            e = self._embed("Clean Job", f"Successful heist! Snatched {stolen:,} {cfg['currency_symbol']} from {target.mention}!")
        await interaction.followup.send(embed=e)

    @app_commands.command(name="deposit", description="Transfer cash to vault.")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        await interaction.response.defer()
        cfg  = await self.get_config(interaction.guild.id)
        data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        try:
            amt = data['wallet'] if amount.lower() == 'all' else int(amount)
        except ValueError:
            return await interaction.followup.send(embed=self._embed("Input Error", "Numeric input or 'all' is required."))

        if amt <= 0 or data['wallet'] < amt:
            return await interaction.followup.send(embed=self._embed("Insufficient Funds", "You do not have enough liquid funds to deposit."))

        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE economy_users SET wallet = wallet - $1, bank = bank + $2 WHERE guild_id = $3 AND user_id = $4",
                amt, amt, interaction.guild.id, interaction.user.id
            )
        await interaction.followup.send(embed=self._embed("Vault Deposit", f"Stored {amt:,} {cfg['currency_symbol']} in the vault."))

    @app_commands.command(name="withdraw", description="Release currency from vault.")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        await interaction.response.defer()
        cfg  = await self.get_config(interaction.guild.id)
        data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        try:
            amt = data['bank'] if amount.lower() == 'all' else int(amount)
        except ValueError:
            return await interaction.followup.send(embed=self._embed("Input Error", "Numeric input or 'all' is required."))

        if amt <= 0 or data['bank'] < amt:
            return await interaction.followup.send(embed=self._embed("Insufficient Funds", "You do not have enough vault balance to withdraw."))

        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE economy_users SET wallet = wallet + $1, bank = bank - $2 WHERE guild_id = $3 AND user_id = $4",
                amt, amt, interaction.guild.id, interaction.user.id
            )
        await interaction.followup.send(embed=self._embed("Vault Withdrawal", f"Released {amt:,} {cfg['currency_symbol']} into your active wallet."))

    @app_commands.command(name="pay", description="Transfer currency to another user.")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)

        if member.id == interaction.user.id:
            return await interaction.followup.send(embed=self._embed("Invalid Transfer", "You cannot transfer currency to yourself."))
        if member.bot:
            return await interaction.followup.send(embed=self._embed("Invalid Recipient", "You cannot transfer currency to bots."))
        if amount <= 0:
            return await interaction.followup.send(embed=self._embed("Invalid Amount", "Amount must be greater than 0."))

        sender_data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        if sender_data['wallet'] < amount:
            return await interaction.followup.send(embed=self._embed("Insufficient Funds", f"You do not have enough {cfg['currency_name']} in your wallet."))

        # Ensure recipient row exists
        await self._get_user_data(interaction.guild.id, member.id)

        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE economy_users SET wallet = wallet - $1 WHERE guild_id = $2 AND user_id = $3",
                amount, interaction.guild.id, interaction.user.id
            )
            await conn.execute(
                "UPDATE economy_users SET wallet = wallet + $1 WHERE guild_id = $2 AND user_id = $3",
                amount, interaction.guild.id, member.id
            )

        e = self._embed("Transfer Complete", f"Transferred {amount:,} {cfg['currency_symbol']} to {member.mention}.")
        await interaction.followup.send(embed=e)

    @app_commands.command(name="slots", description="Risk your currency on the high-end slot machine.")
    async def slots(self, interaction: discord.Interaction, bet: int):
        await interaction.response.defer()
        cfg = await self.get_config(interaction.guild.id)
        if bet < 50:
            return await interaction.followup.send(embed=self._embed("Min Bet", f"Minimum bet is 50 {cfg['currency_name']}."))

        data = await self._get_user_data(interaction.guild.id, interaction.user.id)
        if data['wallet'] < bet:
            return await interaction.followup.send(embed=self._embed("Insufficient Funds", "Wallet balance too low for this bet."))

        icons     = ["<:diamond:1470522339958460591>", "<:cherry:1470522699364171879>", "<:ticket:1470523139229483151>", "<:gold:1470522343267766373>", "<:emerald:1470522362003718348>", "<:quartz:1470522360212750572>"]
        fail_rate = cfg.get('slots_fail_rate', 35)

        if random.randint(1, 100) <= fail_rate:
            r = random.sample(icons, 3)
        else:
            if random.random() < 0.5:
                icon = random.choice(icons)
                r    = [icon, icon, icon]
            else:
                match_icon = random.choice(icons)
                other_icon = random.choice([i for i in icons if i != match_icon])
                r = [match_icon, match_icon, other_icon]
                random.shuffle(r)

        if r[0] == r[1] == r[2]:
            win   = bet * (15 if r[0] == "<:quartz:1470522360212750572>" else 10)
            title = "Slot Machine — JACKPOT!"
            msg   = f"You won {win:,}!"
        elif r[0] == r[1] or r[1] == r[2] or r[0] == r[2]:
            win   = int(bet * 1.5)
            title = "Slot Machine — Match!"
            msg   = f"You won {win:,}."
        else:
            win   = -bet
            title = "Slot Machine — No Luck"
            msg   = f"Lost {bet:,}."

        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE economy_users SET wallet = wallet + $1 WHERE guild_id = $2 AND user_id = $3",
                win, interaction.guild.id, interaction.user.id
            )

        desc = f"[ {r[0]} | {r[1]} | {r[2]} ]\n\n{msg}"
        await interaction.followup.send(embed=self._embed(title, desc))

    @app_commands.command(name="economy-config", description="Admin: Configure all economy variables.")
    @app_commands.describe(slots_fail_rate="Percentage (1-100) of spins that will be forced losses.")
    @app_commands.checks.has_permissions(administrator=True)
    async def econ_config(
        self, interaction: discord.Interaction,
        currency_name: str = None, symbol: str = None, daily_amount: int = None,
        work_min: int = None, work_max: int = None, work_cooldown: int = None,
        stream_min: int = None, stream_max: int = None, stream_cooldown: int = None,
        hunt_min: int = None, hunt_max: int = None, hunt_cooldown: int = None,
        scavenge_min: int = None, scavenge_max: int = None, scavenge_cooldown: int = None,
        slut_min: int = None, slut_max: int = None, slut_cooldown: int = None,
        rob_cooldown: int = None, rob_min_wallet: int = None, slut_fail_rate: int = None,
        rob_fail_rate: int = None, slots_fail_rate: int = None,
    ):
        await interaction.response.defer(ephemeral=True)

        ALLOWED = {
            "currency_name", "currency_symbol", "daily_amount",
            "work_min", "work_max", "work_cooldown",
            "stream_min", "stream_max", "stream_cooldown",
            "hunt_min", "hunt_max", "hunt_cooldown",
            "scavenge_min", "scavenge_max", "scavenge_cooldown",
            "slut_min", "slut_max", "slut_cooldown", "slut_fail_rate",
            "rob_cooldown", "rob_min_wallet", "rob_fail_rate", "slots_fail_rate",
        }

        updates: list[str] = []
        params: list      = [interaction.guild.id]

        for col, val in {
            "currency_name": currency_name, "currency_symbol": symbol, "daily_amount": daily_amount,
            "work_min": work_min, "work_max": work_max, "work_cooldown": work_cooldown,
            "stream_min": stream_min, "stream_max": stream_max, "stream_cooldown": stream_cooldown,
            "hunt_min": hunt_min, "hunt_max": hunt_max, "hunt_cooldown": hunt_cooldown,
            "scavenge_min": scavenge_min, "scavenge_max": scavenge_max, "scavenge_cooldown": scavenge_cooldown,
            "slut_min": slut_min, "slut_max": slut_max, "slut_cooldown": slut_cooldown, "slut_fail_rate": slut_fail_rate,
            "rob_cooldown": rob_cooldown, "rob_min_wallet": rob_min_wallet, "rob_fail_rate": rob_fail_rate,
            "slots_fail_rate": slots_fail_rate,
        }.items():
            if val is not None and col in ALLOWED:
                params.append(val)
                updates.append(f"{col} = ${len(params)}")

        async with self.bot.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO economy_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                interaction.guild.id
            )
            if updates:
                await conn.execute(f"UPDATE economy_settings SET {', '.join(updates)} WHERE guild_id = $1", *params)

        # Invalidate cache so next call fetches fresh data
        self._settings_cache.pop(interaction.guild.id, None)
        await interaction.followup.send(embed=self._embed("System Configured", "Changes applied!"), ephemeral=True)

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        e = self._embed("Error", str(error))
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=e, ephemeral=True)
        else:
            await interaction.followup.send(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))