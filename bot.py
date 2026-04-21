import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv
from database import Database

load_dotenv()

# ── Intents ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members         = True
intents.guilds          = True
intents.voice_states    = True

# ── Bot ───────────────────────────────────────────────────────────────────────
bot = commands.Bot(command_prefix="!", intents=intents)
bot.db = Database()

GLOBAL_COGS = [
    "cogs.moderation",
    "cogs.automod",
    "cogs.onboarding",
    "cogs.verification",
    "cogs.attendance",
    "cogs.leave",
    "cogs.kpi",
    "cogs.compliance",
    "cogs.crypto",
    "cogs.webhooks",
    "cogs.dbtools",
    "cogs.gambling",
    "cogs.screenshare",
]

GUILD_COGS = [
    "cogs.infra",   # guild-only to avoid global 100-command limit set by
]

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"   Guilds: {len(bot.guilds)}")
    try:
        # Sync global commands
        synced = await bot.tree.sync()
        print(f"   Synced {len(synced)} global slash command(s)")

        # Sync guild-only commands to every guild
        for guild in bot.guilds:
            guild_synced = await bot.tree.sync(guild=guild)
            print(f"   Synced {len(guild_synced)} guild command(s) to {guild.name}")
    except Exception as e:
        print(f"   Sync error: {e}")

async def main():
    async with bot:
        await bot.db.init()

        for cog in GLOBAL_COGS:
            try:
                await bot.load_extension(cog)
                print(f"   Loaded: {cog}")
            except Exception as e:
                print(f"   Failed to load {cog}: {e}")

        for cog in GUILD_COGS:
            try:
                await bot.load_extension(cog)
                print(f"   Loaded: {cog}")
            except Exception as e:
                print(f"   Failed to load {cog}: {e}")

        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())