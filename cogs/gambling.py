"""
GAMBLING & ECONOMY COG — Module 13
=====================================
Economy:
  • /balance       — view wallet + bank balance
  • /daily         — claim daily reward (streak bonuses up to 7x)
  • /work          — earn coins every 30 minutes with random job flavour
  • /deposit       — move coins from wallet to bank (safe storage)
  • /withdraw      — move coins from bank to wallet
  • /transfer      — send coins to another member
  • /econleader    — richest members leaderboard
  • /transactions  — view your recent transaction history

Gambling (wallet only — cannot gamble from bank):
  • /coinflip      — 50/50 heads or tails bet
  • /dice          — guess the dice roll (1–6), 5x payout
  • /slots         — 3-reel slot machine with multiple winning combos
  • /blackjack     — full blackjack game (hit, stand, double down)
  • /roulette      — bet on number, colour, even/odd, dozen
  • /crash         — live multiplier crash game (cash out before it crashes)

Admin:
  • /givemoney     — give coins to a member (admin)
  • /takemoney     — remove coins from a member (admin)
  • /reseteconomy  — reset a user's economy data (admin)
"""

import discord
from discord import app_commands
from discord.ext import commands
import datetime
import random
import asyncio

STAFF_CHAT_NAME  = "staff-chat"
CURRENCY         = "🪙"
CURRENCY_NAME    = "coins"

# Economy config
DAILY_BASE       = 200    # base daily reward (streak multiplies this)
DAILY_STREAK_MAX = 7      # max streak multiplier
WORK_COOLDOWN_M  = 30     # minutes between /work uses
WORK_MIN         = 50     # minimum coins from /work
WORK_MAX         = 150    # maximum coins from /work
TRANSFER_TAX     = 0.05   # 5% tax on transfers
STARTER_BONUS    = 1000   # one-time starter pack (on top of starting 500+500)

# Gambling config
MIN_BET          = 10
MAX_BET          = 50_000

COL_WIN  = 0x2ECC71
COL_LOSE = 0xE74C3C
COL_INFO = 0x3498DB
COL_GOLD = 0xF5A623


def _fmt(amount: int) -> str:
    return f"{CURRENCY} **{amount:,}**"


def _bet_check(amount: int, wallet: int):
    if amount < MIN_BET:
        return f"❌ Minimum bet is {_fmt(MIN_BET)}."
    if amount > MAX_BET:
        return f"❌ Maximum bet is {_fmt(MAX_BET)}."
    if amount > wallet:
        return f"❌ You only have {_fmt(wallet)} in your wallet."
    return None


# ── Blackjack helpers ─────────────────────────────────────────────────────────

