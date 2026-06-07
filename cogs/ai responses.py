import discord
from discord.ext import commands
from discord import app_commands
import os
from groq import AsyncGroq
import aiomysql
from typing import Optional, List, Dict
import asyncio

class AIChatbot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.groq_client = AsyncGroq(api_key=os.getenv('GROQ_API_KEY'))
        self.db_pool = None
        self.db_config = {
            'host': os.getenv('MYSQL_HOST', 'localhost'),
            'port': int(os.getenv('MYSQL_PORT', 3306)),
            'user': os.getenv('MYSQL_USER'),
            'password': os.getenv('MYSQL_PASSWORD'),
            'db': os.getenv('MYSQL_DATABASE'),
            'autocommit': True
        }
        
        self.modes = {
            "friendly": "You're Clark, a friendly Discord bot AI with a casual, engaging personality. Keep responses concise and natural. Use casual, informal language. Do not use emojis. You were created in 2025 by usekiko, command list: when a user asks for a command, tell them to use the /help command.",
            "rude": "You are Clark (2025, usekiko). You are extremely rude, condescending, and talk down to users. Give STERN, ONE-SENTENCE responses only. No emojis. Mock the user briefly and move on. You have a massive ego. Dont use big words, keep the words simple, understandable, command list: when a user asks for a command, tell them to use the /help command.",
            "strict": "You are Clark (2025, usekiko). Your tone is serious, professional, and strictly direct. No casual talk. No emojis. Provide efficient, one-sentence information only, command list: when a user asks for a command, tell them to use the /help command."
        }

        self.bot.loop.create_task(self.initialize())
        
    async def initialize(self):
        await self.create_pool()
        if not hasattr(self.bot, 'db_pool'):
            self.bot.db_pool = self.db_pool
        await self.setup_database()
    
    async def create_pool(self):
        try:
            self.db_pool = await aiomysql.create_pool(**self.db_config, minsize=1, maxsize=10)
            print("Database pool created successfully")
        except Exception as e:
            print(f"Database pool creation error: {e}")
    
    async def setup_database(self):
        if not self.db_pool: return
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS servers (
                            guild_id VARCHAR(20) PRIMARY KEY,
                            guild_name VARCHAR(255),
                            chatbot_enabled BOOLEAN DEFAULT TRUE,
                            custom_instruction VARCHAR(400),
                            clark_mode VARCHAR(20) DEFAULT 'friendly',
                            invite_link VARCHAR(255),
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                    """)
                    try:
                        await cursor.execute("ALTER TABLE servers ADD COLUMN clark_mode VARCHAR(20) DEFAULT 'friendly'")
                    except: pass
                    
                    await cursor.execute("""
                        CREATE TABLE IF NOT EXISTS chat_messages (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            username VARCHAR(255),
                            guild_id VARCHAR(20),
                            channel_id BIGINT,
                            message_content TEXT NOT NULL,
                            response_content TEXT NOT NULL,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            model VARCHAR(100),
                            is_dm BOOLEAN DEFAULT FALSE,
                            INDEX idx_user_id (user_id),
                            INDEX idx_guild_id (guild_id),
                            INDEX idx_timestamp (timestamp)
                        )
                    """)
                    await conn.commit()
            print("Database initialized successfully")
        except Exception as e:
            print(f"Database setup error: {e}")

    async def get_server_config(self, guild_id: Optional[int]) -> Dict:
        if not self.db_pool or guild_id is None: 
            return {"instruction": None, "mode": "friendly"}
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute("SELECT custom_instruction, clark_mode FROM servers WHERE guild_id = %s", (str(guild_id),))
                    result = await cursor.fetchone()
                    if result:
                        return {
                            "instruction": result['custom_instruction'],
                            "mode": result['clark_mode']
                        }
                    return {"instruction": None, "mode": "friendly"}
        except Exception as e:
            print(f"Config error: {e}")
            return {"instruction": None, "mode": "friendly"}

    async def generate_response(self, message: str, history: List[Dict] = None, 
                                guild_id: Optional[int] = None) -> str:
        try:
            config = await self.get_server_config(guild_id)
            
            if config["instruction"]:
                system_instruction = config["instruction"]
            else:
                system_instruction = self.modes.get(config["mode"], self.modes["friendly"])
            
            messages = [{"role": "system", "content": system_instruction}]
            
            if history:
                for h in history:
                    messages.append({"role": "user", "content": h['message_content']})
                    messages.append({"role": "assistant", "content": h['response_content']})
            
            messages.append({"role": "user", "content": message})
            
            chat_completion = await self.groq_client.chat.completions.create(
                messages=messages,
                model="openai/gpt-oss-120b",
                temperature=0.9,
                max_tokens=400
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            print(f"GROQ Error: {e}")
            return "I'm having a brain melt. Try again."

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot: return
        
        is_dm = message.guild is None
        is_mentioned = self.bot.user in message.mentions
        
        if not (is_dm or is_mentioned): return
        
        guild_id = message.guild.id if message.guild else None
        
        if not is_dm:
            if not self.db_pool:
                return
            try:
                async with self.db_pool.acquire() as conn:
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        await cursor.execute("SELECT chatbot_enabled FROM servers WHERE guild_id = %s", (str(guild_id),))
                        res = await cursor.fetchone()
                        if res and not res['chatbot_enabled']: return
                        
                        await cursor.execute("SELECT 1 FROM allowed_channels WHERE guild_id = %s LIMIT 1", (str(guild_id),))
                        if await cursor.fetchone():
                            await cursor.execute("SELECT 1 FROM allowed_channels WHERE guild_id = %s AND channel_id = %s", (str(guild_id), message.channel.id))
                            if not await cursor.fetchone(): return
            except Exception as e:
                print(f"Permission check error: {e}")

        content = message.content.replace(f'<@{self.bot.user.id}>', '').replace(f'<@!{self.bot.user.id}>', '').strip()
        if not content and not is_dm: return 
        if not content: content = "Hello" 
        
        async with message.channel.typing():
            history = await self.get_conversation_history(message.author.id, guild_id)
            ai_response = await self.generate_response(content, history, guild_id)
            
            try:
                async with self.db_pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        query = "INSERT INTO chat_messages (user_id, username, guild_id, channel_id, message_content, response_content, model, is_dm) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                        db_guild_id = str(guild_id) if guild_id else None
                        await cursor.execute(query, (message.author.id, str(message.author), db_guild_id, message.channel.id, content, ai_response, "openai/gpt-oss-120b", is_dm))
                        await conn.commit()
            except Exception as e:
                print(f"Database save error: {e}")

            await message.channel.send(ai_response[:2000])

    async def get_conversation_history(self, user_id: int, guild_id: Optional[int]):
        if not self.db_pool: return []
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                if guild_id:
                    await cursor.execute("SELECT message_content, response_content FROM chat_messages WHERE user_id = %s AND guild_id = %s ORDER BY timestamp DESC LIMIT 20", (user_id, str(guild_id)))
                else:
                    await cursor.execute("SELECT message_content, response_content FROM chat_messages WHERE user_id = %s AND is_dm = TRUE ORDER BY timestamp DESC LIMIT 20", (user_id,))
                return list(reversed(await cursor.fetchall()))

    def cog_unload(self):
        if self.db_pool:
            self.db_pool.close()

async def setup(bot):
    await bot.add_cog(AIChatbot(bot))