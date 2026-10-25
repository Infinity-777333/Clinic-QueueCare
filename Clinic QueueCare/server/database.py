"""
server/database.py
Centralized SQLite database persistence layer for QueueCare.
Replaces in-memory storage with SQLite database located at database/clinic_queuecare.db.
Provides thread-safe, transaction-protected database access, idempotent initialization,
multi-shift queue session management, and single-source-of-truth persistence across server restarts.
"""

import sqlite3
import threading
import json
from pathlib import Path
from datetime import datetime, date
from contextlib import contextmanager
import bcrypt

# Determine Project Root and Database File Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = PROJECT_ROOT / 'database'
DB_PATH = DB_DIR / 'clinic_queuecare.db'

db_lock = threading.RLock()


@contextmanager
def get_db():
    """
    Context manager that yields an open SQLite database connection with row factory,
    foreign keys, and WAL journal mode enabled, and ensures connection is closed on exit.
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    try:
        yield conn
    finally:
        conn.close()


def reset_db_for_testing():
    """
    Explicit development and test reset helper.
    Drops and re-initializes tables.
    NEVER called automatically by normal application startup.
    """
    with db_lock:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = OFF;")
            cursor.execute("DROP TABLE IF EXISTS queue_history;")
            cursor.execute("DROP TABLE IF EXISTS queue_state;")
            cursor.execute("DROP TABLE IF EXISTS bookings;")
            cursor.execute("DROP TABLE IF EXISTS patients;")
            cursor.execute("DROP TABLE IF EXISTS clinic_settings;")
            cursor.execute("DROP TABLE IF EXISTS users;")
            cursor.execute("DROP TABLE IF EXISTS queue_undo_log;")
            cursor.execute("PRAGMA foreign_keys = ON;")
            conn.commit()
        init_db()


def init_db():
    """
    Idempotent database initialization & safe migration:
    - Creates database directory if it does not exist.
    - Creates required tables and indexes if they do not exist.
    - Safely migrates existing schemas to support queue_session without data loss.
    - Seeds default staff accounts and clinic settings if not already present.
    - Never drops existing patient bookings or clinic data on restart.
    """
    with db_lock:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with get_db() as conn:
            cursor = conn.cursor()

            # 1. Users table (Doctor & Receptionist accounts)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    specialization TEXT,
                    created_at TEXT NOT NULL
                );
            """)

            # 2. Patients table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    mobile TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 3. Bookings table (Scoped to booking_date, queue_session, token_number)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id TEXT PRIMARY KEY,
                    token_number INTEGER NOT NULL,
                    patient_id INTEGER NOT NULL REFERENCES patients(id),
                    patient_name TEXT NOT NULL,
                    patient_mobile TEXT NOT NULL,
                    source TEXT NOT NULL,
                    booking_date TEXT NOT NULL,
                    queue_session INTEGER NOT NULL DEFAULT 1,
                    booking_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Waiting',
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(booking_date, queue_session, token_number)
                );
            """)

            # Safe migration for existing bookings table if queue_session or compound constraint is missing
            cursor.execute("PRAGMA table_info(bookings);")
            booking_cols = [r["name"] for r in cursor.fetchall()]
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bookings';")
            b_sql_row = cursor.fetchone()
            b_sql = b_sql_row["sql"] if b_sql_row else ""
            if "queue_session" not in booking_cols or "UNIQUE(booking_date, queue_session, token_number)" not in b_sql:
                cursor.execute("""
                    CREATE TABLE bookings_migrated (
                        id TEXT PRIMARY KEY,
                        token_number INTEGER NOT NULL,
                        patient_id INTEGER NOT NULL REFERENCES patients(id),
                        patient_name TEXT NOT NULL,
                        patient_mobile TEXT NOT NULL,
                        source TEXT NOT NULL,
                        booking_date TEXT NOT NULL,
                        queue_session INTEGER NOT NULL DEFAULT 1,
                        booking_time TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'Waiting',
                        started_at TEXT,
                        completed_at TEXT,
                        created_at TEXT NOT NULL,
                        UNIQUE(booking_date, queue_session, token_number)
                    );
                """)
                cursor.execute("""
                    INSERT INTO bookings_migrated (
                        id, token_number, patient_id, patient_name, patient_mobile,
                        source, booking_date, queue_session, booking_time, status, started_at, completed_at, created_at
                    ) SELECT
                        id, token_number, patient_id, patient_name, patient_mobile,
                        source, booking_date, 1, booking_time, status, started_at, completed_at, created_at
                    FROM bookings;
                """)
                cursor.execute("DROP TABLE bookings;")
                cursor.execute("ALTER TABLE bookings_migrated RENAME TO bookings;")

            # 4. Queue State table (Per-day and per-session operational state)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_date TEXT NOT NULL,
                    queue_session INTEGER NOT NULL DEFAULT 1,
                    current_token INTEGER,
                    last_completed_token INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(queue_date, queue_session)
                );
            """)

            # Safe migration for existing queue_state table if queue_session is missing
            cursor.execute("PRAGMA table_info(queue_state);")
            qs_cols = [r["name"] for r in cursor.fetchall()]
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='queue_state';")
            qs_sql_row = cursor.fetchone()
            qs_sql = qs_sql_row["sql"] if qs_sql_row else ""
            if "queue_session" not in qs_cols or "UNIQUE(queue_date, queue_session)" not in qs_sql:
                cursor.execute("""
                    CREATE TABLE queue_state_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        queue_date TEXT NOT NULL,
                        queue_session INTEGER NOT NULL DEFAULT 1,
                        current_token INTEGER,
                        last_completed_token INTEGER DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        UNIQUE(queue_date, queue_session)
                    );
                """)
                cursor.execute("""
                    INSERT INTO queue_state_migrated (
                        id, queue_date, queue_session, current_token, last_completed_token, updated_at
                    ) SELECT
                        id, queue_date, 1, current_token, last_completed_token, updated_at
                    FROM queue_state;
                """)
                cursor.execute("DROP TABLE queue_state;")
                cursor.execute("ALTER TABLE queue_state_migrated RENAME TO queue_state;")

            # 5. Queue Action History table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS queue_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_date TEXT NOT NULL,
                    queue_session INTEGER NOT NULL DEFAULT 1,
                    booking_id TEXT REFERENCES bookings(id) ON DELETE SET NULL,
                    token_number INTEGER NOT NULL,
                    patient_name TEXT NOT NULL,
                    patient_mobile TEXT NOT NULL,
                    source TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            cursor.execute("PRAGMA table_info(queue_history);")
            qh_cols = [r["name"] for r in cursor.fetchall()]
            if "queue_session" not in qh_cols:
                cursor.execute("ALTER TABLE queue_history ADD COLUMN queue_session INTEGER NOT NULL DEFAULT 1;")

            # Safe migration for existing queue_history table to add FOREIGN KEY (booking_id) REFERENCES bookings(id)
            cursor.execute("PRAGMA foreign_key_list(queue_history);")
            qh_fks = [fk["table"] for fk in cursor.fetchall()]
            if "bookings" not in qh_fks:
                cursor.execute("PRAGMA foreign_keys = OFF;")
                cursor.execute("""
                    CREATE TABLE queue_history_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        queue_date TEXT NOT NULL,
                        queue_session INTEGER NOT NULL DEFAULT 1,
                        booking_id TEXT REFERENCES bookings(id) ON DELETE SET NULL,
                        token_number INTEGER NOT NULL,
                        patient_name TEXT NOT NULL,
                        patient_mobile TEXT NOT NULL,
                        source TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT,
                        action TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                """)
                cursor.execute("""
                    INSERT INTO queue_history_migrated (
                        id, queue_date, queue_session, booking_id, token_number,
                        patient_name, patient_mobile, source, started_at, completed_at, action, created_at
                    ) SELECT
                        id, queue_date, queue_session, booking_id, token_number,
                        patient_name, patient_mobile, source, started_at, completed_at, action, created_at
                    FROM queue_history;
                """)
                cursor.execute("DROP TABLE queue_history;")
                cursor.execute("ALTER TABLE queue_history_migrated RENAME TO queue_history;")
                cursor.execute("PRAGMA foreign_keys = ON;")

            # Safe migration cleanup: Drop obsolete queue_undo_log table and its indexes if present
            cursor.execute("DROP TABLE IF EXISTS queue_undo_log;")
            cursor.execute("DROP INDEX IF EXISTS idx_undo_date_sess;")
            cursor.execute("DROP INDEX IF EXISTS idx_undo_date;")

            # 6. Clinic Settings table (Single source of truth with doctor_user_id foreign key)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clinic_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    doctor_user_id INTEGER UNIQUE REFERENCES users(id),
                    clinic_name TEXT NOT NULL,
                    doctor_name TEXT NOT NULL,
                    doctor_specialization TEXT NOT NULL,
                    clinic_start_time TEXT NOT NULL,
                    clinic_end_time TEXT NOT NULL,
                    daily_token_limit INTEGER NOT NULL DEFAULT 100,
                    booking_status TEXT NOT NULL DEFAULT 'OPEN',
                    consultation_status TEXT NOT NULL DEFAULT 'NOT_STARTED',
                    updated_at TEXT NOT NULL
                );
            """)

            # Safe migration for existing clinic_settings table if doctor_user_id is missing
            cursor.execute("PRAGMA table_info(clinic_settings);")
            cs_cols = [r["name"] for r in cursor.fetchall()]
            if "doctor_user_id" not in cs_cols:
                cursor.execute("ALTER TABLE clinic_settings ADD COLUMN doctor_user_id INTEGER REFERENCES users(id);")

            # Indexes for efficient queries
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clinic_settings_doctor_user_id ON clinic_settings(doctor_user_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(booking_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date_sess ON bookings(booking_date, queue_session);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_mobile ON bookings(patient_mobile);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status_date ON bookings(status, booking_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date_sess_tok ON bookings(booking_date, queue_session, token_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_date ON queue_history(queue_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_date_sess ON queue_history(queue_date, queue_session);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_state_date_sess ON queue_state(queue_date, queue_session);")

            # Seed default staff accounts if not existing
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            doc_pw_hash = bcrypt.hashpw(b"doctor123", bcrypt.gensalt()).decode('utf-8')
            rec_pw_hash = bcrypt.hashpw(b"reception123", bcrypt.gensalt()).decode('utf-8')

            cursor.execute("""
                INSERT OR IGNORE INTO users (username, password_hash, role, full_name, specialization, created_at)
                VALUES ('doctor', ?, 'doctor', 'Dr. Sarah Jenkins', 'General Physician', ?);
            """, (doc_pw_hash, now_str))

            cursor.execute("""
                INSERT OR IGNORE INTO users (username, password_hash, role, full_name, specialization, created_at)
                VALUES ('reception', ?, 'receptionist', 'Reception Desk', 'Front Desk', ?);
            """, (rec_pw_hash, now_str))

            # Dynamically resolve doctor user account id for foreign key association
            cursor.execute("SELECT id FROM users WHERE role = 'doctor' ORDER BY id ASC LIMIT 1;")
            doc_user_row = cursor.fetchone()
            doc_user_id = doc_user_row["id"] if doc_user_row else None

            # Seed default clinic settings (row id = 1) if not existing
            cursor.execute("""
                INSERT OR IGNORE INTO clinic_settings (
                    id, doctor_user_id, clinic_name, doctor_name, doctor_specialization,
                    clinic_start_time, clinic_end_time, daily_token_limit,
                    booking_status, consultation_status, updated_at
                ) VALUES (
                    1, ?, 'QueueCare Clinic', 'Dr. Sarah Jenkins', 'General Physician',
                    '09:00', '17:00', 100, 'OPEN', 'NOT_STARTED', ?
                );
            """, (doc_user_id, now_str))

            # Ensure existing clinic_settings row 1 has doctor_user_id populated
            if doc_user_id:
                cursor.execute("""
                    UPDATE clinic_settings
                    SET doctor_user_id = ?
                    WHERE id = 1 AND (doctor_user_id IS NULL OR doctor_user_id != ?);
                """, (doc_user_id, doc_user_id))

            conn.commit()


# ==============================================================================
# CLINIC SETTINGS QUERIES
# ==============================================================================

def get_clinic_settings():
    """Fetches the singleton clinic settings from SQLite."""
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM clinic_settings WHERE id = 1;")
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {
                "id": 1,
                "doctor_user_id": 1,
                "clinic_name": "QueueCare Clinic",
                "doctor_name": "Dr. Sarah Jenkins",
                "doctor_specialization": "General Physician",
                "clinic_start_time": "09:00",
                "clinic_end_time": "17:00",
                "daily_token_limit": 100,
                "booking_status": "OPEN",
                "consultation_status": "NOT_STARTED",
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }


def update_clinic_settings(settings_dict):
    """
    Updates clinic settings in SQLite. Synchronizes doctor user full_name and specialization.
    """
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            allowed_fields = [
                "doctor_user_id", "clinic_name", "doctor_name", "doctor_specialization",
                "clinic_start_time", "clinic_end_time", "daily_token_limit",
                "booking_status", "consultation_status"
            ]

            set_clauses = ["updated_at = ?"]
            params = [now_str]

            for field in allowed_fields:
                if field in settings_dict:
                    set_clauses.append(f"{field} = ?")
                    params.append(settings_dict[field])

            cursor.execute(f"""
                UPDATE clinic_settings SET {', '.join(set_clauses)} WHERE id = 1;
            """, tuple(params))

            # Synchronize doctor's profile in users table
            if "doctor_name" in settings_dict or "doctor_specialization" in settings_dict:
                user_updates = []
                user_params = []
                if "doctor_name" in settings_dict:
                    user_updates.append("full_name = ?")
                    user_params.append(settings_dict["doctor_name"])
                if "doctor_specialization" in settings_dict:
                    user_updates.append("specialization = ?")
                    user_params.append(settings_dict["doctor_specialization"])
                if user_updates:
                    cursor.execute(f"""
                        UPDATE users SET {', '.join(user_updates)}
                        WHERE id = (SELECT doctor_user_id FROM clinic_settings WHERE id = 1)
                           OR (username = 'doctor' AND NOT EXISTS (SELECT 1 FROM clinic_settings WHERE id = 1 AND doctor_user_id IS NOT NULL));
                    """, tuple(user_params))

            conn.commit()

            cursor.execute("SELECT * FROM clinic_settings WHERE id = 1;")
            return dict(cursor.fetchone())


def set_booking_status(status):
    """Opens or closes patient bookings in SQLite."""
    if status not in ["OPEN", "CLOSED"]:
        return False, "Invalid booking status"
    update_clinic_settings({"booking_status": status})
    return True, get_queue_state()


def set_consultation_status(status):
    """Sets doctor consultation status in SQLite."""
    valid_statuses = ["NOT_STARTED", "IN_PROGRESS", "COMPLETED"]
    if status not in valid_statuses:
        return False, f"Status must be one of: {', '.join(valid_statuses)}"
    update_clinic_settings({"consultation_status": status})
    return True, get_queue_state()


# ==============================================================================
# USER AUTHENTICATION QUERIES
# ==============================================================================

def get_user_by_username(username):
    """Fetches user record from SQLite by username."""
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?;", (username.strip(),))
            row = cursor.fetchone()
            return dict(row) if row else None


# ==============================================================================
# QUEUE STATE & SESSION MANAGEMENT
# ==============================================================================

def get_current_session_number(today_str=None, conn=None):
    """
    Returns the active queue session number for the specified date (defaults to 1).
    Ensures an initial queue_state record exists for today.
    """
    if not today_str:
        today_str = date.today().isoformat()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _query(c):
        cursor = c.cursor()
        cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
        row = cursor.fetchone()
        cur_session = row[0] if (row and row[0] is not None) else None
        if not cur_session:
            cur_session = 1
            cursor.execute("""
                INSERT OR IGNORE INTO queue_state (queue_date, queue_session, current_token, last_completed_token, updated_at)
                VALUES (?, 1, NULL, 0, ?);
            """, (today_str, now_str))
            c.commit()
        return cur_session

    if conn is not None:
        return _query(conn)
    else:
        with db_lock:
            with get_db() as c:
                return _query(c)


def get_queue_state(today_str=None, session_num=None):
    """
    Reconstructs complete and accurate queue state from SQLite for the given date and session.
    If session_num is None, defaults to the current active session for that date.
    Counters are derived dynamically from the session's bookings to prevent desynchronization.
    """
    if not today_str:
        today_str = date.today().isoformat()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()

            if session_num is None:
                cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
                row = cursor.fetchone()
                active_session = row[0] if (row and row[0] is not None) else 1
            else:
                active_session = int(session_num)

            cursor.execute("""
                SELECT * FROM queue_state WHERE queue_date = ? AND queue_session = ?;
            """, (today_str, active_session))
            row = cursor.fetchone()

            if not row:
                cursor.execute("""
                    INSERT INTO queue_state (queue_date, queue_session, current_token, last_completed_token, updated_at)
                    VALUES (?, ?, NULL, 0, ?);
                """, (today_str, active_session, now_str))
                conn.commit()
                current_token = None
                last_completed = 0
            else:
                current_token = row["current_token"]
                last_completed = row["last_completed_token"] or 0

            # Derive counts directly from bookings table scoped to this session
            cursor.execute("""
                SELECT COUNT(*) FROM bookings WHERE booking_date = ? AND queue_session = ?;
            """, (today_str, active_session))
            total_tokens = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM bookings WHERE booking_date = ? AND queue_session = ? AND status = 'Waiting';
            """, (today_str, active_session))
            waiting_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM bookings WHERE booking_date = ? AND queue_session = ? AND status = 'Completed';
            """, (today_str, active_session))
            completed_count = cursor.fetchone()[0]

            # Verify current_token status within this session
            if current_token:
                cursor.execute("""
                    SELECT status FROM bookings
                    WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
                """, (today_str, active_session, current_token))
                cur_row = cursor.fetchone()
                if not cur_row or cur_row["status"] != "Serving":
                    cursor.execute("""
                        SELECT token_number FROM bookings
                        WHERE booking_date = ? AND queue_session = ? AND status = 'Serving' LIMIT 1;
                    """, (today_str, active_session))
                    serving_row = cursor.fetchone()
                    current_token = serving_row["token_number"] if serving_row else None
            else:
                cursor.execute("""
                    SELECT token_number FROM bookings
                    WHERE booking_date = ? AND queue_session = ? AND status = 'Serving' LIMIT 1;
                """, (today_str, active_session))
                serving_row = cursor.fetchone()
                if serving_row:
                    current_token = serving_row["token_number"]

            settings = get_clinic_settings()

            return {
                "queue_date": today_str,
                "queue_session": active_session,
                "current_token": current_token,
                "last_completed_token": last_completed,
                "total_tokens": total_tokens,
                "completed_count": completed_count,
                "waiting_count": waiting_count,
                "booking_status": settings.get("booking_status", "OPEN"),
                "consultation_status": settings.get("consultation_status", "NOT_STARTED"),
                "daily_limit": settings.get("daily_token_limit", 100),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }


def update_queue_state(updates, today_str=None, session_num=None):
    """Updates queue_state record in SQLite for specified date and session."""
    if not today_str:
        today_str = date.today().isoformat()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            if session_num is None:
                cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
                row = cursor.fetchone()
                active_session = row[0] if (row and row[0] is not None) else 1
            else:
                active_session = int(session_num)

            cursor.execute("""
                SELECT id FROM queue_state WHERE queue_date = ? AND queue_session = ?;
            """, (today_str, active_session))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO queue_state (queue_date, queue_session, current_token, last_completed_token, updated_at)
                    VALUES (?, ?, NULL, 0, ?);
                """, (today_str, active_session, now_str))

            if "current_token" in updates:
                cursor.execute("""
                    UPDATE queue_state SET current_token = ?, updated_at = ?
                    WHERE queue_date = ? AND queue_session = ?;
                """, (updates["current_token"], now_str, today_str, active_session))

            if "last_completed_token" in updates:
                cursor.execute("""
                    UPDATE queue_state SET last_completed_token = ?, updated_at = ?
                    WHERE queue_date = ? AND queue_session = ?;
                """, (updates["last_completed_token"], now_str, today_str, active_session))

            conn.commit()

        settings_updates = {}
        if "booking_status" in updates:
            settings_updates["booking_status"] = updates["booking_status"]
        if "consultation_status" in updates:
            settings_updates["consultation_status"] = updates["consultation_status"]
        if settings_updates:
            update_clinic_settings(settings_updates)

        return get_queue_state(today_str, active_session)


