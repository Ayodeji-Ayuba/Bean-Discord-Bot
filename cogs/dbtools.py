"""
DATABASE TOOLS COG — Module 12
================================
Features:
  • /serverstats    — full server analytics dashboard (members, activity, mod stats)
  • /exportdata     — export any bot data table as a .csv file (admin)
  • /purge          — bulk-delete messages in a channel with filters (mod)
  • /snapshot       — save a snapshot of current server stats to a log channel
  • /usersummary    — complete profile of a member across all bot systems
  • /botinfo        — bot health, uptime, cog status, command count
  • /dbstats        — database row counts per table (admin)
  • /cleardata      — wipe all bot data for a specific user (admin + GDPR)
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import io
import csv
import aiosqlite
import time

STAFF_CHAT_NAME = "staff-chat"
DB_PATH         = "data/bot.db"

COL_OK   = 0x2ECC71
COL_ERR  = 0xE74C3C
COL_INFO = 0x3498DB
COL_WARN = 0xF5A623


def _fmt_duration(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)


class DBTools(commands.Cog):
    def __init__(self, bot):
        self.bot      = bot
        self._start   = time.time()

    # ── /serverstats ──────────────────────────────────────────────────────────

    @app_commands.command(name="serverstats", description="Full server analytics dashboard")
    async def serverstats(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Member stats
        total        = guild.member_count
        bots         = sum(1 for m in guild.members if m.bot)
        humans       = total - bots
        online       = sum(1 for m in guild.members if m.status != discord.Status.offline and not m.bot)
        boosters     = guild.premium_subscription_count
        boost_level  = guild.premium_tier

        # Channel counts
        text_chs  = len(guild.text_channels)
        voice_chs = len(guild.voice_channels)
        categories = len(guild.categories)
        roles      = len(guild.roles) - 1  # exclude @everyone

        # Bot data counts from DB
        async with aiosqlite.connect(DB_PATH) as db:
            async def count(table, gid_col="guild_id"):
                try:
                    cur = await db.execute(f"SELECT COUNT(*) FROM {table} WHERE {gid_col}=?", (str(guild.id),))
                    return (await cur.fetchone())[0]
                except Exception:
                    return 0

            warns     = await count("warnings")
            mod_logs  = await count("mod_logs")
            incidents = await count("compliance_incidents")
            leaves    = await count("leave_requests")
            kpi_rows  = await count("kpi_entries")
            att_rows  = await count("attendance")

        embed = discord.Embed(
            title=f"📊 Server Stats — {guild.name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="👥 Members",      value=f"**{humans}** humans\n{bots} bots\n{online} online", inline=True)
        embed.add_field(name="📁 Channels",     value=f"{text_chs} text\n{voice_chs} voice\n{categories} categories", inline=True)
        embed.add_field(name="🎭 Roles",        value=str(roles), inline=True)
        embed.add_field(name="💎 Boost",        value=f"Level {boost_level} · {boosters} boosts", inline=True)
        embed.add_field(name="📅 Created",      value=discord.utils.format_dt(guild.created_at, style="D"), inline=True)
        embed.add_field(name="🆔 Server ID",    value=str(guild.id), inline=True)
        embed.add_field(name="⚠️ Warnings",     value=str(warns),     inline=True)
        embed.add_field(name="🛡️ Mod Actions",  value=str(mod_logs),  inline=True)
        embed.add_field(name="📋 Incidents",    value=str(incidents), inline=True)
        embed.add_field(name="🏖️ Leave Reqs",  value=str(leaves),    inline=True)
        embed.add_field(name="📈 KPI Entries",  value=str(kpi_rows),  inline=True)
        embed.add_field(name="⏱️ Att. Records", value=str(att_rows),  inline=True)

        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /exportdata ───────────────────────────────────────────────────────────

    @app_commands.command(name="exportdata", description="Export bot data as a CSV file (admin)")
    @app_commands.describe(table="Which data to export")
    @app_commands.choices(table=[
        app_commands.Choice(name="Warnings",             value="warnings"),
        app_commands.Choice(name="Mod Logs",             value="mod_logs"),
        app_commands.Choice(name="Attendance Records",   value="attendance"),
        app_commands.Choice(name="Leave Requests",       value="leave_requests"),
        app_commands.Choice(name="KPI Entries",          value="kpi_entries"),
        app_commands.Choice(name="Performance Ratings",  value="performance_ratings"),
        app_commands.Choice(name="Compliance Incidents", value="compliance_incidents"),
        app_commands.Choice(name="Levels / XP",          value="levels"),
    ])
    async def exportdata(self, interaction: discord.Interaction, table: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    f"SELECT * FROM {table} WHERE guild_id=?",
                    (str(interaction.guild.id),)
                )
                rows = await cursor.fetchall()
                if not rows:
                    return await interaction.followup.send(f"No data found in `{table}`.", ephemeral=True)

                keys = rows[0].keys()
                buf  = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(keys)
                for row in rows:
                    writer.writerow(list(row))

                buf.seek(0)
                filename = f"{table}_{interaction.guild.id}_{datetime.datetime.utcnow().strftime('%Y%m%d')}.csv"
                file = discord.File(fp=io.BytesIO(buf.getvalue().encode()), filename=filename)

                await interaction.followup.send(
                    content=f"📄 **{table}** export — {len(rows)} rows",
                    file=file,
                    ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(f"❌ Export failed: {e}", ephemeral=True)

    # ── /purge ────────────────────────────────────────────────────────────────

    @app_commands.command(name="purge", description="Bulk-delete messages in this channel (mod)")
    @app_commands.describe(
        amount="Number of messages to delete (max 100)",
        member="Only delete messages from this member (optional)",
        contains="Only delete messages containing this text (optional)"
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        member: discord.Member = None,
        contains: str = None
    ):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        def check(msg: discord.Message) -> bool:
            if member and msg.author != member:
                return False
            if contains and contains.lower() not in msg.content.lower():
                return False
            return True

        try:
            deleted = await interaction.channel.purge(limit=amount, check=check)
        except discord.Forbidden:
            return await interaction.followup.send("❌ Missing permissions to delete messages.", ephemeral=True)

        # Log to staff-chat
        staff_ch = discord.utils.get(interaction.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            embed = discord.Embed(
                title="🗑️ Messages Purged",
                colour=COL_WARN,
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="Channel",  value=interaction.channel.mention, inline=True)
            embed.add_field(name="Deleted",  value=str(len(deleted)), inline=True)
            embed.add_field(name="By",       value=interaction.user.mention, inline=True)
            if member:
                embed.add_field(name="Filter: member", value=member.mention, inline=True)
            if contains:
                embed.add_field(name="Filter: contains", value=f"`{contains}`", inline=True)
            await staff_ch.send(embed=embed)

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"🗑️ Deleted **{len(deleted)}** message(s) from {interaction.channel.mention}.",
                colour=COL_OK
            ),
            ephemeral=True
        )

    # ── /usersummary ──────────────────────────────────────────────────────────

    @app_commands.command(name="usersummary", description="Complete profile of a member across all bot systems (mod)")
    @app_commands.describe(member="Member to view")
    async def usersummary(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        uid = member.id

        # Gather all data concurrently
        warnings_task   = self.bot.db.get_warnings(gid, uid)
        modlogs_task    = self.bot.db.get_mod_logs(gid, uid)
        levels_task     = self.bot.db.get_level_data(gid, uid)
        attendance_task = self.bot.db.get_attendance(gid, uid)
        leaves_task     = self.bot.db.get_leave_requests(gid, uid)
        ratings_task    = self.bot.db.get_rating_avg(gid, uid)
        incidents_task  = self.bot.db.get_incidents(gid, uid)

        (warnings, modlogs, level_data, att_rows, leaves,
         ratings, incidents) = await asyncio.gather(
            warnings_task, modlogs_task, levels_task,
            attendance_task, leaves_task, ratings_task, incidents_task
        )

        active_warns  = sum(1 for w in warnings if w[4])
        open_incidents = sum(1 for i in incidents if i[6] == "open")
        total_att_s   = sum(r[2] for r in att_rows if r[2])

        embed = discord.Embed(
            title=f"👤 Complete Summary — {member.display_name}",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        # Basic info
        embed.add_field(
            name="📋 Account",
            value=(
                f"Joined: {discord.utils.format_dt(member.joined_at, style='D')}\n"
                f"Created: {discord.utils.format_dt(member.created_at, style='D')}\n"
                f"Roles: {len(member.roles) - 1}"
            ),
            inline=True
        )

        # Activity
        if level_data:
            xp, level, msgs = level_data
            embed.add_field(
                name="💬 Activity",
                value=f"Level {level} · {xp} XP\n{msgs} messages",
                inline=True
            )

        # Attendance
        embed.add_field(
            name="⏱️ Attendance",
            value=f"{len(att_rows)} sessions\n{_fmt_duration(total_att_s)} total",
            inline=True
        )

        # Moderation
        embed.add_field(
            name="⚠️ Moderation",
            value=f"{active_warns} active warns\n{len(modlogs)} mod actions",
            inline=True
        )

        # Compliance
        embed.add_field(
            name="🛡️ Compliance",
            value=f"{open_incidents} open incidents\n{len(incidents)} total",
            inline=True
        )

        # Leave
        embed.add_field(
            name="🏖️ Leave",
            value=f"{len(leaves)} request(s)\n{sum(1 for l in leaves if l[6]=='approved')} approved",
            inline=True
        )

        # Ratings
        if ratings:
            overall = sum(r[0] for r in ratings) / len(ratings)
            stars   = "⭐" * round(overall)
            embed.add_field(
                name="⭐ Performance",
                value=f"{stars}\n`{overall:.2f}/5` avg",
                inline=True
            )

        embed.set_footer(text=f"Viewed by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /botinfo ──────────────────────────────────────────────────────────────

    @app_commands.command(name="botinfo", description="Bot health, uptime, and cog status")
    async def botinfo(self, interaction: discord.Interaction):
        uptime_s  = int(time.time() - self._start)
        guilds    = len(self.bot.guilds)
        members   = sum(g.member_count for g in self.bot.guilds)
        cogs      = list(self.bot.cogs.keys())
        cmds      = len(self.bot.tree.get_commands())

        embed = discord.Embed(
            title="🤖 Bot Info",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.add_field(name="🏷️ Name",         value=str(self.bot.user), inline=True)
        embed.add_field(name="⏱️ Uptime",        value=_fmt_duration(uptime_s), inline=True)
        embed.add_field(name="🏠 Guilds",        value=str(guilds), inline=True)
        embed.add_field(name="👥 Total members", value=str(members), inline=True)
        embed.add_field(name="⚡ Commands",      value=str(cmds), inline=True)
        embed.add_field(name="📦 Cogs loaded",   value=str(len(cogs)), inline=True)
        embed.add_field(
            name="📦 Modules",
            value="\n".join(f"✅ {c}" for c in cogs),
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /dbstats ──────────────────────────────────────────────────────────────

    @app_commands.command(name="dbstats", description="Database row counts per table (admin)")
    async def dbstats(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        tables = [
            "warnings", "mod_logs", "spam_track", "levels",
            "verified_users", "attendance", "leave_requests",
            "kpi_entries", "performance_ratings",
            "compliance_rules", "compliance_incidents",
            "crypto_alerts", "crypto_watchlist",
            "webhooks", "webhook_log"
        ]

        embed = discord.Embed(
            title="🗄️ Database Statistics",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )

        total_rows = 0
        async with aiosqlite.connect(DB_PATH) as db:
            for table in tables:
                try:
                    cur = await db.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE guild_id=?",
                        (str(interaction.guild.id),)
                    )
                    count = (await cur.fetchone())[0]
                    total_rows += count
                    embed.add_field(name=table, value=str(count), inline=True)
                except Exception:
                    embed.add_field(name=table, value="N/A", inline=True)

        embed.description = f"**Total rows (this server):** {total_rows:,}"
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /cleardata ────────────────────────────────────────────────────────────

    @app_commands.command(name="cleardata", description="Wipe all bot data for a user (admin — GDPR)")
    @app_commands.describe(member="Member whose data to erase", confirm='Type "CONFIRM" to proceed')
    async def cleardata(self, interaction: discord.Interaction, member: discord.Member, confirm: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        if confirm != "CONFIRM":
            return await interaction.response.send_message(
                '❌ Type `CONFIRM` exactly to proceed. This action is irreversible.', ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        uid = str(member.id)
        gid = str(interaction.guild.id)

        tables_to_clear = [
            "warnings", "mod_logs", "spam_track", "levels",
            "verified_users", "attendance", "leave_requests",
            "kpi_entries", "performance_ratings",
            "compliance_incidents", "crypto_alerts",
        ]

        async with aiosqlite.connect(DB_PATH) as db:
            for table in tables_to_clear:
                try:
                    await db.execute(
                        f"DELETE FROM {table} WHERE guild_id=? AND user_id=?",
                        (gid, uid)
                    )
                except Exception:
                    pass
            await db.commit()

        # Log to staff
        staff_ch = discord.utils.get(interaction.guild.text_channels, name=STAFF_CHAT_NAME)
        if staff_ch:
            embed = discord.Embed(
                title="🗑️ User Data Erased",
                description=f"All bot data for **{member}** (`{member.id}`) has been erased by {interaction.user.mention}.",
                colour=COL_ERR,
                timestamp=datetime.datetime.utcnow()
            )
            await staff_ch.send(embed=embed)

        await interaction.followup.send(
            embed=discord.Embed(
                description=f"✅ All bot data for **{member.display_name}** has been permanently erased.",
                colour=COL_OK
            ),
            ephemeral=True
        )

    # ── /snapshot ─────────────────────────────────────────────────────────────

    @app_commands.command(name="snapshot", description="Save a snapshot of current server stats (mod)")
    async def snapshot(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        lines = [
            f"SERVER SNAPSHOT — {guild.name}",
            f"Taken at: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"{'─'*40}",
            f"Members:       {guild.member_count}",
            f"Text channels: {len(guild.text_channels)}",
            f"Voice channels:{len(guild.voice_channels)}",
            f"Roles:         {len(guild.roles) - 1}",
            f"Boost level:   {guild.premium_tier}",
            f"Boosts:        {guild.premium_subscription_count}",
            f"{'─'*40}",
        ]

        async with aiosqlite.connect(DB_PATH) as db:
            for table in ["warnings", "mod_logs", "attendance", "leave_requests", "kpi_entries", "compliance_incidents"]:
                try:
                    cur = await db.execute(f"SELECT COUNT(*) FROM {table} WHERE guild_id=?", (str(guild.id),))
                    count = (await cur.fetchone())[0]
                    lines.append(f"{table:<25} {count}")
                except Exception:
                    pass

        content   = "\n".join(lines)
        filename  = f"snapshot_{guild.id}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M')}.txt"
        file = discord.File(
            fp=io.BytesIO(content.encode()),
            filename=filename
        )
        await interaction.followup.send(
            content="📸 Server snapshot saved:",
            file=file,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(DBTools(bot))
