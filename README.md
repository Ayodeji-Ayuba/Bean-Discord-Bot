# Bean Discord Bot 

## Project Structure

```
discord_bot/
├── bot.py                  # Entry point
├── database.py             # SQLite async database handler
├── requirements.txt
├── .env.example            # Rename to .env and add your token
├── data/                   # Auto-created; stores bot.db
└── cogs/
    ├── moderation.py       # Modules 1 & 2
    └── automod.py          # Module 3
```

---

## Setup

1. Install dependencies
   pip install -r requirements.txt

2. Configure environment
   cp .env.example .env
   (Edit .env and paste your bot token)

3. Create required Discord channels and roles:

   #staff-chat   — All mod logs are posted here
   #quarantine   — Warned users are sent here
   Quarantined   — Role that locks user out of all channels
   (The bot will auto-create the Quarantined role if missing.)

4. Bot permissions required in Developer Portal:
   - Manage Roles
   - Manage Channels
   - Kick Members
   - Ban Members
   - Moderate Members (for timeouts)
   - Send Messages / Read Message History / Manage Messages
   Also enable: Server Members Intent + Message Content Intent

5. Run:
   python bot.py

---

## Module 1 — Warn System (Wickbot-style)

/warn <member> <reason>

What happens automatically:
  1. Warning saved to database with auto-incrementing ID
  2. User gets the Quarantined role — locked out of all channels
  3. User gains read access to #quarantine only
  4. Bot posts an accept button in #quarantine for the user
  5. Bot DMs the user their warning details
  6. Full embed posted to #staff-chat (user, reason, mod, warn count)
  7. When user clicks "I accept this warning":
     - Quarantined role is removed
     - #staff-chat updated with acknowledgement
     - Warning marked as cleared in database

/warnings <member>  — View full warning history
/clearwarn <id>     — Manually clear a warning by ID

---

## Module 2 — Core Moderation

/ban <member> [reason] [delete_days]  — Ban with DM + staff log
/kick <member> [reason]               — Kick with DM + staff log
/mute <member> <duration> [reason]    — Discord timeout (1-40320 min)
/unmute <member> [reason]             — Remove timeout early
/modlogs [member]                     — View recent mod action history

All actions are logged to #staff-chat and saved to the database.

---

## Module 3 — AutoMod

All fully automatic — no commands needed.

  5+ messages in 5s         -> Auto-mute 10 min + delete messages
  5+ mentions in one msg    -> Delete + auto-mute 5 min
  Discord invite link       -> Delete + warn in channel + log
  URL outside safe channels -> Delete + log
  70%+ caps (10+ chars)     -> Delete + warn in channel
  10+ joins in 10s          -> Full server lockdown + staff alert

Manual admin commands:
  /lockdown   — Manually engage raid lockdown
  /unlockdown — Manually lift lockdown

Customise thresholds in the config block at the top of cogs/automod.py.

---

## Database

Stored in data/bot.db (SQLite). Tables:
  warnings   — warning history per user per guild
  mod_logs   — all mod actions (bans, kicks, mutes, warns)
  spam_track — per-user message rate tracking

---

## Phase 2 (Next)

  Module 4: Role automation, onboarding, leveling system
  Module 5: Verification system (button / CAPTCHA)
  Module 6: Attendance tracking and clock-in/clock-out
