# CLINIC QUEUECARE
## Smart Clinic Token and Queue Management System
**SQLite Persistent Edition** &bull; *Flask + SQLite Backend + Modern Mobile-First Frontend*

---

## 1. Project Purpose & Overview
**Clinic QueueCare** is a production-style, real-time daily clinic token and queue management system with persistent SQLite storage. 

> [!IMPORTANT]
> **This is NOT an appointment scheduling system.** 
> It does not use calendars, time slots, or doctor selection. It manages the continuous, real-time progression of daily patient tokens from check-in through consultation to completion.

### Database Persistence Architecture
- **Persistent Single Source of Truth**: All application data (users, patients, daily tokens, queue progression, audit history, undo log, and clinic configuration) is permanently stored in SQLite at `database/clinic_queuecare.db`.
- **Survives Server Restarts**: When the Flask server stops and restarts, all bookings, current serving state, audit logs, and updated doctor settings remain intact.
- **Transaction Safety**: Atomic token creation and queue advancement use SQLite transactions (`BEGIN IMMEDIATE`) and a `UNIQUE(booking_date, token_number)` constraint to prevent duplicate tokens and race conditions.
- **Built-in `sqlite3`**: Uses Python's native standard library `sqlite3` module with zero external database dependencies or heavyweight ORMs.

---

## 2. Key Features

### Patient Role (No Account Required)
- **High-Level Home Overview**: Real-time display of Clinic Name, Doctor Specialization, Currently Serving Token, Total Tokens Issued Today, Booking Availability status (`OPEN` / `CLOSED`), and Consultation Status (`IN PROGRESS`).
- **Sequential Token Booking**: Dedicated booking form requiring only Patient Name and a valid 10-digit mobile number.
- **Booking Success Card**: Interactive confirmation card displaying the issued token number, patient name, and instant actions to View Receipt, Track Queue, or Book Another.
- **Family / Multi-Booking Memory**: Browser Local Storage tracks multiple token bookings (for self, children, parents, spouses) and queries live server statuses from SQLite.
- **Dedicated Queue Progress Tracking**: Live tracking showing Your Token, Currently Serving Token, Patients Ahead count, exact Queue Position, and visual queue flow.
- **Digital Receipt**: Instant thermal-style digital receipt with options to View Receipt, Print, or Download as PDF.

### Doctor Role (Secure Administration)
- **Secure Authentication**: Bcrypt-hashed credentials stored in SQLite with HTTP-only session cookies.
- **Live Queue Advancement**:
  - **Call Next Patient**: Completes the currently serving patient and advances the next waiting patient in sequential order.
  - **Complete Current Patient**: Marks the serving patient as completed.
  - **Undo Last Action**: Transactionally rolls back the single most recent queue action using existing bookings, queue_state, and queue_history. Supports one-level undo and survives server restarts!
- **Operational Controls**: Toggle online booking availability (`OPEN` vs `CLOSED`) and set consultation status (`NOT_STARTED`, `IN_PROGRESS`, `COMPLETED`). Persists in SQLite across restarts.
- **Today's Patient Roster**: Table on desktop, transforming automatically into stacked responsive cards on mobile.
- **Audit History**: Log of completed consultations and queue actions stored permanently in SQLite.
- **Clinic Settings (Single Source of Truth)**: Edit Clinic Name, Doctor Name, Specialization, Timings, and Daily Token Limits. Updates dynamically reflect across the entire system instantly via WebSocket.

### Receptionist Role (Operational Front Desk)
- **Dedicated Operational Portal**: Visually distinct green/teal theme tailored for high-speed counter check-ins.
- **Walk-in & Phone Bookings**: Issue sequential tokens with sources labeled `Walk-in` or `Phone`.
- **Live Booking Search**: Instant SQL-backed search filter by Patient Name, Mobile Number, or Token Number.
- **Reprint Receipts**: View and reprint thermal digital receipts for patients at the counter.
- **Strict Server-Side Authorization**: Receptionists are prevented from calling next, completing patients, undoing actions, opening/closing bookings, or altering clinic settings (returns `403 Forbidden`).

---

## 3. Technology Stack

- **Backend**: Python 3.9+ (Python 3.14 supported), Flask, Flask-SocketIO (WebSocket updates), Flask-CORS, bcrypt, python-dotenv
- **Database**: SQLite (via Python built-in `sqlite3` module)
- **Frontend**: Semantic HTML5, Mobile-First Responsive CSS3 (CSS Variables, Flexbox/Grid, Print Stylesheet), Vanilla JavaScript (ES6+), Socket.IO client
- **Real-Time Communication**: WebSocket / Socket.IO events (`queue:update`, `booking:created`, `settings:update`)
- **Receipts**: Native browser print & PDF preview

---

## 4. Database Architecture & Schema

### Database File Location
The SQLite database is located at:
```
database/clinic_queuecare.db
```
The database file is directly readable with tools like **DB Browser for SQLite**, **SQLiteStudio**, or **DBeaver**.

### Main Tables

