"""
ATTENDANCE COG — Module 6
==========================
Features:
  • /clockin      — start a work/attendance session (optional note)
  • /clockout     — end your active session, logs duration
  • /session      — check your current active session duration
  • /attendance   — view your personal session history (last 10)
  • /report       — attendance report for whole server (last 7 or 30 days)
  • /staffreport  — full breakdown per user, exportable as text (mod only)

All sessions saved to SQLite.
Clock-in/out events posted to #attendance-log channel.
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime

ATTENDANCE_LOG_CHANNEL = "attendance-log"
STAFF_CHAT_NAME        = "staff-chat"

COL_IN   = 0x2ECC71   # green
COL_OUT  = 0x3498DB   # blue
COL_ERR  = 0xE74C3C
COL_INFO = 0x9B59B6


def _fmt_duration(seconds: int) -> str:
    """Convert seconds to a human-readable duration string."""
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m {s}s"


def _elapsed_since(iso_str: str) -> int:
    """Return seconds elapsed since an ISO timestamp."""
    dt = datetime.datetime.fromisoformat(iso_str)
    return int((datetime.datetime.utcnow() - dt).total_seconds())


class Attendance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _attendance_ch(self, guild):
        return discord.utils.get(guild.text_channels, name=ATTENDANCE_LOG_CHANNEL)

    # ── /clockin ──────────────────────────────────────────────────────────────

    @app_commands.command(name="clockin", description="Start your attendance session")
    @app_commands.describe(note="Optional note for this session (e.g. task you're working on)")
    async def clockin(self, interaction: discord.Interaction, note: str = None):
        result = await self.bot.db.clock_in(interaction.guild.id, interaction.user.id, note)

        if result is None:
            # Already clocked in — show current session
            session = await self.bot.db.get_active_session(interaction.guild.id, interaction.user.id)
            elapsed = _elapsed_since(session[0]) if session else 0
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description=(
                        f"⚠️ You're already clocked in!\n"
                        f"**Session started:** {discord.utils.format_dt(datetime.datetime.fromisoformat(session[0]), style='R')}\n"
                        f"**Elapsed:** {_fmt_duration(elapsed)}\n\n"
                        f"Use `/clockout` to end your session."
                    ),
                    colour=COL_ERR
                ),
                ephemeral=True
            )

        embed = discord.Embed(
            title="🟢 Clocked In",
            colour=COL_IN,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Member",  value=interaction.user.mention, inline=True)
        embed.add_field(name="Time",    value=discord.utils.format_dt(datetime.datetime.utcnow(), style="t"), inline=True)
        if note:
            embed.add_field(name="Note", value=note, inline=False)
        embed.set_footer(text="Use /clockout to end your session.")

        # Log to attendance channel
        log_ch = await self._attendance_ch(interaction.guild)
        if log_ch:
            await log_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ You're clocked in! Use `/clockout` to end your session.",
                colour=COL_IN
            ),
            ephemeral=True
        )

    # ── /clockout ─────────────────────────────────────────────────────────────

    @app_commands.command(name="clockout", description="End your attendance session")
    async def clockout(self, interaction: discord.Interaction):
        clock_in_str, duration_s = await self.bot.db.clock_out(
            interaction.guild.id, interaction.user.id
        )

        if clock_in_str is None:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description="❌ You're not clocked in. Use `/clockin` to start a session.",
                    colour=COL_ERR
                ),
                ephemeral=True
            )

        clock_in_dt = datetime.datetime.fromisoformat(clock_in_str)

        embed = discord.Embed(
            title="🔴 Clocked Out",
            colour=COL_OUT,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Member",     value=interaction.user.mention, inline=True)
        embed.add_field(name="Duration",   value=_fmt_duration(duration_s), inline=True)
        embed.add_field(
            name="Session",
            value=(
                f"**In:** {discord.utils.format_dt(clock_in_dt, style='t')}\n"
                f"**Out:** {discord.utils.format_dt(datetime.datetime.utcnow(), style='t')}"
            ),
            inline=False
        )

        log_ch = await self._attendance_ch(interaction.guild)
        if log_ch:
            await log_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ Clocked out. Session duration: **{_fmt_duration(duration_s)}**"
                ),
                colour=COL_OUT
            ),
            ephemeral=True
        )

    # ── /session ──────────────────────────────────────────────────────────────

    @app_commands.command(name="session", description="Check your current active session")
    async def session(self, interaction: discord.Interaction):
        data = await self.bot.db.get_active_session(interaction.guild.id, interaction.user.id)

        if not data:
            return await interaction.response.send_message(
                embed=discord.Embed(
                    description="You're not currently clocked in.",
                    colour=COL_ERR
                ),
                ephemeral=True
            )

        clock_in_str, note = data
        elapsed = _elapsed_since(clock_in_str)
        clock_in_dt = datetime.datetime.fromisoformat(clock_in_str)

        embed = discord.Embed(
            title="⏱️ Active Session",
            colour=COL_IN,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Clocked in", value=discord.utils.format_dt(clock_in_dt, style="R"), inline=True)
        embed.add_field(name="Elapsed",    value=_fmt_duration(elapsed), inline=True)
        if note:
            embed.add_field(name="Note", value=note, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /attendance ───────────────────────────────────────────────────────────

    @app_commands.command(name="attendance", description="View your session history")
    @app_commands.describe(member="Member to view (mod only for others)")
    async def attendance(self, interaction: discord.Interaction, member: discord.Member = None):
        if member and member != interaction.user:
            if not interaction.user.guild_permissions.manage_messages:
                return await interaction.response.send_message("❌ You can only view your own attendance.", ephemeral=True)
        target = member or interaction.user

        rows = await self.bot.db.get_attendance(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"📋 Attendance — {target.display_name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if not rows:
            embed.description = "No attendance records found."
        else:
            total_s = sum(r[2] for r in rows if r[2])
            completed = [r for r in rows if r[1]]  # has clock_out
            embed.description = f"**Total time (last {len(completed)} sessions):** {_fmt_duration(total_s)}"
            for clock_in, clock_out, duration_s, note in rows[:8]:
                ci_dt = datetime.datetime.fromisoformat(clock_in)
                if clock_out:
                    val = f"🟢 {ci_dt.strftime('%b %d')} · {_fmt_duration(duration_s or 0)}"
                else:
                    val = f"⏱️ {ci_dt.strftime('%b %d')} · **Active** ({_fmt_duration(_elapsed_since(clock_in))})"
                if note:
                    val += f"\n_{note}_"
                embed.add_field(name="\u200b", value=val, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /report ───────────────────────────────────────────────────────────────

    @app_commands.command(name="report", description="Attendance report for the server")
    @app_commands.describe(days="How many days back to report (7 or 30)")
    async def report(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 30] = 7
    ):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.get_attendance_report(interaction.guild.id, days)

        embed = discord.Embed(
            title=f"📊 Attendance Report — Last {days} days",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        if not rows:
            embed.description = "No completed sessions in this period."
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, (user_id, total_s, session_count) in enumerate(rows[:15]):
                m = interaction.guild.get_member(int(user_id))
                name = m.display_name if m else f"ID:{user_id}"
                prefix = medals[i] if i < 3 else f"`{i+1}.`"
                lines.append(
                    f"{prefix} **{name}** — {_fmt_duration(total_s or 0)} over {session_count} session(s)"
                )
            embed.description = "\n".join(lines)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /staffreport ──────────────────────────────────────────────────────────

    @app_commands.command(name="staffreport", description="Export a full attendance breakdown (admin)")
    @app_commands.describe(days="Number of days to cover")
    async def staffreport(
        self,
        interaction: discord.Interaction,
        days: app_commands.Range[int, 1, 90] = 30
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.get_attendance_report(interaction.guild.id, days)

        if not rows:
            return await interaction.followup.send("No data found.", ephemeral=True)

        lines = [
            f"ATTENDANCE REPORT — {interaction.guild.name}",
            f"Period: Last {days} days  |  Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"{'─'*55}",
            f"{'#':<4} {'Name':<25} {'Sessions':<10} {'Total Time':<15}",
            f"{'─'*55}",
        ]
        for i, (user_id, total_s, sessions) in enumerate(rows, 1):
            m = interaction.guild.get_member(int(user_id))
            name = (m.display_name if m else f"ID:{user_id}")[:24]
            lines.append(f"{i:<4} {name:<25} {sessions:<10} {_fmt_duration(total_s or 0):<15}")

        report_text = "\n".join(lines)
        file = discord.File(
            fp=__import__("io").BytesIO(report_text.encode()),
            filename=f"attendance_{days}d_{datetime.datetime.utcnow().strftime('%Y%m%d')}.txt"
        )
        await interaction.followup.send(
            content=f"📄 Attendance report for the last {days} days:",
            file=file,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Attendance(bot))
