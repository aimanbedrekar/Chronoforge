# ChronoForge — System Update & Authentication Guide

This document explains the authentication system, role-based redirection logic, Admin Dashboard, and **Network Diagnostics Page** added to **ChronoForge**, along with instructions on how to run, test, and manually customize the application.

---

## 🚀 1. Overview of Tasks & Features Built

### **Task 1: Authentication & Admin Dashboard**
> *"Add a login page on starting with authentication system with a proper working admin dashboard which contain all the admin related stuff with statistics. When user login or signup then they will redirect to real page when admin login admin redirect to admin dashboard, same for normal user."*

### **Task 2: Network Diagnostics & Wi-Fi Monitor**
> *"Want to create a page or diagnostic like (ESP32 Offline) for network college wifi. One page to verify wifi is connected or not (network diagnostic). If connected to network show Network online, if not offline."*
> **Mechanical Department Wi-Fi Credentials:** `SSID: Mech` | `Password: Mech@123`

---

### **Features Built:**

1. **Authentication System (Login & Sign Up)**
   - Secure SQLite user persistence with Werkzeug password hashing.
   - Session token authentication.
   - Starting login/signup screen (`#view-auth`) with modern glassmorphism UI.
   - Quick Demo account sign-in buttons for easy testing.

2. **Role-Based Redirection**
   - **Normal Users (`role = "user"`)** → Redirected to the **Real Page** (Main Timetable Dashboard & Bell System).
   - **Administrators (`role = "admin"`)** → Redirected to the **Admin Dashboard**.
   - Automatic route protection (normal users attempting to view the admin dashboard are restricted and returned to the real page).

3. **Admin Dashboard with Live Statistics**
   - **4 Visual Analytics Cards**: Users Community, Schedule Versions, ESP32 Link Status, Audit Logs.
   - **User Management Directory**: Promote/demote user roles (`Admin` ↔ `User`), delete users, or register new users inline.
   - **System Operations & Diagnostics**: Live hardware Mock Mode toggle, manual bell test pulse, historical schedule purge, clear event logs.

4. **🌐 Network Diagnostics Page (`#view-diagnostics`)**
   - **Hero Network Banner**:
     - 🟢 **NETWORK ONLINE**: Glowing green backdrop when connected to Wi-Fi & ESP32 is reachable (displays response latency in ms).
     - 🔴 **NETWORK OFFLINE**: Red backdrop when Wi-Fi or ESP32 hardware node is unreachable.
     - ⚡ **DEV MOCK MODE**: Gold badge when running in development mock mode.
   - **Wi-Fi Connection Node Card**: Shows College Wi-Fi SSID (`en24270776`), Password (`Skn@9146777532` with show/hide toggle), Server Local IP, and Connection Status.
   - **ESP32 Hardware Node Card**: Shows ESP32 IP (`192.168.1.100`), Port (`80`), Ping Latency (ms), and Wi-Fi Signal Strength (RSSI dBm).
   - **Diagnostic Troubleshooting Checklist**: Dynamic guidance providing step-by-step resolution advice if the hardware goes offline.

---

## 🛠️ 2. Technical Implementation Details

### **A. Database Schema (`backend/app.py`)**
Tables created in `chronoforge.db`:

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### **B. Seeded Default Accounts & Credentials**
- **Admin Account**: Username `admin` | Password `admin123` | Role `admin`
- **User Account**: Username `user` | Password `user123` | Role `user`
- **College Wi-Fi Credentials**: SSID `en24270776` | Password `Skn@9146777532`

### **C. REST API Endpoints Added**

