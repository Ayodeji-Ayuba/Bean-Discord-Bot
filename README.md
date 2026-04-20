# Discord Portfolio Bot
###

---

## Quick Start

**1. Install dependencies**
```
pip install -r requirements.txt
```

**2. Configure your token**
```
cp .env.example .env
# Open .env and paste your Discord bot token
```

**3. Enable Privileged Intents** in the Discord Developer Portal → Bot:
- ✅ Server Members Intent
- ✅ Message Content Intent
- ✅ Presence Intent (for screen share detection)

**4. Invite the bot** with these permissions:
- Administrator (recommended for full feature access), OR
- Manage Roles, Manage Channels, Ban Members, Kick Members,
  Moderate Members, Send Messages, Read Message History,
  Manage Messages, Embed Links, Attach Files

**5. Run the bot**
```
python bot.py
```

---

## Project Structure

```
discord_bot/
├── bot.py                   Entry point — loads all 15 cogs
├── database.py              Async SQLite handler (all tables + queries)
├── requirements.txt
├── .env.example             Rename to .env and add your token
├── data/
│   └── bot.db               Auto-created SQLite database
└── cogs/
    ├── moderation.py        Modules 1 & 2 — warn, ban, kick, mute
    ├── automod.py           Module 3  — anti-spam, anti-raid, filters
    ├── onboarding.py        Module 4  — roles, welcome, XP/leveling
    ├── verification.py      Module 5  — button/CAPTCHA verification gate
    ├── attendance.py        Module 6  — clock-in/out, session tracking
    ├── leave.py             Module 7  — leave request management
    ├── kpi.py               Module 8  — KPI logging, performance ratings
    ├── compliance.py        Module 9  — compliance rules & incident tracking
    ├── crypto.py            Module 10 — live crypto prices, alerts, watchlist
    ├── webhooks.py          Module 11 — outgoing webhooks, embed builder
    ├── dbtools.py           Module 12 — data export, purge, server stats
    ├── gambling.py          Module 13 — economy system + 6 casino games
    ├── screenshare.py       Module 14 — screen share verification
    └── infra.py             Module 15 — server setup, security audit, health
```

---

## Channels to Create

| Channel name       | Purpose                                      |
|--------------------|----------------------------------------------|
| `#staff-chat`      | All mod logs and bot alerts post here        |
| `#welcome`         | Join announcements                           |
| `#verify`          | Run `/setupverify` here                      |
| `#quarantine`      | Warned/quarantined members land here         |
| `#attendance-log`  | Clock-in/out feed                            |
| `#leave-requests`  | Leave request embeds with approve/deny       |
| `#crypto-updates`  | Market update embeds via `/marketupdate`     |
| `#ss-verify-log`   | Screen share verification requests           |
| `#announcements`   | Used by `/announce` and `/embedbuilder`      |

> Run `/channelsetup` to auto-create all of these at once.

---

## Phase 1 — Moderation

### Module 1 — Warn System (Wickbot-style)

**`/warn <member> <reason>`**

What happens automatically:
1. Warning saved to database with auto-incrementing ID
2. Member receives the `Quarantined` role — locked out of all channels
3. Member gains read-only access to `#quarantine`
4. Bot posts an "Accept Warning" button in `#quarantine` (only the warned user can click it)
5. Bot DMs the user their warning details
6. Rich embed posted to `#staff-chat` with user, reason, moderator, and total warn count
7. When the user clicks **"I accept this warning"**:
   - `Quarantined` role is removed
   - `#staff-chat` is updated with an acknowledgement
   - Warning is marked as cleared in the database

| Command               | Description                              |
|-----------------------|------------------------------------------|
| `/warn <member> <reason>` | Issue a warning and quarantine the user |
| `/warnings <member>`  | View full warning history                |
| `/clearwarn <id>`     | Manually clear a warning by ID          |

---

### Module 2 — Core Moderation

