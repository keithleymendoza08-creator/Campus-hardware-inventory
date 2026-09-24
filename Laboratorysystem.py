# Laboratorysystem.py - NU Laboratory Hardware System (Supabase PostgreSQL Version)
import os
import logging
from datetime import datetime, timedelta
import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, request, redirect, url_for, session, flash

# --- FLASK APP INITIALIZATION ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-change-this')

# Fetch DATABASE_URL from Render Environment Variables
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres.hudetzzomizjnygxkjqu:Cinley%40063004@aws-0-ap-southeast-1.pooler.southeast-1.pooler.supabase.com:6543/postgres?sslmode=require'
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

def get_connection():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

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
        conn.close()
        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.error(f"Database initialization error: {e}")

try:
    init_system()
except Exception as e:
    logging.warning(f"DB Init Error: {e}")

# --- DATABASE HELPER FUNCTIONS ---
def get_user_by_email(email):
    conn = get_connection()
    with conn.cursor() as cur:
        user = cur.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
    conn.close()
    return user

def get_user_profile(user_id):
    conn = get_connection()
    with conn.cursor() as cur:
        user = cur.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
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

def get_all_hardware():
    conn = get_connection()
    with conn.cursor() as cur:
        items = cur.execute("SELECT * FROM hardware ORDER BY name ASC").fetchall()
    conn.close()
    return items

# --- FLASK ROUTES (NAKADIKIT NA SA MGA HTML MO) ---

@app.route('/')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = get_user_by_email(email)
        
        if user and user['password'] == password:
            session['user_id'] = user['id']
            session['user_name'] = user['fullname']
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        fullname = request.form.get('fullname')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'Student')

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (student_id, fullname, email, password, role) VALUES (%s, %s, %s, %s, %s)",
                    (student_id, fullname, email, password, role)
                )
                conn.commit()
            conn.close()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            conn.close()
            flash('Error: Email or Student ID already exists.', 'danger')

    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    hardware_list = get_all_hardware()
    return render_template('dashboard.html', hardware=hardware_list)

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Student sees their own transactions, Admin sees all
    if session.get('role') == 'Admin':
        logs = get_transactions_ledger()
    else:
        logs = get_transactions_ledger(user_id=session['user_id'])
        
    return render_template('transactions.html', transactions=logs)

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = get_user_profile(session['user_id'])
    return render_template('profile.html', user=user)

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'POST':
        email = request.form.get('email')
        flash('If that email exists, reset instructions have been sent.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot.html')

@app.route('/reset', methods=['GET', 'POST'])
@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        flash('Password updated successfully!', 'success')
        return redirect(url_for('login'))
    return render_template('reset_password.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))