| Method | Endpoint | Access | Description |
|--------|----------|--------|-------------|
| `POST` | `/api/auth/login` | Public | Authenticates credentials, returns session token & user role |
| `POST` | `/api/auth/signup` | Public | Registers a new user account (role: `user` or `admin`) |
| `POST` | `/api/auth/logout` | Logged In | Destroys current session token |
| `GET`  | `/api/auth/me` | Logged In | Returns current authenticated user profile |
| `GET`  | `/api/network/diagnostics` | Public | Runs real-time Wi-Fi & ESP32 network ping test & latency check |
| `GET`  | `/api/admin/stats` | Admin | Returns system statistics (users, schedules, logs, ESP32 status) |
| `GET`  | `/api/admin/users` | Admin | Returns list of all registered users |
| `POST` | `/api/admin/users` | Admin | Creates a user account from the admin dashboard |
| `PUT`  | `/api/admin/users/<id>/role` | Admin | Updates a user's role (`admin` or `user`) |
| `DELETE`| `/api/admin/users/<id>` | Admin | Deletes a user account |
| `POST` | `/api/admin/logs/clear` | Admin | Clears all activity logs |
| `POST` | `/api/admin/schedules/purge` | Admin | Purges historical schedule versions |

---

## 🏃 3. How to Run and Test the Application

### **Step 1: Install Python Dependencies**
Ensure you have Python 3.10+ installed, then install required packages:

```bash
cd backend
pip install -r requirements.txt
```

### **Step 2: Start the Backend Server**
```bash
python app.py
```

Output should show:
```
CHRONOFORGE — SMART INSTITUTIONAL BELL SYSTEM
Website  : http://127.0.0.1:5000
Health   : http://127.0.0.1:5000/api/health
```

### **Step 3: Open in Browser**
Navigate to 👉 **`http://127.0.0.1:5000`**

---

### **Testing User Flows:**

#### **Test 1: Network Diagnostics Page**
1. Log in as `admin` or `user`.
2. Click **🌐 Diagnostics** in the top navigation bar.
3. Observe the prominent **Hero Status Banner** (Green `NETWORK ONLINE`, Red `NETWORK OFFLINE`, or Gold `DEV MOCK MODE`).
4. Click **⚡ Run Ping Test** or toggle **Auto-Scan (5s)** to run live ping tests.
5. Click **Show** under Wi-Fi Password to view the College Wi-Fi password (`Skn@9146777532`).

#### **Test 2: Admin Flow**
1. On the starting screen, click **⚡ Login as Admin (admin)**.
2. **Verification**: Redirected to **Admin Dashboard** (`#view-admindashboard`).
3. Inspect stat cards, user directory, or toggle Mock Mode.
4. Click **⚡ Go to Real Page** to switch to the main Timetable Dashboard.

#### **Test 3: Normal User Flow**
1. Log out, then click **👤 Login as User (user)**.
2. **Verification**: Redirected to the **Real Page** (Main Dashboard).
3. **Verification**: The **Admin Dashboard** nav link is hidden and access is restricted.

---

## ✏️ 4. How to Manually Change Anything

### **A. How to Change Wi-Fi Credentials**
1. **In Backend / Settings**: Open **Settings** on the website or edit `wifi_ssid` and `wifi_password` defaults in `backend/app.py` (~Line 180).
2. **In ESP32 Firmware**: Open `esp32/chronoforge_esp32.ino` and edit lines 53-54:
   ```cpp
   const char* WIFI_SSID     = "Mech";
   const char* WIFI_PASSWORD = "Mech@123";
   ```

### **B. How to Change Default Seed Passwords**
Open `backend/app.py` and search for `init_db()`. Look for lines ~200-215:
```python
admin_pw = generate_password_hash("YourNewAdminPassword")
```
> 💡 If you modify seed accounts, delete `backend/chronoforge.db` and restart `python app.py` to re-initialize with new seed data.

---

## 📄 File Sitemap

- `backend/app.py` — Flask server, SQLite database, Multi-Admin Auth & Diagnostics REST APIs.
- `esp32/chronoforge_esp32.ino` — ESP32 firmware configured for Wi-Fi `Mech` with Cloud Heartbeat.
- `frontend/index.html` — HTML containing Auth view, Diagnostics view (`#view-diagnostics`), Multi-Admin view, and Real Page views.
- `frontend/style.css` — Styling for Auth screen, Diagnostics hero banner, and Admin cards.
- `frontend/script.js` — Frontend logic, real-time ping scanner, auto-scan timers, and role guards.
- `NEW-README.md` — This documentation file.