| Table | Purpose | Key Columns / Constraints |
| :--- | :--- | :--- |
| **`users`** | Staff authentication (Doctor & Receptionist) | `id`, `username` (UNIQUE), `password_hash` (bcrypt), `role`, `full_name`, `specialization`, `created_at` |
| **`patients`** | Registered patient profiles | `id`, `name`, `mobile`, `created_at` |
| **`bookings`** | Daily token bookings across sessions/shifts | `id` (PK), `token_number`, `patient_id` (FK), `patient_name`, `patient_mobile`, `source`, `booking_date`, `queue_session`, `booking_time`, `status`, `started_at`, `completed_at`, `created_at`, `UNIQUE(booking_date, queue_session, token_number)` |
| **`queue_state`** | Daily active queue state per session | `id`, `queue_date`, `queue_session`, `current_token`, `last_completed_token`, `updated_at`, `UNIQUE(queue_date, queue_session)` |
| **`queue_history`** | Consultation audit history log | `id`, `queue_date`, `queue_session`, `booking_id`, `token_number`, `patient_name`, `patient_mobile`, `source`, `started_at`, `completed_at`, `action`, `created_at` |
| **`clinic_settings`** | Global clinic configuration | `id` (CHECK id=1), `clinic_name`, `doctor_name`, `doctor_specialization`, `clinic_start_time`, `clinic_end_time`, `daily_token_limit`, `booking_status`, `consultation_status`, `updated_at` |

---

## 5. Project Structure

```
Clinic_Queue_First/
├── client/
│   ├── index.html              # Patient interface (Home, Book, My Bookings, Progress, Receipt)
│   ├── doctor-login.html       # Doctor portal authentication
│   ├── doctor.html             # Doctor control dashboard (Queue Actions, Reset Daily Queue, History)
│   ├── reception-login.html    # Receptionist authentication
│   ├── reception.html          # Reception front-desk dashboard
│   ├── css/
│   │   └── style.css           # Responsive mobile-first healthcare design & thermal print CSS
│   └── js/
│       ├── app.js              # Global configuration, dynamic API discovery, Socket.IO, toasts
│       ├── patient.js          # Patient view switcher, token booking, multi-booking tracker
│       ├── doctor.js           # Doctor queue controls, reset modal, roster, filtered history
│       └── reception.js        # Reception intake, search filter, receipt reprinting
│
├── database/
│   └── clinic_queuecare.db     # Persistent SQLite database file
│
├── server/
│   ├── app.py                  # Flask entry point, SocketIO server, static client host
│   ├── database.py             # Central SQLite connection, schema, queries & multi-shift sessions
│   ├── auth.py                 # Bcrypt hashing, session cookies, role decorators
│   ├── queue.py                # Bridge for queue operations
│   ├── routes.py               # REST API endpoints (Public, Patient, Doctor, Reception)
│   ├── websocket.py            # Socket.IO event handlers and broadcasters
│   ├── data.py                 # Backward-compatibility layer delegating to database.py
│   ├── requirements.txt        # Python dependency manifest
│   └── .env                    # Secret key, Host (0.0.0.0), Port (5000)
│
├── run.py                      # Root launcher
├── test_queue_sessions.py      # Automated multi-shift session & safe queue reset test suite (10 tests)
├── test_verification.py        # Automated end-to-end API test suite (5 tests)
├── test_sqlite_persistence.py  # Automated SQLite server restart persistence test suite (8 tests)
└── README.md
```

---

## 6. Installation & Setup

### Prerequisites
- Python 3.9+ (Python 3.14 tested and supported)
- `pip` package manager

### 1. Install Dependencies
Open PowerShell or your terminal in the project directory:

```bash
cd server
pip install -r requirements.txt
```

---

## 7. How to Run the Application

### Option A: Root Launcher (Recommended)
From the project root directory:

```bash
python run.py
```

### Option B: From the `server/` Directory
```bash
cd server
python app.py
```

Open your browser at:
- **Patient Portal**: [http://localhost:5000](http://localhost:5000)
- **Doctor Portal**: [http://localhost:5000/doctor-login.html](http://localhost:5000/doctor-login.html)
- **Reception Desk**: [http://localhost:5000/reception-login.html](http://localhost:5000/reception-login.html)

### Mobile Network Testing
Because the backend listens on `0.0.0.0:5000` and the frontend discovers `window.location.hostname` automatically:
- Connect your phone and computer to the same Wi-Fi network.
- Open `http://<your-computer-ip>:5000` on your mobile phone browser.

---

## 8. Development Login Credentials

> [!NOTE]
> For security and clean UI design, demo credentials are **not** displayed on the login forms. Use the following internal development accounts for testing:

| Role | Username | Password | Access URL |
| :--- | :--- | :--- | :--- |
| **Doctor** | `doctor` | `doctor123` | `/doctor-login.html` |
| **Receptionist** | `reception` | `reception123` | `/reception-login.html` |

Passwords are stored as bcrypt hashes in SQLite.

---

## 9. Running Verification Tests

Run the full end-to-end API verification test suite:
```bash
python test_verification.py
```

Run the dedicated SQLite persistence and server restart simulation test suite:
```bash
python test_sqlite_persistence.py
```
