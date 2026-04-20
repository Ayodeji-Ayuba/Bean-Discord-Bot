"""
INFRASTRUCTURE & SCALABILITY COG — Module 15
=============================================
Features:
  • /healthcheck   — bot latency, memory, uptime, DB size, guild stats
  • /setconfig     — set a server configuration value (admin)
  • /getconfig     — view all server config values (admin)
  • /rolesetup     — bulk-create a standard role hierarchy (admin)
  • /channelsetup  — bulk-create standard channel categories (admin)
  • /slowmode      — set slowmode on any channel (mod)
  • /lock          — lock a channel (mod)
  • /unlock        — unlock a channel (mod)
  • /nuke          — clone + delete a channel to wipe all messages (admin)
  • /permissions   — audit a member's effective permissions (mod)
  • /roleinfo      — detailed info about a role (mod)
  • /serveraudit   — full server security audit report (admin)
  • /cleanup       — remove all bot messages in a channel (mod)
  • Background task — auto-logs health metrics every 10 minutes
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import time
import os

STAFF_CHAT_NAME = "staff-chat"

COL_OK   = 0x2ECC71
COL_ERR  = 0xE74C3C
COL_INFO = 0x3498DB
COL_WARN = 0xF5A623
COL_GOLD = 0xF39C12
GUILD_ID = discord.Object(id=1494477579149774879)

# Standard role hierarchy template
STANDARD_ROLES = [
    ("👑 Owner",       0xF1C40F, True),
    ("⚙️ Admin",       0xE74C3C, True),
    ("🛡️ Moderator",   0x9B59B6, True),
    ("🌟 VIP",         0xE67E22, False),
    ("💎 Legend",      0x1ABC9C, False),
    ("🔥 Veteran",     0x3498DB, False),
    ("💬 Regular",     0x2ECC71, False),
    ("✅ Member",      0x95A5A6, False),
    ("🔞 18+",         0xE74C3C, False),
    ("🤖 Bot",         0x7F8C8D, True),
    ("📵 Muted",       0x2C3E50, False),
    ("⚠️ Quarantined", 0x922B21, False),
]

# Standard channel categories
STANDARD_CHANNELS = {
    "📢 Information": [
        ("📋│rules",          False, False),
        ("📣│announcements",  False, False),
        ("🗺️│roadmap",        False, False),
    ],
    "🏠 General": [
        ("💬│general",        True, False),
        ("😂│memes",          True, False),
        ("🖼️│media",          True, False),
        ("👋│introductions",  True, False),
    ],
    "🎮 Entertainment": [
        ("🎰│casino",         True, False),
        ("🏆│leaderboards",   False, False),
        ("🪙│crypto-updates", True, False),
    ],
    "🔒 Staff Only": [
        ("📊│staff-chat",     True, False),
        ("🚨│mod-log",        True, False),
        ("📋│leave-requests", True, False),
        ("🖥️│ss-verify-log",  True, False),
    ],
    "✅ Onboarding": [
        ("🔐│verify",         True, False),
        ("⚠️│quarantine",     True, False),
        ("👋│welcome",        False, False),
    ],
    "📞 Voice": [],  # voice channels handled separately
}


def _fmt_bytes(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class Infra(commands.Cog):
    def __init__(self, bot):
        self.bot        = bot
        self._start     = time.time()
        self._health_task = None

    async def cog_load(self):
        self._health_task = self.bot.loop.create_task(self._health_loop())

    async def cog_unload(self):
        if self._health_task:
            self._health_task.cancel()

    # ── Background health logging ──────────────────────────────────────────────

    async def _health_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                latency = round(self.bot.latency * 1000, 2)
                guilds  = len(self.bot.guilds)
                members = sum(g.member_count for g in self.bot.guilds)
                for guild in self.bot.guilds:
                    await self.bot.db.log_health(guild.id, latency, guilds, members)
            except Exception as e:
                print(f"[Infra] Health log error: {e}")
            await asyncio.sleep(600)  # every 10 minutes

    # ── /healthcheck ──────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="healthcheck", description="Bot health — latency, uptime, and system stats")
    async def healthcheck(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        latency   = round(self.bot.latency * 1000, 2)
        uptime_s  = int(time.time() - self._start)
        guilds    = len(self.bot.guilds)
        members   = sum(g.member_count for g in self.bot.guilds)
        cogs      = len(self.bot.cogs)
        commands  = len(self.bot.tree.get_commands())

        # DB file size
        db_path   = "data/bot.db"
        db_size   = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        # Memory (optional — psutil)
        mem_text = "N/A (install psutil)"
        try:
            import psutil
            proc    = psutil.Process()
            mem_mb  = proc.memory_info().rss / 1024 / 1024
            cpu_pct = proc.cpu_percent(interval=0.1)
            mem_text = f"{mem_mb:.1f} MB RAM · {cpu_pct:.1f}% CPU"
        except ImportError:
            pass

        # Latency colour
        colour = COL_OK if latency < 100 else (COL_WARN if latency < 300 else COL_ERR)

        # Uptime breakdown
        d, rem  = divmod(uptime_s, 86400)
        h, rem  = divmod(rem, 3600)
        m, s    = divmod(rem, 60)
        uptime  = f"{d}d {h}h {m}m {s}s"

        embed = discord.Embed(
            title="🤖 Bot Health Check",
            colour=colour,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="📡 Latency",     value=f"`{latency}ms`", inline=True)
        embed.add_field(name="⏱️ Uptime",       value=uptime, inline=True)
        embed.add_field(name="🏠 Guilds",       value=str(guilds), inline=True)
        embed.add_field(name="👥 Members",      value=f"{members:,}", inline=True)
        embed.add_field(name="📦 Cogs",         value=str(cogs), inline=True)
        embed.add_field(name="⚡ Commands",     value=str(commands), inline=True)
        embed.add_field(name="🗄️ DB size",      value=_fmt_bytes(db_size), inline=True)
        embed.add_field(name="💻 Resources",    value=mem_text, inline=True)

        status_icon = "🟢" if latency < 100 else ("🟡" if latency < 300 else "🔴")
        embed.description = f"{status_icon} Bot is **{'healthy' if latency < 200 else 'degraded'}**"
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /setconfig / /getconfig ───────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="setconfig", description="Set a server configuration value (admin)")
    @app_commands.describe(key="Config key (e.g. welcome_message)", value="Value to store")
    async def setconfig(self, interaction: discord.Interaction, key: str, value: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await self.bot.db.set_config(interaction.guild.id, key, value)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Config `{key}` set to `{value[:100]}`.", colour=COL_OK),
            ephemeral=True
        )

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="getconfig", description="View all server config values (admin)")
    async def getconfig(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        rows = await self.bot.db.get_all_config(interaction.guild.id)
        embed = discord.Embed(title="⚙️ Server Configuration", colour=COL_INFO, timestamp=datetime.datetime.utcnow())

        if not rows:
            embed.description = "No config values set. Use `/setconfig` to add some."
        else:
            for key, value, updated_at in rows:
                embed.add_field(name=key, value=f"`{value[:100]}`\n_Updated: {updated_at[:10]}_", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /rolesetup ────────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="rolesetup", description="Bulk-create standard role hierarchy (admin)")
    async def rolesetup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild    = interaction.guild
        created  = []
        existing = []

        for name, colour_int, hoist in STANDARD_ROLES:
            existing_role = discord.utils.get(guild.roles, name=name)
            if existing_role:
                existing.append(name)
                continue
            try:
                await guild.create_role(
                    name=name,
                    colour=discord.Colour(colour_int),
                    hoist=hoist,
                    reason=f"Role setup by {interaction.user}"
                )
                created.append(name)
                await asyncio.sleep(0.5)  # rate limit buffer
            except discord.Forbidden:
                pass

        embed = discord.Embed(
            title="🎭 Role Setup Complete",
            colour=COL_OK,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name=f"✅ Created ({len(created)})", value="\n".join(created) or "None", inline=True)
        embed.add_field(name=f"⏭️ Skipped ({len(existing)})", value="\n".join(existing[:10]) or "None", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /channelsetup ─────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="channelsetup", description="Bulk-create standard channel categories (admin)")
    async def channelsetup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild   = interaction.guild
        created = 0

        for cat_name, channels in STANDARD_CHANNELS.items():
            # Create category if missing
            cat = discord.utils.get(guild.categories, name=cat_name)
            if not cat:
                try:
                    cat = await guild.create_category(cat_name, reason="Channel setup")
                    await asyncio.sleep(0.5)
                except discord.Forbidden:
                    continue

            # Create channels in category
            for ch_name, can_send, is_nsfw in channels:
                existing = discord.utils.get(guild.text_channels, name=ch_name.split("│")[-1])
                if existing:
                    continue
                try:
                    overwrite = {guild.default_role: discord.PermissionOverwrite(send_messages=can_send)}
                    await guild.create_text_channel(
                        ch_name,
                        category=cat,
                        overwrites=overwrite,
                        nsfw=is_nsfw,
                        reason="Channel setup"
                    )
                    created += 1
                    await asyncio.sleep(0.5)
                except discord.Forbidden:
                    pass

        embed = discord.Embed(
            title="📁 Channel Setup Complete",
            description=f"Created **{created}** channel(s) across {len(STANDARD_CHANNELS)} categories.",
            colour=COL_OK,
            timestamp=datetime.datetime.utcnow()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /slowmode ─────────────────────────────────────────────────────────────
    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="slowmode", description="Set slowmode on a channel (mod)")
    @app_commands.describe(
        seconds="Slowmode delay in seconds (0 = disable)",
        channel="Channel to apply to (default: current)"
    )
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
        channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Manage Channels permission required.", ephemeral=True)

        target = channel or interaction.channel
        await target.edit(slowmode_delay=seconds, reason=f"Slowmode set by {interaction.user}")

        msg = f"⏱️ Slowmode {'disabled' if seconds == 0 else f'set to **{seconds}s**'} in {target.mention}."
        await interaction.response.send_message(
            embed=discord.Embed(description=msg, colour=COL_OK if seconds == 0 else COL_WARN),
            ephemeral=True
        )

        staff_ch = discord.utils.get(interaction.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch and target != staff_ch:
            await staff_ch.send(embed=discord.Embed(description=f"🛡️ {interaction.user.mention} {msg}", colour=COL_WARN))

    # ── /lock / /unlock ───────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="lock", description="Lock a channel — prevent members from sending messages (mod)")
    @app_commands.describe(channel="Channel to lock (default: current)", reason="Reason for lock")
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "No reason"):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Manage Channels required.", ephemeral=True)

        target = channel or interaction.channel
        overwrite = target.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=reason)

        embed = discord.Embed(
            title="🔒 Channel Locked",
            description=f"{target.mention} has been locked.\n**Reason:** {reason}",
            colour=COL_ERR,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text=f"By {interaction.user.display_name}")
        await target.send(embed=embed)
        await interaction.response.send_message(embed=discord.Embed(description=f"✅ {target.mention} locked.", colour=COL_OK), ephemeral=True)

        staff_ch = discord.utils.get(interaction.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch and target != staff_ch:
            await staff_ch.send(embed=embed)

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="unlock", description="Unlock a channel (mod)")
    @app_commands.describe(channel="Channel to unlock (default: current)")
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ Manage Channels required.", ephemeral=True)

        target = channel or interaction.channel
        overwrite = target.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)

        embed = discord.Embed(
            title="🔓 Channel Unlocked",
            description=f"{target.mention} is now open.",
            colour=COL_OK,
            timestamp=datetime.datetime.utcnow()
        )
        await target.send(embed=embed)
        await interaction.response.send_message(embed=discord.Embed(description=f"✅ {target.mention} unlocked.", colour=COL_OK), ephemeral=True)

    # ── /nuke ─────────────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="nuke", description="Clone and delete a channel to wipe all messages (admin)")
    @app_commands.describe(channel="Channel to nuke (default: current)", reason="Reason")
    async def nuke(self, interaction: discord.Interaction, channel: discord.TextChannel = None, reason: str = "Channel nuke"):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        target   = channel or interaction.channel
        position = target.position

        await interaction.response.send_message(
            embed=discord.Embed(description=f"💣 Nuking {target.mention}...", colour=COL_ERR),
            ephemeral=True
        )

        new_ch = await target.clone(reason=f"{reason} — by {interaction.user}")
        await new_ch.edit(position=position)
        await target.delete(reason=f"Nuked by {interaction.user}: {reason}")

        embed = discord.Embed(
            title="💥 Channel Nuked",
            description=f"This channel was wiped by {interaction.user.mention}.\n**Reason:** {reason}",
            colour=COL_ERR,
            timestamp=datetime.datetime.utcnow()
        )
        await new_ch.send(embed=embed)

        staff_ch = discord.utils.get(interaction.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            await staff_ch.send(embed=discord.Embed(
                title="💥 Channel Nuked",
                description=f"{interaction.user.mention} nuked a channel.\n**Reason:** {reason}",
                colour=COL_ERR,
                timestamp=datetime.datetime.utcnow()
            ))

    # ── /permissions ──────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="permissions", description="Audit a member's effective permissions (mod)")
    @app_commands.describe(member="Member to audit", channel="Channel context (optional)")
    async def permissions(self, interaction: discord.Interaction, member: discord.Member, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        perms = channel.permissions_for(member) if channel else member.guild_permissions
        context = f"in {channel.mention}" if channel else "server-wide"

        PERM_LABELS = [
            ("administrator",        "👑 Administrator"),
            ("manage_guild",         "⚙️ Manage Server"),
            ("manage_channels",      "📁 Manage Channels"),
            ("manage_roles",         "🎭 Manage Roles"),
            ("manage_messages",      "🗑️ Manage Messages"),
            ("ban_members",          "🔨 Ban Members"),
            ("kick_members",         "👢 Kick Members"),
            ("moderate_members",     "⏱️ Timeout Members"),
            ("mention_everyone",     "📢 Mention Everyone"),
            ("send_messages",        "💬 Send Messages"),
            ("read_messages",        "👁️ Read Messages"),
            ("embed_links",          "🔗 Embed Links"),
            ("attach_files",         "📎 Attach Files"),
            ("use_application_commands", "⚡ Use Slash Commands"),
            ("connect",              "🔊 Connect to Voice"),
            ("speak",                "🎙️ Speak in Voice"),
        ]

        granted = []
        denied  = []
        for attr, label in PERM_LABELS:
            if getattr(perms, attr, False):
                granted.append(f"✅ {label}")
            else:
                denied.append(f"❌ {label}")

        embed = discord.Embed(
            title=f"🔐 Permissions — {member.display_name} {context}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Granted", value="\n".join(granted) or "None", inline=True)
        embed.add_field(name="Denied",  value="\n".join(denied) or "None", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /roleinfo ─────────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="roleinfo", description="Detailed info about a role (mod)")
    @app_commands.describe(role="Role to inspect")
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        embed = discord.Embed(
            title=f"🎭 Role Info — {role.name}",
            colour=role.colour,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="ID",         value=str(role.id), inline=True)
        embed.add_field(name="Members",    value=str(len(role.members)), inline=True)
        embed.add_field(name="Position",   value=str(role.position), inline=True)
        embed.add_field(name="Hoisted",    value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Mentionable",value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Created",    value=discord.utils.format_dt(role.created_at, style="D"), inline=True)
        embed.add_field(name="Colour",     value=str(role.colour), inline=True)

        key_perms = [p for p, v in role.permissions if v and p in
                     ("administrator","manage_guild","ban_members","kick_members","manage_roles","manage_channels")]
        if key_perms:
            embed.add_field(name="Key permissions", value=", ".join(key_perms), inline=False)

        if role.members:
            sample = ", ".join(m.display_name for m in role.members[:10])
            if len(role.members) > 10:
                sample += f" +{len(role.members)-10} more"
            embed.add_field(name="Members (sample)", value=sample, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /serveraudit ──────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="serveraudit", description="Full server security audit report (admin)")
    async def serveraudit(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        issues   = []
        warnings = []
        passed   = []

        # Check 2FA requirement
        if guild.mfa_level == discord.MFALevel.require_2fa:
            passed.append("✅ 2FA required for moderators")
        else:
            warnings.append("⚠️ 2FA not required for moderators")

        # Check verification level
        if guild.verification_level >= discord.VerificationLevel.medium:
            passed.append(f"✅ Verification level: {guild.verification_level.name}")
        else:
            warnings.append(f"⚠️ Low verification level: {guild.verification_level.name}")

        # Check for admin roles given to bots
        bot_admins = [m for m in guild.members if m.bot and m.guild_permissions.administrator]
        if not bot_admins:
            passed.append("✅ No bots have administrator permission")
        else:
            issues.append(f"🔴 {len(bot_admins)} bot(s) have administrator: {', '.join(b.name for b in bot_admins)}")

        # Check for dangerous @everyone permissions
        everyone = guild.default_role
        if everyone.permissions.administrator:
            issues.append("🔴 @everyone has Administrator permission!")
        elif everyone.permissions.manage_guild:
            issues.append("🔴 @everyone has Manage Server permission!")
        elif everyone.permissions.manage_roles:
            warnings.append("⚠️ @everyone has Manage Roles permission")
        else:
            passed.append("✅ @everyone has safe permissions")

        # Check for roles with dangerous permissions
        risky_roles = [
            r for r in guild.roles
            if r != guild.default_role and not r.managed
            and (r.permissions.administrator or r.permissions.manage_guild)
            and len(r.members) > 10
        ]
        if risky_roles:
            warnings.append(f"⚠️ {len(risky_roles)} role(s) with admin/server perms have 10+ members")
        else:
            passed.append("✅ No overpowered roles with large membership")

        # Check for #staff-chat security
        staff_ch = discord.utils.get(guild.text_channels, name="staff-chat")
        if staff_ch:
            ev_perms = staff_ch.permissions_for(guild.default_role)
            if not ev_perms.read_messages:
                passed.append("✅ #staff-chat is private")
            else:
                issues.append("🔴 #staff-chat is visible to @everyone!")
        else:
            warnings.append("⚠️ No #staff-chat channel found")

        # New accounts
        new_acct_threshold = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        new_members = [m for m in guild.members if not m.bot and m.created_at.replace(tzinfo=None) > new_acct_threshold]
        if len(new_members) > 5:
            warnings.append(f"⚠️ {len(new_members)} members joined with accounts < 7 days old")
        else:
            passed.append("✅ Low volume of new account members")

        # Overall score
        score = len(passed) / max(1, len(passed) + len(warnings) + len(issues)) * 100
        colour = COL_OK if score >= 80 else (COL_WARN if score >= 50 else COL_ERR)
        grade  = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"

        embed = discord.Embed(
            title=f"🔍 Security Audit — {guild.name}",
            description=f"**Security Score: {score:.0f}% (Grade {grade})**",
            colour=colour,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

        if issues:
            embed.add_field(name="🔴 Critical Issues", value="\n".join(issues), inline=False)
        if warnings:
            embed.add_field(name="⚠️ Warnings", value="\n".join(warnings), inline=False)
        if passed:
            embed.add_field(name="✅ Passed", value="\n".join(passed[:8]), inline=False)

        embed.set_footer(text=f"Audited by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /cleanup ──────────────────────────────────────────────────────────────

    @app_commands.guilds(GUILD_ID)
    @app_commands.command(name="cleanup", description="Remove bot messages from a channel (mod)")
    @app_commands.describe(limit="Max messages to scan (default 50)", channel="Channel to clean")
    async def cleanup(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 200] = 50, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        target  = channel or interaction.channel
        deleted = await target.purge(limit=limit, check=lambda m: m.author == self.bot.user)

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"🧹 Removed **{len(deleted)}** bot message(s) from {target.mention}.",
                colour=COL_OK
            ),
            ephemeral=True
        )


async def setup(bot):
    cog = Infra(bot)
    await bot.add_cog(cog)
    # Remove infra commands from global tree to avoid the 100-command limit
    for command in cog.get_app_commands():
        bot.tree.remove_command(command.name)