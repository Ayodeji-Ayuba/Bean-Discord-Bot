"""
COMPLIANCE MONITORING COG — Module 9
======================================
Features:
  • /addrule        — define a compliance rule (admin)
  • /rules          — list all active compliance rules
  • /incident       — report a compliance breach against a member (mod)
  • /incidents      — view open/all incidents (mod)
  • /resolveincident— mark an incident as resolved (mod)
  • /compliancereport — server-wide compliance dashboard (admin)
  • /memberaudit    — full compliance audit for one member (mod)
  • Severity levels: low, medium, high, critical
  • Auto-escalation: critical incidents ping admins in #staff-chat
  • Auto-mutes on critical severity if configured
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime

STAFF_CHAT_NAME = "staff-chat"

SEVERITY_LEVELS = ["low", "medium", "high", "critical"]

SEVERITY_COLOURS = {
    "low":      0x2ECC71,
    "medium":   0xF5A623,
    "high":     0xE67E22,
    "critical": 0xE74C3C,
}

SEVERITY_ICONS = {
    "low":      "🟢",
    "medium":   "🟡",
    "high":     "🟠",
    "critical": "🔴",
}

# Auto-mute duration (minutes) on critical incidents — set 0 to disable
CRITICAL_AUTO_MUTE_MINUTES = 30

COL_OK   = 0x2ECC71
COL_INFO = 0x3498DB


class Compliance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_mod(self, member):
        return member.guild_permissions.manage_messages or member.guild_permissions.administrator

    async def _staff_ch(self, guild):
        return discord.utils.get(guild.text_channels, name=STAFF_CHAT_NAME)

    # ── /addrule ──────────────────────────────────────────────────────────────

    @app_commands.command(name="addrule", description="Add a compliance rule (admin)")
    @app_commands.describe(
        name="Short rule name (e.g. 'No Harassment')",
        description="Detailed rule description",
        severity="Default severity when this rule is breached"
    )
    @app_commands.choices(severity=[app_commands.Choice(name=s.title(), value=s) for s in SEVERITY_LEVELS])
    async def addrule(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        severity: str = "medium"
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        rule_id = await self.bot.db.add_compliance_rule(interaction.guild.id, name, description, severity)

        embed = discord.Embed(
            title="📋 Compliance Rule Added",
            colour=SEVERITY_COLOURS[severity],
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Rule ID",     value=f"#{rule_id}", inline=True)
        embed.add_field(name="Name",        value=name, inline=True)
        embed.add_field(name="Severity",    value=f"{SEVERITY_ICONS[severity]} {severity.title()}", inline=True)
        embed.add_field(name="Description", value=description, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /rules ────────────────────────────────────────────────────────────────

    @app_commands.command(name="rules", description="List all active compliance rules")
    async def rules(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_rules(interaction.guild.id)

        embed = discord.Embed(
            title=f"📋 Compliance Rules — {interaction.guild.name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )

        if not rows:
            embed.description = "No compliance rules defined. Use `/addrule` to create one."
        else:
            for rule_id, rule_name, desc, severity, active in rows:
                icon = SEVERITY_ICONS.get(severity, "⚪")
                embed.add_field(
                    name=f"#{rule_id} {icon} {rule_name}",
                    value=f"**Severity:** {severity.title()}\n{desc[:120]}{'...' if len(desc) > 120 else ''}",
                    inline=False
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /incident ─────────────────────────────────────────────────────────────

    @app_commands.command(name="incident", description="Report a compliance incident against a member (mod)")
    @app_commands.describe(
        member="Member involved in the incident",
        rule_name="Rule that was breached (or describe it)",
        description="What happened",
        severity="Incident severity level",
        rule_id="Optional rule ID from /rules"
    )
    @app_commands.choices(severity=[app_commands.Choice(name=s.title(), value=s) for s in SEVERITY_LEVELS])
    async def incident(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rule_name: str,
        description: str,
        severity: str = "medium",
        rule_id: int = None
    ):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        incident_id = await self.bot.db.log_incident(
            interaction.guild.id, member.id, rule_name,
            description, severity, interaction.user.id, rule_id
        )

        colour = SEVERITY_COLOURS[severity]
        icon   = SEVERITY_ICONS[severity]

        embed = discord.Embed(
            title=f"{icon} Compliance Incident #{incident_id}",
            colour=colour,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member",      value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Rule",        value=rule_name, inline=True)
        embed.add_field(name="Severity",    value=f"{icon} {severity.title()}", inline=True)
        embed.add_field(name="Reported by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Description", value=description, inline=False)
        embed.add_field(name="Status",      value="🔓 **Open**", inline=True)
        embed.set_footer(text=f"Incident ID #{incident_id} • Use /resolveincident to close")

        staff_ch = await self._staff_ch(interaction.guild)

        # Auto-escalation for critical
        if severity == "critical":
            admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
            mention = admin_role.mention if admin_role else "@here"

            if CRITICAL_AUTO_MUTE_MINUTES > 0:
                until = discord.utils.utcnow() + datetime.timedelta(minutes=CRITICAL_AUTO_MUTE_MINUTES)
                try:
                    await member.timeout(until, reason=f"Compliance — critical incident #{incident_id}: {rule_name}")
                    embed.add_field(
                        name="⚠️ Auto Action",
                        value=f"Member auto-muted for {CRITICAL_AUTO_MUTE_MINUTES} minutes due to critical severity.",
                        inline=False
                    )
                    await self.bot.db.log_action(
                        interaction.guild.id, "AUTO-MUTE", member.id,
                        self.bot.user.id,
                        f"Critical compliance incident #{incident_id}",
                        f"{CRITICAL_AUTO_MUTE_MINUTES}m"
                    )
                except discord.Forbidden:
                    pass

            if staff_ch:
                await staff_ch.send(
                    f"🚨 {mention} **CRITICAL compliance incident** reported! See below.",
                    embed=embed
                )
        else:
            if staff_ch:
                await staff_ch.send(embed=embed)

        # DM the member
        try:
            dm = discord.Embed(
                title=f"{icon} Compliance Notice — {interaction.guild.name}",
                description=(
                    f"A compliance incident has been filed against you.\n\n"
                    f"**Rule:** {rule_name}\n"
                    f"**Severity:** {severity.title()}\n\n"
                    f"**Details:** {description}"
                ),
                colour=colour,
                timestamp=datetime.datetime.utcnow()
            )
            dm.set_footer(text=f"Incident #{incident_id} — Contact a moderator if you have questions.")
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Incident **#{incident_id}** logged against {member.mention}.",
                colour=COL_OK
            ),
            ephemeral=True
        )

    # ── /incidents ────────────────────────────────────────────────────────────

    @app_commands.command(name="incidents", description="View compliance incidents (mod)")
    @app_commands.describe(
        member="Filter by member (optional)",
        status="Filter by status"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="Open",     value="open"),
        app_commands.Choice(name="Resolved", value="resolved"),
        app_commands.Choice(name="All",      value="all"),
    ])
    async def incidents(
        self,
        interaction: discord.Interaction,
        member: discord.Member = None,
        status: str = "open"
    ):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        status_filter = None if status == "all" else status
        rows = await self.bot.db.get_incidents(
            interaction.guild.id,
            user_id=member.id if member else None,
            status=status_filter
        )

        title = f"📋 Incidents"
        if member:
            title += f" — {member.display_name}"
        title += f" ({status.title()})"

        embed = discord.Embed(title=title, colour=COL_INFO, timestamp=datetime.datetime.utcnow())

        if not rows:
            embed.description = "No incidents found."
        else:
            for row in rows[:10]:
                inc_id, uid, rule_name, desc, severity, reported_by, inc_status, created_at = row
                m = interaction.guild.get_member(int(uid))
                name = m.display_name if m else f"ID:{uid}"
                icon = SEVERITY_ICONS.get(severity, "⚪")
                status_icon = "🔓" if inc_status == "open" else "✅"
                embed.add_field(
                    name=f"#{inc_id} {icon} {rule_name} — {name}",
                    value=(
                        f"{status_icon} **{inc_status.title()}** · {severity.title()}\n"
                        f"_{desc[:80]}{'...' if len(desc)>80 else ''}_\n"
                        f"Date: {created_at[:10]}"
                    ),
                    inline=False
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /resolveincident ──────────────────────────────────────────────────────

    @app_commands.command(name="resolveincident", description="Mark a compliance incident as resolved (mod)")
    @app_commands.describe(incident_id="Incident ID to resolve")
    async def resolveincident(self, interaction: discord.Interaction, incident_id: int):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await self.bot.db.resolve_incident(incident_id)

        staff_ch = await self._staff_ch(interaction.guild)
        if staff_ch:
            embed = discord.Embed(
                title="✅ Incident Resolved",
                description=f"Compliance incident **#{incident_id}** has been marked as resolved by {interaction.user.mention}.",
                colour=COL_OK,
                timestamp=datetime.datetime.utcnow()
            )
            await staff_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Incident **#{incident_id}** resolved.",
                colour=COL_OK
            ),
            ephemeral=True
        )

    # ── /compliancereport ─────────────────────────────────────────────────────

    @app_commands.command(name="compliancereport", description="Server-wide compliance dashboard (admin)")
    async def compliancereport(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        summary   = await self.bot.db.get_compliance_summary(interaction.guild.id)
        all_open  = await self.bot.db.get_incidents(interaction.guild.id, status="open")
        all_rows  = await self.bot.db.get_incidents(interaction.guild.id)
        rules     = await self.bot.db.get_rules(interaction.guild.id)

        total_open     = len(all_open)
        total_all      = len(all_rows)
        total_resolved = total_all - total_open

        embed = discord.Embed(
            title=f"🛡️ Compliance Dashboard — {interaction.guild.name}",
            colour=0xE74C3C if total_open > 0 else COL_OK,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        # Summary counts
        embed.add_field(name="📋 Active Rules",    value=str(len(rules)),        inline=True)
        embed.add_field(name="🔓 Open Incidents",  value=str(total_open),        inline=True)
        embed.add_field(name="✅ Resolved",        value=str(total_resolved),    inline=True)

        # Open by severity
        sev_counts = {s: c for s, c in summary}
        for sev in SEVERITY_LEVELS:
            count = sev_counts.get(sev, 0)
            if count > 0:
                icon = SEVERITY_ICONS[sev]
                embed.add_field(name=f"{icon} {sev.title()} open", value=str(count), inline=True)

        # Repeat offenders (users with 2+ open incidents)
        offender_counts: dict[str, int] = {}
        for row in all_open:
            offender_counts[row[1]] = offender_counts.get(row[1], 0) + 1
        repeats = [(uid, cnt) for uid, cnt in offender_counts.items() if cnt >= 2]
        if repeats:
            repeats.sort(key=lambda x: -x[1])
            lines = []
            for uid, cnt in repeats[:5]:
                m = interaction.guild.get_member(int(uid))
                name = m.mention if m else f"ID:{uid}"
                lines.append(f"• {name} — {cnt} open incidents")
            embed.add_field(name="⚠️ Repeat Offenders", value="\n".join(lines), inline=False)

        # Recent critical/high incidents
        urgent = [r for r in all_open if r[4] in ("critical", "high")][:3]
        if urgent:
            lines = []
            for row in urgent:
                inc_id, uid, rule_name, desc, severity, _, _, created_at = row
                m = interaction.guild.get_member(int(uid))
                name = m.display_name if m else f"ID:{uid}"
                icon = SEVERITY_ICONS[severity]
                lines.append(f"{icon} **#{inc_id}** {name} — {rule_name}")
            embed.add_field(name="🚨 Urgent Incidents", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /memberaudit ──────────────────────────────────────────────────────────

    @app_commands.command(name="memberaudit", description="Full compliance audit for a member (mod)")
    @app_commands.describe(member="Member to audit")
    async def memberaudit(self, interaction: discord.Interaction, member: discord.Member):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        incidents  = await self.bot.db.get_incidents(interaction.guild.id, user_id=member.id)
        warnings   = await self.bot.db.get_warnings(interaction.guild.id, member.id)
        mod_logs   = await self.bot.db.get_mod_logs(interaction.guild.id, user_id=member.id)

        open_inc   = [r for r in incidents if r[6] == "open"]
        closed_inc = [r for r in incidents if r[6] == "resolved"]

        # Determine risk level
        critical_count = sum(1 for r in open_inc if r[4] == "critical")
        high_count     = sum(1 for r in open_inc if r[4] == "high")
        active_warns   = sum(1 for r in warnings if r[4] == 1)

        if critical_count > 0 or (high_count >= 2 and active_warns >= 2):
            risk = "🔴 HIGH RISK"
            risk_colour = 0xE74C3C
        elif high_count > 0 or active_warns >= 2:
            risk = "🟠 MEDIUM RISK"
            risk_colour = 0xE67E22
        elif len(open_inc) > 0 or active_warns > 0:
            risk = "🟡 LOW RISK"
            risk_colour = 0xF5A623
        else:
            risk = "🟢 COMPLIANT"
            risk_colour = 0x2ECC71

        embed = discord.Embed(
            title=f"🔍 Member Audit — {member.display_name}",
            colour=risk_colour,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Risk Level",        value=risk, inline=True)
        embed.add_field(name="Open incidents",    value=str(len(open_inc)), inline=True)
        embed.add_field(name="Active warnings",   value=str(active_warns), inline=True)
        embed.add_field(name="Total incidents",   value=str(len(incidents)), inline=True)
        embed.add_field(name="Total warnings",    value=str(len(warnings)), inline=True)
        embed.add_field(name="Mod actions",       value=str(len(mod_logs)), inline=True)

        # Show open incidents
        if open_inc:
            lines = []
            for row in open_inc[:5]:
                inc_id, uid, rule_name, desc, severity, _, _, created_at = row
                icon = SEVERITY_ICONS.get(severity, "⚪")
                lines.append(f"{icon} **#{inc_id}** {rule_name} ({created_at[:10]})")
            embed.add_field(name="🔓 Open Incidents", value="\n".join(lines), inline=False)

        # Show recent mod actions
        if mod_logs:
            icons = {"BAN":"🔨","KICK":"👢","MUTE":"🔇","WARN":"⚠️","AUTO-MUTE":"🤖"}
            lines = []
            for action, uid, mid, reason, duration, created_at in mod_logs[:4]:
                icon = icons.get(action, "🛡️")
                lines.append(f"{icon} **{action}** — {created_at[:10]} — _{reason or 'No reason'}_")
            embed.add_field(name="🛡️ Recent Mod Actions", value="\n".join(lines), inline=False)

        embed.set_footer(text=f"Audited by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Compliance(bot))