# ==============================================================================
# TOKEN BOOKING & SAFE SEQUENTIAL GENERATION
# ==============================================================================

def create_booking(patient_name, patient_mobile, source="Patient"):
    """
    Atomically creates a patient booking with SQLite transaction protection:
    - Identifies current active queue session for today
    - Verifies booking_status (for public online bookings)
    - Verifies daily_token_limit for the session
    - Determines next sequential token for this session (starts from 1)
    - Inserts or reuses patient record
    - Inserts booking with UNIQUE(booking_date, queue_session, token_number) constraint
    - Returns created booking dict
    """
    today_str = date.today().isoformat()
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    created_at_str = now.strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")

            # 1. Identify current active session for today
            cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
            row = cursor.fetchone()
            cur_session = row[0] if (row and row[0] is not None) else 1

            # Ensure queue_state exists for this session
            cursor.execute("SELECT id FROM queue_state WHERE queue_date = ? AND queue_session = ?;", (today_str, cur_session))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO queue_state (queue_date, queue_session, current_token, last_completed_token, updated_at)
                    VALUES (?, ?, NULL, 0, ?);
                """, (today_str, cur_session, created_at_str))

            # 2. Check booking status for online patients
            cursor.execute("SELECT booking_status, daily_token_limit FROM clinic_settings WHERE id = 1;")
            settings_row = cursor.fetchone()
            booking_status = settings_row["booking_status"] if settings_row else "OPEN"
            daily_limit = settings_row["daily_token_limit"] if settings_row else 100

            if source == "Patient" and booking_status != "OPEN":
                conn.rollback()
                return None, "Online booking is currently closed."

            # 3. Check daily token limit for this session
            cursor.execute("""
                SELECT COUNT(*) FROM bookings WHERE booking_date = ? AND queue_session = ?;
            """, (today_str, cur_session))
            total_in_session = cursor.fetchone()[0]
            if total_in_session >= daily_limit:
                conn.rollback()
                return None, "Today's token limit has been reached."

            # 4. Determine next sequential token for this session (starts from 1)
            cursor.execute("""
                SELECT COALESCE(MAX(token_number), 0) + 1 FROM bookings
                WHERE booking_date = ? AND queue_session = ?;
            """, (today_str, cur_session))
            next_token_num = cursor.fetchone()[0]

            # 5. Insert or find patient record
            cursor.execute("SELECT id FROM patients WHERE mobile = ? ORDER BY id DESC LIMIT 1;", (patient_mobile.strip(),))
            p_row = cursor.fetchone()
            if p_row:
                patient_id = p_row["id"]
            else:
                cursor.execute("""
                    INSERT INTO patients (name, mobile, created_at)
                    VALUES (?, ?, ?);
                """, (patient_name.strip(), patient_mobile.strip(), created_at_str))
                patient_id = cursor.lastrowid

            # 6. Insert booking scoped to current session
            token_id = f"tok_{int(now.timestamp() * 1000)}"
            cursor.execute("""
                INSERT INTO bookings (
                    id, token_number, patient_id, patient_name, patient_mobile,
                    source, booking_date, queue_session, booking_time, status, started_at, completed_at, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Waiting', NULL, NULL, ?
                );
            """, (
                token_id, next_token_num, patient_id, patient_name.strip(),
                patient_mobile.strip(), source, today_str, cur_session, time_str, created_at_str
            ))

            conn.commit()

            return {
                "id": token_id,
                "token_number": next_token_num,
                "patient_id": patient_id,
                "patient_name": patient_name.strip(),
                "patient_mobile": patient_mobile.strip(),
                "source": source,
                "booking_date": today_str,
                "queue_session": cur_session,
                "booking_time": time_str,
                "status": "Waiting",
                "started_at": None,
                "completed_at": None,
                "created_at": created_at_str
            }, None


def get_all_today_tokens(today_str=None, session_num=None):
    """
    Returns tokens issued today from SQLite.
    If session_num is provided, filters by that session.
    If session_num is None, returns all tokens for today ordered by queue_session ASC, token_number ASC.
    """
    if not today_str:
        today_str = date.today().isoformat()

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            if session_num is not None:
                cursor.execute("""
                    SELECT * FROM bookings WHERE booking_date = ? AND queue_session = ?
                    ORDER BY token_number ASC;
                """, (today_str, int(session_num)))
            else:
                cursor.execute("""
                    SELECT * FROM bookings WHERE booking_date = ?
                    ORDER BY queue_session ASC, token_number ASC;
                """, (today_str,))
            return [dict(r) for r in cursor.fetchall()]


def get_all_tokens():
    """Alias for get_all_today_tokens for backwards compatibility."""
    return get_all_today_tokens()


def get_token_by_id(token_id):
    """Fetches single token by unique string ID."""
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bookings WHERE id = ?;", (token_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def get_token_by_number(token_number, today_str=None, session_num=None):
    """
    Fetches token by daily token number, optionally scoped to session.
    If session_num is None, orders by queue_session DESC LIMIT 1 (picks the latest session).
    """
    if not today_str:
        today_str = date.today().isoformat()

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            if session_num is not None:
                cursor.execute("""
                    SELECT * FROM bookings WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
                """, (today_str, int(session_num), token_number))
            else:
                cursor.execute("""
                    SELECT * FROM bookings WHERE booking_date = ? AND token_number = ?
                    ORDER BY queue_session DESC LIMIT 1;
                """, (today_str, token_number))
            row = cursor.fetchone()
            return dict(row) if row else None


def auto_expire_previous_days_bookings(today_str=None):
    """
    Automatically marks any Waiting or Serving bookings from previous clinic days as Expired.
    Preserves all Completed bookings, patients, and historical records.
    Idempotent and executed atomically.
    """
    if not today_str:
        today_str = date.today().isoformat()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, token_number, booking_date, queue_session, patient_name, patient_mobile, source, started_at
                FROM bookings
                WHERE booking_date < ? AND status IN ('Waiting', 'Serving');
            """, (today_str,))
            expired_rows = cursor.fetchall()
            if expired_rows:
                cursor.execute("""
                    UPDATE bookings
                    SET status = 'Expired'
                    WHERE booking_date < ? AND status IN ('Waiting', 'Serving');
                """, (today_str,))
                for r in expired_rows:
                    cursor.execute("""
                        INSERT INTO queue_history (
                            queue_date, queue_session, booking_id, token_number,
                            patient_name, patient_mobile, source, started_at,
                            completed_at, action, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'Expired', ?);
                    """, (
                        r["booking_date"], r["queue_session"], r["id"], r["token_number"],
                        r["patient_name"], r["patient_mobile"], r["source"],
                        r["started_at"], now_str
                    ))
                conn.commit()
                return len(expired_rows)
    return 0