| Command                              | Permission      | Description                          |
|--------------------------------------|-----------------|--------------------------------------|
| `/ban <member> [reason] [days]`      | Ban Members     | Ban with DM + staff log              |
| `/kick <member> [reason]`            | Kick Members    | Kick with DM + staff log             |
| `/mute <member> <minutes> [reason]`  | Manage Messages | Discord timeout (1–40320 min)        |
| `/unmute <member> [reason]`          | Manage Messages | Remove timeout early                 |
| `/modlogs [member]`                  | Manage Messages | View recent mod action history       |

All actions: DM the user, log to `#staff-chat`, save to database.

---

### Module 3 — AutoMod

Fully automatic — no setup required.

| Trigger                         | Action                                          |
|---------------------------------|-------------------------------------------------|
| 5+ messages in 5 seconds        | Delete messages, auto-mute 10 min, staff alert |
| 5+ mentions in one message      | Delete message, auto-mute 5 min                |
| Discord invite link posted      | Delete, warn in channel, staff alert            |
| URL outside whitelisted channels| Delete, staff alert                             |
| 70%+ caps in message (10+ chars)| Delete, warn in channel                        |
| 10+ joins in 10 seconds         | Full server lockdown, staff alert, auto-lift 5 min |
| Account < 7 days old joins      | Staff alert (no auto-action)                   |

Manual admin commands: `/lockdown`, `/unlockdown`

Customise thresholds in the config block at the top of `cogs/automod.py`.

---

## Phase 2 — Automation & Onboarding

### Module 4 — Onboarding, Roles & Leveling

- Auto-assigns `Member` role to every new joiner
- Posts a welcome embed in `#welcome` and DMs the user
- Logs joins/leaves to `#staff-chat`
- XP system: 15–25 XP per message, 60-second cooldown
- Level-up announcements with progress bar
- Role rewards at levels 5, 10, 20, 50 (auto-creates roles if missing)

| Command                  | Description                                   |
|--------------------------|-----------------------------------------------|
| `/rank [member]`         | View XP rank card and progress bar            |
| `/leaderboard`           | Top 10 XP leaderboard                         |
| `/givexp <member> <amt>` | Manually award XP (admin)                     |

---

### Module 5 — Verification

Admin runs `/setupverify` once → bot posts a panel in `#verify`.

| Mode         | How it works                                        |
|--------------|-----------------------------------------------------|
| Button only  | One click → role assigned                          |
| CAPTCHA      | Solve a simple math question via modal popup       |
| Age gate     | Type "I am 18 or older" to confirm (optional)     |

Toggle modes at the top of `cogs/verification.py`.

| Command              | Description                                  |
|----------------------|----------------------------------------------|
| `/setupverify`       | Post the verification panel (admin)          |
| `/unverify <member>` | Remove verification from a member (mod)      |
| `/verifyinfo <member>`| Check verification status (mod)             |

---

### Module 6 — Attendance & Clock-in/Out

| Command                    | Description                                    |
|----------------------------|------------------------------------------------|
| `/clockin [note]`          | Start an attendance session                    |
| `/clockout`                | End your session, logs exact duration          |
| `/session`                 | Check current session elapsed time            |
| `/attendance [member]`     | Personal session history with total hours      |
| `/report [days]`           | Server-wide hours leaderboard (mod)            |
| `/staffreport [days]`      | Export attendance as `.txt` file (admin)       |

All sessions logged to `#attendance-log`.

---

## Phase 3 — Workforce & HR Tools

### Module 7 — Leave Management

| Command                           | Description                               |
|-----------------------------------|-------------------------------------------|
| `/leaverequest <type> <start> <end> [reason]` | Submit a leave request     |
| `/myleaves`                       | View your leave history                   |
| `/pendingleaves`                  | View all pending requests (mod)           |
| `/reviewleave <id> <decision>`    | Approve or deny by ID (mod)               |
| `/leavestats`                     | Server-wide leave statistics (admin)      |

Leave types: annual 🏖️, sick 🤒, personal 🧍, emergency 🚨, maternity 👶, paternity 👨‍👧, unpaid 💸

Requests are posted to `#leave-requests` with interactive **Approve / Deny** buttons.
The requester is DM'd automatically when their request is reviewed.

---

### Module 8 — KPI Analytics & Performance Ratings

