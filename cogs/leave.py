"""
LEAVE MANAGEMENT COG — Module 7
================================
Features:
  • /leaverequest  — submit a leave request (annual, sick, personal, emergency)
  • /myleaves      — view your own leave history
  • /peningleaves  — list all pending requests (mod only)
  • /reviewleave   — approve or deny a leave request (mod only)
  • /leavestats    — server-wide leave statistics (admin)
  • Interactive approve/deny buttons on leave request embeds in #staff-chat
  • DM notifications for submission, approval, and denial
  • Leave balance tracking concept (configurable days per type)
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime

STAFF_CHAT_NAME  = "staff-chat"
LEAVE_LOG_NAME   = "leave-requests"  # channel where requests are posted

# Leave type config: name -> (emoji, max_days_per_year)
LEAVE_TYPES = {
    "annual":    ("🏖️", 21),
    "sick":      ("🤒", 14),
    "personal":  ("🧍", 5),
    "emergency": ("🚨", 3),
    "maternity": ("👶", 90),
    "paternity": ("👨‍👧", 14),
    "unpaid":    ("💸", 30),
}

COL_PENDING  = 0xF5A623
COL_APPROVED = 0x2ECC71
COL_DENIED   = 0xE74C3C
COL_INFO     = 0x3498DB


def _parse_date(s: str):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _working_days(start: datetime.date, end: datetime.date) -> int:
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += datetime.timedelta(days=1)
    return days


# ── Review View (approve / deny buttons) ─────────────────────────────────────

class LeaveReviewView(discord.ui.View):
    def __init__(self, leave_id: int, user_id: int):
        super().__init__(timeout=None)
        self.leave_id = leave_id
        self.user_id  = user_id

    async def _process(self, interaction: discord.Interaction, status: str):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.client.db.review_leave(self.leave_id, status, interaction.user.id)

        colour = COL_APPROVED if status == "approved" else COL_DENIED
        icon   = "✅" if status == "approved" else "❌"
        label  = status.capitalize()

        # Update embed
        embed = interaction.message.embeds[0]
        embed.colour = colour
        embed.set_field_at(
            next(i for i, f in enumerate(embed.fields) if f.name == "Status"),
            name="Status",
            value=f"{icon} **{label}** by {interaction.user.mention}",
            inline=True
        )

        # Disable buttons
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

        # DM the requester
        member = interaction.guild.get_member(self.user_id)
        if member:
            try:
                dm = discord.Embed(
                    title=f"{icon} Leave Request {label}",
                    description=(
                        f"Your leave request (ID #{self.leave_id}) has been **{status}** "
                        f"by {interaction.user.display_name}."
                    ),
                    colour=colour,
                    timestamp=datetime.datetime.utcnow()
                )
                await member.send(embed=dm)
            except discord.Forbidden:
                pass

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="leave_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process(interaction, "approved")

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="leave_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._process(interaction, "denied")


# ── Leave Cog ─────────────────────────────────────────────────────────────────

class Leave(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_leave_channel(self, guild):
        ch = discord.utils.get(guild.text_channels, name=LEAVE_LOG_NAME)
        if not ch:
            ch = discord.utils.get(guild.text_channels, name=STAFF_CHAT_NAME)
        return ch

    # ── /leaverequest ─────────────────────────────────────────────────────────

    @app_commands.command(name="leaverequest", description="Submit a leave request")
    @app_commands.describe(
        leave_type="Type of leave",
        start_date="Start date (YYYY-MM-DD)",
        end_date="End date (YYYY-MM-DD)",
        reason="Reason for leave"
    )
    @app_commands.choices(leave_type=[
        app_commands.Choice(name=f"{v[0]} {k.capitalize()}", value=k)
        for k, v in LEAVE_TYPES.items()
    ])
    async def leaverequest(
        self,
        interaction: discord.Interaction,
        leave_type: str,
        start_date: str,
        end_date: str,
        reason: str = "No reason provided"
    ):
        start = _parse_date(start_date)
        end   = _parse_date(end_date)

        if not start or not end:
            return await interaction.response.send_message(
                "❌ Invalid date format. Use `YYYY-MM-DD` (e.g. `2025-08-01`).", ephemeral=True
            )
        if end < start:
            return await interaction.response.send_message("❌ End date must be after start date.", ephemeral=True)
        if start < datetime.date.today():
            return await interaction.response.send_message("❌ Start date cannot be in the past.", ephemeral=True)

        working_days = _working_days(start, end)
        emoji, max_days = LEAVE_TYPES.get(leave_type, ("📅", 30))

        leave_id = await self.bot.db.submit_leave(
            interaction.guild.id, interaction.user.id,
            leave_type, str(start), str(end), reason
        )

        # Build embed
        embed = discord.Embed(
            title=f"{emoji} Leave Request #{leave_id}",
            colour=COL_PENDING,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Applicant",     value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Leave type",    value=f"{emoji} {leave_type.capitalize()}", inline=True)
        embed.add_field(name="Working days",  value=str(working_days), inline=True)
        embed.add_field(name="Status",        value="⏳ **Pending**", inline=True)
        embed.add_field(name="Period",        value=f"`{start}` → `{end}`", inline=False)
        embed.add_field(name="Reason",        value=reason, inline=False)
        embed.set_footer(text=f"ID #{leave_id} • Max {max_days} days/year for this type")

        view = LeaveReviewView(leave_id, interaction.user.id)
        leave_ch = await self._get_leave_channel(interaction.guild)
        if leave_ch:
            await leave_ch.send(embed=embed, view=view)

        # DM confirmation
        try:
            dm = discord.Embed(
                title=f"📋 Leave Request Submitted — #{leave_id}",
                description=f"Your **{leave_type}** leave request for `{start}` → `{end}` ({working_days} working days) has been submitted for review.",
                colour=COL_PENDING,
                timestamp=datetime.datetime.utcnow()
            )
            await interaction.user.send(embed=dm)
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Leave request **#{leave_id}** submitted! You'll be notified when it's reviewed.",
                colour=COL_APPROVED
            ),
            ephemeral=True
        )

    # ── /myleaves ─────────────────────────────────────────────────────────────

    @app_commands.command(name="myleaves", description="View your leave request history")
    async def myleaves(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_leave_requests(interaction.guild.id, user_id=interaction.user.id)

        embed = discord.Embed(
            title="📋 My Leave Requests",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        if not rows:
            embed.description = "You have no leave requests on record."
        else:
            status_icons = {"pending": "⏳", "approved": "✅", "denied": "❌"}
            for row in rows[:8]:
                lid, uid, ltype, start, end, reason, status, reviewed_by, created_at = row
                emoji = LEAVE_TYPES.get(ltype, ("📅",))[0]
                icon  = status_icons.get(status, "❓")
                wd    = _working_days(
                    datetime.date.fromisoformat(start),
                    datetime.date.fromisoformat(end)
                )
                embed.add_field(
                    name=f"{icon} #{lid} — {emoji} {ltype.capitalize()} ({wd}d)",
                    value=f"`{start}` → `{end}`\n_{reason[:60]}_",
                    inline=False
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /pendingleaves ────────────────────────────────────────────────────────

    @app_commands.command(name="pendingleaves", description="View all pending leave requests (mod only)")
    async def pendingleaves(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        rows = await self.bot.db.get_leave_requests(interaction.guild.id, status="pending")

        embed = discord.Embed(
            title="⏳ Pending Leave Requests",
            colour=COL_PENDING,
            timestamp=datetime.datetime.utcnow()
        )
        if not rows:
            embed.description = "No pending leave requests. ✅"
        else:
            for row in rows[:10]:
                lid, uid, ltype, start, end, reason, status, _, created_at = row
                m = interaction.guild.get_member(int(uid))
                name = m.display_name if m else f"ID:{uid}"
                emoji = LEAVE_TYPES.get(ltype, ("📅",))[0]
                wd = _working_days(datetime.date.fromisoformat(start), datetime.date.fromisoformat(end))
                embed.add_field(
                    name=f"#{lid} — {name}",
                    value=f"{emoji} {ltype.capitalize()} · {wd}d · `{start}` → `{end}`\nUse `/reviewleave {lid} approve/deny`",
                    inline=False
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /reviewleave ──────────────────────────────────────────────────────────

    @app_commands.command(name="reviewleave", description="Approve or deny a leave request (mod only)")
    @app_commands.describe(leave_id="Leave request ID", decision="approve or deny")
    @app_commands.choices(decision=[
        app_commands.Choice(name="✅ Approve", value="approved"),
        app_commands.Choice(name="❌ Deny",    value="denied"),
    ])
    async def reviewleave(self, interaction: discord.Interaction, leave_id: int, decision: str):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        row = await self.bot.db.get_leave_by_id(leave_id)
        if not row:
            return await interaction.response.send_message(f"❌ Leave request #{leave_id} not found.", ephemeral=True)

        lid, guild_id, user_id, ltype, start, end, reason, status = row
        if status != "pending":
            return await interaction.response.send_message(f"❌ Request #{leave_id} is already `{status}`.", ephemeral=True)

        await self.bot.db.review_leave(leave_id, decision, interaction.user.id)

        icon = "✅" if decision == "approved" else "❌"
        colour = COL_APPROVED if decision == "approved" else COL_DENIED

        member = interaction.guild.get_member(int(user_id))
        if member:
            try:
                dm = discord.Embed(
                    title=f"{icon} Leave Request {decision.capitalize()} — #{leave_id}",
                    description=f"Your **{ltype}** leave (`{start}` → `{end}`) has been **{decision}** by {interaction.user.display_name}.",
                    colour=colour,
                    timestamp=datetime.datetime.utcnow()
                )
                await member.send(embed=dm)
            except discord.Forbidden:
                pass

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{icon} Leave request **#{leave_id}** has been **{decision}**.",
                colour=colour
            ),
            ephemeral=True
        )

    # ── /leavestats ───────────────────────────────────────────────────────────

    @app_commands.command(name="leavestats", description="Server-wide leave statistics (admin)")
    async def leavestats(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        all_rows = await self.bot.db.get_leave_requests(interaction.guild.id)

        embed = discord.Embed(
            title=f"📊 Leave Statistics — {interaction.guild.name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )

        total = len(all_rows)
        pending  = sum(1 for r in all_rows if r[6] == "pending")
        approved = sum(1 for r in all_rows if r[6] == "approved")
        denied   = sum(1 for r in all_rows if r[6] == "denied")

        type_counts: dict[str, int] = {}
        for r in all_rows:
            type_counts[r[2]] = type_counts.get(r[2], 0) + 1

        embed.add_field(name="Total requests", value=str(total),    inline=True)
        embed.add_field(name="⏳ Pending",      value=str(pending),  inline=True)
        embed.add_field(name="✅ Approved",     value=str(approved), inline=True)
        embed.add_field(name="❌ Denied",       value=str(denied),   inline=True)

        if type_counts:
            breakdown = "\n".join(
                f"{LEAVE_TYPES.get(k, ('📅',))[0]} **{k.capitalize()}**: {v}"
                for k, v in sorted(type_counts.items(), key=lambda x: -x[1])
            )
            embed.add_field(name="By type", value=breakdown, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Leave(bot))