def get_active_queue_tokens(today_str=None, session_num=None, ids=None):
    """
    Returns only currently active queue tokens from SQLite for Queue Progress.
    A token is active only if:
    - It belongs to today_str (current clinic date)
    - It belongs to current active queue session
    - Its status is 'Waiting' or 'Serving'
    - Not Expired, not Completed, not from closed/reset queue
    """
    if not today_str:
        today_str = date.today().isoformat()

    auto_expire_previous_days_bookings(today_str)

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            if session_num is None:
                cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
                row = cursor.fetchone()
                session_num = row[0] if (row and row[0] is not None) else 1

            cursor.execute("SELECT consultation_status, booking_status FROM clinic_settings WHERE id = 1;")
            c_row = cursor.fetchone()
            consult_stat = c_row["consultation_status"] if c_row else "NOT_STARTED"

            # Query only Waiting and Serving tokens in current session
            cursor.execute("""
                SELECT * FROM bookings
                WHERE booking_date = ? AND queue_session = ? AND status IN ('Waiting', 'Serving')
                ORDER BY token_number ASC;
            """, (today_str, session_num))
            active_list = [dict(r) for r in cursor.fetchall()]

            user_tokens = []
            if ids:
                id_set = set(str(i).strip() for i in ids if str(i).strip())
                for t in active_list:
                    if str(t["id"]) in id_set or str(t["token_number"]) in id_set:
                        user_tokens.append(t)

            return {
                "active_tokens": active_list,
                "user_tokens": user_tokens,
                "queue_session": session_num,
                "queue_date": today_str,
                "consultation_status": consult_stat
            }


