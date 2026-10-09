from flask import Flask, render_template, request, redirect, url_for, flash, session, g, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg
from psycopg.rows import dict_row
import HRISsystem as hris
from io import StringIO
import csv
import os
import random
import requests
import threading
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'global-payments-hris-2026')

# --- TRANSACTION POOLER CONNECTION STRING (IPv4 - Port 6543) ---
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres.hudetzzomizjnygxkjqu:Keithleyvien0516@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres?sslmode=require'
)

# --- BREVO REST API CONFIGURATION ---
BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'no-reply@globalpayments.com')

def send_otp_email_worker(receiver_email, otp, intent):
    """Background worker for sending OTP emails via Brevo API without blocking HTTP response."""
    if not BREVO_API_KEY or 'YOUR-BREVO' in BREVO_API_KEY:
        print("API Error: Missing or default BREVO_API_KEY.")
        return

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    payload = {
        "sender": {
            "name": "Global Payments HRIS",
            "email": SENDER_EMAIL
        },
        "to": [
            {
                "email": receiver_email
            }
        ],
        "subject": f"Global Payments HRIS - {intent} OTP",
        "textContent": f"Your {intent} One-Time Password (OTP) is: {otp}\n\nThis OTP is valid for 5 minutes. Please enter this code to proceed. Do not share this code with anyone."
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"Brevo API Email Sent. Status Code: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"Brevo API Request Error: {e}")

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'profile')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

hris.init_system()

def migrate_users_table():
    try:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id TEXT DEFAULT '';")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title TEXT DEFAULT '';")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT DEFAULT '';")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hourly_rate NUMERIC DEFAULT 0;")
            conn.commit()
        conn.close()
    except Exception as e:
        print("Migration Warning:", e)

migrate_users_table()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return db

@app.teardown_appcontext
def close(exception):
    db = getattr(g, '_database', None)
    if db:
        db.close()

@app.route('/')
def index():
    return redirect('/login')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        db = get_db()
        with db.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email=%s", (request.form['email'],))
            user = cur.fetchone()
        if user and check_password_hash(user['password'], request.form['password']):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['fullname'] = user['fullname']
            return redirect('/dashboard')
        flash('Invalid email or password', 'danger')
    return render_template('login.html')

# ===== REGISTER WITH OTP =====
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    employee_id = request.form.get('employee_id', '').strip()
    fullname = request.form.get('fullname', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'employee').strip()

    if len(password) < 8:
        flash('Password must be at least 8 characters', 'danger')
        return render_template('register.html')

    department = request.form.get('department','').strip()
    job_title = request.form.get('job_title','').strip()

    if not department or not job_title:
        flash('Please select Department and Job Title', 'danger')
        return render_template('register.html')

    otp = str(random.randint(100000, 999999))
    session['pending_user'] = {
        'employee_id': employee_id,
        'fullname': fullname,
        'email': email,
        'password': password,
        'role': role,
        'job_title': job_title,
        'department': department,
        'otp': otp,
        'otp_expiry': time.time() + 300
    }

    threading.Thread(target=send_otp_email_worker, args=(email, otp, "Account Registration")).start()
    flash("We sent a 6-digit OTP code to your email address. Please check your Inbox / Spam folder.", "info")

    return redirect(url_for("verify_otp", action="register"))

# ===== STEP 1 FORGOT PASSWORD: REQUEST EMAIL =====
@app.route('/forgot', methods=['GET', 'POST'])
@app.route('/reset-request', methods=['GET', 'POST'])
def reset_request():
    if request.method == 'GET':
        return render_template('forgot.html')

    email = request.form.get('email', '').strip()

    if not email:
        flash('Please enter your email address.', 'danger')
        return redirect(url_for('reset_request'))

    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        if not user:
            flash('Email address not found.', 'danger')
            return redirect(url_for('reset_request'))

    otp = str(random.randint(100000, 999999))
    session['pending_reset'] = {
        'email': email,
        'otp': otp,
        'otp_expiry': time.time() + 300
    }

    threading.Thread(target=send_otp_email_worker, args=(email, otp, "Password Reset")).start()
    flash("We sent a 6-digit OTP code to your email address. Please check your Inbox / Spam folder.", "info")

    return redirect(url_for("verify_otp", action="reset"))

