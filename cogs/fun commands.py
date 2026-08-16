import discord
from discord.ext import commands
from discord import app_commands, ui
import random
import os
import json

from utils import embed

JSON_DIR = "json"

class Funny(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ensure_files_exist()

    def ensure_files_exist(self):
        if not os.path.exists(JSON_DIR):
            os.makedirs(JSON_DIR)

        files = {
            "jokes.json": ["Why did the scarecrow win? He was outstanding in his field!"],
            "memes.json": ["https://media.tenor.com/images/123456/meme.gif"],
            "tiktoks.json": ["https://www.tiktok.com/@user/video/123"],
            "roasts.json": ["You are like a cloud. When you disappear, it is a beautiful day."],
            "facts.json": ["Honey never spoils."]
        }

        for filename, defaults in files.items():
            filepath = os.path.join(JSON_DIR, filename)
            if not os.path.exists(filepath):
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(defaults, f, indent=4)

    def get_random_content(self, filename):
        filepath = os.path.join(JSON_DIR, filename)
        try:
            if not os.path.exists(filepath): return None, "File missing."
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data: return None, "List is empty."
            return random.choice(data), None
        except Exception as e:
            return None, str(e)


    @app_commands.command(name="joke", description="Tells a random joke")
    @app_commands.checks.cooldown(1, 3.0) 
    async def joke(self, interaction: discord.Interaction):
        content, error = self.get_random_content("jokes.json")
        if error:
            e = embed("Error", error)
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        e = embed("Random Joke", content)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="meme", description="Sends a random meme")
    @app_commands.checks.cooldown(1, 3.0)
    async def meme(self, interaction: discord.Interaction):
        content, error = self.get_random_content("memes.json")
        if error:
            e = embed("Error", error)
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        e = embed("Random Meme", content)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="tiktok", description="Sends a funny TikTok")
    @app_commands.checks.cooldown(1, 5.0)
    async def tiktok(self, interaction: discord.Interaction):
        content, error = self.get_random_content("tiktoks.json")
        if error:
            e = embed("Error", error)
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        e = embed("Funny TikTok", content)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="roast", description="Roast someone")
    @app_commands.describe(user="The user to roast")
    @app_commands.checks.cooldown(1, 3.0)
    async def roast(self, interaction: discord.Interaction, user: discord.Member = None):
        content, error = self.get_random_content("roasts.json")
        if error:
            e = embed("Error", error)
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        target = user.mention if user else "You"
        e = embed("Roast", f"{target}, {content}")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="fact", description="Learn a random fact")
    @app_commands.checks.cooldown(1, 3.0)
    async def fact(self, interaction: discord.Interaction):
        content, error = self.get_random_content("facts.json")
        if error:
            e = embed("Error", error)
            await interaction.response.send_message(embed=e, ephemeral=True)
            return
        e = embed("Random Fact", f"Did you know? {content}")
        await interaction.response.send_message(embed=e)

async def setup(bot):
    await bot.add_cog(Funny(bot))