| Command                                   | Description                                    |
|-------------------------------------------|------------------------------------------------|
| `/logkpi <member> <metric> <value> [target]` | Log a KPI metric for a member (mod)        |
| `/kpi [member] [period]`                  | View KPI entries (default: current month)      |
| `/kpireport [period]`                     | Aggregated team KPI summary (mod)              |
| `/rate <member> <rating> <category>`      | Submit 1–5 star performance rating (mod)       |
| `/myratings [period]`                     | View your performance rating card              |
| `/perfoverview <member> [period]`         | Full performance card: ratings + KPI + hours   |
| `/teamstats [period]`                     | Team-wide top performers (admin)               |

Available metrics: sales, tasks_completed, tickets_resolved, response_time_min,
attendance_rate, quality_score, customer_satisfaction, revenue, calls_made,
deals_closed, errors_reported, projects_delivered

Rating categories: teamwork, communication, quality, punctuality, initiative

---

### Module 9 — Compliance Monitoring

| Command                       | Description                                         |
|-------------------------------|-----------------------------------------------------|
| `/addrule <name> <desc> <severity>` | Define a compliance rule (admin)            |
| `/rules`                      | List all active compliance rules                    |
| `/incident <member> <rule> <desc> <severity>` | Report a breach (mod)           |
| `/incidents [member] [status]`| View open/resolved incidents (mod)                  |
| `/resolveincident <id>`       | Mark an incident as resolved (mod)                  |
| `/compliancereport`           | Full dashboard: open counts, repeat offenders (admin)|
| `/memberaudit <member>`       | Risk-scored audit: incidents + warnings + mod actions|

Severity levels: low 🟢, medium 🟡, high 🟠, critical 🔴

Critical incidents: auto-mute the member + ping admins in `#staff-chat`.

`/memberaudit` produces a risk score: 🟢 Compliant → 🟡 Low → 🟠 Medium → 🔴 High Risk

---

## Phase 4 — Integrations & APIs

### Module 10 — Cryptocurrency Integration

Uses the CoinGecko public API — **no API key required**.

| Command                              | Description                                      |
|--------------------------------------|--------------------------------------------------|
| `/price <symbol> [currency]`         | Live price with 24h change, market cap, volume   |
| `/crypto <symbol>`                   | Deep detail: ATH, ATL, 1h/24h/7d changes        |
| `/convert <amount> <coin> <currency>`| Real-time crypto-to-fiat conversion              |
| `/watchlist`                         | Server watchlist with live prices                |
| `/addwatch <symbol>`                 | Add coin to server watchlist (mod)               |
| `/removewatch <symbol>`              | Remove from watchlist (mod)                      |
| `/marketupdate [channel]`            | Post top-10 market summary embed (mod)           |
| `/setalert <symbol> <price> <direction>` | Set a price alert — DM when triggered       |
| `/myalerts`                          | View your active alerts                          |
| `/removealert <id>`                  | Cancel an alert                                  |

Supported currencies: USD, EUR, GBP, NGN, JPY, CAD, AUD, CHF

Background task checks all alerts every **5 minutes** automatically.

---

### Module 11 — Webhooks & External Dashboards

| Command                              | Description                                       |
|--------------------------------------|---------------------------------------------------|
| `/registerwebhook <name> <url> <event>` | Register an outgoing webhook URL (admin)       |
| `/listwebhooks`                      | List all registered webhooks (admin)              |
| `/togglewebhook <id> <true/false>`   | Enable or disable a webhook (admin)               |
| `/testwebhook <id>`                  | Send a live test ping to a webhook (admin)        |
| `/postwebhook <id> <json>`           | Manually fire a webhook with custom JSON (admin)  |
| `/dashboardstatus`                   | Overview of all integrations + health (admin)     |
| `/embedbuilder`                      | Modal form to build and post rich embeds (mod)    |
| `/announce <channel> <title> <msg>`  | Post a formatted announcement with role ping (mod)|

Webhook event triggers: `mod_action`, `member_join`, `member_leave`,
`level_up`, `compliance`, `leave_request`, `custom`

