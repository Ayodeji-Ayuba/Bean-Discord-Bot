"""
AUTO-MOD COG — Module 3
=======================
Features:
  • Anti-spam         — auto-mute if user sends >5 messages in 5 seconds
  • Mention spam      — auto-warn if >5 mentions in one message
  • Link filter       — blocks links in non-whitelisted channels
  • Anti-raid         — lockdown mode if 10+ joins in 10 seconds
  • Invite filter     — deletes Discord invite links from non-mods
  • Caps filter       — deletes messages that are >70% caps (min 10 chars)
  • All actions log to #staff-chat
"""

import discord
from discord.ext import commands
import datetime
import re
import asyncio
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────
STAFF_CHAT_NAME    = "staff-chat"
QUARANTINE_ROLE    = "Quarantined"
QUARANTINE_CHANNEL = "quarantine"

SPAM_THRESHOLD     = 5     # messages
SPAM_WINDOW        = 5     # seconds
MENTION_THRESHOLD  = 5     # mentions per message
CAPS_THRESHOLD     = 0.70  # 70% uppercase
CAPS_MIN_LENGTH    = 10    # minimum message length to check
RAID_JOIN_COUNT    = 10    # joins to trigger raid mode
RAID_WINDOW        = 10    # seconds

# Channels where links are allowed (by name)
LINK_WHITELIST_CHANNELS = {"links", "resources", "self-promo", "bots"}

INVITE_PATTERN = re.compile(r"discord(?:\.gg|app\.com/invite)/[\w-]+", re.IGNORECASE)
URL_PATTERN    = re.compile(r"https?://\S+", re.IGNORECASE)
COL_AUTOMOD    = 0xE74C3C
COL_OK         = 0x2ECC71