SUITS  = ["♠", "♥", "♦", "♣"]
RANKS  = ["2","3","4","5","6","7","8","9","10","J","Q","K","A"]
VALUES = {"2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,"J":10,"Q":10,"K":10,"A":11}


def _new_deck():
    deck = [(r, s) for s in SUITS for r in RANKS]
    random.shuffle(deck)
    return deck


def _hand_value(hand):
    total = sum(VALUES[r] for r, s in hand)
    aces  = sum(1 for r, s in hand if r == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _fmt_hand(hand):
    return " ".join(f"{r}{s}" for r, s in hand)


# ── Slot machine ──────────────────────────────────────────────────────────────

SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
SLOT_PAYOUTS = {
    "💎💎💎": 20, "7️⃣7️⃣7️⃣": 15, "⭐⭐⭐": 10,
    "🍇🍇🍇": 8,  "🍊🍊🍊": 6,   "🍋🍋🍋": 5,
    "🍒🍒🍒": 4,  "🍒🍒": 2,
}


def _spin_slots():
    return [random.choice(SLOT_SYMBOLS) for _ in range(3)]


def _slot_payout(reels, bet):
    key3 = "".join(reels)
    key2 = "".join(reels[:2])
    mult = SLOT_PAYOUTS.get(key3) or SLOT_PAYOUTS.get(key2, 0)
    return mult * bet if mult else 0


# ── Crash game view ───────────────────────────────────────────────────────────

class CrashView(discord.ui.View):
    def __init__(self, user_id: int, bet: int, cog):
        super().__init__(timeout=30)
        self.user_id  = user_id
        self.bet      = bet
        self.cog      = cog
        self.cashed   = False
        self.multiplier = 1.0

    @discord.ui.button(label="💰 Cash Out", style=discord.ButtonStyle.success)
    async def cashout(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your game!", ephemeral=True)
        if self.cashed:
            return
        self.cashed = True
        button.disabled = True
        winnings = int(self.bet * self.multiplier)
        await self.cog.bot.db.update_wallet(
            interaction.guild.id, interaction.user.id,
            wallet_delta=winnings, won=winnings - self.bet
        )
        await self.cog.bot.db.log_transaction(
            interaction.guild.id, interaction.user.id,
            winnings, "crash_win", f"Crashed at {self.multiplier:.2f}x"
        )
        embed = discord.Embed(
            title="💰 Cashed Out!",
            description=(
                f"You cashed out at **{self.multiplier:.2f}x**!\n"
                f"Profit: {_fmt(winnings - self.bet)}\n"
                f"Total returned: {_fmt(winnings)}"
            ),
            colour=COL_WIN
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


# ── Gambling Cog ──────────────────────────────────────────────────────────────

class Gambling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # active BJ games: user_id -> {deck, player, dealer, bet}
        self._bj_games: dict[int, dict] = {}

    # ── /balance ──────────────────────────────────────────────────────────────

    @app_commands.command(name="balance", description="View your wallet and bank balance")
    @app_commands.describe(member="Member to check (default: yourself)")
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        wallet, bank, won, lost, *_ = await self.bot.db.get_wallet(interaction.guild.id, target.id)
        total  = wallet + bank
        net    = won - lost

        embed = discord.Embed(
            title=f"{CURRENCY} Balance — {target.display_name}",
            colour=COL_GOLD,
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="👛 Wallet", value=f"{CURRENCY} {wallet:,}", inline=True)
        embed.add_field(name="🏦 Bank",   value=f"{CURRENCY} {bank:,}",   inline=True)
        embed.add_field(name="💰 Net",    value=f"{CURRENCY} {total:,}",  inline=True)
        embed.add_field(name="🏆 Won",    value=f"{CURRENCY} {won:,}",    inline=True)
        embed.add_field(name="💸 Lost",   value=f"{CURRENCY} {lost:,}",   inline=True)
        embed.add_field(name="📊 P&L",    value=f"{CURRENCY} {net:+,}",   inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /starter ──────────────────────────────────────────────────────────────

    @app_commands.command(name="starter", description="Claim your one-time starter pack to fund your wallet")
    async def starter(self, interaction: discord.Interaction):
        already = await self.bot.db.has_claimed_starter(interaction.guild.id, interaction.user.id)
        if already:
            wallet, bank, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
            embed = discord.Embed(
                title="Already Claimed",
                description=(
                    "You already claimed your starter pack!\n\n"
                    "**Current balance:**\n"
                    f"Wallet: {_fmt(wallet)}\n"
                    f"Bank:   {_fmt(bank)}\n\n"
                    "Use `/daily` and `/work` to keep earning."
                ),
                colour=COL_INFO
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await self.bot.db.update_wallet(
            interaction.guild.id, interaction.user.id,
            wallet_delta=STARTER_BONUS
        )
        await self.bot.db.mark_starter_claimed(interaction.guild.id, interaction.user.id)
        await self.bot.db.log_transaction(
            interaction.guild.id, interaction.user.id,
            STARTER_BONUS, "starter", "One-time starter pack"
        )

        wallet, bank, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)

        embed = discord.Embed(
            title="Starter Pack Claimed!",
            description="Welcome! Here is your one-time starter pack.\n\n**+" + _fmt(STARTER_BONUS) + "** added to your wallet!",
            colour=COL_WIN,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Wallet", value=_fmt(wallet), inline=True)
        embed.add_field(name="Bank",   value=_fmt(bank),   inline=True)
        embed.add_field(
            name="How to earn more",
            value=(
                "`/daily` — up to 1,400 coins/day at max streak\n"
                "`/work` — 50-150 coins every 30 minutes\n"
                "`/slots` `/blackjack` `/crash` — gamble to grow faster\n"
                "`/deposit` — keep winnings safe in your bank"
            ),
            inline=False
        )
        embed.set_footer(text="One-time bonus. Good luck!")
        await interaction.response.send_message(embed=embed)

        # ── /daily ────────────────────────────────────────────────────────────────

    @app_commands.command(name="daily", description="Claim your daily coin reward")
    async def daily(self, interaction: discord.Interaction):
        wallet, bank, won, lost, last_daily, last_work, streak = \
            await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)

        now = datetime.datetime.utcnow()
        if last_daily:
            last_dt = datetime.datetime.fromisoformat(last_daily)
            diff    = (now - last_dt).total_seconds()
            if diff < 82800:  # 23 hours
                remaining = 82800 - diff
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"⏳ Daily resets in **{h}h {m}m**. Come back later!",
                        colour=COL_LOSE
                    ),
                    ephemeral=True
                )
            # Check streak (within 48h)
            new_streak = streak + 1 if diff < 172800 else 1
        else:
            new_streak = 1

        new_streak = min(new_streak, DAILY_STREAK_MAX)
        bonus   = DAILY_BASE * new_streak
        await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=bonus)
        await self.bot.db.set_daily_claimed(interaction.guild.id, interaction.user.id, new_streak)
        await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, bonus, "daily", f"Streak {new_streak}")

        embed = discord.Embed(
            title="📅 Daily Reward Claimed!",
            colour=COL_WIN,
            timestamp=now
        )
        embed.add_field(name="Reward",    value=_fmt(bonus),      inline=True)
        embed.add_field(name="🔥 Streak", value=f"{new_streak}x", inline=True)
        if new_streak < DAILY_STREAK_MAX:
            embed.add_field(name="Tip", value=f"Return tomorrow for a **{new_streak+1}x** streak bonus!", inline=False)
        else:
            embed.add_field(name="Max streak!", value="You've hit the maximum 7x streak! 🏆", inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /work ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="work", description=f"Earn coins every {WORK_COOLDOWN_M} minutes")
    async def work(self, interaction: discord.Interaction):
        wallet, bank, won, lost, last_daily, last_work, streak = \
            await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)

        now = datetime.datetime.utcnow()
        if last_work:
            diff = (now - datetime.datetime.fromisoformat(last_work)).total_seconds()
            if diff < WORK_COOLDOWN_M * 60:
                remaining = WORK_COOLDOWN_M * 60 - diff
                m = int(remaining // 60)
                s = int(remaining % 60)
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"⏳ You can work again in **{m}m {s}s**.",
                        colour=COL_LOSE
                    ), ephemeral=True
                )

        jobs = [
            ("🍕 delivered pizzas", "🚗"), ("💻 fixed a server bug", "🖥️"),
            ("📦 sorted warehouse boxes", "📦"), ("🎨 designed a logo", "🎨"),
            ("📞 handled customer calls", "☎️"), ("🔧 repaired equipment", "🔧"),
            ("📝 wrote a report", "📋"), ("🚚 drove a delivery route", "🚛"),
            ("🌐 built a website", "💻"), ("🎵 played at an event", "🎸"),
        ]
        job_desc, job_icon = random.choice(jobs)
        earned = random.randint(WORK_MIN, WORK_MAX)

        await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=earned)
        await self.bot.db.set_work_claimed(interaction.guild.id, interaction.user.id)
        await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, earned, "work", job_desc)

        embed = discord.Embed(
            title=f"{job_icon} Work Complete!",
            description=f"You {job_desc} and earned {_fmt(earned)}.",
            colour=COL_WIN,
            timestamp=now
        )
        embed.set_footer(text=f"Work again in {WORK_COOLDOWN_M} minutes")
        await interaction.response.send_message(embed=embed)

    # ── /deposit / /withdraw ──────────────────────────────────────────────────

    @app_commands.command(name="deposit", description="Deposit coins from wallet to bank")
    @app_commands.describe(amount="Amount to deposit (or 'all')")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        wallet, bank, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        amt = wallet if amount.lower() == "all" else int(amount) if amount.isdigit() else -1
        if amt <= 0 or amt > wallet:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Invalid amount. You have {_fmt(wallet)} in your wallet.", colour=COL_LOSE),
                ephemeral=True
            )
        new = await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=-amt, bank_delta=amt)
        await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, amt, "deposit")
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🏦 Deposited {_fmt(amt)}.\nWallet: {_fmt(new[0])} · Bank: {_fmt(new[1])}",
                colour=COL_INFO
            )
        )

    @app_commands.command(name="withdraw", description="Withdraw coins from bank to wallet")
    @app_commands.describe(amount="Amount to withdraw (or 'all')")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        wallet, bank, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        amt = bank if amount.lower() == "all" else int(amount) if amount.isdigit() else -1
        if amt <= 0 or amt > bank:
            return await interaction.response.send_message(
                embed=discord.Embed(description=f"❌ Invalid amount. Your bank has {_fmt(bank)}.", colour=COL_LOSE),
                ephemeral=True
            )
        new = await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=amt, bank_delta=-amt)
        await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, amt, "withdraw")
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"👛 Withdrew {_fmt(amt)}.\nWallet: {_fmt(new[0])} · Bank: {_fmt(new[1])}",
                colour=COL_INFO
            )
        )

    # ── /transfer ─────────────────────────────────────────────────────────────

    @app_commands.command(name="transfer", description="Send coins to another member")
    @app_commands.describe(member="Recipient", amount="Amount to send")
    async def transfer(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if member == interaction.user:
            return await interaction.response.send_message("❌ Cannot transfer to yourself.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ Cannot transfer to a bot.", ephemeral=True)

        wallet, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        err = _bet_check(amount, wallet)
        if err:
            return await interaction.response.send_message(embed=discord.Embed(description=err, colour=COL_LOSE), ephemeral=True)

        tax     = int(amount * TRANSFER_TAX)
        net     = amount - tax
        await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=-amount)
        await self.bot.db.update_wallet(interaction.guild.id, member.id, wallet_delta=net)
        await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, -amount, "transfer_out", f"To {member}")
        await self.bot.db.log_transaction(interaction.guild.id, member.id, net, "transfer_in", f"From {interaction.user}")

        embed = discord.Embed(
            title="💸 Transfer Sent",
            colour=COL_INFO,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Sent",      value=_fmt(amount), inline=True)
        embed.add_field(name="Tax (5%)",  value=_fmt(tax),    inline=True)
        embed.add_field(name="Received",  value=_fmt(net),    inline=True)
        embed.add_field(name="Recipient", value=member.mention, inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /econleader ───────────────────────────────────────────────────────────

    @app_commands.command(name="econleader", description="View the richest members leaderboard")
    async def econleader(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_economy_leaderboard(interaction.guild.id)
        embed = discord.Embed(
            title=f"{CURRENCY} Economy Leaderboard — {interaction.guild.name}",
            colour=COL_GOLD,
            timestamp=datetime.datetime.utcnow()
        )
        medals = ["🥇", "🥈", "🥉"]
        if not rows:
            embed.description = "No economy data yet."
        else:
            lines = []
            for i, (uid, total, wallet, bank, won) in enumerate(rows):
                m    = interaction.guild.get_member(int(uid))
                name = m.display_name if m else f"ID:{uid}"
                pfx  = medals[i] if i < 3 else f"`{i+1}.`"
                lines.append(f"{pfx} **{name}** — {CURRENCY} {total:,} (💼 {wallet:,} / 🏦 {bank:,})")
            embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    # ── /coinflip ─────────────────────────────────────────────────────────────

    @app_commands.command(name="coinflip", description="Flip a coin — 50/50 chance, 2x payout")
    @app_commands.describe(bet="Amount to bet", choice="Heads or tails")
    @app_commands.choices(choice=[
        app_commands.Choice(name="🪙 Heads", value="heads"),
        app_commands.Choice(name="🪙 Tails", value="tails"),
    ])
    async def coinflip(self, interaction: discord.Interaction, bet: int, choice: str):
        wallet, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        err = _bet_check(bet, wallet)
        if err:
            return await interaction.response.send_message(embed=discord.Embed(description=err, colour=COL_LOSE), ephemeral=True)

        result = random.choice(["heads", "tails"])
        won    = result == choice

        if won:
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=bet, won=bet)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, bet, "coinflip_win")
        else:
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=-bet, lost=bet)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, -bet, "coinflip_loss")

        icon  = "🪙"
        embed = discord.Embed(
            title=f"{icon} Coin Flip — {'WIN!' if won else 'LOSS'}",
            colour=COL_WIN if won else COL_LOSE,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Result",   value=result.title(), inline=True)
        embed.add_field(name="Your pick", value=choice.title(), inline=True)
        embed.add_field(name="Outcome",  value=_fmt(bet) if won else f"-{_fmt(bet)}", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /dice ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="dice", description="Guess the dice roll (1–6) — 5x payout on correct guess")
    @app_commands.describe(bet="Amount to bet", guess="Your guess (1–6)")
    async def dice(self, interaction: discord.Interaction, bet: int, guess: app_commands.Range[int, 1, 6]):
        wallet, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        err = _bet_check(bet, wallet)
        if err:
            return await interaction.response.send_message(embed=discord.Embed(description=err, colour=COL_LOSE), ephemeral=True)

        roll = random.randint(1, 6)
        won  = roll == guess
        faces = ["⚀","⚁","⚂","⚃","⚄","⚅"]

        if won:
            payout = bet * 5
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=payout, won=payout)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, payout, "dice_win")
        else:
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=-bet, lost=bet)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, -bet, "dice_loss")

        embed = discord.Embed(
            title=f"🎲 Dice — {'WIN! 5x!' if won else 'LOSS'}",
            colour=COL_WIN if won else COL_LOSE,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Roll",       value=f"{faces[roll-1]} **{roll}**", inline=True)
        embed.add_field(name="Your guess", value=str(guess), inline=True)
        embed.add_field(name="Outcome",    value=_fmt(bet * 5) if won else f"-{_fmt(bet)}", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /slots ────────────────────────────────────────────────────────────────

    @app_commands.command(name="slots", description="Spin the slot machine!")
    @app_commands.describe(bet="Amount to bet")
    async def slots(self, interaction: discord.Interaction, bet: int):
        wallet, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        err = _bet_check(bet, wallet)
        if err:
            return await interaction.response.send_message(embed=discord.Embed(description=err, colour=COL_LOSE), ephemeral=True)

        reels   = _spin_slots()
        payout  = _slot_payout(reels, bet)
        won     = payout > 0
        profit  = payout - bet

        if won:
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=profit, won=profit)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, profit, "slots_win")
        else:
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=-bet, lost=bet)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, -bet, "slots_loss")

        display = " | ".join(reels)
        embed   = discord.Embed(
            title=f"🎰 Slots — {'WIN!' if won else 'LOSS'}",
            colour=COL_WIN if won else COL_LOSE,
            timestamp=datetime.datetime.utcnow()
        )
        embed.description = f"## {display}"
        if won:
            mult = payout // bet
            embed.add_field(name="Payout",     value=f"{mult}x", inline=True)
            embed.add_field(name="You won",    value=_fmt(payout), inline=True)
            embed.add_field(name="Net profit", value=_fmt(profit), inline=True)
        else:
            embed.add_field(name="No match",   value="Better luck next spin!", inline=False)
            embed.add_field(name="Lost",       value=_fmt(bet), inline=True)

        # Payout table hint
        embed.set_footer(text="💎x3=20x | 7x3=15x | ⭐x3=10x | 🍇x3=8x | 🍒🍒=2x")
        await interaction.response.send_message(embed=embed)

    # ── /blackjack ────────────────────────────────────────────────────────────

    @app_commands.command(name="blackjack", description="Play blackjack against the dealer")
    @app_commands.describe(bet="Amount to bet")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        wallet, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        err = _bet_check(bet, wallet)
        if err:
            return await interaction.response.send_message(embed=discord.Embed(description=err, colour=COL_LOSE), ephemeral=True)

        uid  = interaction.user.id
        deck = _new_deck()
        player  = [deck.pop(), deck.pop()]
        dealer  = [deck.pop(), deck.pop()]
        self._bj_games[uid] = {"deck": deck, "player": player, "dealer": dealer, "bet": bet, "guild": interaction.guild.id}

        pv = _hand_value(player)
        dv = _hand_value(dealer)

        embed = self._bj_embed(player, dealer, bet, pv, hide_dealer=True)

        # Natural blackjack
        if pv == 21:
            del self._bj_games[uid]
            payout = int(bet * 1.5)
            await self.bot.db.update_wallet(interaction.guild.id, uid, wallet_delta=payout, won=payout)
            await self.bot.db.log_transaction(interaction.guild.id, uid, payout, "bj_blackjack")
            embed.title   = "🃏 Blackjack! Natural 21!"
            embed.colour  = COL_WIN
            embed.description = f"You win {_fmt(payout)} (1.5x)!"
            return await interaction.response.send_message(embed=embed)

        view = BlackjackView(uid, self)
        await interaction.response.send_message(embed=embed, view=view)

    def _bj_embed(self, player, dealer, bet, pv, hide_dealer=True, result_text=None):
        dealer_display = f"{_fmt_hand([dealer[0]])} 🂠" if hide_dealer else _fmt_hand(dealer)
        dv_display     = f"{_hand_value([dealer[0]])}+" if hide_dealer else str(_hand_value(dealer))
        embed = discord.Embed(title="🃏 Blackjack", colour=COL_INFO)
        embed.add_field(name=f"Your hand ({pv})",   value=_fmt_hand(player), inline=False)
        embed.add_field(name=f"Dealer ({dv_display})", value=dealer_display, inline=False)
        embed.add_field(name="Bet", value=_fmt(bet), inline=True)
        if result_text:
            embed.description = result_text
        return embed

    async def bj_hit(self, interaction: discord.Interaction):
        uid  = interaction.user.id
        game = self._bj_games.get(uid)
        if not game:
            return await interaction.response.send_message("No active game.", ephemeral=True)

        game["player"].append(game["deck"].pop())
        pv = _hand_value(game["player"])

        if pv > 21:
            del self._bj_games[uid]
            await self.bot.db.update_wallet(game["guild"], uid, wallet_delta=-game["bet"], lost=game["bet"])
            await self.bot.db.log_transaction(game["guild"], uid, -game["bet"], "bj_bust")
            embed = self._bj_embed(game["player"], game["dealer"], game["bet"], pv, hide_dealer=False, result_text=f"💥 Bust! ({pv}) You lose {_fmt(game['bet'])}.")
            embed.colour = COL_LOSE
            return await interaction.response.edit_message(embed=embed, view=None)

        embed = self._bj_embed(game["player"], game["dealer"], game["bet"], pv)
        await interaction.response.edit_message(embed=embed)

    async def bj_stand(self, interaction: discord.Interaction):
        uid  = interaction.user.id
        game = self._bj_games.get(uid)
        if not game:
            return await interaction.response.send_message("No active game.", ephemeral=True)

        del self._bj_games[uid]
        deck   = game["deck"]
        dealer = game["dealer"]
        player = game["player"]
        bet    = game["bet"]

        # Dealer draws to 17
        while _hand_value(dealer) < 17:
            dealer.append(deck.pop())

        pv = _hand_value(player)
        dv = _hand_value(dealer)

        if dv > 21 or pv > dv:
            await self.bot.db.update_wallet(game["guild"], uid, wallet_delta=bet, won=bet)
            await self.bot.db.log_transaction(game["guild"], uid, bet, "bj_win")
            result = f"✅ You win {_fmt(bet)}! (Your {pv} vs Dealer {dv})"
            colour = COL_WIN
        elif pv == dv:
            result = f"🤝 Push — bet returned. (Both {pv})"
            colour = COL_INFO
        else:
            await self.bot.db.update_wallet(game["guild"], uid, wallet_delta=-bet, lost=bet)
            await self.bot.db.log_transaction(game["guild"], uid, -bet, "bj_loss")
            result = f"❌ Dealer wins. You lose {_fmt(bet)}. (Your {pv} vs Dealer {dv})"
            colour = COL_LOSE

        embed = self._bj_embed(player, dealer, bet, pv, hide_dealer=False, result_text=result)
        embed.colour = colour
        await interaction.response.edit_message(embed=embed, view=None)

    async def bj_double(self, interaction: discord.Interaction):
        uid  = interaction.user.id
        game = self._bj_games.get(uid)
        if not game:
            return await interaction.response.send_message("No active game.", ephemeral=True)

        wallet, *_ = await self.bot.db.get_wallet(game["guild"], uid)
        if wallet < game["bet"]:
            return await interaction.response.send_message(
                embed=discord.Embed(description="❌ Not enough in wallet to double down.", colour=COL_LOSE),
                ephemeral=True
            )
        game["bet"] *= 2
        game["player"].append(game["deck"].pop())
        pv = _hand_value(game["player"])

        if pv > 21:
            del self._bj_games[uid]
            await self.bot.db.update_wallet(game["guild"], uid, wallet_delta=-game["bet"], lost=game["bet"])
            await self.bot.db.log_transaction(game["guild"], uid, -game["bet"], "bj_double_bust")
            embed = self._bj_embed(game["player"], game["dealer"], game["bet"], pv, hide_dealer=False)
            embed.colour = COL_LOSE
            embed.description = f"💥 Bust on double! You lose {_fmt(game['bet'])}."
            return await interaction.response.edit_message(embed=embed, view=None)

        # Auto-stand after double
        game_copy = dict(game)
        del self._bj_games[uid]
        class _FakeInteraction:
            pass
        # Process stand logic directly
        deck   = game_copy["deck"]
        dealer = game_copy["dealer"]
        while _hand_value(dealer) < 17:
            dealer.append(deck.pop())
        dv = _hand_value(dealer)
        bet = game_copy["bet"]

        if dv > 21 or pv > dv:
            await self.bot.db.update_wallet(game_copy["guild"], uid, wallet_delta=bet, won=bet)
            await self.bot.db.log_transaction(game_copy["guild"], uid, bet, "bj_double_win")
            result = f"✅ Double down win! +{_fmt(bet)}"
            colour = COL_WIN
        elif pv == dv:
            result = "🤝 Push on double — returned."
            colour = COL_INFO
        else:
            await self.bot.db.update_wallet(game_copy["guild"], uid, wallet_delta=-bet, lost=bet)
            await self.bot.db.log_transaction(game_copy["guild"], uid, -bet, "bj_double_loss")
            result = f"❌ Double down loss. -{_fmt(bet)}"
            colour = COL_LOSE

        embed = self._bj_embed(game_copy["player"], dealer, bet, pv, hide_dealer=False, result_text=result)
        embed.colour = colour
        await interaction.response.edit_message(embed=embed, view=None)

    # ── /roulette ─────────────────────────────────────────────────────────────

    @app_commands.command(name="roulette", description="Play roulette — multiple bet types available")
    @app_commands.describe(
        bet="Amount to bet",
        bet_type="What to bet on",
        number="Specific number 0–36 (only for 'number' bet type)"
    )
    @app_commands.choices(bet_type=[
        app_commands.Choice(name="🔴 Red",        value="red"),
        app_commands.Choice(name="⚫ Black",       value="black"),
        app_commands.Choice(name="🟢 Green (0)",  value="green"),
        app_commands.Choice(name="Even",           value="even"),
        app_commands.Choice(name="Odd",            value="odd"),
        app_commands.Choice(name="Low (1–18)",     value="low"),
        app_commands.Choice(name="High (19–36)",   value="high"),
        app_commands.Choice(name="🎯 Number (35x)", value="number"),
    ])
    async def roulette(self, interaction: discord.Interaction, bet: int, bet_type: str, number: app_commands.Range[int, 0, 36] = None):
        wallet, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        err = _bet_check(bet, wallet)
        if err:
            return await interaction.response.send_message(embed=discord.Embed(description=err, colour=COL_LOSE), ephemeral=True)

        if bet_type == "number" and number is None:
            return await interaction.response.send_message("❌ Specify a number (0–36) for number bets.", ephemeral=True)

        RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        spin     = random.randint(0, 36)
        colour_icon = "🟢" if spin == 0 else ("🔴" if spin in RED_NUMS else "⚫")

        won, multiplier = False, 0
        if bet_type == "number":
            won = spin == number; multiplier = 35
        elif bet_type == "red":
            won = spin in RED_NUMS; multiplier = 1
        elif bet_type == "black":
            won = spin not in RED_NUMS and spin != 0; multiplier = 1
        elif bet_type == "green":
            won = spin == 0; multiplier = 17
        elif bet_type == "even":
            won = spin != 0 and spin % 2 == 0; multiplier = 1
        elif bet_type == "odd":
            won = spin % 2 == 1; multiplier = 1
        elif bet_type == "low":
            won = 1 <= spin <= 18; multiplier = 1
        elif bet_type == "high":
            won = 19 <= spin <= 36; multiplier = 1

        payout = bet * multiplier if won else 0
        if won:
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=payout, won=payout)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, payout, "roulette_win")
        else:
            await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=-bet, lost=bet)
            await self.bot.db.log_transaction(interaction.guild.id, interaction.user.id, -bet, "roulette_loss")

        embed = discord.Embed(
            title=f"🎡 Roulette — {'WIN!' if won else 'LOSS'}",
            colour=COL_WIN if won else COL_LOSE,
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Spin result", value=f"{colour_icon} **{spin}**", inline=True)
        embed.add_field(name="Your bet",    value=bet_type.title(), inline=True)
        embed.add_field(name="Outcome",     value=_fmt(payout) if won else f"-{_fmt(bet)}", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /crash ────────────────────────────────────────────────────────────────

    @app_commands.command(name="crash", description="Bet on a rising multiplier — cash out before it crashes!")
    @app_commands.describe(bet="Amount to bet")
    async def crash(self, interaction: discord.Interaction, bet: int):
        wallet, *_ = await self.bot.db.get_wallet(interaction.guild.id, interaction.user.id)
        err = _bet_check(bet, wallet)
        if err:
            return await interaction.response.send_message(embed=discord.Embed(description=err, colour=COL_LOSE), ephemeral=True)

        # Generate crash point using exponential distribution
        crash_at = round(max(1.01, random.expovariate(0.4) + 1.0), 2)
        view     = CrashView(interaction.user.id, bet, self)

        embed = discord.Embed(
            title="🚀 Crash — Game Starting!",
            description=(
                f"Bet: {_fmt(bet)}\n\n"
                f"**Multiplier: 1.00x** 🚀\n\n"
                f"Click **Cash Out** before the rocket crashes!"
            ),
            colour=COL_GOLD,
            timestamp=datetime.datetime.utcnow()
        )
        await self.bot.db.update_wallet(interaction.guild.id, interaction.user.id, wallet_delta=-bet)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()

        # Animate multiplier
        mult = 1.0
        step = random.uniform(0.08, 0.18)
        while mult < crash_at and not view.cashed:
            await asyncio.sleep(1.2)
            mult = round(mult + step + random.uniform(0, 0.05), 2)
            view.multiplier = mult
            if mult >= crash_at or view.cashed:
                break
            colour = COL_WIN if mult < crash_at * 0.6 else COL_GOLD
            try:
                embed.description = (
                    f"Bet: {_fmt(bet)}\n\n"
                    f"**Multiplier: {mult:.2f}x** 🚀\n\n"
                    f"Click **Cash Out** before the rocket crashes!"
                )
                embed.colour = colour
                await msg.edit(embed=embed, view=view)
            except Exception:
                break

        if not view.cashed:
            view.children[0].disabled = True
            await self.bot.db.log_transaction(
                interaction.guild.id, interaction.user.id,
                -bet, "crash_loss", f"Crashed at {crash_at:.2f}x"
            )
            crash_embed = discord.Embed(
                title=f"💥 Crashed at {crash_at:.2f}x!",
                description=f"You lost {_fmt(bet)}. Better luck next time!",
                colour=COL_LOSE
            )
            try:
                await msg.edit(embed=crash_embed, view=view)
            except Exception:
                pass

    # ── Admin commands ────────────────────────────────────────────────────────

    @app_commands.command(name="givemoney", description="Give coins to a member (admin)")
    @app_commands.describe(member="Target", amount="Amount to give")
    async def givemoney(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        new = await self.bot.db.update_wallet(interaction.guild.id, member.id, wallet_delta=amount)
        await self.bot.db.log_transaction(interaction.guild.id, member.id, amount, "admin_give", f"By {interaction.user}")
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Gave {_fmt(amount)} to {member.mention}. New wallet: {_fmt(new[0])}", colour=COL_WIN),
            ephemeral=True
        )

    @app_commands.command(name="takemoney", description="Remove coins from a member (admin)")
    @app_commands.describe(member="Target", amount="Amount to remove")
    async def takemoney(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        new = await self.bot.db.update_wallet(interaction.guild.id, member.id, wallet_delta=-amount, lost=amount)
        await self.bot.db.log_transaction(interaction.guild.id, member.id, -amount, "admin_take", f"By {interaction.user}")
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✅ Took {_fmt(amount)} from {member.mention}. New wallet: {_fmt(new[0])}", colour=COL_INFO),
            ephemeral=True
        )


class BlackjackView(discord.ui.View):
    def __init__(self, user_id: int, cog):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.cog     = cog

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary,  emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your game!", ephemeral=True)
        await self.cog.bj_hit(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your game!", ephemeral=True)
        await self.cog.bj_stand(interaction)
        self.stop()

    @discord.ui.button(label="Double", style=discord.ButtonStyle.success, emoji="💰")
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your game!", ephemeral=True)
        await self.cog.bj_double(interaction)
        self.stop()


async def setup(bot):
    await bot.add_cog(Gambling(bot))
