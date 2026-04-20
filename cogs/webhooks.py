"""
WEBHOOKS & DASHBOARDS COG — Module 11
=======================================
Features:
  • /registerwebhook  — register an outgoing webhook URL for a bot event (admin)
  • /listwebhooks     — list all registered webhooks (admin)
  • /togglewebhook    — enable/disable a webhook (admin)
  • /testwebhook      — send a test ping to a registered webhook (admin)
  • /postwebhook      — manually fire a webhook with custom JSON payload (admin)
  • /dashboardstatus  — overview of all webhook endpoints and their health
  • /embedbuilder     — interactive rich embed builder for announcements
  • /announce         — post a pre-built announcement embed to any channel (mod)
  • Automatic event firing: mod actions, member joins/leaves fire registered webhooks
  Uses aiohttp for outgoing POST requests
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import aiohttp
import json

STAFF_CHAT_NAME = "staff-chat"

# Supported event types that can trigger webhooks
WEBHOOK_EVENTS = [
    "mod_action",       # ban, kick, mute, warn
    "member_join",      # new member joins
    "member_leave",     # member leaves
    "level_up",         # user levels up
    "compliance",       # compliance incident filed
    "leave_request",    # leave request submitted
    "custom",           # manual trigger only
]

COL_OK   = 0x2ECC71
COL_ERR  = 0xE74C3C
COL_INFO = 0x3498DB
COL_WARN = 0xF5A623


class EmbedBuilderModal(discord.ui.Modal, title="Build Announcement Embed"):
    embed_title   = discord.ui.TextInput(label="Title", max_length=256)
    embed_body    = discord.ui.TextInput(label="Body", style=discord.TextStyle.paragraph, max_length=2000)
    embed_colour  = discord.ui.TextInput(label="Colour (hex, e.g. #2ECC71)", default="#3498DB", max_length=7)
    embed_footer  = discord.ui.TextInput(label="Footer text (optional)", required=False, max_length=200)
    embed_channel = discord.ui.TextInput(label="Channel name to post in", default="announcements", max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hex_str = self.embed_colour.value.strip().lstrip("#")
            colour  = int(hex_str, 16)
        except ValueError:
            colour = 0x3498DB

        embed = discord.Embed(
            title=self.embed_title.value,
            description=self.embed_body.value,
            colour=colour,
            timestamp=datetime.datetime.utcnow()
        )
        if self.embed_footer.value:
            embed.set_footer(text=self.embed_footer.value)

        ch_name = self.embed_channel.value.strip().lstrip("#")
        channel = discord.utils.get(interaction.guild.text_channels, name=ch_name)

        if not channel:
            return await interaction.response.send_message(
                f"❌ Channel `#{ch_name}` not found.", ephemeral=True
            )

        await channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Announcement posted in {channel.mention}.", ephemeral=True
        )


class Webhooks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._session: aiohttp.ClientSession = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()

    async def _fire_webhook(self, webhook_id: int, url: str, payload: dict) -> bool:
        """POST payload to webhook URL. Returns True on success."""
        try:
            async with self._session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": "DiscordBot/1.0"},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                status = "ok" if r.status in (200, 201, 204) else f"error:{r.status}"
                await self.bot.db.log_webhook_delivery(webhook_id, json.dumps(payload)[:500], status)
                return r.status in (200, 201, 204)
        except Exception as e:
            await self.bot.db.log_webhook_delivery(webhook_id, json.dumps(payload)[:500], f"exception:{str(e)[:50]}")
            return False

    async def dispatch_event(self, guild_id: int, event_type: str, data: dict):
        """Called internally to fire all webhooks registered for an event."""
        rows = await self.bot.db.get_webhooks(guild_id, event_type)
        if not rows:
            return
        payload = {
            "event": event_type,
            "guild_id": str(guild_id),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "data": data
        }
        for wh_id, name, url, _, active in rows:
            asyncio.create_task(self._fire_webhook(wh_id, url, payload))

    # ── /registerwebhook ──────────────────────────────────────────────────────

    @app_commands.command(name="registerwebhook", description="Register an outgoing webhook URL (admin)")
    @app_commands.describe(
        name="Friendly name for this webhook",
        url="Destination URL (must accept POST JSON)",
        event_type="Which event triggers this webhook"
    )
    @app_commands.choices(event_type=[app_commands.Choice(name=e, value=e) for e in WEBHOOK_EVENTS])
    async def registerwebhook(
        self,
        interaction: discord.Interaction,
        name: str,
        url: str,
        event_type: str
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        if not url.startswith(("http://", "https://")):
            return await interaction.response.send_message("❌ URL must start with http:// or https://", ephemeral=True)

        wh_id = await self.bot.db.register_webhook(
            interaction.guild.id, name, url, event_type, interaction.user.id
        )

        embed = discord.Embed(
            title="🔗 Webhook Registered",
            colour=COL_OK,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="ID",         value=f"#{wh_id}", inline=True)
        embed.add_field(name="Name",       value=name, inline=True)
        embed.add_field(name="Event",      value=event_type, inline=True)
        embed.add_field(name="URL",        value=f"`{url[:60]}{'...' if len(url)>60 else ''}`", inline=False)
        embed.set_footer(text=f"Registered by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /listwebhooks ─────────────────────────────────────────────────────────

    @app_commands.command(name="listwebhooks", description="List all registered webhooks (admin)")
    async def listwebhooks(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        rows = await self.bot.db.get_webhooks(interaction.guild.id)

        embed = discord.Embed(
            title="🔗 Registered Webhooks",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )

        if not rows:
            embed.description = "No webhooks registered. Use `/registerwebhook` to add one."
        else:
            for wh_id, name, url, event_type, active in rows:
                status = "🟢 Active" if active else "🔴 Disabled"
                embed.add_field(
                    name=f"#{wh_id} — {name}",
                    value=f"**Event:** {event_type}\n**Status:** {status}\n**URL:** `{url[:50]}...`",
                    inline=False
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /togglewebhook ────────────────────────────────────────────────────────

    @app_commands.command(name="togglewebhook", description="Enable or disable a webhook (admin)")
    @app_commands.describe(webhook_id="Webhook ID from /listwebhooks", enable="True to enable, False to disable")
    async def togglewebhook(self, interaction: discord.Interaction, webhook_id: int, enable: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await self.bot.db.toggle_webhook(webhook_id, enable)
        status = "enabled 🟢" if enable else "disabled 🔴"
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ Webhook **#{webhook_id}** is now **{status}**.",
                colour=COL_OK if enable else COL_ERR
            ),
            ephemeral=True
        )

    # ── /testwebhook ──────────────────────────────────────────────────────────

    @app_commands.command(name="testwebhook", description="Send a test ping to a webhook (admin)")
    @app_commands.describe(webhook_id="Webhook ID to test")
    async def testwebhook(self, interaction: discord.Interaction, webhook_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.get_webhooks(interaction.guild.id)
        wh   = next((r for r in rows if r[0] == webhook_id), None)

        if not wh:
            return await interaction.followup.send("❌ Webhook not found.", ephemeral=True)

        _, name, url, event_type, active = wh
        payload = {
            "event": "test",
            "guild_id": str(interaction.guild.id),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "data": {"message": "This is a test ping from your Discord bot.", "sent_by": str(interaction.user)}
        }

        success = await self._fire_webhook(webhook_id, url, payload)

        colour = COL_OK if success else COL_ERR
        status = "✅ Success — webhook responded correctly." if success else "❌ Failed — check the URL and server."
        await interaction.followup.send(
            embed=discord.Embed(description=f"**Webhook #{webhook_id} — {name}**\n{status}", colour=colour),
            ephemeral=True
        )

    # ── /postwebhook ──────────────────────────────────────────────────────────

    @app_commands.command(name="postwebhook", description="Manually fire a webhook with custom JSON data (admin)")
    @app_commands.describe(webhook_id="Webhook ID", json_data="JSON string to send as payload data")
    async def postwebhook(self, interaction: discord.Interaction, webhook_id: int, json_data: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        try:
            parsed = json.loads(json_data)
        except json.JSONDecodeError as e:
            return await interaction.response.send_message(f"❌ Invalid JSON: {e}", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.get_webhooks(interaction.guild.id)
        wh   = next((r for r in rows if r[0] == webhook_id), None)

        if not wh:
            return await interaction.followup.send("❌ Webhook not found.", ephemeral=True)

        _, name, url, event_type, _ = wh
        payload = {
            "event": "manual",
            "guild_id": str(interaction.guild.id),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "data": parsed
        }

        success = await self._fire_webhook(webhook_id, url, payload)
        colour  = COL_OK if success else COL_ERR
        status  = "✅ Delivered successfully." if success else "❌ Delivery failed."

        await interaction.followup.send(
            embed=discord.Embed(description=f"**{name}** — {status}", colour=colour),
            ephemeral=True
        )

    # ── /dashboardstatus ──────────────────────────────────────────────────────

    @app_commands.command(name="dashboardstatus", description="Overview of all webhook endpoints (admin)")
    async def dashboardstatus(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        rows = await self.bot.db.get_webhooks(interaction.guild.id)

        embed = discord.Embed(
            title="📡 Integration Dashboard",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        active_count   = sum(1 for r in rows if r[4])
        inactive_count = len(rows) - active_count

        embed.add_field(name="Total webhooks", value=str(len(rows)),      inline=True)
        embed.add_field(name="🟢 Active",      value=str(active_count),   inline=True)
        embed.add_field(name="🔴 Inactive",    value=str(inactive_count), inline=True)

        # Group by event type
        by_event: dict[str, list] = {}
        for r in rows:
            by_event.setdefault(r[3], []).append(r)

        for event, webhooks in by_event.items():
            lines = [
                f"{'🟢' if w[4] else '🔴'} **#{w[0]}** {w[1]}"
                for w in webhooks
            ]
            embed.add_field(name=f"📌 {event}", value="\n".join(lines), inline=False)

        if not rows:
            embed.description = "No webhooks registered. Use `/registerwebhook` to connect external services."

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /embedbuilder ─────────────────────────────────────────────────────────

    @app_commands.command(name="embedbuilder", description="Interactively build and post a rich embed (mod)")
    async def embedbuilder(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)
        await interaction.response.send_modal(EmbedBuilderModal())

    # ── /announce ─────────────────────────────────────────────────────────────

    @app_commands.command(name="announce", description="Post a formatted announcement embed (mod)")
    @app_commands.describe(
        channel="Channel to post in",
        title="Announcement title",
        message="Announcement body",
        ping="Role to ping (optional)"
    )
    async def announce(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        title: str,
        message: str,
        ping: discord.Role = None
    ):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        embed = discord.Embed(
            title=f"📢 {title}",
            description=message,
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text=f"Announced by {interaction.user.display_name}")
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        content = ping.mention if ping else None
        await channel.send(content=content, embed=embed)

        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Announcement posted in {channel.mention}.", colour=COL_OK),
            ephemeral=True
        )

    # ── Event listeners that fire webhooks ────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.dispatch_event(member.guild.id, "member_join", {
            "user_id":    str(member.id),
            "username":   str(member),
            "account_age_days": (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days,
            "member_count": member.guild.member_count,
        })

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.dispatch_event(member.guild.id, "member_leave", {
            "user_id":  str(member.id),
            "username": str(member),
        })


async def setup(bot):
    await bot.add_cog(Webhooks(bot))