async def get_staff_channel(guild):
    return discord.utils.get(guild.text_channels, name=STAFF_CHAT_NAME)


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # In-memory tracking (resets on restart — use DB for persistence)
        self._message_times: dict[tuple, list] = defaultdict(list)
        self._join_times: dict[int, list] = defaultdict(list)
        self._lockdown_guilds: set = set()

    # ── Staff log embed ───────────────────────────────────────────────────────

    async def _log(self, guild, title, description, member=None):
        ch = await get_staff_channel(guild)
        if not ch:
            return
        embed = discord.Embed(
            title=f"🛡️ AutoMod — {title}",
            description=description,
            colour=COL_AUTOMOD,
            timestamp=datetime.datetime.utcnow()
        )
        if member:
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
        await ch.send(embed=embed)

    def _is_mod(self, member):
        return (
            member.guild_permissions.manage_messages
            or member.guild_permissions.administrator
        )

    # ── Message listener ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        member = message.author
        guild  = message.guild

        # Skip mods
        if self._is_mod(member):
            return

        checks = [
            self._check_spam(message),
            self._check_mentions(message),
            self._check_invites(message),
            self._check_links(message),
            self._check_caps(message),
        ]
        await asyncio.gather(*checks)

    # ── Anti-Spam ─────────────────────────────────────────────────────────────

    async def _check_spam(self, message: discord.Message):
        key  = (message.guild.id, message.author.id)
        now  = datetime.datetime.utcnow().timestamp()
        self._message_times[key] = [
            t for t in self._message_times[key] if now - t < SPAM_WINDOW
        ]
        self._message_times[key].append(now)

        if len(self._message_times[key]) >= SPAM_THRESHOLD:
            self._message_times[key] = []
            member = message.author
            until  = discord.utils.utcnow() + datetime.timedelta(minutes=10)
            try:
                await member.timeout(until, reason="AutoMod: spam detected")
            except discord.Forbidden:
                pass

            try:
                await message.channel.purge(limit=SPAM_THRESHOLD + 2, check=lambda m: m.author == member)
            except discord.Forbidden:
                pass

            await self._log(
                message.guild,
                "Spam Detected",
                f"{member.mention} sent **{SPAM_THRESHOLD}+ messages** in {SPAM_WINDOW}s and was muted for 10 minutes.",
                member
            )

            await self.bot.db.log_action(
                message.guild.id, "AUTO-MUTE", member.id, self.bot.user.id,
                "AutoMod: spam", "10m"
            )

    # ── Mention Spam ──────────────────────────────────────────────────────────

    async def _check_mentions(self, message: discord.Message):
        if len(message.mentions) >= MENTION_THRESHOLD:
            try:
                await message.delete()
            except discord.Forbidden:
                pass

            member = message.author
            until  = discord.utils.utcnow() + datetime.timedelta(minutes=5)
            try:
                await member.timeout(until, reason="AutoMod: mention spam")
            except discord.Forbidden:
                pass

            await self._log(
                message.guild,
                "Mention Spam",
                f"{member.mention} pinged **{len(message.mentions)} users** in one message — message deleted, user muted 5 min.",
                member
            )

    # ── Invite Filter ─────────────────────────────────────────────────────────

    async def _check_invites(self, message: discord.Message):
        if INVITE_PATTERN.search(message.content):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await self._log(
                message.guild,
                "Invite Link Blocked",
                f"{message.author.mention} posted a Discord invite in {message.channel.mention} — message deleted.",
                message.author
            )
            try:
                await message.channel.send(
                    f"{message.author.mention} ❌ Posting invite links is not allowed here.",
                    delete_after=8
                )
            except discord.Forbidden:
                pass

    # ── Link Filter ───────────────────────────────────────────────────────────

    async def _check_links(self, message: discord.Message):
        if message.channel.name in LINK_WHITELIST_CHANNELS:
            return
        if URL_PATTERN.search(message.content):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await self._log(
                message.guild,
                "Link Blocked",
                f"{message.author.mention} posted a link in {message.channel.mention} — message deleted.",
                message.author
            )
            try:
                await message.channel.send(
                    f"{message.author.mention} ❌ Links are not allowed in this channel.",
                    delete_after=8
                )
            except discord.Forbidden:
                pass

    # ── Caps Filter ───────────────────────────────────────────────────────────

    async def _check_caps(self, message: discord.Message):
        content = message.content
        if len(content) < CAPS_MIN_LENGTH:
            return
        letters = [c for c in content if c.isalpha()]
        if not letters:
            return
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio >= CAPS_THRESHOLD:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            try:
                await message.channel.send(
                    f"{message.author.mention} ❌ Please avoid excessive caps.",
                    delete_after=6
                )
            except discord.Forbidden:
                pass

    # ── Anti-Raid (join flood) ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        now   = datetime.datetime.utcnow().timestamp()
        gid   = guild.id

        self._join_times[gid] = [t for t in self._join_times[gid] if now - t < RAID_WINDOW]
        self._join_times[gid].append(now)

        # New account alert (< 7 days old)
        age_days = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days
        if age_days < 7:
            ch = await get_staff_channel(guild)
            if ch:
                embed = discord.Embed(
                    title="⚠️  New account joined",
                    description=f"{member.mention} — account is only **{age_days}d** old.",
                    colour=0xF5A623,
                    timestamp=datetime.datetime.utcnow()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await ch.send(embed=embed)

        # Raid detection
        if len(self._join_times[gid]) >= RAID_JOIN_COUNT and gid not in self._lockdown_guilds:
            self._lockdown_guilds.add(gid)
            await self._engage_lockdown(guild)

    async def _engage_lockdown(self, guild: discord.Guild):
        """Lock all public channels from new messages during a raid."""
        locked = []
        for channel in guild.text_channels:
            try:
                overwrite = channel.overwrites_for(guild.default_role)
                if overwrite.send_messages is not False:
                    overwrite.send_messages = False
                    await channel.set_permissions(guild.default_role, overwrite=overwrite)
                    locked.append(channel)
            except discord.Forbidden:
                pass

        staff_ch = await get_staff_channel(guild)
        if staff_ch:
            embed = discord.Embed(
                title="🚨 RAID DETECTED — Server Locked",
                description=(
                    f"**{RAID_JOIN_COUNT}+ members** joined within **{RAID_WINDOW} seconds**.\n\n"
                    f"🔒 Locked **{len(locked)} channel(s)**.\n\n"
                    "Use `/unlockdown` to restore access once the threat is resolved."
                ),
                colour=0xFF0000,
                timestamp=datetime.datetime.utcnow()
            )
            await staff_ch.send("@here", embed=embed)

        # Auto-lift after 5 minutes
        await asyncio.sleep(300)
        await self._lift_lockdown(guild)

    async def _lift_lockdown(self, guild: discord.Guild):
        self._lockdown_guilds.discard(guild.id)
        for channel in guild.text_channels:
            try:
                overwrite = channel.overwrites_for(guild.default_role)
                if overwrite.send_messages is False:
                    overwrite.send_messages = None
                    await channel.set_permissions(guild.default_role, overwrite=overwrite)
            except discord.Forbidden:
                pass

        staff_ch = await get_staff_channel(guild)
        if staff_ch:
            embed = discord.Embed(
                title="✅ Server Unlocked",
                description="Lockdown has been lifted. Normal access restored.",
                colour=COL_OK,
                timestamp=datetime.datetime.utcnow()
            )
            await staff_ch.send(embed=embed)

    # ── /lockdown and /unlockdown (manual) ────────────────────────────────────

    @discord.app_commands.command(name="lockdown", description="Manually lock all channels (anti-raid)")
    async def lockdown(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._engage_lockdown(interaction.guild)
        await interaction.followup.send("🔒 Server locked down.", ephemeral=True)

    @discord.app_commands.command(name="unlockdown", description="Manually lift server lockdown")
    async def unlockdown(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._lift_lockdown(interaction.guild)
        await interaction.followup.send("✅ Lockdown lifted.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
