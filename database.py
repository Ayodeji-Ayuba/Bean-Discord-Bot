import aiosqlite
import datetime
import os

DB_PATH = "data/bot.db"

class Database:
    def __init__(self):
        self.db_path = DB_PATH

    async def init(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    mod_id      TEXT NOT NULL,
                    reason      TEXT NOT NULL,
                    active      INTEGER DEFAULT 1,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS mod_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    mod_id      TEXT NOT NULL,
                    reason      TEXT,
                    duration    TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS spam_track (
                    guild_id      TEXT NOT NULL,
                    user_id       TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0,
                    last_reset    TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            # Phase 2 ─────────────────────────────────────────────────────────
            await db.execute("""
                CREATE TABLE IF NOT EXISTS levels (
                    guild_id   TEXT NOT NULL,
                    user_id    TEXT NOT NULL,
                    xp         INTEGER DEFAULT 0,
                    level      INTEGER DEFAULT 0,
                    total_msgs INTEGER DEFAULT 0,
                    last_xp_at TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS verified_users (
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    method      TEXT DEFAULT 'button',
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id   TEXT NOT NULL,
                    user_id    TEXT NOT NULL,
                    clock_in   TEXT NOT NULL,
                    clock_out  TEXT,
                    duration_s INTEGER,
                    note       TEXT
                )
            """)
            await db.commit()
        await self._ensure_phase3()
        await self._ensure_phase4()
        await self._ensure_phase5()
        print("   Database initialised ✓")

    # ── Warnings ──────────────────────────────────────────────────────────────

    async def add_warning(self, guild_id, user_id, mod_id, reason):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO warnings (guild_id,user_id,mod_id,reason,created_at) VALUES (?,?,?,?,?)",
                (str(guild_id), str(user_id), str(mod_id), reason, now)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            row = await cursor.fetchone()
            return row[0]

    async def get_warnings(self, guild_id, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id,mod_id,reason,created_at,active FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC",
                (str(guild_id), str(user_id))
            )
            return await cursor.fetchall()

    async def count_active_warnings(self, guild_id, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=? AND active=1",
                (str(guild_id), str(user_id))
            )
            row = await cursor.fetchone()
            return row[0]

    async def clear_warning(self, warning_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE warnings SET active=0 WHERE id=?", (warning_id,))
            await db.commit()

    # ── Mod Logs ──────────────────────────────────────────────────────────────

    async def log_action(self, guild_id, action, user_id, mod_id, reason=None, duration=None):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO mod_logs (guild_id,action,user_id,mod_id,reason,duration,created_at) VALUES (?,?,?,?,?,?,?)",
                (str(guild_id), action, str(user_id), str(mod_id), reason, duration, now)
            )
            await db.commit()

    async def get_mod_logs(self, guild_id, user_id=None, limit=20):
        async with aiosqlite.connect(self.db_path) as db:
            if user_id:
                cursor = await db.execute(
                    "SELECT action,user_id,mod_id,reason,duration,created_at FROM mod_logs WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                    (str(guild_id), str(user_id), limit)
                )
            else:
                cursor = await db.execute(
                    "SELECT action,user_id,mod_id,reason,duration,created_at FROM mod_logs WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                    (str(guild_id), limit)
                )
            return await cursor.fetchall()

    # ── Spam Tracking ─────────────────────────────────────────────────────────

    async def increment_message_count(self, guild_id, user_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO spam_track (guild_id,user_id,message_count,last_reset)
                VALUES (?,?,1,?)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET message_count = message_count + 1
            """, (str(guild_id), str(user_id), now))
            await db.commit()
            cursor = await db.execute(
                "SELECT message_count FROM spam_track WHERE guild_id=? AND user_id=?",
                (str(guild_id), str(user_id))
            )
            row = await cursor.fetchone()
            return row[0] if row else 1

    async def reset_message_count(self, guild_id, user_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE spam_track SET message_count=0,last_reset=? WHERE guild_id=? AND user_id=?",
                (now, str(guild_id), str(user_id))
            )
            await db.commit()

    # ── Leveling ──────────────────────────────────────────────────────────────

    async def add_xp(self, guild_id, user_id, amount):
        """Add XP. Returns (new_xp, new_level, leveled_up)."""
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO levels (guild_id,user_id,xp,level,total_msgs,last_xp_at)
                VALUES (?,?,?,0,1,?)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET
                    xp=xp+?, total_msgs=total_msgs+1, last_xp_at=?
            """, (str(guild_id), str(user_id), amount, now, amount, now))
            await db.commit()
            cursor = await db.execute(
                "SELECT xp, level FROM levels WHERE guild_id=? AND user_id=?",
                (str(guild_id), str(user_id))
            )
            xp, level = await cursor.fetchone()
            new_level = int((xp / 100) ** 0.5)
            leveled_up = new_level > level
            if leveled_up:
                await db.execute(
                    "UPDATE levels SET level=? WHERE guild_id=? AND user_id=?",
                    (new_level, str(guild_id), str(user_id))
                )
                await db.commit()
            return xp, new_level, leveled_up

    async def get_level_data(self, guild_id, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT xp, level, total_msgs FROM levels WHERE guild_id=? AND user_id=?",
                (str(guild_id), str(user_id))
            )
            return await cursor.fetchone()

    async def get_leaderboard(self, guild_id, limit=10):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT user_id, xp, level, total_msgs FROM levels WHERE guild_id=? ORDER BY xp DESC LIMIT ?",
                (str(guild_id), limit)
            )
            return await cursor.fetchall()

    # ── Verification ──────────────────────────────────────────────────────────

    async def mark_verified(self, guild_id, user_id, method="button"):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO verified_users (guild_id,user_id,verified_at,method)
                VALUES (?,?,?,?)
            """, (str(guild_id), str(user_id), now, method))
            await db.commit()

    async def is_verified(self, guild_id, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM verified_users WHERE guild_id=? AND user_id=?",
                (str(guild_id), str(user_id))
            )
            return await cursor.fetchone() is not None

    # ── Attendance ────────────────────────────────────────────────────────────

    async def clock_in(self, guild_id, user_id, note=None):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM attendance WHERE guild_id=? AND user_id=? AND clock_out IS NULL",
                (str(guild_id), str(user_id))
            )
            if await cursor.fetchone():
                return None  # already clocked in
            await db.execute(
                "INSERT INTO attendance (guild_id,user_id,clock_in,note) VALUES (?,?,?,?)",
                (str(guild_id), str(user_id), now, note)
            )
            await db.commit()
            return now

    async def clock_out(self, guild_id, user_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, clock_in FROM attendance WHERE guild_id=? AND user_id=? AND clock_out IS NULL",
                (str(guild_id), str(user_id))
            )
            row = await cursor.fetchone()
            if not row:
                return None, None
            entry_id, clock_in_str = row
            clock_in_dt = datetime.datetime.fromisoformat(clock_in_str)
            duration_s = int((datetime.datetime.utcnow() - clock_in_dt).total_seconds())
            await db.execute(
                "UPDATE attendance SET clock_out=?, duration_s=? WHERE id=?",
                (now, duration_s, entry_id)
            )
            await db.commit()
            return clock_in_str, duration_s

    async def get_active_session(self, guild_id, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT clock_in, note FROM attendance WHERE guild_id=? AND user_id=? AND clock_out IS NULL",
                (str(guild_id), str(user_id))
            )
            return await cursor.fetchone()

    async def get_attendance(self, guild_id, user_id, limit=10):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT clock_in,clock_out,duration_s,note FROM attendance WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                (str(guild_id), str(user_id), limit)
            )
            return await cursor.fetchall()

    async def get_attendance_report(self, guild_id, days=7):
        since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT user_id, SUM(duration_s), COUNT(*) FROM attendance WHERE guild_id=? AND clock_in>? AND clock_out IS NOT NULL GROUP BY user_id ORDER BY SUM(duration_s) DESC",
                (str(guild_id), since)
            )
            return await cursor.fetchall()

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 3 — Leave, KPI, Compliance
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Leave Management ──────────────────────────────────────────────────────

    async def _ensure_phase3(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS leave_requests (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id     TEXT NOT NULL,
                    user_id      TEXT NOT NULL,
                    leave_type   TEXT NOT NULL,
                    start_date   TEXT NOT NULL,
                    end_date     TEXT NOT NULL,
                    reason       TEXT,
                    status       TEXT DEFAULT 'pending',
                    reviewed_by  TEXT,
                    reviewed_at  TEXT,
                    created_at   TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS kpi_entries (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    metric      TEXT NOT NULL,
                    value       REAL NOT NULL,
                    target      REAL,
                    period      TEXT NOT NULL,
                    logged_by   TEXT NOT NULL,
                    note        TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS performance_ratings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    rated_by    TEXT NOT NULL,
                    rating      INTEGER NOT NULL,
                    category    TEXT NOT NULL,
                    comment     TEXT,
                    period      TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS compliance_rules (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    rule_name   TEXT NOT NULL,
                    description TEXT,
                    severity    TEXT DEFAULT 'medium',
                    active      INTEGER DEFAULT 1,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS compliance_incidents (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    rule_id     INTEGER,
                    rule_name   TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity    TEXT NOT NULL,
                    reported_by TEXT NOT NULL,
                    status      TEXT DEFAULT 'open',
                    resolved_at TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.commit()

    # Leave requests

    async def submit_leave(self, guild_id, user_id, leave_type, start_date, end_date, reason):
        await self._ensure_phase3()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO leave_requests (guild_id,user_id,leave_type,start_date,end_date,reason,created_at) VALUES (?,?,?,?,?,?,?)",
                (str(guild_id), str(user_id), leave_type, start_date, end_date, reason, now)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            return (await cursor.fetchone())[0]

    async def review_leave(self, leave_id, status, reviewer_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE leave_requests SET status=?,reviewed_by=?,reviewed_at=? WHERE id=?",
                (status, str(reviewer_id), now, leave_id)
            )
            await db.commit()

    async def get_leave_requests(self, guild_id, user_id=None, status=None):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT id,user_id,leave_type,start_date,end_date,reason,status,reviewed_by,created_at FROM leave_requests WHERE guild_id=?"
            params = [str(guild_id)]
            if user_id:
                q += " AND user_id=?"; params.append(str(user_id))
            if status:
                q += " AND status=?"; params.append(status)
            q += " ORDER BY id DESC LIMIT 25"
            cursor = await db.execute(q, params)
            return await cursor.fetchall()

    async def get_leave_by_id(self, leave_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id,guild_id,user_id,leave_type,start_date,end_date,reason,status FROM leave_requests WHERE id=?",
                (leave_id,)
            )
            return await cursor.fetchone()

    # KPI entries

    async def log_kpi(self, guild_id, user_id, metric, value, target, period, logged_by, note):
        await self._ensure_phase3()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO kpi_entries (guild_id,user_id,metric,value,target,period,logged_by,note,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(guild_id), str(user_id), metric, value, target, period, str(logged_by), note, now)
            )
            await db.commit()

    async def get_kpi(self, guild_id, user_id=None, metric=None, period=None):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT user_id,metric,value,target,period,note,created_at FROM kpi_entries WHERE guild_id=?"
            params = [str(guild_id)]
            if user_id:  q += " AND user_id=?";  params.append(str(user_id))
            if metric:   q += " AND metric=?";    params.append(metric)
            if period:   q += " AND period=?";    params.append(period)
            q += " ORDER BY id DESC LIMIT 50"
            cursor = await db.execute(q, params)
            return await cursor.fetchall()

    async def get_kpi_summary(self, guild_id, period):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT user_id, metric, AVG(value), MAX(value), MIN(value), target FROM kpi_entries WHERE guild_id=? AND period=? GROUP BY user_id, metric ORDER BY AVG(value) DESC",
                (str(guild_id), period)
            )
            return await cursor.fetchall()

    # Performance ratings

    async def add_rating(self, guild_id, user_id, rated_by, rating, category, comment, period):
        await self._ensure_phase3()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO performance_ratings (guild_id,user_id,rated_by,rating,category,comment,period,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(guild_id), str(user_id), str(rated_by), rating, category, comment, period, now)
            )
            await db.commit()

    async def get_ratings(self, guild_id, user_id, period=None):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT rated_by,rating,category,comment,period,created_at FROM performance_ratings WHERE guild_id=? AND user_id=?"
            params = [str(guild_id), str(user_id)]
            if period: q += " AND period=?"; params.append(period)
            q += " ORDER BY id DESC LIMIT 20"
            cursor = await db.execute(q, params)
            return await cursor.fetchall()

    async def get_rating_avg(self, guild_id, user_id, period=None):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT AVG(rating), COUNT(*), category FROM performance_ratings WHERE guild_id=? AND user_id=?"
            params = [str(guild_id), str(user_id)]
            if period: q += " AND period=?"; params.append(period)
            q += " GROUP BY category"
            cursor = await db.execute(q, params)
            return await cursor.fetchall()

    # Compliance rules & incidents

    async def add_compliance_rule(self, guild_id, rule_name, description, severity):
        await self._ensure_phase3()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO compliance_rules (guild_id,rule_name,description,severity,created_at) VALUES (?,?,?,?,?)",
                (str(guild_id), rule_name, description, severity, now)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            return (await cursor.fetchone())[0]

    async def get_rules(self, guild_id, active_only=True):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT id,rule_name,description,severity,active FROM compliance_rules WHERE guild_id=?"
            params = [str(guild_id)]
            if active_only: q += " AND active=1"
            cursor = await db.execute(q, params)
            return await cursor.fetchall()

    async def log_incident(self, guild_id, user_id, rule_name, description, severity, reported_by, rule_id=None):
        await self._ensure_phase3()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO compliance_incidents (guild_id,user_id,rule_id,rule_name,description,severity,reported_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(guild_id), str(user_id), rule_id, rule_name, description, severity, str(reported_by), now)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            return (await cursor.fetchone())[0]

    async def resolve_incident(self, incident_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE compliance_incidents SET status='resolved', resolved_at=? WHERE id=?",
                (now, incident_id)
            )
            await db.commit()

    async def get_incidents(self, guild_id, user_id=None, status=None):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT id,user_id,rule_name,description,severity,reported_by,status,created_at FROM compliance_incidents WHERE guild_id=?"
            params = [str(guild_id)]
            if user_id: q += " AND user_id=?"; params.append(str(user_id))
            if status:  q += " AND status=?";  params.append(status)
            q += " ORDER BY id DESC LIMIT 30"
            cursor = await db.execute(q, params)
            return await cursor.fetchall()

    async def get_compliance_summary(self, guild_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT severity, COUNT(*) FROM compliance_incidents WHERE guild_id=? AND status='open' GROUP BY severity",
                (str(guild_id),)
            )
            return await cursor.fetchall()

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 4 — Crypto, Webhooks, DB Tools
    # ═══════════════════════════════════════════════════════════════════════════

    async def _ensure_phase4(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Crypto price alerts
            await db.execute("""
                CREATE TABLE IF NOT EXISTS crypto_alerts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    target_price REAL NOT NULL,
                    direction   TEXT NOT NULL,
                    triggered   INTEGER DEFAULT 0,
                    created_at  TEXT NOT NULL
                )
            """)
            # Crypto watchlist per guild
            await db.execute("""
                CREATE TABLE IF NOT EXISTS crypto_watchlist (
                    guild_id   TEXT NOT NULL,
                    symbol     TEXT NOT NULL,
                    added_by   TEXT NOT NULL,
                    added_at   TEXT NOT NULL,
                    PRIMARY KEY (guild_id, symbol)
                )
            """)
            # Webhook registry
            await db.execute("""
                CREATE TABLE IF NOT EXISTS webhooks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    name        TEXT NOT NULL,
                    url         TEXT NOT NULL,
                    event_type  TEXT NOT NULL,
                    active      INTEGER DEFAULT 1,
                    created_by  TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            # Webhook delivery log
            await db.execute("""
                CREATE TABLE IF NOT EXISTS webhook_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    webhook_id  INTEGER NOT NULL,
                    payload     TEXT,
                    status      TEXT,
                    delivered_at TEXT NOT NULL
                )
            """)
            await db.commit()

    # ── Crypto alerts ─────────────────────────────────────────────────────────

    async def add_crypto_alert(self, guild_id, user_id, symbol, target_price, direction):
        await self._ensure_phase4()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO crypto_alerts (guild_id,user_id,symbol,target_price,direction,created_at) VALUES (?,?,?,?,?,?)",
                (str(guild_id), str(user_id), symbol.upper(), target_price, direction, now)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            return (await cursor.fetchone())[0]

    async def get_active_alerts(self, guild_id, user_id=None):
        async with aiosqlite.connect(self.db_path) as db:
            if user_id:
                cursor = await db.execute(
                    "SELECT id,symbol,target_price,direction,created_at FROM crypto_alerts WHERE guild_id=? AND user_id=? AND triggered=0",
                    (str(guild_id), str(user_id))
                )
            else:
                cursor = await db.execute(
                    "SELECT id,user_id,symbol,target_price,direction FROM crypto_alerts WHERE guild_id=? AND triggered=0",
                    (str(guild_id),)
                )
            return await cursor.fetchall()

    async def mark_alert_triggered(self, alert_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE crypto_alerts SET triggered=1 WHERE id=?", (alert_id,))
            await db.commit()

    async def remove_alert(self, alert_id, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM crypto_alerts WHERE id=? AND user_id=?",
                (alert_id, str(user_id))
            )
            await db.commit()

    # ── Crypto watchlist ──────────────────────────────────────────────────────

    async def add_to_watchlist(self, guild_id, symbol, added_by):
        await self._ensure_phase4()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO crypto_watchlist (guild_id,symbol,added_by,added_at) VALUES (?,?,?,?)",
                (str(guild_id), symbol.upper(), str(added_by), now)
            )
            await db.commit()

    async def remove_from_watchlist(self, guild_id, symbol):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM crypto_watchlist WHERE guild_id=? AND symbol=?",
                (str(guild_id), symbol.upper())
            )
            await db.commit()

    async def get_watchlist(self, guild_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT symbol, added_by, added_at FROM crypto_watchlist WHERE guild_id=? ORDER BY added_at",
                (str(guild_id),)
            )
            return await cursor.fetchall()

    # ── Webhooks ──────────────────────────────────────────────────────────────

    async def register_webhook(self, guild_id, name, url, event_type, created_by):
        await self._ensure_phase4()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO webhooks (guild_id,name,url,event_type,created_by,created_at) VALUES (?,?,?,?,?,?)",
                (str(guild_id), name, url, event_type, str(created_by), now)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            return (await cursor.fetchone())[0]

    async def get_webhooks(self, guild_id, event_type=None):
        async with aiosqlite.connect(self.db_path) as db:
            if event_type:
                cursor = await db.execute(
                    "SELECT id,name,url,event_type,active FROM webhooks WHERE guild_id=? AND event_type=? AND active=1",
                    (str(guild_id), event_type)
                )
            else:
                cursor = await db.execute(
                    "SELECT id,name,url,event_type,active FROM webhooks WHERE guild_id=?",
                    (str(guild_id),)
                )
            return await cursor.fetchall()

    async def toggle_webhook(self, webhook_id, active):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE webhooks SET active=? WHERE id=?", (1 if active else 0, webhook_id))
            await db.commit()

    async def log_webhook_delivery(self, webhook_id, payload, status):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO webhook_log (webhook_id,payload,status,delivered_at) VALUES (?,?,?,?)",
                (webhook_id, payload, status, now)
            )
            await db.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 5 — Gambling/Economy, Screen Share, Infra
    # ═══════════════════════════════════════════════════════════════════════════

    async def _ensure_phase5(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Economy wallets
            await db.execute("""
                CREATE TABLE IF NOT EXISTS economy (
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    balance     INTEGER DEFAULT 0,
                    bank        INTEGER DEFAULT 0,
                    total_earned INTEGER DEFAULT 0,
                    total_lost   INTEGER DEFAULT 0,
                    last_daily   TEXT,
                    last_work    TEXT,
                    created_at   TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            # Transaction log
            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    amount      INTEGER NOT NULL,
                    type        TEXT NOT NULL,
                    description TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            # Gambling history
            await db.execute("""
                CREATE TABLE IF NOT EXISTS gamble_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    game        TEXT NOT NULL,
                    bet         INTEGER NOT NULL,
                    outcome     INTEGER NOT NULL,
                    result      TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            # Screen share sessions
            await db.execute("""
                CREATE TABLE IF NOT EXISTS screenshare_sessions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id     TEXT NOT NULL,
                    user_id      TEXT NOT NULL,
                    channel_id   TEXT NOT NULL,
                    started_at   TEXT NOT NULL,
                    ended_at     TEXT,
                    verified_by  TEXT,
                    status       TEXT DEFAULT 'pending',
                    notes        TEXT
                )
            """)
            # Server config / settings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id    TEXT NOT NULL,
                    key         TEXT NOT NULL,
                    value       TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    PRIMARY KEY (guild_id, key)
                )
            """)
            # Slow mode / rate limit overrides
            await db.execute("""
                CREATE TABLE IF NOT EXISTS slowmode_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    channel_id  TEXT NOT NULL,
                    delay_s     INTEGER NOT NULL,
                    set_by      TEXT NOT NULL,
                    reason      TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            await db.commit()

    # ── Economy ───────────────────────────────────────────────────────────────

    async def _ensure_wallet(self, guild_id, user_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO economy (guild_id, user_id, balance, bank, total_earned, total_lost, created_at)
                VALUES (?,?,0,0,0,0,?)
            """, (str(guild_id), str(user_id), now))
            await db.commit()

    async def get_wallet(self, guild_id, user_id):
        await self._ensure_phase5()
        await self._ensure_wallet(guild_id, user_id)
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT balance, bank, total_earned, total_lost, last_daily, last_work FROM economy WHERE guild_id=? AND user_id=?",
                (str(guild_id), str(user_id))
            )
            return await cur.fetchone()

    async def update_balance(self, guild_id, user_id, amount, txn_type, description=None):
        await self._ensure_wallet(guild_id, user_id)
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            if amount > 0:
                await db.execute(
                    "UPDATE economy SET balance=balance+?, total_earned=total_earned+? WHERE guild_id=? AND user_id=?",
                    (amount, amount, str(guild_id), str(user_id))
                )
            else:
                await db.execute(
                    "UPDATE economy SET balance=balance+?, total_lost=total_lost+? WHERE guild_id=? AND user_id=?",
                    (amount, abs(amount), str(guild_id), str(user_id))
                )
            await db.execute(
                "INSERT INTO transactions (guild_id,user_id,amount,type,description,created_at) VALUES (?,?,?,?,?,?)",
                (str(guild_id), str(user_id), amount, txn_type, description, now)
            )
            await db.commit()

    async def transfer_balance(self, guild_id, from_id, to_id, amount):
        await self._ensure_wallet(guild_id, from_id)
        await self._ensure_wallet(guild_id, to_id)
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy SET balance=balance-? WHERE guild_id=? AND user_id=?",
                (amount, str(guild_id), str(from_id))
            )
            await db.execute(
                "UPDATE economy SET balance=balance+? WHERE guild_id=? AND user_id=?",
                (amount, str(guild_id), str(to_id))
            )
            await db.execute(
                "INSERT INTO transactions (guild_id,user_id,amount,type,description,created_at) VALUES (?,?,?,?,?,?)",
                (str(guild_id), str(from_id), -amount, "transfer_out", f"To {to_id}", now)
            )
            await db.execute(
                "INSERT INTO transactions (guild_id,user_id,amount,type,description,created_at) VALUES (?,?,?,?,?,?)",
                (str(guild_id), str(to_id), amount, "transfer_in", f"From {from_id}", now)
            )
            await db.commit()

    async def deposit_bank(self, guild_id, user_id, amount):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy SET balance=balance-?, bank=bank+? WHERE guild_id=? AND user_id=?",
                (amount, amount, str(guild_id), str(user_id))
            )
            await db.commit()

    async def withdraw_bank(self, guild_id, user_id, amount):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy SET balance=balance+?, bank=bank-? WHERE guild_id=? AND user_id=?",
                (amount, amount, str(guild_id), str(user_id))
            )
            await db.commit()

    async def set_daily_claimed(self, guild_id, user_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy SET last_daily=? WHERE guild_id=? AND user_id=?",
                (now, str(guild_id), str(user_id))
            )
            await db.commit()

    async def set_work_claimed(self, guild_id, user_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy SET last_work=? WHERE guild_id=? AND user_id=?",
                (now, str(guild_id), str(user_id))
            )
            await db.commit()

    async def log_gamble(self, guild_id, user_id, game, bet, outcome, result):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO gamble_log (guild_id,user_id,game,bet,outcome,result,created_at) VALUES (?,?,?,?,?,?,?)",
                (str(guild_id), str(user_id), game, bet, outcome, result, now)
            )
            await db.commit()

    async def get_economy_leaderboard(self, guild_id, limit=10):
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT user_id, balance+bank as total, balance, bank FROM economy WHERE guild_id=? ORDER BY total DESC LIMIT ?",
                (str(guild_id), limit)
            )
            return await cur.fetchall()

    async def get_gamble_stats(self, guild_id, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT game, COUNT(*), SUM(outcome), SUM(bet) FROM gamble_log WHERE guild_id=? AND user_id=? GROUP BY game",
                (str(guild_id), str(user_id))
            )
            return await cur.fetchall()

    # ── Screen Share ──────────────────────────────────────────────────────────

    async def start_screenshare_session(self, guild_id, user_id, channel_id):
        await self._ensure_phase5()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO screenshare_sessions (guild_id,user_id,channel_id,started_at) VALUES (?,?,?,?)",
                (str(guild_id), str(user_id), str(channel_id), now)
            )
            await db.commit()
            cur = await db.execute("SELECT last_insert_rowid()")
            return (await cur.fetchone())[0]

    async def update_screenshare(self, session_id, status, verified_by=None, notes=None):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE screenshare_sessions SET status=?, ended_at=?, verified_by=?, notes=? WHERE id=?",
                (status, now, str(verified_by) if verified_by else None, notes, session_id)
            )
            await db.commit()

    async def get_screenshare_sessions(self, guild_id, user_id=None, status=None):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT id,user_id,channel_id,started_at,ended_at,verified_by,status,notes FROM screenshare_sessions WHERE guild_id=?"
            params = [str(guild_id)]
            if user_id: q += " AND user_id=?"; params.append(str(user_id))
            if status:  q += " AND status=?";  params.append(status)
            q += " ORDER BY id DESC LIMIT 20"
            cur = await db.execute(q, params)
            return await cur.fetchall()

    # ── Guild Config ──────────────────────────────────────────────────────────

    async def set_config(self, guild_id, key, value):
        await self._ensure_phase5()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO guild_config (guild_id, key, value, updated_at) VALUES (?,?,?,?)",
                (str(guild_id), key, str(value), now)
            )
            await db.commit()

    async def get_config(self, guild_id, key, default=None):
        async with aiosqlite.connect(self.db_path) as db:
            try:
                cur = await db.execute(
                    "SELECT value FROM guild_config WHERE guild_id=? AND key=?",
                    (str(guild_id), key)
                )
                row = await cur.fetchone()
                return row[0] if row else default
            except Exception:
                return default

    async def get_all_config(self, guild_id):
        async with aiosqlite.connect(self.db_path) as db:
            try:
                cur = await db.execute(
                    "SELECT key, value, updated_at FROM guild_config WHERE guild_id=? ORDER BY key",
                    (str(guild_id),)
                )
                return await cur.fetchall()
            except Exception:
                return []

    # ═══════════════════════════════════════════════════════════════════════════
    # PHASE 5 — Gambling/Economy, Screen Share, Infra
    # ═══════════════════════════════════════════════════════════════════════════

    async def _ensure_phase5(self):
        async with aiosqlite.connect(self.db_path) as db:
            # Economy wallets
            await db.execute("""
                CREATE TABLE IF NOT EXISTS economy (
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    wallet      INTEGER DEFAULT 0,
                    bank        INTEGER DEFAULT 100,
                    total_won   INTEGER DEFAULT 0,
                    total_lost  INTEGER DEFAULT 0,
                    last_daily  TEXT,
                    last_work   TEXT,
                    streak      INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            # Transaction ledger
            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    amount      INTEGER NOT NULL,
                    type        TEXT NOT NULL,
                    description TEXT,
                    created_at  TEXT NOT NULL
                )
            """)
            # Screen share sessions
            await db.execute("""
                CREATE TABLE IF NOT EXISTS screenshare_sessions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    channel_id  TEXT NOT NULL,
                    verified_by TEXT,
                    status      TEXT DEFAULT 'pending',
                    started_at  TEXT NOT NULL,
                    verified_at TEXT,
                    note        TEXT
                )
            """)
            # Infra: server config store
            await db.execute("""
                CREATE TABLE IF NOT EXISTS server_config (
                    guild_id    TEXT NOT NULL,
                    key         TEXT NOT NULL,
                    value       TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    PRIMARY KEY (guild_id, key)
                )
            """)
            # Infra: health check log
            await db.execute("""
                CREATE TABLE IF NOT EXISTS health_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id    TEXT NOT NULL,
                    latency_ms  REAL,
                    guilds      INTEGER,
                    members     INTEGER,
                    recorded_at TEXT NOT NULL
                )
            """)
            await db.commit()

    # ── Economy ───────────────────────────────────────────────────────────────

    async def get_wallet(self, guild_id, user_id):
        await self._ensure_phase5()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT wallet, bank, total_won, total_lost, last_daily, last_work, streak FROM economy WHERE guild_id=? AND user_id=?",
                (str(guild_id), str(user_id))
            )
            row = await cursor.fetchone()
            if not row:
                await db.execute(
                    "INSERT OR IGNORE INTO economy (guild_id, user_id) VALUES (?,?)",
                    (str(guild_id), str(user_id))
                )
                await db.commit()
                return (0, 100, 0, 0, None, None, 0)
            return row

    async def update_wallet(self, guild_id, user_id, wallet_delta=0, bank_delta=0, won=0, lost=0):
        await self._ensure_phase5()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO economy (guild_id, user_id, wallet, bank, total_won, total_lost)
                VALUES (?,?,MAX(0,?),MAX(0,?),?,?)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET
                    wallet    = MAX(0, wallet + ?),
                    bank      = MAX(0, bank + ?),
                    total_won  = total_won + ?,
                    total_lost = total_lost + ?
            """, (str(guild_id), str(user_id),
                  max(0, wallet_delta), max(0, bank_delta), won, lost,
                  wallet_delta, bank_delta, won, lost))
            await db.commit()
            cursor = await db.execute(
                "SELECT wallet, bank FROM economy WHERE guild_id=? AND user_id=?",
                (str(guild_id), str(user_id))
            )
            return await cursor.fetchone()

    async def set_daily_claimed(self, guild_id, user_id, streak):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy SET last_daily=?, streak=? WHERE guild_id=? AND user_id=?",
                (now, streak, str(guild_id), str(user_id))
            )
            await db.commit()

    async def set_work_claimed(self, guild_id, user_id):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy SET last_work=? WHERE guild_id=? AND user_id=?",
                (now, str(guild_id), str(user_id))
            )
            await db.commit()

    async def log_transaction(self, guild_id, user_id, amount, tx_type, description=None):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO transactions (guild_id,user_id,amount,type,description,created_at) VALUES (?,?,?,?,?,?)",
                (str(guild_id), str(user_id), amount, tx_type, description, now)
            )
            await db.commit()

    async def get_economy_leaderboard(self, guild_id, limit=10):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT user_id, wallet+bank as total, wallet, bank, total_won FROM economy WHERE guild_id=? ORDER BY total DESC LIMIT ?",
                (str(guild_id), limit)
            )
            return await cursor.fetchall()

    # ── Screen Share Sessions ─────────────────────────────────────────────────

    async def create_ss_session(self, guild_id, user_id, channel_id):
        await self._ensure_phase5()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO screenshare_sessions (guild_id,user_id,channel_id,started_at) VALUES (?,?,?,?)",
                (str(guild_id), str(user_id), str(channel_id), now)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            return (await cursor.fetchone())[0]

    async def verify_ss_session(self, session_id, verified_by, note=None):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE screenshare_sessions SET status='verified', verified_by=?, verified_at=?, note=? WHERE id=?",
                (str(verified_by), now, note, session_id)
            )
            await db.commit()

    async def reject_ss_session(self, session_id, note=None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE screenshare_sessions SET status='rejected', note=? WHERE id=?",
                (note, session_id)
            )
            await db.commit()

    async def get_ss_sessions(self, guild_id, user_id=None, status=None):
        async with aiosqlite.connect(self.db_path) as db:
            q = "SELECT id,user_id,channel_id,verified_by,status,started_at,verified_at,note FROM screenshare_sessions WHERE guild_id=?"
            params = [str(guild_id)]
            if user_id: q += " AND user_id=?"; params.append(str(user_id))
            if status:  q += " AND status=?";  params.append(status)
            q += " ORDER BY id DESC LIMIT 30"
            cursor = await db.execute(q, params)
            return await cursor.fetchall()

    # ── Server Config ─────────────────────────────────────────────────────────

    async def get_config(self, guild_id, key, default=None):
        await self._ensure_phase5()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM server_config WHERE guild_id=? AND key=?",
                (str(guild_id), key)
            )
            row = await cursor.fetchone()
            return row[0] if row else default

    async def set_config(self, guild_id, key, value):
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO server_config (guild_id,key,value,updated_at)
                VALUES (?,?,?,?)
                ON CONFLICT(guild_id,key) DO UPDATE SET value=?,updated_at=?
            """, (str(guild_id), key, str(value), now, str(value), now))
            await db.commit()

    async def get_all_config(self, guild_id):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT key, value, updated_at FROM server_config WHERE guild_id=? ORDER BY key",
                (str(guild_id),)
            )
            return await cursor.fetchall()

    # ── Health Log ────────────────────────────────────────────────────────────

    async def log_health(self, guild_id, latency_ms, guilds, members):
        await self._ensure_phase5()
        now = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO health_log (guild_id,latency_ms,guilds,members,recorded_at) VALUES (?,?,?,?,?)",
                (str(guild_id), latency_ms, guilds, members, now)
            )
            # Keep only last 100 health records per guild
            await db.execute("""
                DELETE FROM health_log WHERE guild_id=? AND id NOT IN (
                    SELECT id FROM health_log WHERE guild_id=? ORDER BY id DESC LIMIT 100
                )
            """, (str(guild_id), str(guild_id)))
            await db.commit()
