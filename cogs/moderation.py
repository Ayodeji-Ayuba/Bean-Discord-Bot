"""
MODERATION COG
==============
Module 1 — /warn  : Issue warnings, log to #staff-chat, quarantine user
Module 2 — /ban   : Permanent ban with reason + DM
           /kick  : Kick with reason + DM
           /mute  : Timeout (Discord native) up to 28 days
           /unmute: Remove timeout early
           /warnings : View a user's warning history
           /clearwarn: Remove a specific warning
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime

# ── Config ────────────────────────────────────────────────────────────────────
# Set these channel names to match your server exactly
STAFF_CHAT_NAME    = "staff-chat"
QUARANTINE_ROLE    = "Quarantined"
QUARANTINE_CHANNEL = "quarantine"

# Embed colour palette
COL_WARN    = 0xF5A623   # orange
COL_BAN     = 0xE74C3C   # red
COL_KICK    = 0xE67E22   # dark orange
COL_MUTE    = 0x9B59B6   # purple
COL_OK      = 0x2ECC71   # green
COL_INFO    = 0x3498DB   # blue


def _ts():
    return discord.utils.format_dt(datetime.datetime.utcnow(), style="F")


def mod_footer(moderator: discord.Member) -> str:
    return f"Moderator: {moderator} • {discord.utils.format_dt(datetime.datetime.utcnow(), style='R')}"


async def get_staff_channel(guild: discord.Guild):
    return discord.utils.get(guild.text_channels, name=STAFF_CHAT_NAME)


# ── Accept Warning View ───────────────────────────────────────────────────────

class AcceptWarningView(discord.ui.View):
    """Persistent button sent in quarantine channel for the warned user to accept."""

    def __init__(self, user_id: int, guild_id: int, warn_id: int):
        super().__init__(timeout=None)
        self.user_id  = user_id
        self.guild_id = guild_id
        self.warn_id  = warn_id

        # Encode IDs into custom_id so it survives bot restarts
        btn = discord.ui.Button(
            label="✅  I accept this warning",
            style=discord.ButtonStyle.success,
            custom_id=f"accept_warning:{user_id}:{warn_id}"
        )
        btn.callback = self.accept
        self.add_item(btn)

    async def accept(self, interaction: discord.Interaction):
        # Parse IDs from custom_id
        _, user_id_str, warn_id_str = interaction.data["custom_id"].split(":")
        user_id = int(user_id_str)
        warn_id = int(warn_id_str)

        # Only the warned user can click
        if interaction.user.id != user_id:
            await interaction.response.send_message(
                "This button is not for you.", ephemeral=True
            )
            return

        guild  = interaction.guild
        member = guild.get_member(user_id)
        if not member:
            await interaction.response.send_message(
                "Could not find you in the server.", ephemeral=True
            )
            return

        # Remove quarantine role
        q_role = discord.utils.get(guild.roles, name=QUARANTINE_ROLE)
        if q_role and q_role in member.roles:
            await member.remove_roles(q_role, reason="Warning accepted")

        # Mark warning as acknowledged in DB
        await interaction.client.db.clear_warning(warn_id)

        # Disable button
        for item in self.children:
            item.disabled = True
            item.label = "✅  Warning accepted"
        await interaction.response.edit_message(view=self)

        # Notify staff-chat
        staff_ch = await get_staff_channel(guild)
        if staff_ch:
            embed = discord.Embed(
                title="⚠️  Warning Accepted",
                description=f"{member.mention} has accepted their warning and been released from quarantine.",
                colour=COL_OK,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await staff_ch.send(embed=embed)


# ── Moderation Cog ────────────────────────────────────────────────────────────

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Helper: permission check ──────────────────────────────────────────────

    def _is_mod(self, member: discord.Member) -> bool:
        return (
            member.guild_permissions.manage_messages
            or member.guild_permissions.ban_members
            or member.guild_permissions.administrator
        )

    async def _check_mod(self, interaction: discord.Interaction) -> bool:
        if not self._is_mod(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True
            )
            return False
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # MODULE 1 — /warn
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Issue a warning to a member")
    @app_commands.describe(
        member="The member to warn",
        reason="Reason for the warning"
    )
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str
    ):
        if not await self._check_mod(interaction):
            return

        guild = interaction.guild

        # Prevent warning bots or higher-ranked members
        if member.bot:
            return await interaction.response.send_message("❌ Cannot warn a bot.", ephemeral=True)
        if member.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ You cannot warn someone with equal or higher rank.", ephemeral=True)

        # Save to database
        db = self.bot.db
        warn_id = await db.add_warning(guild.id, member.id, interaction.user.id, reason)
        warn_count = await db.count_active_warnings(guild.id, member.id)
        await db.log_action(guild.id, "WARN", member.id, interaction.user.id, reason)

        # ── Apply quarantine role ─────────────────────────────────────────────
        q_role = discord.utils.get(guild.roles, name=QUARANTINE_ROLE)
        if not q_role:
            # Auto-create the role if it doesn't exist
            q_role = await guild.create_role(
                name=QUARANTINE_ROLE,
                colour=discord.Colour.dark_red(),
                reason="Auto-created by bot for warning quarantine"
            )
            # Lock all channels for this role
            for channel in guild.channels:
                await channel.set_permissions(q_role, send_messages=False, speak=False, read_messages=False)

        await member.add_roles(q_role, reason=f"Warned: {reason}")

        # ── Grant access only to #quarantine ──────────────────────────────────
        q_channel = discord.utils.get(guild.text_channels, name=QUARANTINE_CHANNEL)
        if q_channel:
            await q_channel.set_permissions(q_role, read_messages=True, send_messages=False)

        # ── DM the warned user ────────────────────────────────────────────────
        dm_embed = discord.Embed(
            title=f"⚠️  You have received a warning in {guild.name}",
            colour=COL_WARN,
            timestamp=datetime.datetime.utcnow()
        )
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        dm_embed.add_field(name="Total warnings", value=str(warn_count), inline=True)
        dm_embed.add_field(name="Issued by", value=str(interaction.user), inline=True)
        dm_embed.set_footer(text="Please accept your warning in the server to regain access.")
        try:
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # User has DMs closed

        # ── Post in #quarantine with accept button ────────────────────────────
        if q_channel:
            q_embed = discord.Embed(
                title="⚠️  Warning Issued",
                description=(
                    f"You have been warned, {member.mention}.\n\n"
                    f"**Reason:** {reason}\n\n"
                    "You are currently locked out of the server. "
                    "Press the button below to acknowledge and accept this warning "
                    "to regain access to all channels."
                ),
                colour=COL_WARN,
                timestamp=datetime.datetime.utcnow()
            )
            q_embed.set_footer(text=f"Warning #{warn_count} • ID: {warn_id}")
            view = AcceptWarningView(member.id, guild.id, warn_id)
            await q_channel.send(content=member.mention, embed=q_embed, view=view)

        # ── Log to #staff-chat ────────────────────────────────────────────────
        staff_ch = await get_staff_channel(guild)
        if staff_ch:
            log_embed = discord.Embed(
                title="⚠️  Warning Issued",
                colour=COL_WARN,
                timestamp=datetime.datetime.utcnow()
            )
            log_embed.set_thumbnail(url=member.display_avatar.url)
            log_embed.add_field(name="User",      value=f"{member.mention} (`{member.id}`)", inline=False)
            log_embed.add_field(name="Reason",    value=reason, inline=False)
            log_embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
            log_embed.add_field(name="Total warns",value=str(warn_count), inline=True)
            log_embed.add_field(name="Warn ID",   value=str(warn_id), inline=True)
            log_embed.set_footer(text=f"Awaiting acknowledgement • ID: {warn_id}")
            await staff_ch.send(embed=log_embed)

        # ── Confirm to moderator ──────────────────────────────────────────────
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ {member.mention} has been warned and quarantined. **Warn #{warn_count}**",
                colour=COL_OK
            ),
            ephemeral=True
        )

    # ── /warnings ─────────────────────────────────────────────────────────────

    @app_commands.command(name="warnings", description="View warning history for a member")
    @app_commands.describe(member="Member to check")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await self._check_mod(interaction):
            return

        db = self.bot.db
        rows = await db.get_warnings(interaction.guild.id, member.id)

        embed = discord.Embed(
            title=f"Warning history — {member.display_name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if not rows:
            embed.description = "No warnings on record."
        else:
            for row in rows[:10]:  # show latest 10
                warn_id, mod_id, reason, created_at, active = row
                mod = interaction.guild.get_member(int(mod_id))
                mod_name = str(mod) if mod else f"ID:{mod_id}"
                status = "🟡 Active" if active else "✅ Cleared"
                embed.add_field(
                    name=f"#{warn_id} — {status}",
                    value=f"**Reason:** {reason}\n**By:** {mod_name}\n**Date:** {created_at[:10]}",
                    inline=False
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /clearwarn ────────────────────────────────────────────────────────────

    @app_commands.command(name="clearwarn", description="Clear a specific warning by ID")
    @app_commands.describe(warn_id="The warning ID to clear (see /warnings)")
    async def clearwarn(self, interaction: discord.Interaction, warn_id: int):
        if not await self._check_mod(interaction):
            return

        await self.bot.db.clear_warning(warn_id)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Warning `#{warn_id}` cleared.", colour=COL_OK),
            ephemeral=True
        )

    # ─────────────────────────────────────────────────────────────────────────
    # MODULE 2 — /ban, /kick, /mute, /unmute, /modlogs
    # ─────────────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Permanently ban a member")
    @app_commands.describe(member="Member to ban", reason="Reason for ban", delete_days="Days of messages to delete (0-7)")
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
        delete_days: app_commands.Range[int, 0, 7] = 0
    ):
        if not await self._check_mod(interaction):
            return
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ You need Ban Members permission.", ephemeral=True)
        if member.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Cannot ban someone with equal or higher rank.", ephemeral=True)

        # DM before ban
        try:
            dm = discord.Embed(
                title=f"🔨 You have been banned from {interaction.guild.name}",
                colour=COL_BAN,
                timestamp=datetime.datetime.utcnow()
            )
            dm.add_field(name="Reason", value=reason)
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

        await member.ban(reason=f"{interaction.user} — {reason}", delete_message_days=delete_days)
        await self.bot.db.log_action(interaction.guild.id, "BAN", member.id, interaction.user.id, reason)

        embed = discord.Embed(
            title="🔨 Member Banned",
            colour=COL_BAN,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=mod_footer(interaction.user))

        staff_ch = await get_staff_channel(interaction.guild)
        if staff_ch:
            await staff_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ **{member}** has been banned.", colour=COL_OK),
            ephemeral=True
        )

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for kick")
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        if not await self._check_mod(interaction):
            return
        if not interaction.user.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ You need Kick Members permission.", ephemeral=True)
        if member.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Cannot kick someone with equal or higher rank.", ephemeral=True)

        try:
            dm = discord.Embed(
                title=f"👢 You have been kicked from {interaction.guild.name}",
                colour=COL_KICK
            )
            dm.add_field(name="Reason", value=reason)
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

        await member.kick(reason=f"{interaction.user} — {reason}")
        await self.bot.db.log_action(interaction.guild.id, "KICK", member.id, interaction.user.id, reason)

        embed = discord.Embed(title="👢 Member Kicked", colour=COL_KICK, timestamp=datetime.datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=mod_footer(interaction.user))

        staff_ch = await get_staff_channel(interaction.guild)
        if staff_ch:
            await staff_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ **{member}** has been kicked.", colour=COL_OK),
            ephemeral=True
        )

    @app_commands.command(name="mute", description="Timeout (mute) a member")
    @app_commands.describe(
        member="Member to mute",
        duration="Duration in minutes (max 40320 = 28 days)",
        reason="Reason for mute"
    )
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: app_commands.Range[int, 1, 40320],
        reason: str = "No reason provided"
    ):
        if not await self._check_mod(interaction):
            return
        if member.top_role >= interaction.user.top_role and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Cannot mute someone with equal or higher rank.", ephemeral=True)

        until = discord.utils.utcnow() + datetime.timedelta(minutes=duration)
        await member.timeout(until, reason=f"{interaction.user} — {reason}")
        await self.bot.db.log_action(interaction.guild.id, "MUTE", member.id, interaction.user.id, reason, f"{duration}m")

        human_dur = f"{duration}m" if duration < 60 else f"{duration//60}h {duration%60}m"
        embed = discord.Embed(title="🔇 Member Muted", colour=COL_MUTE, timestamp=datetime.datetime.utcnow())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User",     value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Duration", value=human_dur, inline=True)
        embed.add_field(name="Expires",  value=discord.utils.format_dt(until, style="R"), inline=True)
        embed.add_field(name="Reason",   value=reason, inline=False)
        embed.set_footer(text=mod_footer(interaction.user))

        staff_ch = await get_staff_channel(interaction.guild)
        if staff_ch:
            await staff_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ **{member}** muted for **{human_dur}**.", colour=COL_OK),
            ephemeral=True
        )

    @app_commands.command(name="unmute", description="Remove a member's timeout early")
    @app_commands.describe(member="Member to unmute", reason="Reason for early unmute")
    async def unmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided"
    ):
        if not await self._check_mod(interaction):
            return

        await member.timeout(None, reason=f"{interaction.user} — {reason}")
        await self.bot.db.log_action(interaction.guild.id, "UNMUTE", member.id, interaction.user.id, reason)

        staff_ch = await get_staff_channel(interaction.guild)
        if staff_ch:
            embed = discord.Embed(title="🔊 Member Unmuted", colour=COL_OK, timestamp=datetime.datetime.utcnow())
            embed.add_field(name="User",   value=member.mention, inline=True)
            embed.add_field(name="By",     value=interaction.user.mention, inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            await staff_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ **{member}** has been unmuted.", colour=COL_OK),
            ephemeral=True
        )

    @app_commands.command(name="modlogs", description="View recent moderation action log")
    @app_commands.describe(member="Filter by member (optional)")
    async def modlogs(
        self,
        interaction: discord.Interaction,
        member: discord.Member = None
    ):
        if not await self._check_mod(interaction):
            return

        rows = await self.bot.db.get_mod_logs(interaction.guild.id, member.id if member else None)
        embed = discord.Embed(
            title=f"Mod logs{f' — {member.display_name}' if member else ''}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        if not rows:
            embed.description = "No mod actions on record."
        else:
            icons = {"BAN":"🔨","KICK":"👢","MUTE":"🔇","UNMUTE":"🔊","WARN":"⚠️"}
            for row in rows[:10]:
                action, user_id, mod_id, reason, duration, created_at = row
                icon = icons.get(action, "🛡️")
                u = interaction.guild.get_member(int(user_id))
                m = interaction.guild.get_member(int(mod_id))
                dur_txt = f" ({duration})" if duration else ""
                embed.add_field(
                    name=f"{icon} {action}{dur_txt} — {created_at[:10]}",
                    value=(
                        f"**User:** {u.mention if u else user_id}\n"
                        f"**Mod:** {m.mention if m else mod_id}\n"
                        f"**Reason:** {reason or 'None'}"
                    ),
                    inline=False
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
    bot.add_view(AcceptWarningView(0, 0, 0))  # registers the custom_id pattern