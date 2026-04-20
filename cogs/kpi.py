"""
KPI & PERFORMANCE COG — Module 8
==================================
Features:
  • /logkpi        — log a KPI metric for a user (mod/admin)
  • /kpi           — view KPI entries for yourself or another member
  • /kpireport     — aggregated KPI summary by period (mod)
  • /rate          — submit a performance rating for a member (1–5 stars)
  • /myratings     — view your performance ratings
  • /perfoverview  — full performance overview card for a member (mod)
  • /teamstats     — team-wide performance summary (admin)

KPI Metrics (customisable):
  sales, tasks_completed, tickets_resolved, response_time,
  attendance_rate, quality_score, customer_satisfaction, revenue

Rating Categories:
  teamwork, communication, quality, punctuality, initiative
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime

STAFF_CHAT_NAME = "staff-chat"

# Available KPI metrics
METRICS = [
    "sales", "tasks_completed", "tickets_resolved", "response_time_min",
    "attendance_rate", "quality_score", "customer_satisfaction", "revenue",
    "calls_made", "deals_closed", "errors_reported", "projects_delivered"
]

# Performance rating categories
RATING_CATEGORIES = ["teamwork", "communication", "quality", "punctuality", "initiative"]

STAR_MAP = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}

COL_KPI  = 0x1ABC9C
COL_RATE = 0x9B59B6
COL_OK   = 0x2ECC71
COL_INFO = 0x3498DB
COL_WARN = 0xF5A623


def _current_period() -> str:
    now = datetime.datetime.utcnow()
    return f"{now.year}-{now.month:02d}"


def _rating_colour(avg: float) -> int:
    if avg >= 4.5: return 0x2ECC71
    if avg >= 3.5: return 0x3498DB
    if avg >= 2.5: return 0xF5A623
    return 0xE74C3C


def _progress_bar(value: float, target: float, length: int = 10) -> str:
    if not target or target == 0:
        return f"`{'─' * length}` N/A"
    ratio  = min(1.0, value / target)
    filled = int(ratio * length)
    bar    = "█" * filled + "░" * (length - filled)
    pct    = int(ratio * 100)
    return f"`{bar}` {pct}%"


class KPI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _is_mod(self, member):
        return member.guild_permissions.manage_messages or member.guild_permissions.administrator

    # ── /logkpi ───────────────────────────────────────────────────────────────

    @app_commands.command(name="logkpi", description="Log a KPI metric for a member (mod/admin)")
    @app_commands.describe(
        member="Target member",
        metric="KPI metric name",
        value="Metric value",
        target="Target/goal value (optional)",
        period="Period (default: current month YYYY-MM)",
        note="Optional note"
    )
    @app_commands.choices(metric=[app_commands.Choice(name=m.replace("_", " ").title(), value=m) for m in METRICS])
    async def logkpi(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        metric: str,
        value: float,
        target: float = None,
        period: str = None,
        note: str = None
    ):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        period = period or _current_period()

        await self.bot.db.log_kpi(
            interaction.guild.id, member.id, metric,
            value, target, period, interaction.user.id, note
        )

        embed = discord.Embed(
            title="📊 KPI Logged",
            colour=COL_KPI,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member",  value=member.mention, inline=True)
        embed.add_field(name="Metric",  value=metric.replace("_", " ").title(), inline=True)
        embed.add_field(name="Period",  value=period, inline=True)
        embed.add_field(name="Value",   value=str(value), inline=True)
        if target:
            embed.add_field(name="Target",   value=str(target), inline=True)
            embed.add_field(name="Progress", value=_progress_bar(value, target), inline=True)
        if note:
            embed.add_field(name="Note", value=note, inline=False)
        embed.set_footer(text=f"Logged by {interaction.user.display_name}")

        # Post to staff-chat
        staff_ch = discord.utils.get(interaction.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            await staff_ch.send(embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ KPI logged for {member.mention}.", colour=COL_OK),
            ephemeral=True
        )

    # ── /kpi ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="kpi", description="View KPI entries for a member")
    @app_commands.describe(member="Member to check (default: yourself)", period="Period filter (YYYY-MM)")
    async def kpi(
        self,
        interaction: discord.Interaction,
        member: discord.Member = None,
        period: str = None
    ):
        target = member or interaction.user
        if target != interaction.user and not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only for other members.", ephemeral=True)

        period_filter = period or _current_period()
        rows = await self.bot.db.get_kpi(interaction.guild.id, target.id, period=period_filter)

        embed = discord.Embed(
            title=f"📊 KPI — {target.display_name} ({period_filter})",
            colour=COL_KPI,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if not rows:
            embed.description = f"No KPI data for period `{period_filter}`."
        else:
            for user_id, metric, value, target_val, p, note, created_at in rows[:10]:
                bar = _progress_bar(value, target_val) if target_val else ""
                val_text = f"**{value}**"
                if target_val:
                    val_text += f" / {target_val} {bar}"
                if note:
                    val_text += f"\n_{note}_"
                embed.add_field(
                    name=f"📈 {metric.replace('_', ' ').title()}",
                    value=val_text,
                    inline=True
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /kpireport ────────────────────────────────────────────────────────────

    @app_commands.command(name="kpireport", description="Aggregated KPI summary by period (mod)")
    @app_commands.describe(period="Period to report on (YYYY-MM, default: current month)")
    async def kpireport(self, interaction: discord.Interaction, period: str = None):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        period = period or _current_period()
        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.get_kpi_summary(interaction.guild.id, period)

        embed = discord.Embed(
            title=f"📊 KPI Report — {period}",
            colour=COL_KPI,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        if not rows:
            embed.description = f"No KPI data logged for period `{period}`."
        else:
            # Group by user
            by_user: dict[str, list] = {}
            for user_id, metric, avg, high, low, target_val in rows:
                by_user.setdefault(user_id, []).append((metric, avg, high, low, target_val))

            for user_id, entries in list(by_user.items())[:8]:
                m = interaction.guild.get_member(int(user_id))
                name = m.display_name if m else f"ID:{user_id}"
                lines = []
                for metric, avg, high, low, target_val in entries:
                    bar = _progress_bar(avg, target_val) if target_val else ""
                    lines.append(f"• **{metric.replace('_', ' ').title()}**: avg {avg:.1f} {bar}")
                embed.add_field(name=f"👤 {name}", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /rate ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="rate", description="Submit a performance rating for a member")
    @app_commands.describe(
        member="Member to rate",
        rating="Rating 1–5",
        category="Rating category",
        comment="Optional comment",
        period="Period (default: current month)"
    )
    @app_commands.choices(
        rating=[app_commands.Choice(name=f"{i} star{'s' if i>1 else ''}", value=i) for i in range(1, 6)],
        category=[app_commands.Choice(name=c.title(), value=c) for c in RATING_CATEGORIES]
    )
    async def rate(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rating: int,
        category: str,
        comment: str = None,
        period: str = None
    ):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)
        if member == interaction.user:
            return await interaction.response.send_message("❌ You cannot rate yourself.", ephemeral=True)

        period = period or _current_period()
        await self.bot.db.add_rating(
            interaction.guild.id, member.id, interaction.user.id,
            rating, category, comment, period
        )

        embed = discord.Embed(
            title="⭐ Performance Rating Submitted",
            colour=COL_RATE,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Member",   value=member.mention, inline=True)
        embed.add_field(name="Category", value=category.title(), inline=True)
        embed.add_field(name="Rating",   value=STAR_MAP[rating], inline=True)
        embed.add_field(name="Period",   value=period, inline=True)
        if comment:
            embed.add_field(name="Comment", value=comment, inline=False)
        embed.set_footer(text=f"Rated by {interaction.user.display_name}")

        staff_ch = discord.utils.get(interaction.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            await staff_ch.send(embed=embed)

        # DM the rated member
        try:
            dm = discord.Embed(
                title="⭐ You received a performance rating",
                colour=COL_RATE,
                timestamp=datetime.datetime.utcnow()
            )
            dm.add_field(name="Category", value=category.title(), inline=True)
            dm.add_field(name="Rating",   value=STAR_MAP[rating], inline=True)
            if comment:
                dm.add_field(name="Feedback", value=comment, inline=False)
            await member.send(embed=dm)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Rating submitted for {member.mention}.",
                colour=COL_OK
            ),
            ephemeral=True
        )

    # ── /myratings ────────────────────────────────────────────────────────────

    @app_commands.command(name="myratings", description="View your performance ratings")
    @app_commands.describe(period="Period filter (YYYY-MM)")
    async def myratings(self, interaction: discord.Interaction, period: str = None):
        avgs = await self.bot.db.get_rating_avg(interaction.guild.id, interaction.user.id, period)
        rows = await self.bot.db.get_ratings(interaction.guild.id, interaction.user.id, period)

        embed = discord.Embed(
            title=f"⭐ My Performance Ratings{f' — {period}' if period else ''}",
            colour=COL_RATE,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        if not avgs:
            embed.description = "No ratings on record yet."
        else:
            overall = sum(a[0] for a in avgs) / len(avgs)
            embed.description = f"**Overall average:** {STAR_MAP.get(round(overall), '⭐')} `{overall:.2f}/5`"
            for avg, count, category in avgs:
                bar = "█" * round(avg) + "░" * (5 - round(avg))
                embed.add_field(
                    name=category.title(),
                    value=f"`{bar}` {avg:.2f}/5 ({count} ratings)",
                    inline=True
                )

            # Recent comments
            comments = [(r[3], r[2], r[0]) for r in rows if r[3]][:3]
            if comments:
                feedback_text = "\n".join(
                    f"**{cat.title()}:** _{comment}_ — {STAR_MAP.get(rating, '')}"
                    for comment, cat, rated_by in comments
                )
                embed.add_field(name="Recent feedback", value=feedback_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /perfoverview ─────────────────────────────────────────────────────────

    @app_commands.command(name="perfoverview", description="Full performance overview for a member (mod)")
    @app_commands.describe(member="Member to review", period="Period (YYYY-MM)")
    async def perfoverview(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        period: str = None
    ):
        if not self._is_mod(interaction.user):
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        period = period or _current_period()
        await interaction.response.defer(ephemeral=True)

        avgs    = await self.bot.db.get_rating_avg(interaction.guild.id, member.id, period)
        kpi_rows = await self.bot.db.get_kpi(interaction.guild.id, member.id, period=period)
        att_rows = await self.bot.db.get_attendance(interaction.guild.id, member.id, limit=20)
        att_total = sum(r[2] for r in att_rows if r[2])

        overall_rating = (sum(a[0] for a in avgs) / len(avgs)) if avgs else None

        embed = discord.Embed(
            title=f"📋 Performance Overview — {member.display_name}",
            description=f"Period: `{period}`",
            colour=_rating_colour(overall_rating) if overall_rating else COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Ratings section
        if avgs:
            overall = sum(a[0] for a in avgs) / len(avgs)
            embed.add_field(
                name="⭐ Overall Rating",
                value=f"{STAR_MAP.get(round(overall), '⭐')} `{overall:.2f}/5`",
                inline=True
            )
            cat_lines = [f"• **{cat.title()}**: {avg:.1f}/5" for avg, _, cat in avgs]
            embed.add_field(name="By category", value="\n".join(cat_lines), inline=True)
        else:
            embed.add_field(name="⭐ Ratings", value="No ratings this period.", inline=True)

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        # KPI section
        if kpi_rows:
            kpi_lines = []
            for _, metric, value, target_val, p, note, _ in kpi_rows[:5]:
                bar = _progress_bar(value, target_val) if target_val else ""
                kpi_lines.append(f"• **{metric.replace('_',' ').title()}**: {value} {bar}")
            embed.add_field(name="📈 KPI Metrics", value="\n".join(kpi_lines), inline=False)
        else:
            embed.add_field(name="📈 KPI Metrics", value="No KPI data this period.", inline=False)

        # Attendance section
        hrs = att_total // 3600
        mins = (att_total % 3600) // 60
        embed.add_field(name="⏱️ Total Hours (recent)", value=f"{hrs}h {mins}m", inline=True)

        # Level / XP
        level_data = await self.bot.db.get_level_data(interaction.guild.id, member.id)
        if level_data:
            xp, level, msgs = level_data
            embed.add_field(name="💬 Activity", value=f"Level {level} · {xp} XP · {msgs} messages", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /teamstats ────────────────────────────────────────────────────────────

    @app_commands.command(name="teamstats", description="Team-wide performance summary (admin)")
    @app_commands.describe(period="Period (YYYY-MM, default: current month)")
    async def teamstats(self, interaction: discord.Interaction, period: str = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        period = period or _current_period()
        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.get_kpi_summary(interaction.guild.id, period)

        embed = discord.Embed(
            title=f"👥 Team Stats — {period}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )

        if not rows:
            embed.description = "No data for this period."
        else:
            by_metric: dict[str, list] = {}
            for user_id, metric, avg, high, low, target in rows:
                by_metric.setdefault(metric, []).append((user_id, avg, high))

            for metric, entries in list(by_metric.items())[:6]:
                top = sorted(entries, key=lambda x: -x[1])[:3]
                lines = []
                for uid, avg, high in top:
                    m = interaction.guild.get_member(int(uid))
                    name = m.display_name if m else f"ID:{uid}"
                    lines.append(f"• **{name}**: avg {avg:.1f} (best {high:.0f})")
                embed.add_field(
                    name=f"📈 {metric.replace('_', ' ').title()}",
                    value="\n".join(lines),
                    inline=True
                )

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(KPI(bot))
