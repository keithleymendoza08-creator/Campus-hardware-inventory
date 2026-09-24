# Laboratorysystem.py - NU Laboratory Hardware System
# Roles: STUDENT / EMPLOYEE (User), LABORATORY_TECHNICIAN / FACULTY_MEMBER (Admin)
# Features: Beginning Balance -> Borrowed -> Ending Balance + Days + Damage/Payment + Profile Pic + Reset

import sqlite3
import logging
import os
from datetime import datetime, timedelta

DATABASE = 'hardware_inventory.db'
os.makedirs('app_logging', exist_ok=True)
logging.basicConfig(filename='app_logging/app.log', level=logging.INFO, format='%(asctime)s %(message)s')

def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def _add_column(conn, table, col_def):
    col_name = col_def.split()[0]
    cols = [r['name'] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")

def init_system():
    conn = get_connection()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            fullname TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hardware (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            category TEXT DEFAULT 'General',
            total_quantity INTEGER DEFAULT 0,
            available INTEGER DEFAULT 0,
            borrowed INTEGER DEFAULT 0,
            unit_price REAL DEFAULT 0,
            location TEXT DEFAULT 'Lab A'
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            hardware_id INTEGER,
            type TEXT,
            beginning_balance INTEGER,
            quantity INTEGER,
            ending_balance INTEGER,
            borrow_days INTEGER DEFAULT 3,
            expected_return DATE,
            actual_return DATE,
            status TEXT DEFAULT 'Pending',
            return_status TEXT DEFAULT 'Pending',
            damage_status TEXT DEFAULT 'Good',
            damage_remarks TEXT,
            payment_amount REAL DEFAULT 0,
            payment_status TEXT DEFAULT 'None',
            remarks TEXT,
            date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_approved TIMESTAMP,
            approved_by INTEGER
        );
    ''')
    _add_column(conn, "hardware", "unit_price REAL DEFAULT 0")
    _add_column(conn, "transactions", "borrow_days INTEGER DEFAULT 3")
    _add_column(conn, "transactions", "expected_return DATE")
    _add_column(conn, "transactions", "actual_return DATE")
    _add_column(conn, "transactions", "return_status TEXT DEFAULT 'Pending'")
    _add_column(conn, "transactions", "damage_status TEXT DEFAULT 'Good'")
    _add_column(conn, "transactions", "damage_remarks TEXT")
    _add_column(conn, "transactions", "payment_amount REAL DEFAULT 0")
    _add_column(conn, "transactions", "payment_status TEXT DEFAULT 'None'")
    # FOR PROFILE PIC AND RESET PASSWORD
    _add_column(conn, "users", "profile_pic TEXT DEFAULT 'default.png'")
    _add_column(conn, "users", "reset_token TEXT DEFAULT NULL")
    _add_column(conn, "users", "reset_token_expiry TIMESTAMP DEFAULT NULL")

    if conn.execute("SELECT COUNT(*) as c FROM hardware").fetchone()['c'] == 0:
        conn.executemany("INSERT INTO hardware (name, category, total_quantity, available, borrowed, unit_price, location) VALUES (?,?,?,?,?,?,?)", [
            ('Arduino Uno R3', 'Microcontroller', 20, 20, 0, 400, 'Lab A'),
            ('Raspberry Pi 4 4GB', 'SBC', 10, 10, 0, 2500, 'Lab B'),
            ('Breadboard 830pts', 'Prototyping', 50, 50, 0, 120, 'Lab A'),
            ('Servo Motor MG90S', 'Actuator', 15, 15, 0, 350, 'Stock Room'),
            ('DHT11 Sensor', 'Sensor', 30, 30, 0, 95, 'Lab A'),
            ('Jumper Wires M-M', 'Accessories', 100, 100, 0, 50, 'Stock Room'),
        ])
    conn.commit()
    conn.close()

# --- USER BORROW/RETURN ---
def request_borrow(user_id, hw_id, qty, days, remarks):
    conn = get_connection()
    hw = conn.execute("SELECT * FROM hardware WHERE id=?", (hw_id,)).fetchone()
    if not hw:
        conn.close()
        return False, "Hardware not found"
    if qty > hw['available']:
        conn.close()
        return False, f"Insufficient stock! Ending Balance Available: {hw['available']}"
    exp = (datetime.now() + timedelta(days=int(days))).strftime('%Y-%m-%d')
    conn.execute("""
        INSERT INTO transactions
        (user_id, hardware_id, type, beginning_balance, quantity, ending_balance, borrow_days, expected_return, status, return_status, remarks)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (user_id, hw_id, 'BORROW', hw['available'], qty, hw['available']-qty, int(days), exp, 'Pending', 'Pending', remarks))
    conn.commit()
    conn.close()
    return True, f"Borrow request submitted! Expected return: {exp}"

def request_return(trans_id):
    conn = get_connection()
    conn.execute("UPDATE transactions SET return_status='For Checking' WHERE id=?", (trans_id,))
    conn.commit()
    conn.close()

def pay_damage(trans_id):
    conn = get_connection()
    conn.execute("UPDATE transactions SET payment_status='Paid' WHERE id=?", (trans_id,))
    conn.commit()
    conn.close()

# --- ADMIN ---
def approve_borrow(trans_id, admin_id):
    conn = get_connection()
    t = conn.execute("SELECT * FROM transactions WHERE id=?", (trans_id,)).fetchone()
    hw = conn.execute("SELECT * FROM hardware WHERE id=?", (t['hardware_id'],)).fetchone()
    beg = hw['available']
    if beg < t['quantity']:
        conn.execute("UPDATE transactions SET status='Rejected' WHERE id=?", (trans_id,))
        conn.commit()
        conn.close()
        return False, f"Rejected - insufficient stock. Ending: {beg}"
    new_end = beg - t['quantity']
    conn.execute("UPDATE hardware SET available=?, borrowed=borrowed+? WHERE id=?", (new_end, t['quantity'], hw['id']))
    conn.execute("UPDATE transactions SET beginning_balance=?, ending_balance=?, status='Approved', date_approved=?, approved_by=? WHERE id=?",
                 (beg, new_end, datetime.now(), admin_id, trans_id))
    conn.commit()
    conn.close()
    return True, f"Approved! New Ending Balance: {new_end}"

def admin_check_return(trans_id, condition, remarks, payment):
    conn = get_connection()
    t = conn.execute("SELECT * FROM transactions WHERE id=?", (trans_id,)).fetchone()
    hw = conn.execute("SELECT * FROM hardware WHERE id=?", (t['hardware_id'],)).fetchone()
    beg = hw['available']
    if condition == 'Good':
        new_end = beg + t['quantity']
        conn.execute("UPDATE hardware SET available=?, borrowed=borrowed-? WHERE id=?", (new_end, t['quantity'], hw['id']))
        conn.execute("UPDATE transactions SET return_status='Complete', damage_status='Good', actual_return=?, status='Returned' WHERE id=?",
                     (datetime.now().strftime('%Y-%m-%d'), trans_id))
    else:
        conn.execute("UPDATE hardware SET borrowed=borrowed-? WHERE id=?", (t['quantity'], hw['id']))
        conn.execute("UPDATE transactions SET return_status='Damage', damage_status='Damage', damage_remarks=?, payment_amount=?, payment_status='Unpaid', actual_return=?, status='Returned' WHERE id=?",
                     (remarks, payment, datetime.now().strftime('%Y-%m-%d'), trans_id))
        new_end = beg
    conn.commit()
    conn.close()
    return new_end

def add_or_restock_hardware(name, category, qty, location, price, admin_id):
    conn = get_connection()
    hw = conn.execute("SELECT * FROM hardware WHERE name=?", (name,)).fetchone()
    if hw:
        new_end = hw['available'] + int(qty)
        conn.execute("UPDATE hardware SET total_quantity=total_quantity+?, available=?, unit_price=?, location=? WHERE id=?",
                     (qty, new_end, price, location, hw['id']))
    else:
        conn.execute("INSERT INTO hardware (name, category, total_quantity, available, borrowed, unit_price, location) VALUES (?,?,?,?,?,?,?)",
                     (name, category, qty, qty, 0, price, location))
    conn.commit()
    conn.close()

def edit_hardware(hw_id, name, category, available, price, location):
    conn = get_connection()
    old = conn.execute("SELECT * FROM hardware WHERE id=?", (hw_id,)).fetchone()
    diff = int(available) - int(old['available'])
    conn.execute("UPDATE hardware SET name=?, category=?, available=?, total_quantity=total_quantity+?, unit_price=?, location=? WHERE id=?",
                 (name, category, available, diff, price, location, hw_id))
    conn.commit()
    conn.close()

def delete_hardware(hw_id):
    conn = get_connection()
    conn.execute("DELETE FROM hardware WHERE id=?", (hw_id,))
    conn.execute("DELETE FROM transactions WHERE hardware_id=?", (hw_id,))
    conn.commit()
    conn.close()

# --- FOR TRANSACTIONS / PROFILE / RESET PASSWORD ---
def get_user_profile(user_id):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return user

def get_user_by_email(email):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    return user

def get_transactions_ledger(user_id=None):
    conn = get_connection()
    if user_id:
        logs = conn.execute("""
            SELECT t.*, u.fullname, h.name as hname, h.category
            FROM transactions t
            JOIN users u ON u.id=t.user_id
            JOIN hardware h ON h.id=t.hardware_id
            WHERE t.user_id=? ORDER BY t.date_created DESC
        """, (user_id,)).fetchall()
    else:
        logs = conn.execute("""
            SELECT t.*, u.fullname, h.name as hname, h.category
            FROM transactions t
            JOIN users u ON u.id=t.user_id
            JOIN hardware h ON h.id=t.hardware_id
            ORDER BY t.date_created DESC
        """).fetchall()
    conn.close()
    return logs

# --- PROFILE PIC (user_3.png logic) ---
def update_profile_pic(user_id, filename):
    conn = get_connection()
    conn.execute("UPDATE users SET profile_pic=? WHERE id=?", (filename, user_id))
    conn.commit()
    conn.close()
    return True

# --- RESET PASSWORD ---
def update_password(user_id, new_hashed_password):
    conn = get_connection()
    conn.execute("UPDATE users SET password=?, reset_token=NULL, reset_token_expiry=NULL WHERE id=?", (new_hashed_password, user_id))
    conn.commit()
    conn.close()

def set_reset_token(email, token, expiry):
    conn = get_connection()
    conn.execute("UPDATE users SET reset_token=?, reset_token_expiry=? WHERE email=?", (token, expiry, email))
    conn.commit()
    conn.close()

def get_user_by_reset_token(token):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE reset_token=?", (token,)).fetchone()
    conn.close()
    return user