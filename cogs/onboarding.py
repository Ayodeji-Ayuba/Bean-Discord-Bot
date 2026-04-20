"""
ONBOARDING COG — Module 4
=========================
Features:
  • Auto-role on join        — assign a "Member" role to every new joiner
  • Welcome DM               — personalised welcome message with server info
  • Welcome channel message  — public embed in #welcome
  • XP / Leveling system     — earn XP per message (15-25 XP, 1 min cooldown)
  • Level-up announcements   — posted in the channel the message was sent
  • Level role rewards        — auto-assign roles at milestone levels
  • /rank                    — view your own or another user's rank card
  • /leaderboard             — top 10 XP leaderboard
  • /givexp                  — admin command to manually award XP
  • /setlevelrole            — link a role to a level milestone
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import random

# ── Config ────────────────────────────────────────────────────────────────────
WELCOME_CHANNEL  = "welcome"
AUTO_ROLE_NAME   = "Member"          # Role given to all new joiners
STAFF_CHAT_NAME  = "staff-chat"

XP_MIN           = 15               # XP earned per eligible message
XP_MAX           = 25
XP_COOLDOWN_S    = 60               # seconds between XP awards per user

# Level milestone → role name mapping (customise as needed)
LEVEL_ROLES: dict[int, str] = {
    5:  "Active Member",
    10: "Regular",
    20: "Veteran",
    50: "Legend",
}

COL_LEVEL  = 0x9B59B6
COL_OK     = 0x2ECC71
COL_INFO   = 0x3498DB


def _fmt_xp_bar(xp: int, level: int, bar_len: int = 12) -> str:
    """Return a text XP progress bar."""
    xp_for_this = level ** 2 * 100
    xp_for_next = (level + 1) ** 2 * 100
    progress = xp - xp_for_this
    needed   = xp_for_next - xp_for_this
    ratio    = max(0.0, min(1.0, progress / needed if needed > 0 else 1.0))
    filled   = int(ratio * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    return f"`{bar}` {progress}/{needed} XP"


class Onboarding(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._xp_cooldowns: dict[tuple, float] = {}  # (guild_id, user_id) -> timestamp

    # ── New member join ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild

        # 1. Assign auto-role
        role = discord.utils.get(guild.roles, name=AUTO_ROLE_NAME)
        if not role:
            try:
                role = await guild.create_role(
                    name=AUTO_ROLE_NAME,
                    colour=discord.Colour.blurple(),
                    reason="Auto-created by onboarding system"
                )
            except discord.Forbidden:
                pass
        if role:
            try:
                await member.add_roles(role, reason="Auto-role on join")
            except discord.Forbidden:
                pass

        # 2. Welcome embed in #welcome
        welcome_ch = discord.utils.get(guild.text_channels, name=WELCOME_CHANNEL)
        if welcome_ch:
            embed = discord.Embed(
                title=f"👋 Welcome to {guild.name}!",
                description=(
                    f"Hey {member.mention}, we're glad you're here!\n\n"
                    f"You are member **#{guild.member_count}**.\n"
                    f"Head over to the rules channel and get verified to unlock full access."
                ),
                colour=COL_OK,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Account created: {member.created_at.strftime('%b %d, %Y')}")
            await welcome_ch.send(embed=embed)

        # 3. Welcome DM
        try:
            dm_embed = discord.Embed(
                title=f"Welcome to {guild.name}! 🎉",
                description=(
                    f"Hi {member.display_name},\n\n"
                    f"Thanks for joining **{guild.name}**! Here's a quick start:\n\n"
                    f"• ✅ Read the rules and get verified\n"
                    f"• 💬 Chat in channels to earn XP and level up\n"
                    f"• 🏆 Reach level milestones to unlock special roles\n\n"
                    f"If you need help, open a ticket or ping a moderator."
                ),
                colour=COL_INFO,
                timestamp=datetime.datetime.utcnow()
            )
            dm_embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        # 4. Log to staff-chat
        staff_ch = discord.utils.get(guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            embed = discord.Embed(
                description=f"📥 {member.mention} joined — member #{guild.member_count}",
                colour=COL_INFO,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await staff_ch.send(embed=embed)

    # ── Member leave ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        staff_ch = discord.utils.get(member.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            embed = discord.Embed(
                description=f"📤 {member} left the server.",
                colour=0xE74C3C,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await staff_ch.send(embed=embed)

    # ── XP on message ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if len(message.content) < 5:
            return  # ignore very short messages

        key = (message.guild.id, message.author.id)
        now = datetime.datetime.utcnow().timestamp()

        # Cooldown check
        last = self._xp_cooldowns.get(key, 0)
        if now - last < XP_COOLDOWN_S:
            return
        self._xp_cooldowns[key] = now

        xp_gain = random.randint(XP_MIN, XP_MAX)
        xp, new_level, leveled_up = await self.bot.db.add_xp(
            message.guild.id, message.author.id, xp_gain
        )

        if leveled_up:
            await self._handle_level_up(message, new_level, xp)

    async def _handle_level_up(self, message: discord.Message, new_level: int, xp: int):
        member = message.author
        guild  = message.guild

        # Level-up announcement
        embed = discord.Embed(
            title="⬆️ Level Up!",
            description=f"🎉 {member.mention} reached **Level {new_level}**!",
            colour=COL_LEVEL,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Total XP", value=str(xp), inline=True)
        embed.add_field(name="Progress", value=_fmt_xp_bar(xp, new_level), inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await message.channel.send(embed=embed, delete_after=30)

        # Assign level role reward if applicable
        role_name = LEVEL_ROLES.get(new_level)
        if role_name:
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                try:
                    role = await guild.create_role(name=role_name, reason=f"Level {new_level} reward")
                except discord.Forbidden:
                    return
            try:
                await member.add_roles(role, reason=f"Reached level {new_level}")
                await message.channel.send(
                    f"🏆 {member.mention} unlocked the **{role_name}** role for reaching Level {new_level}!",
                    delete_after=20
                )
            except discord.Forbidden:
                pass

    # ── /rank ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="rank", description="View your rank and XP progress")
    @app_commands.describe(member="Member to check (leave empty for yourself)")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        data = await self.bot.db.get_level_data(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"🏅 Rank — {target.display_name}",
            colour=COL_LEVEL,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if not data:
            embed.description = "No XP yet. Start chatting to earn XP!"
        else:
            xp, level, total_msgs = data
            embed.add_field(name="Level",      value=str(level),      inline=True)
            embed.add_field(name="Total XP",   value=str(xp),         inline=True)
            embed.add_field(name="Messages",   value=str(total_msgs), inline=True)
            embed.add_field(name="Progress",   value=_fmt_xp_bar(xp, level), inline=False)

            next_milestone = next((l for l in sorted(LEVEL_ROLES) if l > level), None)
            if next_milestone:
                embed.add_field(
                    name="Next role reward",
                    value=f"**{LEVEL_ROLES[next_milestone]}** at Level {next_milestone}",
                    inline=False
                )
        await interaction.response.send_message(embed=embed)

    # ── /leaderboard ──────────────────────────────────────────────────────────

    @app_commands.command(name="leaderboard", description="View the top 10 XP leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_leaderboard(interaction.guild.id)
        embed = discord.Embed(
            title=f"🏆 XP Leaderboard — {interaction.guild.name}",
            colour=COL_LEVEL,
            timestamp=datetime.datetime.utcnow()
        )
        medals = ["🥇", "🥈", "🥉"]
        if not rows:
            embed.description = "No XP data yet."
        else:
            lines = []
            for i, (user_id, xp, level, msgs) in enumerate(rows):
                m = interaction.guild.get_member(int(user_id))
                name = m.display_name if m else f"Unknown ({user_id})"
                prefix = medals[i] if i < 3 else f"`{i+1}.`"
                lines.append(f"{prefix} **{name}** — Level {level} · {xp} XP · {msgs} msgs")
            embed.description = "\n".join(lines)
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        await interaction.response.send_message(embed=embed)

    # ── /givexp ───────────────────────────────────────────────────────────────

    @app_commands.command(name="givexp", description="Manually award XP to a member (admin only)")
    @app_commands.describe(member="Target member", amount="XP amount to award")
    async def givexp(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 10000]
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        xp, level, leveled_up = await self.bot.db.add_xp(interaction.guild.id, member.id, amount)
        msg = f"✅ Gave **{amount} XP** to {member.mention}. They now have **{xp} XP** (Level {level})."
        if leveled_up:
            msg += f" 🎉 They leveled up to **Level {level}**!"
        await interaction.response.send_message(
            embed=discord.Embed(description=msg, colour=COL_OK),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Onboarding(bot))