Payloads are delivered as JSON POST requests to any URL (Zapier, n8n, your API, etc.)

---

### Module 12 — Database Tools

| Command                    | Description                                          |
|----------------------------|------------------------------------------------------|
| `/serverstats`             | Full server analytics dashboard (mod)                |
| `/exportdata <table>`      | Export any data table as `.csv` (admin)              |
| `/purge <amount> [member] [contains]` | Bulk-delete messages with filters (mod)  |
| `/usersummary <member>`    | Complete profile across all bot systems (mod)        |
| `/botinfo`                 | Uptime, guild count, cog list, command count         |
| `/dbstats`                 | Row counts per database table (admin)                |
| `/cleardata <member> CONFIRM` | GDPR-compliant full data erase (admin)            |
| `/snapshot`                | Export a text file snapshot of current server stats  |

Exportable tables: warnings, mod_logs, attendance, leave_requests,
kpi_entries, performance_ratings, compliance_incidents, levels

---

## Phase 5 — Advanced Features

### Module 13 — Economy & Gambling

**Economy commands:**

| Command                    | Description                                          |
|----------------------------|------------------------------------------------------|
| `/balance [member]`        | View wallet + bank balance, total won/lost           |
| `/daily`                   | Claim daily reward (streak bonuses up to 7x)         |
| `/work`                    | Earn coins every 30 min with random job flavour      |
| `/deposit <amount\|all>`   | Move coins from wallet to bank (safe storage)        |
| `/withdraw <amount\|all>`  | Move coins from bank to wallet                       |
| `/transfer <member> <amt>` | Send coins to another member (5% tax)                |
| `/econleader`              | Richest members leaderboard                          |

Admin: `/givemoney`, `/takemoney`

Note: You can only gamble from your **wallet**. Bank balance is always safe.

**Gambling games:**

| Command       | Description                                            |
|---------------|--------------------------------------------------------|
| `/coinflip`   | 50/50 heads or tails — 2x payout                      |
| `/dice`       | Guess the roll (1–6) — 5x payout on correct guess     |
| `/slots`      | 3-reel slot machine — up to 20x payout (💎💎💎)        |
| `/blackjack`  | Full game with Hit, Stand, Double Down buttons         |
| `/roulette`   | Red/black/green/even/odd/low/high/specific number      |
| `/crash`      | Live animated multiplier — cash out before it crashes  |

Slots payout table: 💎x3=20x · 7️⃣x3=15x · ⭐x3=10x · 🍇x3=8x · 🍒x2=2x

---

### Module 14 — Screen Share Verification

Members' screen sharing sessions can be verified by moderators before they're
trusted with access to specific content or roles.

| Command                  | Description                                         |
|--------------------------|-----------------------------------------------------|
| `/setupss`               | Create log channel + role with correct permissions (admin) |
| `/ssverify [note]`       | Manually request a verification session             |
| `/ssapprove <id> [note]` | Approve a session, assign Screen Verified role (mod)|
| `/ssreject <id> [reason]`| Reject a session with reason (mod)                  |
| `/pendingss`             | View all pending verification requests (mod)        |
| `/sshistory <member>`    | View screen share history for a member (mod)        |
| `/ssstats`               | Server-wide screen share statistics (admin)         |

**Auto-detection:** When a member starts screen sharing in a voice channel,
the bot automatically posts a verification request to `#ss-verify-log` with
Approve/Deny buttons. No command needed from the member.

---

### Module 15 — Infrastructure & Scalability

| Command                          | Description                                        |
|----------------------------------|----------------------------------------------------|
| `/healthcheck`                   | Latency, uptime, memory, DB size, guild count      |
| `/setconfig <key> <value>`       | Store a server config value (admin)                |
| `/getconfig`                     | View all server config values (admin)              |
| `/rolesetup`                     | Bulk-create 12-role standard hierarchy (admin)     |
| `/channelsetup`                  | Bulk-create all standard channels + categories (admin)|
| `/slowmode <seconds> [channel]`  | Set or remove slowmode on a channel (mod)          |
| `/lock [channel] [reason]`       | Lock a channel from member messages (mod)          |
| `/unlock [channel]`              | Unlock a channel (mod)                             |
| `/nuke [channel] [reason]`       | Clone + delete channel to wipe all messages (admin)|
| `/permissions <member> [channel]`| Audit a member's effective permissions (mod)       |
| `/roleinfo <role>`               | Detailed role info + member sample (mod)           |
| `/serveraudit`                   | Graded security audit report (admin)               |
| `/cleanup [limit] [channel]`     | Remove bot messages from a channel (mod)           |

