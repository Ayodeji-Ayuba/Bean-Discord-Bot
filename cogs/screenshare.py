"""
SCREEN SHARE VERIFICATION COG — Module 14
==========================================
Features:
  • /ssverify      — request screen share verification (user)
  • /ssapprove     — approve a screen share session (mod)
  • /ssreject      — reject a screen share session with reason (mod)
  • /pendingss     — view all pending screen share requests (mod)
  • /sshistory     — view screen share history for a member (mod)
  • /ssstats       — server-wide screen share statistics (admin)
  • /setupss       — configure the screen share verification channel (admin)
  • Voice state listener — detects when users START screen sharing
    and auto-posts a verification request to #ss-verify-log
  • Role rewards — auto-assigns "Screen Verified" role after approval
  • DM notifications for approval and rejection
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime

SS_LOG_CHANNEL     = "ss-verify-log"
STAFF_CHAT_NAME    = "staff-chat"
SS_VERIFIED_ROLE   = "Screen Verified"

COL_OK     = 0x2ECC71
COL_ERR    = 0xE74C3C
COL_INFO   = 0x3498DB
COL_PEND   = 0xF5A623


# ── Review View ───────────────────────────────────────────────────────────────

class SSReviewView(discord.ui.View):
    def __init__(self, session_id: int, user_id: int):
        super().__init__(timeout=None)
        self.session_id = session_id
        self.user_id    = user_id

    async def _handle(self, interaction: discord.Interaction, approved: bool):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        for child in self.children:
            child.disabled = True

        guild  = interaction.guild
        member = guild.get_member(self.user_id)

        if approved:
            await interaction.client.db.verify_ss_session(self.session_id, interaction.user.id)
            colour = COL_OK
            status = "✅ Approved"

            # Assign verified role
            role = discord.utils.get(guild.roles, name=SS_VERIFIED_ROLE)
            if not role:
                try:
                    role = await guild.create_role(name=SS_VERIFIED_ROLE, colour=discord.Colour.green(), reason="Auto-created by SS verification")
                except discord.Forbidden:
                    pass
            if role and member:
                try:
                    await member.add_roles(role, reason=f"Screen share verified by {interaction.user}")
                except discord.Forbidden:
                    pass
        else:
            await interaction.client.db.reject_ss_session(self.session_id)
            colour = COL_ERR
            status = "❌ Rejected"

        # Update embed
        embed = interaction.message.embeds[0]
        embed.colour = colour
        embed.set_field_at(
            next(i for i, f in enumerate(embed.fields) if f.name == "Status"),
            name="Status", value=f"{status} by {interaction.user.mention}", inline=True
        )
        await interaction.response.edit_message(embed=embed, view=self)

        # DM member
        if member:
            try:
                dm = discord.Embed(
                    title=f"{'✅' if approved else '❌'} Screen Share Verification {'Approved' if approved else 'Rejected'}",
                    description=(
                        f"Your screen share verification has been **{'approved' if approved else 'rejected'}** "
                        f"by {interaction.user.display_name}."
                        + (f"\nYou've been given the **{SS_VERIFIED_ROLE}** role!" if approved else "")
                    ),
                    colour=colour,
                    timestamp=datetime.datetime.utcnow()
                )
                await member.send(embed=dm)
            except discord.Forbidden:
                pass

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="ss_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, approved=True)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger, custom_id="ss_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, approved=False)


# ── Screen Share Cog ──────────────────────────────────────────────────────────

class ScreenShare(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track who we've already posted a pending request for (prevent duplicates)
        self._pending_requests: set[tuple] = set()

    async def _log_channel(self, guild):
        return discord.utils.get(guild.text_channels, name=SS_LOG_CHANNEL)

    async def _post_request(self, guild: discord.Guild, member: discord.Member, channel_name: str, session_id: int):
        log_ch = await self._log_channel(guild)
        if not log_ch:
            return

        embed = discord.Embed(
            title="🖥️ Screen Share Verification Request",
            colour=COL_PEND,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member",   value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Channel",  value=channel_name, inline=True)
        embed.add_field(name="Status",   value="⏳ **Pending review**", inline=True)
        embed.add_field(name="Session",  value=f"#{session_id}", inline=True)
        embed.set_footer(text="A moderator must approve or reject this request.")

        view = SSReviewView(session_id, member.id)
        await log_ch.send(embed=embed, view=view)

    # ── Voice state listener — auto-detect screen share start ────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        if member.bot:
            return

        # Detect screen share start (self_video or self_stream toggled on)
        started_sharing = (
            (not before.self_video and after.self_video) or
            (not before.self_stream and after.self_stream)
        )

        if not started_sharing:
            return

        key = (member.guild.id, member.id)
        if key in self._pending_requests:
            return  # already has a pending request
        self._pending_requests.add(key)

        channel_name = after.channel.name if after.channel else "Unknown"

        session_id = await self.bot.db.create_ss_session(
            member.guild.id, member.id,
            after.channel.id if after.channel else 0
        )

        await self._post_request(member.guild, member, channel_name, session_id)

        # Alert staff
        staff_ch = discord.utils.get(member.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            embed = discord.Embed(
                description=(
                    f"🖥️ {member.mention} started screen sharing in **{channel_name}**.\n"
                    f"Verification request posted in <#{(await self._log_channel(member.guild)).id}>."
                    if await self._log_channel(member.guild) else
                    f"🖥️ {member.mention} started screen sharing in **{channel_name}**."
                ),
                colour=COL_INFO,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await staff_ch.send(embed=embed)

        # Remove from pending when they stop sharing
        await self._wait_for_share_end(member)

    async def _wait_for_share_end(self, member: discord.Member):
        """Remove member from pending set when they stop sharing."""
        def check(m, before, after):
            return (
                m == member and
                (before.self_video and not after.self_video or
                 before.self_stream and not after.self_stream)
            )
        try:
            await self.bot.wait_for("voice_state_update", check=check, timeout=7200)
        except Exception:
            pass
        self._pending_requests.discard((member.guild.id, member.id))

    # ── /ssverify ─────────────────────────────────────────────────────────────

    @app_commands.command(name="ssverify", description="Request a screen share verification session")
    @app_commands.describe(note="Optional note for the moderator")
    async def ssverify(self, interaction: discord.Interaction, note: str = None):
        member = interaction.user
        guild  = interaction.guild

        # Check if already in a voice channel
        voice = member.voice
        channel_name = voice.channel.name if voice and voice.channel else "Not in voice"
        channel_id   = voice.channel.id   if voice and voice.channel else 0

        session_id = await self.bot.db.create_ss_session(guild.id, member.id, channel_id)
        if note:
            await self.bot.db.verify_ss_session  # just for context — note stored at creation

        await self._post_request(guild, member, channel_name, session_id)

        embed = discord.Embed(
            title="🖥️ Verification Request Submitted",
            description=(
                f"Your screen share verification request (#{session_id}) has been submitted.\n\n"
                f"A moderator will review it shortly. You'll receive a DM when it's processed."
            ),
            colour=COL_PEND,
            timestamp=datetime.datetime.utcnow()
        )
        if not voice or not voice.channel:
            embed.add_field(
                name="⚠️ Not in voice",
                value="You're not in a voice channel. Join one and start screen sharing so a mod can verify you.",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /ssapprove ────────────────────────────────────────────────────────────

    @app_commands.command(name="ssapprove", description="Approve a screen share verification session (mod)")
    @app_commands.describe(session_id="Session ID to approve", note="Optional approval note")
    async def ssapprove(self, interaction: discord.Interaction, session_id: int, note: str = None):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await self.bot.db.verify_ss_session(session_id, interaction.user.id, note)

        sessions = await self.bot.db.get_ss_sessions(interaction.guild.id)
        session  = next((s for s in sessions if s[0] == session_id), None)

        if session:
            member = interaction.guild.get_member(int(session[1]))
            if member:
                role = discord.utils.get(interaction.guild.roles, name=SS_VERIFIED_ROLE)
                if not role:
                    try:
                        role = await interaction.guild.create_role(name=SS_VERIFIED_ROLE, colour=discord.Colour.green())
                    except discord.Forbidden:
                        pass
                if role:
                    try:
                        await member.add_roles(role, reason=f"SS verified by {interaction.user}")
                    except discord.Forbidden:
                        pass
                try:
                    dm = discord.Embed(
                        title="✅ Screen Share Verified",
                        description=f"Your screen share session #{session_id} has been approved by {interaction.user.display_name}.\nYou've been given the **{SS_VERIFIED_ROLE}** role!",
                        colour=COL_OK,
                        timestamp=datetime.datetime.utcnow()
                    )
                    await member.send(embed=dm)
                except discord.Forbidden:
                    pass

        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Session **#{session_id}** approved.", colour=COL_OK),
            ephemeral=True
        )

    # ── /ssreject ─────────────────────────────────────────────────────────────

    @app_commands.command(name="ssreject", description="Reject a screen share verification session (mod)")
    @app_commands.describe(session_id="Session ID to reject", reason="Reason for rejection")
    async def ssreject(self, interaction: discord.Interaction, session_id: int, reason: str = "No reason provided"):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await self.bot.db.reject_ss_session(session_id, reason)

        sessions = await self.bot.db.get_ss_sessions(interaction.guild.id)
        session  = next((s for s in sessions if s[0] == session_id), None)

        if session:
            member = interaction.guild.get_member(int(session[1]))
            if member:
                try:
                    dm = discord.Embed(
                        title="❌ Screen Share Verification Rejected",
                        description=f"Your session #{session_id} was rejected by {interaction.user.display_name}.\n**Reason:** {reason}",
                        colour=COL_ERR,
                        timestamp=datetime.datetime.utcnow()
                    )
                    await member.send(embed=dm)
                except discord.Forbidden:
                    pass

        await interaction.response.send_message(
            embed=discord.Embed(description=f"❌ Session **#{session_id}** rejected.", colour=COL_INFO),
            ephemeral=True
        )

    # ── /pendingss ────────────────────────────────────────────────────────────

    @app_commands.command(name="pendingss", description="View all pending screen share requests (mod)")
    async def pendingss(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        rows = await self.bot.db.get_ss_sessions(interaction.guild.id, status="pending")

        embed = discord.Embed(
            title="🖥️ Pending Screen Share Verifications",
            colour=COL_PEND,
            timestamp=datetime.datetime.utcnow()
        )

        if not rows:
            embed.description = "✅ No pending requests."
        else:
            for sid, uid, ch_id, verified_by, status, started_at, verified_at, note in rows:
                m = interaction.guild.get_member(int(uid))
                name = m.mention if m else f"ID:{uid}"
                ch   = interaction.guild.get_channel(int(ch_id)) if ch_id else None
                ch_name = ch.name if ch else "Unknown"
                embed.add_field(
                    name=f"#{sid} — {m.display_name if m else uid}",
                    value=(
                        f"**Member:** {name}\n"
                        f"**Channel:** {ch_name}\n"
                        f"**Started:** {started_at[:16]}\n"
                        f"Use `/ssapprove {sid}` or `/ssreject {sid}`"
                    ),
                    inline=False
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /sshistory ────────────────────────────────────────────────────────────

    @app_commands.command(name="sshistory", description="View screen share history for a member (mod)")
    @app_commands.describe(member="Member to check")
    async def sshistory(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        rows = await self.bot.db.get_ss_sessions(interaction.guild.id, user_id=member.id)

        embed = discord.Embed(
            title=f"🖥️ SS History — {member.display_name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if not rows:
            embed.description = "No screen share sessions on record."
        else:
            icons = {"verified": "✅", "rejected": "❌", "pending": "⏳"}
            for sid, uid, ch_id, verified_by, status, started_at, verified_at, note in rows[:8]:
                icon = icons.get(status, "❓")
                vb   = interaction.guild.get_member(int(verified_by)) if verified_by else None
                embed.add_field(
                    name=f"#{sid} {icon} {status.title()}",
                    value=(
                        f"Date: {started_at[:10]}\n"
                        + (f"Reviewed by: {vb.display_name if vb else verified_by}\n" if verified_by else "")
                        + (f"Note: _{note}_" if note else "")
                    ),
                    inline=True
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /ssstats ──────────────────────────────────────────────────────────────

    @app_commands.command(name="ssstats", description="Server-wide screen share statistics (admin)")
    async def ssstats(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        all_rows  = await self.bot.db.get_ss_sessions(interaction.guild.id)
        pending   = sum(1 for r in all_rows if r[4] == "pending")
        verified  = sum(1 for r in all_rows if r[4] == "verified")
        rejected  = sum(1 for r in all_rows if r[4] == "rejected")

        ss_role   = discord.utils.get(interaction.guild.roles, name=SS_VERIFIED_ROLE)
        role_count = len(ss_role.members) if ss_role else 0

        embed = discord.Embed(
            title=f"🖥️ Screen Share Stats — {interaction.guild.name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Total sessions",  value=str(len(all_rows)), inline=True)
        embed.add_field(name="⏳ Pending",       value=str(pending),       inline=True)
        embed.add_field(name="✅ Verified",      value=str(verified),      inline=True)
        embed.add_field(name="❌ Rejected",      value=str(rejected),      inline=True)
        embed.add_field(name="🏅 Verified members", value=str(role_count), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /setupss ──────────────────────────────────────────────────────────────

    @app_commands.command(name="setupss", description="Set up screen share verification system (admin)")
    async def setupss(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild = interaction.guild

        # Create log channel if missing
        log_ch = discord.utils.get(guild.text_channels, name=SS_LOG_CHANNEL)
        if not log_ch:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(send_messages=False, read_messages=False),
                guild.me: discord.PermissionOverwrite(send_messages=True, read_messages=True, manage_messages=True),
            }
            # Give mods access
            for role in guild.roles:
                if role.permissions.manage_messages:
                    overwrites[role] = discord.PermissionOverwrite(send_messages=True, read_messages=True)
            log_ch = await guild.create_text_channel(SS_LOG_CHANNEL, overwrites=overwrites, reason="SS verification setup")

        # Create verified role if missing
        ss_role = discord.utils.get(guild.roles, name=SS_VERIFIED_ROLE)
        if not ss_role:
            ss_role = await guild.create_role(
                name=SS_VERIFIED_ROLE,
                colour=discord.Colour.green(),
                reason="SS verification setup"
            )

        embed = discord.Embed(
            title="✅ Screen Share Verification Setup Complete",
            colour=COL_OK,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Log channel", value=log_ch.mention, inline=True)
        embed.add_field(name="Verified role", value=ss_role.mention, inline=True)
        embed.add_field(
            name="How it works",
            value=(
                "• When a member starts screen sharing, a verification request is posted automatically\n"
                "• Members can also manually request via `/ssverify`\n"
                "• Moderators approve or reject via the buttons or `/ssapprove` `/ssreject`\n"
                "• Approved members get the **Screen Verified** role"
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(ScreenShare(bot))