def get_tokens_by_ids(token_ids, today_str=None):
    """
    Fetches multiple tokens by IDs or token numbers for My Bookings.
    Evaluates authoritative lifecycle status (Waiting, Serving, Completed, Expired)
    from SQLite, guaranteeing past-day or closed-session unserved tokens are Expired.
    """
    if not token_ids:
        return []
    if not today_str:
        today_str = date.today().isoformat()

    auto_expire_previous_days_bookings(today_str)

    results = []
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
            sess_row = cursor.fetchone()
            cur_session = sess_row[0] if (sess_row and sess_row[0] is not None) else 1

            cursor.execute("SELECT consultation_status, booking_status FROM clinic_settings WHERE id = 1;")
            c_row = cursor.fetchone()
            consult_stat = c_row["consultation_status"] if c_row else "NOT_STARTED"
            booking_stat = c_row["booking_status"] if c_row else "OPEN"

            status_updates = []

            for tid in token_ids:
                if not tid:
                    continue
                tid_str = str(tid).strip()
                if tid_str.isdigit():
                    cursor.execute("""
                        SELECT * FROM bookings WHERE booking_date = ? AND (id = ? OR token_number = ?)
                        ORDER BY queue_session DESC LIMIT 1;
                    """, (today_str, tid_str, int(tid_str)))
                    row = cursor.fetchone()
                    if not row:
                        cursor.execute("""
                            SELECT * FROM bookings WHERE id = ? OR token_number = ?
                            ORDER BY booking_date DESC, queue_session DESC LIMIT 1;
                        """, (tid_str, int(tid_str)))
                        row = cursor.fetchone()
                else:
                    cursor.execute("SELECT * FROM bookings WHERE id = ?;", (tid_str,))
                    row = cursor.fetchone()

                if row:
                    item = dict(row)
                    # Authoritative lifecycle status checks
                    if item["booking_date"] < today_str and item["status"] != "Completed":
                        if item["status"] != "Expired":
                            item["status"] = "Expired"
                            status_updates.append(item["id"])
                    elif item["booking_date"] == today_str:
                        if item["queue_session"] < cur_session and item["status"] == "Waiting":
                            item["status"] = "Expired"
                            status_updates.append(item["id"])

                    item["is_active"] = (
                        item["booking_date"] == today_str and
                        item["queue_session"] == cur_session and
                        item["status"] in ("Waiting", "Serving")
                    )
                    item["is_expired"] = (item["status"] == "Expired")

                    if not any(r["id"] == item["id"] for r in results):
                        results.append(item)

            if status_updates:
                placeholders = ",".join("?" for _ in status_updates)
                cursor.execute(f"UPDATE bookings SET status = 'Expired' WHERE id IN ({placeholders});", tuple(status_updates))
                conn.commit()

    return results


