# Laboratorysystem.py - NU Laboratory Hardware System (Supabase PostgreSQL Version)
# Roles: STUDENT / EMPLOYEE (User), LABORATORY_TECHNICIAN / FACULTY_MEMBER (Admin)
# Features: Beginning Balance -> Borrowed -> Ending Balance + Days + Damage/Payment + Profile Pic + Reset

import psycopg
from psycopg.rows import dict_row
import logging
import os
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres.hudetzzomizjnygxkjqu:Cinley%40063004@aws-0-ap-southeast-1.pooler.southeast-1.pooler.supabase.com:6543/postgres?sslmode=require'
)

os.makedirs('app_logging', exist_ok=True)
logging.basicConfig(filename='app_logging/app.log', level=logging.INFO, format='%(asctime)s %(message)s')

def get_connection():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def _add_column_if_not_exists(conn, table, col_name, col_type):
    with conn.cursor() as cur:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type};")

def init_system():
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    student_id TEXT UNIQUE NOT NULL,
                    fullname TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL,
                    course TEXT DEFAULT '',
                    section TEXT DEFAULT '',
                    department TEXT DEFAULT '',
                    profile_pic TEXT DEFAULT 'default.png',
                    reset_token TEXT DEFAULT NULL,
                    reset_token_expiry TIMESTAMP DEFAULT NULL
                );
                CREATE TABLE IF NOT EXISTS hardware (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    category TEXT DEFAULT 'General',
                    total_quantity INTEGER DEFAULT 0,
                    available INTEGER DEFAULT 0,
                    borrowed INTEGER DEFAULT 0,
                    unit_price REAL DEFAULT 0,
                    location TEXT DEFAULT 'Lab A'
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
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
            conn.commit()

        # Schema migrations / safety column additions
        _add_column_if_not_exists(conn, "hardware", "unit_price", "REAL DEFAULT 0")
        _add_column_if_not_exists(conn, "transactions", "borrow_days", "INTEGER DEFAULT 3")
        _add_column_if_not_exists(conn, "transactions", "expected_return", "DATE")
        _add_column_if_not_exists(conn, "transactions", "actual_return", "DATE")
        _add_column_if_not_exists(conn, "transactions", "return_status", "TEXT DEFAULT 'Pending'")
        _add_column_if_not_exists(conn, "transactions", "damage_status", "TEXT DEFAULT 'Good'")
        _add_column_if_not_exists(conn, "transactions", "damage_remarks", "TEXT")
        _add_column_if_not_exists(conn, "transactions", "payment_amount", "REAL DEFAULT 0")
        _add_column_if_not_exists(conn, "transactions", "payment_status", "TEXT DEFAULT 'None'")
        _add_column_if_not_exists(conn, "users", "profile_pic", "TEXT DEFAULT 'default.png'")
        _add_column_if_not_exists(conn, "users", "reset_token", "TEXT DEFAULT NULL")
        _add_column_if_not_exists(conn, "users", "reset_token_expiry", "TIMESTAMP DEFAULT NULL")

        with conn.cursor() as cur:
            count = cur.execute("SELECT COUNT(*) as c FROM hardware").fetchone()['c']
            if count == 0:
                items = [
                    ('Arduino Uno R3', 'Microcontroller', 20, 20, 0, 400, 'Lab A'),
                    ('Raspberry Pi 4 4GB', 'SBC', 10, 10, 0, 2500, 'Lab B'),
                    ('Breadboard 830pts', 'Prototyping', 50, 50, 0, 120, 'Lab A'),
                    ('Servo Motor MG90S', 'Actuator', 15, 15, 0, 350, 'Stock Room'),
                    ('DHT11 Sensor', 'Sensor', 30, 30, 0, 95, 'Lab A'),
                    ('Jumper Wires M-M', 'Accessories', 100, 100, 0, 50, 'Stock Room')
                ]
                for item in items:
                    cur.execute(
                        "INSERT INTO hardware (name, category, total_quantity, available, borrowed, unit_price, location) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        item
                    )
                conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Init system error: {e}")

# --- USER BORROW/RETURN ---
def request_borrow(user_id, hw_id, qty, days, remarks):
    conn = get_connection()
    with conn.cursor() as cur:
        hw = cur.execute("SELECT * FROM hardware WHERE id=%s", (hw_id,)).fetchone()
        if not hw:
            conn.close()
            return False, "Hardware not found"
        if qty > hw['available']:
            conn.close()
            return False, f"Insufficient stock! Ending Balance Available: {hw['available']}"
        exp = (datetime.now() + timedelta(days=int(days))).strftime('%Y-%m-%d')
        cur.execute("""
            INSERT INTO transactions
            (user_id, hardware_id, type, beginning_balance, quantity, ending_balance, borrow_days, expected_return, status, return_status, remarks)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (user_id, hw_id, 'BORROW', hw['available'], qty, hw['available']-qty, int(days), exp, 'Pending', 'Pending', remarks))
        conn.commit()
    conn.close()
    return True, f"Borrow request submitted! Expected return: {exp}"

def request_return(trans_id):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE transactions SET return_status='For Checking' WHERE id=%s", (trans_id,))
        conn.commit()
    conn.close()

def pay_damage(trans_id):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE transactions SET payment_status='Paid' WHERE id=%s", (trans_id,))
        conn.commit()
    conn.close()

# --- ADMIN ---
def approve_borrow(trans_id, admin_id):
    conn = get_connection()
    with conn.cursor() as cur:
        t = cur.execute("SELECT * FROM transactions WHERE id=%s", (trans_id,)).fetchone()
        if not t:
            conn.close()
            return False, "Transaction not found."
        hw = cur.execute("SELECT * FROM hardware WHERE id=%s", (t['hardware_id'],)).fetchone()
        beg = hw['available']
        if beg < t['quantity']:
            cur.execute("UPDATE transactions SET status='Rejected' WHERE id=%s", (trans_id,))
            conn.commit()
            conn.close()
            return False, f"Rejected - insufficient stock. Ending: {beg}"
        new_end = beg - t['quantity']
        cur.execute("UPDATE hardware SET available=%s, borrowed=borrowed+%s WHERE id=%s", (new_end, t['quantity'], hw['id']))
        cur.execute("UPDATE transactions SET beginning_balance=%s, ending_balance=%s, status='Approved', date_approved=%s, approved_by=%s WHERE id=%s",
                    (beg, new_end, datetime.now(), admin_id, trans_id))
        conn.commit()
    conn.close()
    return True, f"Approved! New Ending Balance: {new_end}"

def admin_check_return(trans_id, condition, remarks, payment):
    conn = get_connection()
    with conn.cursor() as cur:
        t = cur.execute("SELECT * FROM transactions WHERE id=%s", (trans_id,)).fetchone()
        hw = cur.execute("SELECT * FROM hardware WHERE id=%s", (t['hardware_id'],)).fetchone()
        beg = hw['available']
        if condition == 'Good':
            new_end = beg + t['quantity']
            cur.execute("UPDATE hardware SET available=%s, borrowed=borrowed-%s WHERE id=%s", (new_end, t['quantity'], hw['id']))
            cur.execute("UPDATE transactions SET return_status='Complete', damage_status='Good', actual_return=%s, status='Returned' WHERE id=%s",
                        (datetime.now().strftime('%Y-%m-%d'), trans_id))
        else:
            cur.execute("UPDATE hardware SET borrowed=borrowed-%s WHERE id=%s", (t['quantity'], hw['id']))
            cur.execute("UPDATE transactions SET return_status='Damage', damage_status='Damage', damage_remarks=%s, payment_amount=%s, payment_status='Unpaid', actual_return=%s, status='Returned' WHERE id=%s",
                        (remarks, payment, datetime.now().strftime('%Y-%m-%d'), trans_id))
            new_end = beg
        conn.commit()
    conn.close()
    return new_end

def add_or_restock_hardware(name, category, qty, location, price, admin_id):
    conn = get_connection()
    with conn.cursor() as cur:
        hw = cur.execute("SELECT * FROM hardware WHERE name=%s", (name,)).fetchone()
        if hw:
            new_end = hw['available'] + int(qty)
            cur.execute("UPDATE hardware SET total_quantity=total_quantity+%s, available=%s, unit_price=%s, location=%s WHERE id=%s",
                        (qty, new_end, price, location, hw['id']))
        else:
            cur.execute("INSERT INTO hardware (name, category, total_quantity, available, borrowed, unit_price, location) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (name, category, qty, qty, 0, price, location))
        conn.commit()
    conn.close()

def edit_hardware(hw_id, name, category, available, price, location):
    conn = get_connection()
    with conn.cursor() as cur:
        old = cur.execute("SELECT * FROM hardware WHERE id=%s", (hw_id,)).fetchone()
        diff = int(available) - int(old['available'])
        cur.execute("UPDATE hardware SET name=%s, category=%s, available=%s, total_quantity=total_quantity+%s, unit_price=%s, location=%s WHERE id=%s",
                    (name, category, available, diff, price, location, hw_id))
        conn.commit()
    conn.close()

def delete_hardware(hw_id):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM hardware WHERE id=%s", (hw_id,))
        cur.execute("DELETE FROM transactions WHERE hardware_id=%s", (hw_id,))
        conn.commit()
    conn.close()

# --- FOR TRANSACTIONS / PROFILE / RESET PASSWORD ---
def get_user_profile(user_id):
    conn = get_connection()
    with conn.cursor() as cur:
        user = cur.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
    conn.close()
    return user

def get_user_by_email(email):
    conn = get_connection()
    with conn.cursor() as cur:
        user = cur.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    conn.close()
    return user

def get_transactions_ledger(user_id=None):
    conn = get_connection()
    with conn.cursor() as cur:
        if user_id:
            logs = cur.execute("""
                SELECT t.*, u.fullname, h.name as hname, h.category
                FROM transactions t
                JOIN users u ON u.id=t.user_id
                JOIN hardware h ON h.id=t.hardware_id
                WHERE t.user_id=%s ORDER BY t.date_created DESC
            """, (user_id,)).fetchall()
        else:
            logs = cur.execute("""
                SELECT t.*, u.fullname, h.name as hname, h.category
                FROM transactions t
                JOIN users u ON u.id=t.user_id
                JOIN hardware h ON h.id=t.hardware_id
                ORDER BY t.date_created DESC
            """).fetchall()
    conn.close()
    return logs

# --- PROFILE PIC ---
def update_profile_pic(user_id, filename):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET profile_pic=%s WHERE id=%s", (filename, user_id))
        conn.commit()
    conn.close()
    return True

# --- RESET PASSWORD ---
def update_password(user_id, new_hashed_password):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET password=%s, reset_token=NULL, reset_token_expiry=NULL WHERE id=%s", (new_hashed_password, user_id))
        conn.commit()
    conn.close()

def set_reset_token(email, token, expiry):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET reset_token=%s, reset_token_expiry=%s WHERE email=%s", (token, expiry, email))
        conn.commit()
    conn.close()

def get_user_by_reset_token(token):
    conn = get_connection()
    with conn.cursor() as cur:
        user = cur.execute("SELECT * FROM users WHERE reset_token=%s", (token,)).fetchone()
    conn.close()
    return user