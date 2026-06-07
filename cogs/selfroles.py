import discord
from discord.ext import commands
from discord import app_commands, ui
import json
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
    def __init__(self, container: ui.Container):
        super().__init__(timeout=300)
        self.add_item(container)

class SelfRoleSelect(ui.Select):
    def __init__(self, options: list[discord.SelectOption] = None):
        # If options are None (during bot restart/persistence loading), 
        # we need a placeholder to satisfy the class requirement.
        if options is None:
            options = [discord.SelectOption(label="Loading...", value="persistent_placeholder")]
            
        super().__init__(
            placeholder="Select roles to toggle...",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="selfrole:select" # This ID must match exactly for persistence
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        if not hasattr(interaction.client, 'db_pool'):
            return await interaction.followup.send("Database connection failed.", ephemeral=True)

        async with interaction.client.db_pool.acquire() as conn:
            # Fetch valid roles for THIS specific message
            data = await conn.fetchrow("SELECT role_ids FROM self_roles WHERE message_id = $1", interaction.message.id)

        if not data:
            return await interaction.followup.send("This self-role menu is no longer active.", ephemeral=True)

        valid_role_ids = json.loads(data['role_ids'])
        
        # self.values contains what the user JUST clicked
        selected_values = []
        for v in self.values:
            if v.isdigit():
                selected_values.append(int(v))
        
        added = []
        removed = []
        errors = []
        
        member = interaction.user
        
        # We iterate through the VALID roles for this menu (from DB)
        # to ensure security and that we only toggle relevant roles
        for role_id in valid_role_ids:
            role = interaction.guild.get_role(role_id)
            if not role:
                continue
            
            if role_id in selected_values:
                # User selected this role -> Add it
                if role not in member.roles:
                    try:
                        await member.add_roles(role, reason="Self-Role Toggle")
                        added.append(role.name)
                    except discord.Forbidden:
                        errors.append(role.name)
            else:
                # User did NOT select this role -> Remove it
                if role in member.roles:
                    try:
                        await member.remove_roles(role, reason="Self-Role Toggle")
                        removed.append(role.name)
                    except discord.Forbidden:
                        errors.append(role.name)

        cog = interaction.client.get_cog("SelfRoles")
        if cog:
            desc = ""
            if added: desc += f"**Added:** {', '.join(added)}\n"
            if removed: desc += f"**Removed:** {', '.join(removed)}\n"
            if errors: desc += f"**Failed (Permissions):** {', '.join(errors)}"
            if not desc: desc = "No changes made."
            
            status = "ERROR" if errors else "SUCCESS"
            view = cog._create_response_container("Roles Updated", desc, status)
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.followup.send("Roles updated successfully.", ephemeral=True)

# This View is used only during persistence loading to register the custom_id
class PersistentSelfRoleView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelfRoleSelect(options=None))

class SelfRoleView(ui.LayoutView):
    def __init__(self, title: str, description: str, roles: list[discord.Role], bot_avatar_url: str = None):
        super().__init__(timeout=None)
        
        # FIXED: Using the specific emoji and arrow as requested
        clean_title = title.strip()
        formatted_header = f"### <:excellent:1444475037938876427> ›  {clean_title}\n{description}"
        
        header_text = ui.TextDisplay(formatted_header)
        accessory = ui.Thumbnail(media=bot_avatar_url) if bot_avatar_url else None
        section = ui.Section(header_text, accessory=accessory)
        
        options = []
        for role in roles:
            # We use the Role ID as the value
            options.append(discord.SelectOption(label=role.name, value=str(role.id), emoji="<:mention:1454546376296763452>"))

        select_row = ui.ActionRow()
        # Pass the real options here for creation
        select_row.add_item(SelfRoleSelect(options=options))
        
        container = ui.Container(
            section,
            ui.Separator(spacing=discord.SeparatorSpacing.small),
            select_row,
            accent_color=None # FIXED: Removed side color (blurple)
        )
        self.add_item(container)

class SelfRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.EMOJIS = {
            'SUCCESS':  '<:goodconnection:1454536158208983051> ›  ',
            'ERROR':    '<:lowconnection:1454536160545214527> ›  ',
            'INFO':     '<:mediumconnection:1454536162189512734> ›  ',
        }
        self.response_thumbnail_accessory = None

    async def setup_database(self):
        if self.bot.user:
            self.response_thumbnail_accessory = ui.Thumbnail(media=self.bot.user.display_avatar.url)

        try:
            if not hasattr(self.bot, 'db_pool') or self.bot.db_pool is None:
                print(f"{Colors.RED}[ERROR] Database pool not set.{Colors.RESET}")
                return

            async with self.bot.db_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS self_roles (
                        message_id BIGINT PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        role_ids JSONB NOT NULL
                    )
                """)
            print(f"{Colors.GREEN}[SUCCESS] cogs.selfroles.py initialized tables.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to init self_roles table: {e}{Colors.RESET}")

    def _create_response_container(self, title: str, description: str, status: str = 'INFO') -> ResponseView:
        header = ui.TextDisplay(f"**{title}**")
        sep = ui.Separator(spacing=discord.SeparatorSpacing.small)
        body = ui.TextDisplay(description)
        
        container = ui.Container(header, sep, body)
        return ResponseView(container)

    @app_commands.command(name="selfrole", description="Creates a persistent self-role menu.")
    @app_commands.describe(title="Menu Title", description="Menu Description")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def create_selfrole(
        self, 
        interaction: discord.Interaction, 
        title: str, 
        description: str,
        role1: discord.Role,
        role2: discord.Role = None,
        role3: discord.Role = None,
        role4: discord.Role = None,
        role5: discord.Role = None,
        role6: discord.Role = None,
        role7: discord.Role = None,
        role8: discord.Role = None,
        role9: discord.Role = None,
        role10: discord.Role = None
    ):
        raw_roles = [role1, role2, role3, role4, role5, role6, role7, role8, role9, role10]
        roles = [r for r in raw_roles if r is not None]

        if len(roles) != len(set(roles)):
             view = self._create_response_container("Action Failed", "Duplicate roles detected.", "ERROR")
             return await interaction.response.send_message(view=view, ephemeral=True)

        for role in roles:
            if role >= interaction.guild.me.top_role:
                view = self._create_response_container("Permission Denied", f"I cannot manage {role.mention} (Hierarchy).", "ERROR")
                return await interaction.response.send_message(view=view, ephemeral=True)
            if role.is_default() or role.is_premium_subscriber():
                view = self._create_response_container("Invalid Role", f"{role.mention} cannot be used.", "ERROR")
                return await interaction.response.send_message(view=view, ephemeral=True)

        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        view = SelfRoleView(title, description, roles, avatar_url)
        
        await interaction.response.send_message(view=view)
        message = await interaction.original_response()

        role_ids = [r.id for r in roles]
        
        try:
            async with self.bot.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO self_roles (message_id, guild_id, channel_id, role_ids) VALUES ($1, $2, $3, $4)",
                    message.id, interaction.guild.id, interaction.channel.id, json.dumps(role_ids)
                )
        except Exception as e:
            print(f"{Colors.RED}[ERROR] Failed to save selfrole to DB: {e}{Colors.RESET}")

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_database()
        self.bot.add_view(PersistentSelfRoleView())

async def setup(bot: commands.Bot):
    await bot.add_cog(SelfRoles(bot))