def update_token(token_number, updates, today_str=None, session_num=None):
    """Updates a booking's status/timestamps in SQLite."""
    if not today_str:
        today_str = date.today().isoformat()

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            if session_num is None:
                cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
                row = cursor.fetchone()
                session_num = row[0] if (row and row[0] is not None) else 1

            set_clauses = []
            values = []
            for k, v in updates.items():
                set_clauses.append(f"{k} = ?")
                values.append(v)
            values.extend([today_str, session_num, token_number])

            cursor.execute(f"""
                UPDATE bookings SET {', '.join(set_clauses)}
                WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
            """, tuple(values))
            conn.commit()

            return get_token_by_number(token_number, today_str, session_num)


# ==============================================================================
# QUEUE PROGRESSION & TRANSACTION-SAFE ADVANCEMENT
# ==============================================================================

def call_next_patient(today_str=None):
    """
    Transactionally completes the current serving patient in the active session,
    promotes the next waiting patient in the active session, records history with session,
    and updates queue state.
    """
    if not today_str:
        today_str = date.today().isoformat()

    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    created_at_str = now.strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")

            # 1. Determine active session
            cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
            row = cursor.fetchone()
            cur_session = row[0] if (row and row[0] is not None) else 1

            # Read current serving and last completed token before changes
            cursor.execute("""
                SELECT * FROM bookings WHERE booking_date = ? AND queue_session = ? AND status = 'Serving';
            """, (today_str, cur_session))
            prev_serving_rows = [dict(r) for r in cursor.fetchall()]
            prev_serving = prev_serving_rows[0] if prev_serving_rows else None

            cursor.execute("""
                SELECT last_completed_token FROM queue_state
                WHERE queue_date = ? AND queue_session = ?;
            """, (today_str, cur_session))
            q_row = cursor.fetchone()
            prev_last_comp = q_row["last_completed_token"] if q_row else 0

            # Find next waiting patient in this session
            cursor.execute("""
                SELECT * FROM bookings WHERE booking_date = ? AND queue_session = ? AND status = 'Waiting'
                ORDER BY token_number ASC LIMIT 1;
            """, (today_str, cur_session))
            next_waiting_row = cursor.fetchone()
            next_patient = dict(next_waiting_row) if next_waiting_row else None

            # 1. Complete previous serving patient
            if prev_serving:
                cursor.execute("""
                    UPDATE bookings SET status = 'Completed', completed_at = ?
                    WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
                """, (time_str, today_str, cur_session, prev_serving["token_number"]))

                cursor.execute("""
                    INSERT INTO queue_history (
                        queue_date, queue_session, booking_id, token_number, patient_name, patient_mobile,
                        source, started_at, completed_at, action, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completed', ?);
                """, (
                    today_str, cur_session, prev_serving["id"], prev_serving["token_number"],
                    prev_serving["patient_name"], prev_serving["patient_mobile"],
                    prev_serving["source"], prev_serving["started_at"], time_str, created_at_str
                ))

            # 2. Promote next patient if available
            if next_patient:
                cursor.execute("""
                    UPDATE bookings SET status = 'Serving', started_at = ?
                    WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
                """, (time_str, today_str, cur_session, next_patient["token_number"]))

                cursor.execute("""
                    INSERT INTO queue_history (
                        queue_date, queue_session, booking_id, token_number, patient_name, patient_mobile,
                        source, started_at, completed_at, action, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'Serving', ?);
                """, (
                    today_str, cur_session, next_patient["id"], next_patient["token_number"],
                    next_patient["patient_name"], next_patient["patient_mobile"],
                    next_patient["source"], time_str, created_at_str
                ))

                new_cur_tok = next_patient["token_number"]
                new_last_comp = prev_serving["token_number"] if prev_serving else prev_last_comp
                new_consult_stat = "IN_PROGRESS"
            else:
                new_cur_tok = None
                new_last_comp = prev_serving["token_number"] if prev_serving else prev_last_comp
                new_consult_stat = "COMPLETED"

            # 3. Update queue state for this session
            cursor.execute("""
                UPDATE queue_state
                SET current_token = ?, last_completed_token = ?, updated_at = ?
                WHERE queue_date = ? AND queue_session = ?;
            """, (new_cur_tok, new_last_comp, created_at_str, today_str, cur_session))

            cursor.execute("""
                UPDATE clinic_settings SET consultation_status = ?, updated_at = ? WHERE id = 1;
            """, (new_consult_stat, created_at_str))

            conn.commit()

        new_state = get_queue_state(today_str, cur_session)
        return True, new_state, next_patient