# ===== STEP 2: VERIFY OTP ROUTE =====
@app.route('/verify-otp/<action>', methods=['GET', 'POST'])
def verify_otp(action):
    session_key = 'pending_user' if action == 'register' else 'pending_reset'

    if session_key not in session:
        flash("Session expired or invalid access. Please try again.", "warning")
        return redirect(url_for("register" if action == "register" else "reset_request"))

    if request.method == "POST":
        user_otp = request.form.get("otp_code", "").strip()
        data = session[session_key]

        if time.time() > data.get('otp_expiry', 0):
            flash("The OTP code has expired. Please click 'Resend OTP' to receive a new code.", "danger")
            return render_template("otp_verify.html", action_url=url_for('verify_otp', action=action), action=action)

        if user_otp == data['otp']:
            db = get_db()
            if action == "register":
                try:
                    with db.cursor() as cur:
                        cur.execute("""
                            INSERT INTO users (employee_id, fullname, email, password, role, job_title, department)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (data['employee_id'], data['fullname'], data['email'],
                              generate_password_hash(data['password']), data['role'],
                              data['job_title'], data['department']))
                        db.commit()
                    session.pop(session_key, None)
                    flash("Account successfully verified and created! Please login.", "success")
                    return redirect(url_for("login"))
                except Exception as e:
                    print("Registration Error:", e)
                    flash("Email or Employee ID already exists in the system.", "danger")
                    return redirect(url_for("register"))

            elif action == "reset":
                session['otp_verified_for_reset'] = True
                flash("OTP code verified! Please set your new password.", "success")
                return redirect(url_for("set_new_password"))
        else:
            flash("Invalid OTP code. Try again.", "danger")

    return render_template("otp_verify.html", action_url=url_for('verify_otp', action=action), action=action)

# ===== STEP 3: SET NEW PASSWORD AFTER OTP VERIFICATION =====
@app.route('/set-new-password', methods=['GET', 'POST'])
def set_new_password():
    if 'pending_reset' not in session or not session.get('otp_verified_for_reset'):
        flash("Unauthorized access. Please request a password reset first.", "danger")
        return redirect(url_for("reset_request"))

    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if len(new_password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('reset_password.html')

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html')

        email = session['pending_reset']['email']
        try:
            db = get_db()
            hashed = generate_password_hash(new_password)
            with db.cursor() as cur:
                cur.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
                db.commit()

            session.pop('pending_reset', None)
            session.pop('otp_verified_for_reset', None)
            flash("Password successfully reset! You can now login with your new password.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            print("Reset Error:", e)
            flash("Failed to update password. Please try again.", "danger")
            return redirect(url_for("reset_request"))

    return render_template('reset_password.html')

# ===== RESEND OTP ROUTE =====
@app.route('/resend-otp/<action>', methods=['GET'])
def resend_otp(action):
    session_key = 'pending_user' if action == 'register' else 'pending_reset'

    if session_key not in session:
        flash("Session expired. Please restart the process.", "warning")
        return redirect(url_for("register" if action == "register" else "reset_request"))

    data = session[session_key]
    new_otp = str(random.randint(100000, 999999))
    
    data['otp'] = new_otp
    data['otp_expiry'] = time.time() + 300
    session[session_key] = data

    intent = "Account Registration" if action == "register" else "Password Reset"
    threading.Thread(target=send_otp_email_worker, args=(data['email'], new_otp, intent)).start()

    flash("A new 6-digit OTP code has been sent to your email address.", "info")
    return redirect(url_for("verify_otp", action=action))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')

    db = get_db()
    q = request.args.get('q', '')

    try:
        with db.cursor() as cur:
            # 1. Fetch current user
            cur.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
            current_user = cur.fetchone()

            if not current_user:
                current_user = {
                    'fullname': session.get('fullname', 'Employee Profile'),
                    'role': session.get('role', 'employee'),
                    'email': session.get('user_email', '')
                }

            # 2. Employees search
            cur.execute("SELECT * FROM users WHERE fullname ILIKE %s ORDER BY id DESC", (f"%{q}%",))
            employees = cur.fetchall() or []

            # 3. Total employees count
            cur.execute("SELECT COUNT(*) as c FROM users WHERE role='employee'")
            t_res = cur.fetchone()
            total_employees = t_res['c'] if (t_res and 'c' in t_res) else 0

            # 4. Pending leaves count
            cur.execute("SELECT COUNT(*) as c FROM leave_applications WHERE status='Pending'")
            l_res = cur.fetchone()
            pending_leaves = l_res['c'] if (l_res and 'c' in l_res) else 0

            # 5. Total payroll sum
            cur.execute("SELECT SUM(net_pay) as c FROM payroll_records")
            p_res = cur.fetchone()
            total_payroll = p_res['c'] if (p_res and 'c' in p_res and p_res['c'] is not None) else 0.0

            # 6. User's leave applications
            cur.execute("""
                SELECT * FROM leave_applications
                WHERE user_id=%s ORDER BY date_created DESC
            """, (session['user_id'],))
            my_leaves = cur.fetchall() or []

            # 7. Pending leaves list
            cur.execute("""
                SELECT l.*, u.fullname, u.department, u.job_title FROM leave_applications l
                JOIN users u ON u.id=l.user_id
                WHERE l.status='Pending' ORDER BY l.date_created DESC
            """)
            pending_leaves_list = cur.fetchall() or []

            # 8. Timekeeping records
            cur.execute("""
                SELECT t.*, u.fullname, u.department FROM timekeeping t
                JOIN users u ON u.id=t.user_id
                ORDER BY t.clock_in DESC LIMIT 20
            """)
            timekeeping_records = cur.fetchall() or []

        return render_template(
            'dashboard.html', 
            user=current_user,
            employees=employees, 
            my_leaves=my_leaves, 
            pending_leaves=pending_leaves_list, 
            timekeeping_records=timekeeping_records, 
            total_employees=total_employees, 
            pending_leaves_count=pending_leaves, 
            total_payroll=total_payroll, 
            search_q=q
        )

    except Exception as e:
        print("Dashboard Route Error:", e)
        fallback_user = {
            'fullname': session.get('fullname', 'Employee Profile'),
            'role': session.get('role', 'employee')
        }
        return render_template(
            'dashboard.html', 
            user=fallback_user,
            employees=[], 
            my_leaves=[], 
            pending_leaves=[], 
            timekeeping_records=[], 
            total_employees=0, 
            pending_leaves_count=0, 
            total_payroll=0.0, 
            search_q=q
        )

@app.route('/timekeeping', methods=['GET', 'POST'])
def timekeeping():
    if 'user_id' not in session:
        return redirect('/login')
    if request.method == 'POST':
        action_type = request.form.get('action')
        if action_type == 'time_in':
            hris.record_time_in(session['user_id'])
            flash('Successfully Clocked In!', 'success')
        elif action_type == 'time_out':
            hris.record_time_out(session['user_id'])
            flash('Successfully Clocked Out!', 'success')
        return redirect('/timekeeping')

    db = get_db()
    with db.cursor() as cur:
        cur.execute("""
            SELECT t.*, u.fullname, u.department FROM timekeeping t
            JOIN users u ON u.id=t.user_id
            WHERE t.user_id=%s ORDER BY t.clock_in DESC
        """, (session['user_id'],))
        records = cur.fetchall() or []
    return render_template('timekeeping.html', records=records)

@app.route('/leave/apply', methods=['POST'])
def apply_leave():
    if 'user_id' not in session:
        return redirect('/login')
    ok, msg = hris.request_leave(
        session['user_id'], 
        request.form['leave_type'], 
        request.form['start_date'], 
        request.form['end_date'], 
        request.form['reason']
    )
    flash(msg, 'success' if ok else 'danger')
    return redirect('/dashboard')

@app.route('/profile', methods=['GET','POST'])
def profile():
    if 'user_id' not in session:
        return redirect('/login')
    if request.method == 'POST':
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename != '' and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"user_{session['user_id']}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                hris.update_profile_pic(session['user_id'], filename)
                flash('Profile photo updated!', 'success')
                return redirect('/profile')
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],))
        user = cur.fetchone()
        
        cur.execute("""
            SELECT COUNT(*) as total_leaves, 
                   SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) as pending 
            FROM leave_applications WHERE user_id=%s
        """, (session['user_id'],))
        stats = cur.fetchall() or []
    return render_template('profile.html', user=user, stats=stats)

@app.route('/admin/approve_leave/<int:id>')
def approve_leave(id):
    if session.get('role') not in ['admin', 'hr_manager', 'supervisor']:
        return redirect('/dashboard')
    ok, msg = hris.approve_leave(id, session['user_id'])
    flash(msg, 'success' if ok else 'danger')
    return redirect('/dashboard')

@app.route('/admin/calculate_payroll', methods=['POST'])
def calculate_payroll():
    if session.get('role') not in ['admin', 'hr_manager']:
        return redirect('/dashboard')
    period_start = request.form.get('period_start')
    period_end = request.form.get('period_end')
    hris.process_periodic_payroll(period_start, period_end)
    flash(f"Payroll successfully processed for period {period_start} to {period_end}.", 'success')
    return redirect('/dashboard')

@app.route('/export_payroll_csv')
def export_payroll_csv():
    if 'user_id' not in session:
        return redirect('/login')
    db = get_db()
    with db.cursor() as cur:
        cur.execute("""
            SELECT p.*, u.fullname, u.department, u.employee_id 
            FROM payroll_records p
            JOIN users u ON u.id=p.user_id
        """)
        payroll_data = cur.fetchall() or []
    si = StringIO()
    w = csv.writer(si)
    w.writerow(['Employee ID', 'Fullname', 'Department', 'Basic Pay', 'Overtime Pay', 'Tardy Deductions', 'Tax Deductions', 'Net Pay'])
    for p in payroll_data:
        w.writerow([p['employee_id'], p['fullname'], p['department'], p['basic_pay'], p['overtime_pay'], p['tardy_deductions'], p['tax_deductions'], p['net_pay']])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=global_payments_payroll_register.csv"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)