`/serveraudit` checks: 2FA requirement, verification level, @everyone permissions,
bot administrator grants, staff channel privacy, new account member volume.
Returns a grade from A to D with actionable findings.

`/rolesetup` creates: Owner, Admin, Moderator, VIP, Legend, Veteran, Regular,
Member, 18+, Bot, Muted, Quarantined — with correct colours and hoist settings.

Background task: logs latency + member count to the database every 10 minutes.

---

## Database Tables

| Table                  | Phase | Contents                                      |
|------------------------|-------|-----------------------------------------------|
| warnings               | 1     | Warning history per user                      |
| mod_logs               | 1     | All mod actions (ban, kick, mute, warn)       |
| spam_track             | 1     | Per-user message rate for anti-spam           |
| levels                 | 2     | XP, level, message count per user             |
| verified_users         | 2     | Verification status + method                  |
| attendance             | 2     | Clock-in/out sessions with duration           |
| leave_requests         | 3     | Leave requests with status + reviewer         |
| kpi_entries            | 3     | KPI metric logs per user per period           |
| performance_ratings    | 3     | Star ratings per category per user            |
| compliance_rules       | 3     | Defined compliance rules with severity        |
| compliance_incidents   | 3     | Incidents filed against members               |
| crypto_alerts          | 4     | Price alerts per user per coin                |
| crypto_watchlist       | 4     | Server-wide coin watchlist                    |
| webhooks               | 4     | Registered outgoing webhook URLs              |
| webhook_log            | 4     | Delivery history per webhook                  |
| economy                | 5     | Wallet, bank, won, lost, streak per user      |
| transactions           | 5     | Full transaction ledger                       |
| screenshare_sessions   | 5     | SS verification sessions with status          |
| server_config          | 5     | Key-value config store per guild              |
| health_log             | 5     | Bot health metrics over time                  |

---

## Requirements

```
discord.py>=2.3.0
aiosqlite>=0.19.0
python-dotenv>=1.0.0
aiohttp>=3.9.0
psutil>=5.9.0    # optional — enables memory/CPU in /healthcheck
```

---

## Module Summary

| # | Module       | Cog               | Key commands                                      |
|---|--------------|-------------------|---------------------------------------------------|
| 1 | Warn system  | moderation.py     | /warn /warnings /clearwarn                        |
| 2 | Core mod     | moderation.py     | /ban /kick /mute /unmute /modlogs                 |
| 3 | AutoMod      | automod.py        | /lockdown /unlockdown (rest is automatic)         |
| 4 | Onboarding   | onboarding.py     | /rank /leaderboard /givexp                        |
| 5 | Verification | verification.py   | /setupverify /unverify /verifyinfo                |
| 6 | Attendance   | attendance.py     | /clockin /clockout /session /report               |
| 7 | Leave        | leave.py          | /leaverequest /reviewleave /leavestats            |
| 8 | KPI          | kpi.py            | /logkpi /rate /perfoverview /teamstats            |
| 9 | Compliance   | compliance.py     | /incident /compliancereport /memberaudit          |
|10 | Crypto       | crypto.py         | /price /crypto /convert /setalert /watchlist      |
|11 | Webhooks     | webhooks.py       | /registerwebhook /testwebhook /announce           |
|12 | DB Tools     | dbtools.py        | /exportdata /purge /usersummary /serveraudit      |
|13 | Economy      | gambling.py       | /balance /daily /work /slots /blackjack /crash    |
|14 | Screen Share | screenshare.py    | /setupss /ssapprove /ssreject /pendingss          |
|15 | Infra        | infra.py          | /healthcheck /rolesetup /channelsetup /serveraudit|