def complete_current_patient(today_str=None):
    """
    Marks the currently serving patient in the active session as Completed in SQLite without calling the next.
    """
    if not today_str:
        today_str = date.today().isoformat()

    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    created_at_str = now.strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")

            cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
            row = cursor.fetchone()
            cur_session = row[0] if (row and row[0] is not None) else 1

            cursor.execute("""
                SELECT * FROM bookings WHERE booking_date = ? AND queue_session = ? AND status = 'Serving';
            """, (today_str, cur_session))
            serving_row = cursor.fetchone()
            if not serving_row:
                conn.rollback()
                return False, "No patient is currently being served."

            serving_patient = dict(serving_row)

            cursor.execute("""
                UPDATE bookings SET status = 'Completed', completed_at = ?
                WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
            """, (time_str, today_str, cur_session, serving_patient["token_number"]))

            cursor.execute("""
                INSERT INTO queue_history (
                    queue_date, queue_session, booking_id, token_number, patient_name, patient_mobile,
                    source, started_at, completed_at, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Completed', ?);
            """, (
                today_str, cur_session, serving_patient["id"], serving_patient["token_number"],
                serving_patient["patient_name"], serving_patient["patient_mobile"],
                serving_patient["source"], serving_patient["started_at"], time_str, created_at_str
            ))

            cursor.execute("""
                SELECT COUNT(*) FROM bookings WHERE booking_date = ? AND queue_session = ? AND status = 'Waiting';
            """, (today_str, cur_session))
            waiting_c = cursor.fetchone()[0]
            new_consult = "COMPLETED"

            cursor.execute("""
                UPDATE queue_state
                SET current_token = NULL, last_completed_token = ?, updated_at = ?
                WHERE queue_date = ? AND queue_session = ?;
            """, (serving_patient["token_number"], created_at_str, today_str, cur_session))

            cursor.execute("""
                UPDATE clinic_settings SET consultation_status = ?, updated_at = ? WHERE id = 1;
            """, (new_consult, created_at_str))

            conn.commit()

        return True, get_queue_state(today_str, cur_session)


def is_undo_available(today_str=None, session_num=None):
    """
    Determines whether a one-level Undo action is available for today's active session.
    Undo is available ONLY if the most recent queue action in queue_history was
    a queue-progressing action ('Serving' or 'Completed') and has not already been undone.
    """
    if not today_str:
        today_str = date.today().isoformat()

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            if session_num is None:
                cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
                row = cursor.fetchone()
                active_session = row[0] if (row and row[0] is not None) else 1
            else:
                active_session = int(session_num)

            cursor.execute("""
                SELECT action FROM queue_history
                WHERE queue_date = ? AND queue_session = ?
                ORDER BY id DESC LIMIT 1;
            """, (today_str, active_session))
            last_action = cursor.fetchone()

            if not last_action:
                return False

            return last_action["action"] in ("Serving", "Completed")


