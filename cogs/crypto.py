"""
CRYPTO COG — Module 10
=======================
Features:
  • /price        — live price for any coin (BTC, ETH, SOL, etc.)
  • /crypto       — detailed coin info (price, market cap, 24h change, volume)
  • /convert      — convert between crypto and fiat (BTC → USD, ETH → GBP, etc.)
  • /watchlist    — server watchlist of coins to track
  • /addwatch     — add a coin to the server watchlist (mod)
  • /removewatch  — remove from watchlist (mod)
  • /marketupdate — post a full market summary embed to a channel (mod)
  • /setalert     — set a price alert (DM when coin hits target)
  • /myalerts     — view your active alerts
  • /removealert  — cancel an alert
  • Background task checks alerts every 5 minutes
  Uses CoinGecko public API (no key required)
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import asyncio
import aiohttp

STAFF_CHAT_NAME   = "staff-chat"
CRYPTO_NEWS_NAME  = "crypto-updates"

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Common coin ID mapping (symbol → CoinGecko id)
COIN_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "MATIC": "matic-network", "DOT": "polkadot",
    "AVAX": "avalanche-2", "LINK": "chainlink", "LTC": "litecoin",
    "UNI": "uniswap", "ATOM": "cosmos", "XLM": "stellar",
    "ALGO": "algorand", "VET": "vechain", "FIL": "filecoin",
    "TRX": "tron", "NEAR": "near", "SHIB": "shiba-inu",
    "APT": "aptos", "ARB": "arbitrum", "OP": "optimism",
    "SUI": "sui", "INJ": "injective-protocol", "TON": "the-open-network",
}

SUPPORTED_CURRENCIES = ["usd", "eur", "gbp", "ngn", "jpy", "cad", "aud", "chf"]

COL_UP   = 0x2ECC71
COL_DOWN = 0xE74C3C
COL_FLAT = 0x3498DB
COL_INFO = 0x9B59B6


def _resolve_id(symbol: str) -> str:
    return COIN_IDS.get(symbol.upper(), symbol.lower())


def _change_icon(pct: float) -> str:
    if pct > 0: return "📈"
    if pct < 0: return "📉"
    return "➡️"


def _fmt_price(value: float) -> str:
    if value >= 1:
        return f"${value:,.4f}"
    return f"${value:.8f}"


def _fmt_large(value: float) -> str:
    if value >= 1_000_000_000:
        return f"${value/1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    return f"${value:,.0f}"


class Crypto(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._session: aiohttp.ClientSession = None
        self._alert_task = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        self._alert_task = self.bot.loop.create_task(self._alert_loop())

    async def cog_unload(self):
        if self._alert_task:
            self._alert_task.cancel()
        if self._session:
            await self._session.close()

    async def _get(self, endpoint: str, params: dict = None):
        try:
            async with self._session.get(
                f"{COINGECKO_BASE}{endpoint}",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    return await r.json()
                return None
        except Exception:
            return None

    async def _fetch_price(self, coin_id: str, currency: str = "usd"):
        data = await self._get("/simple/price", {
            "ids": coin_id,
            "vs_currencies": currency,
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        })
        if data and coin_id in data:
            return data[coin_id]
        return None

    async def _fetch_detail(self, coin_id: str):
        return await self._get(f"/coins/{coin_id}", {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
        })

    # ── /price ────────────────────────────────────────────────────────────────

    @app_commands.command(name="price", description="Get the live price of a cryptocurrency")
    @app_commands.describe(
        symbol="Coin symbol or name (e.g. BTC, ETH, SOL)",
        currency="Fiat currency to display in (default: USD)"
    )
    @app_commands.choices(currency=[
        app_commands.Choice(name=c.upper(), value=c) for c in SUPPORTED_CURRENCIES
    ])
    async def price(self, interaction: discord.Interaction, symbol: str, currency: str = "usd"):
        await interaction.response.defer()
        coin_id = _resolve_id(symbol)
        data = await self._fetch_price(coin_id, currency)

        if not data:
            return await interaction.followup.send(
                embed=discord.Embed(
                    description=f"❌ Could not find price data for `{symbol.upper()}`. Check the symbol and try again.",
                    colour=COL_DOWN
                )
            )

        price_val   = data.get(currency, 0)
        change_24h  = data.get(f"{currency}_24h_change", 0)
        market_cap  = data.get(f"{currency}_market_cap", 0)
        volume      = data.get(f"{currency}_24h_vol", 0)

        colour = COL_UP if change_24h >= 0 else COL_DOWN
        icon   = _change_icon(change_24h)

        embed = discord.Embed(
            title=f"{icon} {symbol.upper()} / {currency.upper()}",
            colour=colour,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="💰 Price",       value=_fmt_price(price_val), inline=True)
        embed.add_field(name="24h Change",     value=f"{change_24h:+.2f}%", inline=True)
        embed.add_field(name="Market Cap",     value=_fmt_large(market_cap), inline=True)
        embed.add_field(name="24h Volume",     value=_fmt_large(volume), inline=True)
        embed.set_footer(text="Data: CoinGecko • Prices may be delayed")
        await interaction.followup.send(embed=embed)

    # ── /crypto ───────────────────────────────────────────────────────────────

    @app_commands.command(name="crypto", description="Detailed info about a cryptocurrency")
    @app_commands.describe(symbol="Coin symbol (e.g. BTC, ETH, SOL)")
    async def crypto(self, interaction: discord.Interaction, symbol: str):
        await interaction.response.defer()
        coin_id = _resolve_id(symbol)
        data = await self._fetch_detail(coin_id)

        if not data:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"❌ Coin `{symbol.upper()}` not found.", colour=COL_DOWN)
            )

        md       = data.get("market_data", {})
        price    = md.get("current_price", {}).get("usd", 0)
        change1h = md.get("price_change_percentage_1h_in_currency", {}).get("usd", 0) or 0
        change24 = md.get("price_change_percentage_24h", 0) or 0
        change7d = md.get("price_change_percentage_7d", 0) or 0
        ath      = md.get("ath", {}).get("usd", 0)
        atl      = md.get("atl", {}).get("usd", 0)
        mcap     = md.get("market_cap", {}).get("usd", 0)
        vol      = md.get("total_volume", {}).get("usd", 0)
        supply   = md.get("circulating_supply", 0)
        rank     = data.get("market_cap_rank", "N/A")
        name     = data.get("name", symbol.upper())
        desc     = data.get("description", {}).get("en", "")[:200]

        colour = COL_UP if change24 >= 0 else COL_DOWN
        icon   = _change_icon(change24)

        embed = discord.Embed(
            title=f"{icon} {name} ({symbol.upper()})",
            description=desc + ("..." if len(desc) == 200 else ""),
            colour=colour,
            timestamp=datetime.datetime.utcnow()
        )
        if data.get("image", {}).get("small"):
            embed.set_thumbnail(url=data["image"]["small"])

        embed.add_field(name="💰 Price (USD)",  value=_fmt_price(price), inline=True)
        embed.add_field(name="📊 Rank",         value=f"#{rank}", inline=True)
        embed.add_field(name="🏦 Market Cap",   value=_fmt_large(mcap), inline=True)
        embed.add_field(name="1h Change",       value=f"{change1h:+.2f}%", inline=True)
        embed.add_field(name="24h Change",      value=f"{change24:+.2f}%", inline=True)
        embed.add_field(name="7d Change",       value=f"{change7d:+.2f}%", inline=True)
        embed.add_field(name="📈 ATH",          value=_fmt_price(ath), inline=True)
        embed.add_field(name="📉 ATL",          value=_fmt_price(atl), inline=True)
        embed.add_field(name="🔄 Volume 24h",   value=_fmt_large(vol), inline=True)
        if supply:
            embed.add_field(name="🪙 Supply",   value=f"{supply:,.0f}", inline=True)

        embed.set_footer(text="Data: CoinGecko • Prices may be delayed")
        await interaction.followup.send(embed=embed)

    # ── /convert ──────────────────────────────────────────────────────────────

    @app_commands.command(name="convert", description="Convert between crypto and fiat")
    @app_commands.describe(
        amount="Amount to convert",
        from_coin="Coin to convert from (e.g. BTC)",
        to_currency="Currency to convert to (e.g. USD, EUR, NGN)"
    )
    @app_commands.choices(to_currency=[
        app_commands.Choice(name=c.upper(), value=c) for c in SUPPORTED_CURRENCIES
    ])
    async def convert(
        self,
        interaction: discord.Interaction,
        amount: float,
        from_coin: str,
        to_currency: str = "usd"
    ):
        await interaction.response.defer()
        coin_id = _resolve_id(from_coin)
        data = await self._fetch_price(coin_id, to_currency)

        if not data:
            return await interaction.followup.send(
                embed=discord.Embed(description=f"❌ Could not find `{from_coin.upper()}`.", colour=COL_DOWN)
            )

        rate   = data.get(to_currency, 0)
        result = amount * rate
        change = data.get(f"{to_currency}_24h_change", 0)

        embed = discord.Embed(
            title="💱 Crypto Converter",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="You send",    value=f"**{amount:,.6g} {from_coin.upper()}**", inline=True)
        embed.add_field(name="You receive", value=f"**{result:,.2f} {to_currency.upper()}**", inline=True)
        embed.add_field(name="Rate",        value=f"1 {from_coin.upper()} = {_fmt_price(rate)} {to_currency.upper()}", inline=False)
        embed.add_field(name="24h Change",  value=f"{change:+.2f}%", inline=True)
        embed.set_footer(text="Data: CoinGecko • For reference only, not financial advice")
        await interaction.followup.send(embed=embed)

    # ── /addwatch / /removewatch / /watchlist ─────────────────────────────────

    @app_commands.command(name="addwatch", description="Add a coin to the server watchlist (mod)")
    @app_commands.describe(symbol="Coin symbol to add (e.g. BTC)")
    async def addwatch(self, interaction: discord.Interaction, symbol: str):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)
        await self.bot.db.add_to_watchlist(interaction.guild.id, symbol.upper(), interaction.user.id)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ **{symbol.upper()}** added to the server watchlist.", colour=COL_UP),
            ephemeral=True
        )

    @app_commands.command(name="removewatch", description="Remove a coin from the server watchlist (mod)")
    @app_commands.describe(symbol="Coin symbol to remove")
    async def removewatch(self, interaction: discord.Interaction, symbol: str):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)
        await self.bot.db.remove_from_watchlist(interaction.guild.id, symbol.upper())
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ **{symbol.upper()}** removed from watchlist.", colour=COL_UP),
            ephemeral=True
        )

    @app_commands.command(name="watchlist", description="View the server crypto watchlist with live prices")
    async def watchlist(self, interaction: discord.Interaction):
        await interaction.response.defer()
        rows = await self.bot.db.get_watchlist(interaction.guild.id)

        if not rows:
            return await interaction.followup.send(
                embed=discord.Embed(
                    description="No coins on the watchlist yet. Use `/addwatch BTC` to add one.",
                    colour=COL_INFO
                )
            )

        symbols = [r[0] for r in rows]
        ids     = [_resolve_id(s) for s in symbols]
        ids_str = ",".join(ids)

        data = await self._get("/simple/price", {
            "ids": ids_str,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        })

        embed = discord.Embed(
            title=f"📊 {interaction.guild.name} Crypto Watchlist",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )

        for symbol, cid in zip(symbols, ids):
            coin_data = (data or {}).get(cid, {})
            price     = coin_data.get("usd", None)
            change    = coin_data.get("usd_24h_change", None)

            if price is not None:
                icon = _change_icon(change or 0)
                embed.add_field(
                    name=f"{icon} {symbol}",
                    value=f"{_fmt_price(price)}\n`{change:+.2f}%`" if change is not None else _fmt_price(price),
                    inline=True
                )
            else:
                embed.add_field(name=f"⚠️ {symbol}", value="Unavailable", inline=True)

        embed.set_footer(text="Data: CoinGecko • Prices may be delayed")
        await interaction.followup.send(embed=embed)

    # ── /marketupdate ─────────────────────────────────────────────────────────

    @app_commands.command(name="marketupdate", description="Post a full market summary to a channel (mod)")
    @app_commands.describe(channel="Channel to post the update in (default: #crypto-updates)")
    async def marketupdate(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Moderators only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        target_ch = channel or discord.utils.get(interaction.guild.text_channels, name=CRYPTO_NEWS_NAME)
        if not target_ch:
            return await interaction.followup.send("❌ Channel not found. Create `#crypto-updates` or specify a channel.", ephemeral=True)

        # Fetch top 10 coins
        data = await self._get("/coins/markets", {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 10,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        })

        if not data:
            return await interaction.followup.send("❌ Could not fetch market data. Try again later.", ephemeral=True)

        embed = discord.Embed(
            title="🌐 Crypto Market Update — Top 10",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text=f"Posted by {interaction.user.display_name} • Data: CoinGecko")

        lines = []
        for coin in data:
            name    = coin.get("symbol", "?").upper()
            price   = coin.get("current_price", 0)
            change  = coin.get("price_change_percentage_24h", 0) or 0
            rank    = coin.get("market_cap_rank", "?")
            icon    = "🟢" if change >= 0 else "🔴"
            lines.append(f"`#{rank:>2}` {icon} **{name}** {_fmt_price(price)} `{change:+.2f}%`")

        embed.description = "\n".join(lines)

        # Overall sentiment
        gainers = sum(1 for c in data if (c.get("price_change_percentage_24h") or 0) > 0)
        losers  = len(data) - gainers
        embed.add_field(
            name="Market Sentiment",
            value=f"🟢 {gainers} gaining · 🔴 {losers} falling",
            inline=False
        )

        await target_ch.send(embed=embed)
        await interaction.followup.send(f"✅ Market update posted in {target_ch.mention}.", ephemeral=True)

    # ── /setalert ─────────────────────────────────────────────────────────────

    @app_commands.command(name="setalert", description="Set a price alert — get a DM when a coin hits your target")
    @app_commands.describe(
        symbol="Coin symbol (e.g. BTC)",
        target_price="Target price in USD",
        direction="Alert when price goes above or below target"
    )
    @app_commands.choices(direction=[
        app_commands.Choice(name="📈 Above target", value="above"),
        app_commands.Choice(name="📉 Below target", value="below"),
    ])
    async def setalert(
        self,
        interaction: discord.Interaction,
        symbol: str,
        target_price: float,
        direction: str
    ):
        alert_id = await self.bot.db.add_crypto_alert(
            interaction.guild.id, interaction.user.id,
            symbol.upper(), target_price, direction
        )
        icon = "📈" if direction == "above" else "📉"
        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    f"✅ Alert **#{alert_id}** set!\n"
                    f"{icon} You'll be DM'd when **{symbol.upper()}** goes **{direction}** `${target_price:,.4f}`."
                ),
                colour=COL_UP
            ),
            ephemeral=True
        )

    # ── /myalerts ─────────────────────────────────────────────────────────────

    @app_commands.command(name="myalerts", description="View your active price alerts")
    async def myalerts(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_active_alerts(interaction.guild.id, interaction.user.id)

        embed = discord.Embed(
            title="🔔 My Price Alerts",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        if not rows:
            embed.description = "No active alerts. Use `/setalert` to create one."
        else:
            for alert_id, symbol, target, direction, created_at in rows:
                icon = "📈" if direction == "above" else "📉"
                embed.add_field(
                    name=f"#{alert_id} — {symbol}",
                    value=f"{icon} {direction.title()} `${target:,.4f}`\nSet: {created_at[:10]}",
                    inline=True
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /removealert ──────────────────────────────────────────────────────────

    @app_commands.command(name="removealert", description="Cancel a price alert")
    @app_commands.describe(alert_id="Alert ID from /myalerts")
    async def removealert(self, interaction: discord.Interaction, alert_id: int):
        await self.bot.db.remove_alert(alert_id, interaction.user.id)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Alert **#{alert_id}** cancelled.", colour=COL_UP),
            ephemeral=True
        )

    # ── Background alert checker ──────────────────────────────────────────────

    async def _alert_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self._check_all_alerts()
            except Exception as e:
                print(f"[Crypto] Alert loop error: {e}")
            await asyncio.sleep(300)  # check every 5 minutes

    async def _check_all_alerts(self):
        for guild in self.bot.guilds:
            rows = await self.bot.db.get_active_alerts(guild.id)
            if not rows:
                continue

            # Group by symbol to batch API calls
            symbols: dict[str, list] = {}
            for alert_id, user_id, symbol, target, direction in rows:
                symbols.setdefault(symbol, []).append((alert_id, user_id, target, direction))

            ids_str = ",".join(_resolve_id(s) for s in symbols)
            data = await self._get("/simple/price", {"ids": ids_str, "vs_currencies": "usd"})
            if not data:
                continue

            for symbol, alerts in symbols.items():
                coin_id   = _resolve_id(symbol)
                coin_data = data.get(coin_id, {})
                price     = coin_data.get("usd")
                if price is None:
                    continue

                for alert_id, user_id, target, direction in alerts:
                    triggered = (
                        (direction == "above" and price >= target) or
                        (direction == "below" and price <= target)
                    )
                    if triggered:
                        await self.bot.db.mark_alert_triggered(alert_id)
                        member = guild.get_member(int(user_id))
                        if member:
                            icon = "📈" if direction == "above" else "📉"
                            try:
                                dm = discord.Embed(
                                    title=f"🔔 Price Alert Triggered — {symbol}",
                                    description=(
                                        f"{icon} **{symbol}** is now at `${price:,.4f}`\n"
                                        f"Your alert: **{direction}** `${target:,.4f}`"
                                    ),
                                    colour=COL_UP if direction == "above" else COL_DOWN,
                                    timestamp=datetime.datetime.utcnow()
                                )
                                dm.set_footer(text="Alert ID #{alert_id} — automatically removed")
                                await member.send(embed=dm)
                            except discord.Forbidden:
                                pass


async def setup(bot):
    await bot.add_cog(Crypto(bot))
