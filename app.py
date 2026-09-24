import os
import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import Laboratorysystem as lab

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'nu-lab-final-english-2026')

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres.hudetzzomizjnygxkjqu:Cinley%40063004@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres')

def get_db():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

# Siguraduhing na-initialize ang database tables
try:
    lab.init_system()
except Exception as e:
    print(f"Database init info/notice: {e}")

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        with conn.cursor() as cur:
            user = cur.execute("SELECT * FROM users WHERE email = %s AND password = %s", (email, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['fullname'] = user['fullname']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    with conn.cursor() as cur:
        hardware_list = cur.execute("SELECT * FROM hardware ORDER BY name ASC").fetchall()
    conn.close()
    
    user_id = session['user_id']
    role = session['role']
    logs = lab.get_transactions_ledger(None if role in ['LABORATORY_TECHNICIAN', 'FACULTY_MEMBER'] else user_id)
    
    return render_template('dashboard.html', hardware=hardware_list, logs=logs, role=role)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)