def undo_last_action(today_str=None):
    """
    Restores the queue in the active session for the single most recent queue-changing action
    using only bookings, queue_state, queue_history, and clinic_settings.
    Supports ONE-LEVEL undo: once undone, no older undo is available until a new queue action occurs.
    """
    if not today_str:
        today_str = date.today().isoformat()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")

            cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
            row = cursor.fetchone()
            cur_session = row[0] if (row and row[0] is not None) else 1

            # Fetch the most recent action in queue_history for this date and session
            cursor.execute("""
                SELECT * FROM queue_history
                WHERE queue_date = ? AND queue_session = ?
                ORDER BY id DESC LIMIT 1;
            """, (today_str, cur_session))
            latest_action = cursor.fetchone()

            if not latest_action or latest_action["action"] not in ("Serving", "Completed"):
                conn.rollback()
                return False, "No queue action available to undo."

            latest_row = dict(latest_action)
            action_type = latest_row["action"]
            undone_tok = latest_row["token_number"]

            # Read current queue state
            cursor.execute("""
                SELECT current_token, last_completed_token FROM queue_state
                WHERE queue_date = ? AND queue_session = ?;
            """, (today_str, cur_session))
            q_row = cursor.fetchone()
            cur_tok = q_row["current_token"] if q_row else None
            last_comp_tok = q_row["last_completed_token"] if q_row else 0

            if action_type == "Serving":
                # A patient was promoted to Serving.
                # Check if this was a paired call (where a previous serving patient was completed in the same action)
                cursor.execute("""
                    SELECT * FROM queue_history
                    WHERE queue_date = ? AND queue_session = ? AND id < ?
                    ORDER BY id DESC LIMIT 1;
                """, (today_str, cur_session, latest_row["id"]))
                prev_action = cursor.fetchone()

                is_paired = (
                    prev_action is not None
                    and prev_action["action"] == "Completed"
                    and prev_action["id"] == latest_row["id"] - 1
                    and (prev_action["created_at"] == latest_row["created_at"] or prev_action["token_number"] == last_comp_tok)
                )

                # 1. Revert promoted patient from Serving back to Waiting
                cursor.execute("""
                    UPDATE bookings SET status = 'Waiting', started_at = NULL
                    WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
                """, (today_str, cur_session, latest_row["token_number"]))

                if is_paired:
                    prev_row = dict(prev_action)
                    prev_comp_tok = prev_row["token_number"]

                    # 2. Revert previous patient from Completed back to Serving
                    cursor.execute("""
                        UPDATE bookings SET status = 'Serving', completed_at = NULL
                        WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
                    """, (today_str, cur_session, prev_comp_tok))

                    # 3. Find what was last completed BEFORE prev_row
                    cursor.execute("""
                        SELECT token_number FROM queue_history
                        WHERE queue_date = ? AND queue_session = ? AND action = 'Completed' AND id < ?
                        ORDER BY id DESC LIMIT 1;
                    """, (today_str, cur_session, prev_row["id"]))
                    prior_comp = cursor.fetchone()
                    restored_last_comp = prior_comp["token_number"] if prior_comp else 0

                    restored_cur_tok = prev_comp_tok
                    restored_consult_stat = "IN_PROGRESS"
                else:
                    # No previous patient was completed in this action; queue was at start or paused
                    cursor.execute("""
                        SELECT token_number FROM queue_history
                        WHERE queue_date = ? AND queue_session = ? AND action = 'Completed' AND id < ?
                        ORDER BY id DESC LIMIT 1;
                    """, (today_str, cur_session, latest_row["id"]))
                    prior_comp = cursor.fetchone()
                    restored_last_comp = prior_comp["token_number"] if prior_comp else 0

                    restored_cur_tok = None
                    restored_consult_stat = "COMPLETED" if restored_last_comp > 0 else "NOT_STARTED"

                # 4. Restore queue_state
                cursor.execute("""
                    UPDATE queue_state
                    SET current_token = ?, last_completed_token = ?, updated_at = ?
                    WHERE queue_date = ? AND queue_session = ?;
                """, (restored_cur_tok, restored_last_comp, now_str, today_str, cur_session))

                # 5. Restore clinic_settings
                cursor.execute("""
                    UPDATE clinic_settings SET consultation_status = ?, updated_at = ? WHERE id = 1;
                """, (restored_consult_stat, now_str))

            elif action_type == "Completed":
                # A patient was completed with no next patient promoted (Complete Current, or Next with no waiting)
                comp_tok = latest_row["token_number"]

                # 1. Revert patient from Completed back to Serving
                cursor.execute("""
                    UPDATE bookings SET status = 'Serving', completed_at = NULL
                    WHERE booking_date = ? AND queue_session = ? AND token_number = ?;
                """, (today_str, cur_session, comp_tok))

                # 2. Find what was completed before this action
                cursor.execute("""
                    SELECT token_number FROM queue_history
                    WHERE queue_date = ? AND queue_session = ? AND action = 'Completed' AND id < ?
                    ORDER BY id DESC LIMIT 1;
                """, (today_str, cur_session, latest_row["id"]))
                prior_comp = cursor.fetchone()
                restored_last_comp = prior_comp["token_number"] if prior_comp else 0

                restored_cur_tok = comp_tok
                restored_consult_stat = "IN_PROGRESS"

                # 3. Restore queue_state
                cursor.execute("""
                    UPDATE queue_state
                    SET current_token = ?, last_completed_token = ?, updated_at = ?
                    WHERE queue_date = ? AND queue_session = ?;
                """, (restored_cur_tok, restored_last_comp, now_str, today_str, cur_session))

                # 4. Restore clinic_settings
                cursor.execute("""
                    UPDATE clinic_settings SET consultation_status = ?, updated_at = ? WHERE id = 1;
                """, (restored_consult_stat, now_str))

            # Record Undo in queue_history (marking that the previous action has been undone)
            cursor.execute("""
                INSERT INTO queue_history (
                    queue_date, queue_session, booking_id, token_number, patient_name, patient_mobile,
                    source, started_at, completed_at, action, created_at
                ) VALUES (?, ?, NULL, ?, 'Undo Action', '—', 'System', NULL, NULL, 'Undo', ?);
            """, (today_str, cur_session, undone_tok, now_str))

            conn.commit()

        return True, get_queue_state(today_str, cur_session)


def get_undo_stack_size(today_str=None, session_num=None):
    """Returns number of available undo actions for today's active session (1 or 0)."""
    return 1 if is_undo_available(today_str, session_num) else 0


# ==============================================================================
# SAFE QUEUE RESET & SESSION TRANSITIONS
# ==============================================================================

def reset_queue_session(today_str=None, expire_waiting=False):
    """
    Transactionally resets the daily queue session:
    - If expire_waiting=False: Rejects if any patient has status = 'Waiting'
    - If expire_waiting=True: Marks all remaining 'Waiting' patients as 'Expired'
    - Always rejects if any patient is currently 'Serving'
    - Creates the next queue session for today starting fresh from Token 1
    - Initializes current_token = NULL, last_completed_token = 0
    - Preserves all historical bookings, patient profiles, and audit history
    - Records an audit log entry in queue_history
    """
    if not today_str:
        today_str = date.today().isoformat()

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")

            # 1. Identify current active session
            cursor.execute("SELECT MAX(queue_session) FROM queue_state WHERE queue_date = ?;", (today_str,))
            row = cursor.fetchone()
            cur_session = row[0] if (row and row[0] is not None) else 1

            # 2. Check for serving patients in this session (cannot reset while serving)
            cursor.execute("""
                SELECT COUNT(*) FROM bookings
                WHERE booking_date = ? AND queue_session = ? AND status = 'Serving';
            """, (today_str, cur_session))
            serving_count = cursor.fetchone()[0]
            if serving_count > 0:
                conn.rollback()
                return False, "Queue cannot be reset while a patient is being served."

            # 3. Check / handle waiting patients
            cursor.execute("""
                SELECT id, token_number, patient_name, patient_mobile, source, started_at
                FROM bookings
                WHERE booking_date = ? AND queue_session = ? AND status = 'Waiting';
            """, (today_str, cur_session))
            waiting_rows = cursor.fetchall()

            if waiting_rows and not expire_waiting:
                conn.rollback()
                return False, "Queue cannot be reset. Some patients are still waiting."

            if waiting_rows and expire_waiting:
                cursor.execute("""
                    UPDATE bookings SET status = 'Expired'
                    WHERE booking_date = ? AND queue_session = ? AND status = 'Waiting';
                """, (today_str, cur_session))
                for w in waiting_rows:
                    cursor.execute("""
                        INSERT INTO queue_history (
                            queue_date, queue_session, booking_id, token_number, patient_name, patient_mobile,
                            source, started_at, completed_at, action, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'Expired', ?);
                    """, (
                        today_str, cur_session, w["id"], w["token_number"],
                        w["patient_name"], w["patient_mobile"], w["source"],
                        w["started_at"], now_str
                    ))

            # 4. Check for any other active/pending bookings (status NOT IN ('Completed', 'Expired'))
            cursor.execute("""
                SELECT COUNT(*) FROM bookings
                WHERE booking_date = ? AND queue_session = ? AND status NOT IN ('Completed', 'Expired');
            """, (today_str, cur_session))
            other_active = cursor.fetchone()[0]
            if other_active > 0:
                conn.rollback()
                return False, "Queue cannot be reset until all patients in the current queue are completed."

            # 5. Create the next queue session
            next_session = cur_session + 1
            cursor.execute("""
                INSERT INTO queue_state (queue_date, queue_session, current_token, last_completed_token, updated_at)
                VALUES (?, ?, NULL, 0, ?);
            """, (today_str, next_session, now_str))

            # 6. Reset consultation status to NOT_STARTED for the new session
            cursor.execute("""
                UPDATE clinic_settings SET consultation_status = 'NOT_STARTED', updated_at = ? WHERE id = 1;
            """, (now_str,))

            # 7. Record Session Closed/Reset in queue_history for audit trail
            cursor.execute("""
                INSERT INTO queue_history (
                    queue_date, queue_session, booking_id, token_number, patient_name, patient_mobile,
                    source, started_at, completed_at, action, created_at
                ) VALUES (?, ?, NULL, 0, 'Session Closed', '—', 'System', NULL, NULL, 'Reset', ?);
            """, (today_str, cur_session, now_str))

            conn.commit()

        new_state = get_queue_state(today_str, next_session)
        return True, "Daily queue has been reset successfully. A new queue session has started from Token 1."


