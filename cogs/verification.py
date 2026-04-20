"""
VERIFICATION COG — Module 5
============================
Features:
  • /setupverify   — post the verification panel in #verify (admin)
  • Button verify  — one-click verification with role assignment
  • Math CAPTCHA   — optional extra step (solve a simple equation via modal)
  • Age gate       — optional 18+ confirmation step
  • /unverify      — remove verification from a user (mod)
  • /verifyinfo    — check if a user is verified and when
  • Auto-logs all verifications to #staff-chat

How it works:
  1. Admin runs /setupverify → bot posts an embed with a "Verify" button in #verify
  2. User clicks the button
  3. If CAPTCHA is enabled → modal pops up asking them to solve a math question
  4. On success → bot assigns the "Verified" role, logs to #staff-chat, DMs user
  5. If already verified → ephemeral message tells them so
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import random

# ── Config ────────────────────────────────────────────────────────────────────
VERIFY_CHANNEL_NAME = "verify"
VERIFIED_ROLE_NAME  = "Verified"
STAFF_CHAT_NAME     = "staff-chat"

CAPTCHA_ENABLED     = True   # Set False to use single-click button only
AGE_GATE_ENABLED    = False  # Set True to add 18+ confirmation step

COL_OK    = 0x2ECC71
COL_ERR   = 0xE74C3C
COL_INFO  = 0x3498DB


def _make_captcha() -> tuple[str, int]:
    """Return (question_string, correct_answer)."""
    a = random.randint(2, 15)
    b = random.randint(2, 15)
    op = random.choice(["+", "-", "*"])
    if op == "+":
        return f"{a} + {b}", a + b
    elif op == "-":
        a, b = max(a, b), min(a, b)
        return f"{a} - {b}", a - b
    else:
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        return f"{a} × {b}", a * b


# ── CAPTCHA Modal ─────────────────────────────────────────────────────────────

class CaptchaModal(discord.ui.Modal, title="Human Verification"):
    def __init__(self, answer: int, cog):
        super().__init__()
        self._answer = answer
        self._cog    = cog

    response = discord.ui.TextInput(
        label="Solve the equation above",
        placeholder="Enter a number...",
        min_length=1,
        max_length=6
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            given = int(self.response.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number.", ephemeral=True
            )
            return

        if given != self._answer:
            await interaction.response.send_message(
                f"❌ Incorrect answer. Please click **Verify** again to try again.",
                ephemeral=True
            )
            return

        await self._cog._complete_verification(interaction)


# ── Age Gate Modal ────────────────────────────────────────────────────────────

class AgeGateModal(discord.ui.Modal, title="Age Confirmation"):
    confirm = discord.ui.TextInput(
        label='Type "I am 18 or older" to confirm',
        placeholder="I am 18 or older",
        min_length=5,
        max_length=30
    )

    def __init__(self, cog):
        super().__init__()
        self._cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.strip().lower() != "i am 18 or older":
            await interaction.response.send_message(
                "❌ Age confirmation failed. You must be 18 or older to join this server.",
                ephemeral=True
            )
            return
        await self._cog._complete_verification(interaction)


# ── Verify Button View ────────────────────────────────────────────────────────

class VerifyView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self._cog = cog

    @discord.ui.button(
        label="✅  Verify Me",
        style=discord.ButtonStyle.success,
        custom_id="verify_button"
    )
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if already verified
        already = await self._cog.bot.db.is_verified(interaction.guild.id, interaction.user.id)
        if already:
            await interaction.response.send_message(
                "✅ You are already verified!", ephemeral=True
            )
            return

        if AGE_GATE_ENABLED:
            await interaction.response.send_modal(AgeGateModal(self._cog))
        elif CAPTCHA_ENABLED:
            question, answer = _make_captcha()
            modal = CaptchaModal(answer, self._cog)
            modal.title = f"Solve: {question} = ?"
            modal.response.label = f"What is {question}?"
            await interaction.response.send_modal(modal)
        else:
            await self._cog._complete_verification(interaction)


# ── Verification Cog ──────────────────────────────────────────────────────────

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_or_create_role(self, guild: discord.Guild) -> discord.Role:
        role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
        if not role:
            role = await guild.create_role(
                name=VERIFIED_ROLE_NAME,
                colour=discord.Colour.green(),
                reason="Auto-created by verification system"
            )
        return role

    async def _complete_verification(self, interaction: discord.Interaction):
        guild  = interaction.guild
        member = interaction.user

        # Assign Verified role
        role = await self._get_or_create_role(guild)
        try:
            await member.add_roles(role, reason="Passed verification")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to assign the Verified role. Please contact an admin.",
                ephemeral=True
            )
            return

        # Record in database
        await self.bot.db.mark_verified(guild.id, member.id, "captcha" if CAPTCHA_ENABLED else "button")

        # Respond to user
        method_used = "captcha" if CAPTCHA_ENABLED else "one-click"
        embed = discord.Embed(
            title="✅ You're Verified!",
            description=f"Welcome to **{guild.name}**, {member.mention}! You now have full access.",
            colour=COL_OK,
            timestamp=datetime.datetime.utcnow()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # DM confirmation
        try:
            dm = discord.Embed(
                title=f"✅ Verified in {guild.name}",
                description="You've been successfully verified and now have access to the server.",
                colour=COL_OK,
                timestamp=datetime.datetime.utcnow()
            )
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

        # Log to #staff-chat
        staff_ch = discord.utils.get(guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            log = discord.Embed(
                title="✅ Member Verified",
                colour=COL_OK,
                timestamp=datetime.datetime.utcnow()
            )
            log.set_thumbnail(url=member.display_avatar.url)
            log.add_field(name="User",   value=f"{member.mention} (`{member.id}`)", inline=False)
            log.add_field(name="Method", value=method_used, inline=True)
            log.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, style="R"), inline=True)
            await staff_ch.send(embed=log)

    # ── /setupverify ──────────────────────────────────────────────────────────

    @app_commands.command(name="setupverify", description="Post the verification panel (admin only)")
    async def setupverify(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        ch = discord.utils.get(interaction.guild.text_channels, name=VERIFY_CHANNEL_NAME)
        if not ch:
            return await interaction.response.send_message(
                f"❌ Channel `#{VERIFY_CHANNEL_NAME}` not found. Create it first.", ephemeral=True
            )

        method_desc = (
            "🔢 **CAPTCHA enabled** — you'll solve a quick math question."
            if CAPTCHA_ENABLED
            else "🖱️ **One-click verification** — press the button below."
        )

        embed = discord.Embed(
            title="🔐 Server Verification",
            description=(
                f"Welcome to **{interaction.guild.name}**!\n\n"
                f"To gain access to the server, please verify below.\n\n"
                f"{method_desc}\n\n"
                "This keeps our community safe from bots and spam accounts."
            ),
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.set_footer(text="Verification is required to access this server.")

        view = VerifyView(self)
        await ch.send(embed=embed, view=view)

        await interaction.response.send_message(
            f"✅ Verification panel posted in {ch.mention}.", ephemeral=True
        )

    # ── /unverify ─────────────────────────────────────────────────────────────

    @app_commands.command(name="unverify", description="Remove verification from a member (mod)")
    @app_commands.describe(member="Member to unverify")
    async def unverify(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("❌ Insufficient permissions.", ephemeral=True)

        role = discord.utils.get(interaction.guild.roles, name=VERIFIED_ROLE_NAME)
        if role and role in member.roles:
            await member.remove_roles(role, reason=f"Unverified by {interaction.user}")

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ {member.mention} has been unverified.",
                colour=COL_OK
            ),
            ephemeral=True
        )

    # ── /verifyinfo ───────────────────────────────────────────────────────────

    @app_commands.command(name="verifyinfo", description="Check verification status of a member")
    @app_commands.describe(member="Member to check")
    async def verifyinfo(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Insufficient permissions.", ephemeral=True)

        verified = await self.bot.db.is_verified(interaction.guild.id, member.id)
        role = discord.utils.get(interaction.guild.roles, name=VERIFIED_ROLE_NAME)
        has_role = role in member.roles if role else False

        embed = discord.Embed(
            title=f"Verification status — {member.display_name}",
            colour=COL_OK if verified else COL_ERR,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Verified in DB", value="✅ Yes" if verified else "❌ No", inline=True)
        embed.add_field(name="Has role",       value="✅ Yes" if has_role else "❌ No", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Verification(bot))