# ==============================================================================
# AUDIT HISTORY & SEARCH QUERIES
# ==============================================================================

def get_queue_history(today_str=None, session=None):
    """
    Returns queue history records from SQLite in reverse chronological order (newest first).
    Supports optional filtering by queue_date and queue_session.
    If today_str is None or empty, returns all history across all available dates.
    """
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM queue_history"
            conditions = []
            params = []

            if today_str and str(today_str).strip():
                conditions.append("queue_date = ?")
                params.append(str(today_str).strip())

            if session is not None and str(session).strip() and str(session).strip().lower() != "all":
                try:
                    conditions.append("queue_session = ?")
                    params.append(int(session))
                except (ValueError, TypeError):
                    pass

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY id DESC;"
            cursor.execute(query, tuple(params))
            return [dict(r) for r in cursor.fetchall()]


def add_queue_history_record(record):
    """Directly inserts a queue history record into SQLite."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO queue_history (
                    queue_date, queue_session, booking_id, token_number, patient_name, patient_mobile,
                    source, started_at, completed_at, action, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                record.get("queue_date", date.today().isoformat()),
                record.get("queue_session", 1),
                record.get("booking_id"),
                record.get("token_number", 0),
                record.get("patient_name", ""),
                record.get("patient_mobile", ""),
                record.get("source", "Patient"),
                record.get("started_at"),
                record.get("completed_at"),
                record.get("action", "Serving"),
                now_str
            ))
            conn.commit()
            record["id"] = cursor.lastrowid
            return record


def search_bookings(query, today_str=None):
    """
    Searches bookings in SQLite by patient name, mobile, or token number.
    Returns matching bookings ordered by queue_session ASC, token_number ASC.
    """
    if not today_str:
        today_str = date.today().isoformat()

    q_clean = query.strip()
    with db_lock:
        with get_db() as conn:
            cursor = conn.cursor()
            if not q_clean:
                cursor.execute("""
                    SELECT * FROM bookings WHERE booking_date = ?
                    ORDER BY queue_session ASC, token_number ASC;
                """, (today_str,))
            else:
                wildcard = f"%{q_clean}%"
                cursor.execute("""
                    SELECT * FROM bookings
                    WHERE booking_date = ? AND (
                        patient_name LIKE ? OR
                        patient_mobile LIKE ? OR
                        CAST(token_number AS TEXT) = ?
                    )
                    ORDER BY queue_session ASC, token_number ASC;
                """, (today_str, wildcard, wildcard, q_clean))
            return [dict(r) for r in cursor.fetchall()]


# ==============================================================================
# AGGREGATED PAYLOAD & PROGRESS
# ==============================================================================

def get_full_queue_payload(today_str=None):
    """
    Aggregates full queue state for REST responses and Socket.IO broadcasts directly from SQLite.
    Current serving, waiting, and completed statistics are scoped to the active queue session.
    """
    if not today_str:
        today_str = date.today().isoformat()

    settings = get_clinic_settings()
    state = get_queue_state(today_str)
    cur_session = state.get("queue_session", 1)
    session_tokens = get_all_today_tokens(today_str, session_num=cur_session)

    serving = next((t for t in session_tokens if t["status"] == "Serving"), None)
    waiting = [t for t in session_tokens if t["status"] == "Waiting"]
    completed = [t for t in session_tokens if t["status"] == "Completed"]

    completed.sort(key=lambda x: x["token_number"], reverse=True)
    recently_completed = completed[:5]

    return {
        "clinic_settings": settings,
        "queue_state": state,
        "serving_patient": serving,
        "waiting_patients": waiting,
        "recently_completed": recently_completed,
        "total_issued": len(session_tokens),
        "waiting_count": len(waiting),
        "completed_count": len(completed),
        "undo_available": is_undo_available(today_str, cur_session)
    }


def get_patient_progress(identifier, today_str=None, session_num=None):
    """
    Calculates detailed queue position and wait details for a specific token number or booking ID from SQLite.
    Scoped to the patient token's queue session.
    """
    if not today_str:
        today_str = date.today().isoformat()

    token = None
    ident_str = str(identifier).strip()

    # 1. Try by unique booking ID first if not purely numeric
    if not ident_str.isdigit():
        token = get_token_by_id(ident_str)

    # 2. Try by token number if digits or integer
    if not token:
        try:
            tok_num = int(ident_str)
            token = get_token_by_number(tok_num, today_str, session_num)
        except (ValueError, TypeError):
            pass

    # 3. Fallback try by ID string
    if not token:
        token = get_token_by_id(ident_str)

    if not token:
        return None, "Token number not found."

    token_session = token.get("queue_session", 1)
    state = get_queue_state(today_str, session_num=token_session)
    session_tokens = get_all_today_tokens(today_str, session_num=token_session)

    serving_token = state.get("current_token")

    if token["status"] == "Waiting":
        patients_ahead = sum(
            1 for t in session_tokens
            if t["status"] == "Waiting" and t["token_number"] < token["token_number"]
        )
        queue_position = patients_ahead + 1
    elif token["status"] == "Serving":
        patients_ahead = 0
        queue_position = 0
    else:  # Completed
        patients_ahead = 0
        queue_position = 0

    completed = [t for t in session_tokens if t["status"] == "Completed"]
    completed.sort(key=lambda x: x["token_number"], reverse=True)
    recently_completed = completed[:5]

    active_queue = [
        {
            "id": t["id"],
            "token_number": t["token_number"],
            "status": t["status"],
            "source": t["source"]
        }
        for t in session_tokens if t["status"] in ["Serving", "Waiting"]
    ]

    return {
        "id": token["id"],
        "your_token": token["token_number"],
        "patient_name": token["patient_name"],
        "status": token["status"],
        "booking_time": token["booking_time"],
        "booking_date": token["booking_date"],
        "queue_session": token_session,
        "source": token["source"],
        "currently_serving": serving_token,
        "patients_ahead": patients_ahead,
        "queue_position": queue_position,
        "consultation_status": state.get("consultation_status", "IN_PROGRESS"),
        "booking_status": state.get("booking_status", "OPEN"),
        "recently_completed": recently_completed,
        "live_queue": active_queue
    }, None
