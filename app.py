from flask import Flask, render_template, request, redirect, url_for, flash, session, g, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg
from psycopg.rows import dict_row
import Laboratorysystem as lab
from io import StringIO
import csv
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nu-lab-final-english-2026')

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres.hudetzzomizjnygxkjqu:Cinley%40063004@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres')

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'profile')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# AUTO MIGRATION FOR POSTGRESQL
def migrate_users_table():
    try:
        conn = psycopg.connect(DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS course TEXT DEFAULT '';")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS section TEXT DEFAULT '';")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT DEFAULT '';")
            conn.commit()
        conn.close()
    except Exception as e:
        print("Migration info:", e)

# SAFELY INITIALIZE DB TABLES ON APP STARTUP
with app.app_context():
    try:
        lab.init_system()
        migrate_users_table()
    except Exception as e:
        print("Startup Init Warning:", e)

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
            user = cur.execute("SELECT * FROM users WHERE email=%s", (request.form['email'],)).fetchone()
        if user and check_password_hash(user['password'], request.form['password']):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['fullname'] = user['fullname']
            return redirect('/dashboard')
        flash('Invalid email or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        db = get_db()
        role = request.form['role']
        password = request.form['password']

        if len(password) < 8:
            flash('Password must be at least 8 characters (standard)', 'danger')
            return render_template('register.html')

        department = request.form.get('department','').strip()
        section = request.form.get('section','').strip()
        course = department if role == 'student' else request.form.get('course','').strip()

        if role in ['student', 'employee']:
            if not department or not section:
                flash('Please select Department and Section', 'danger')
                return render_template('register.html')

        try:
            with db.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (student_id, fullname, email, password, role, course, section, department)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (request.form['student_id'], request.form['fullname'], request.form['email'],
                      generate_password_hash(password), role, course, section, department))
                db.commit()
            flash(f'Account created! {department} - {section} (8 chars password OK)', 'success')
            return redirect('/login')
        except Exception as e:
            print(e)
            flash('Email or ID already exists', 'danger')
    return render_template('register.html')

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
    with db.cursor() as cur:
        hardwares = cur.execute("SELECT * FROM hardware WHERE name ILIKE %s ORDER BY id DESC", (f"%{q}%",)).fetchall()
        
        t_res = cur.execute("SELECT SUM(total_quantity) as c FROM hardware").fetchone()
        total = t_res['c'] if t_res and t_res['c'] else 0
        
        b_res = cur.execute("SELECT SUM(borrowed) as c FROM hardware").fetchone()
        borrowed = b_res['c'] if b_res and b_res['c'] else 0
        
        e_res = cur.execute("SELECT SUM(available) as c FROM hardware").fetchone()
        ending = e_res['c'] if e_res and e_res['c'] else 0

        my_borrowed = cur.execute("""
            SELECT t.*, h.name as hname FROM transactions t
            JOIN hardware h ON h.id=t.hardware_id
            WHERE t.user_id=%s ORDER BY t.date_created DESC
        """, (session['user_id'],)).fetchall()

        pending = cur.execute("""
            SELECT t.*, u.fullname, u.course, u.section, u.department, h.name as hname FROM transactions t
            JOIN users u ON u.id=t.user_id
            JOIN hardware h ON h.id=t.hardware_id
            WHERE t.status='Pending' AND t.type='BORROW' ORDER BY t.date_created DESC
        """).fetchall()

        for_check = cur.execute("""
            SELECT t.*, u.fullname, u.course, u.section, u.department, h.name as hname FROM transactions t
            JOIN users u ON u.id=t.user_id
            JOIN hardware h ON h.id=t.hardware_id
            WHERE t.return_status='For Checking' ORDER BY t.date_created DESC
        """).fetchall()

    return render_template('dashboard.html', hardwares=hardwares, my_borrowed=my_borrowed, pending=pending, for_check=for_check, total_stocks=total, borrowed=borrowed, ending=ending, search_q=q)

@app.route('/transactions')
def transactions():
    if 'user_id' not in session:
        return redirect('/login')
    db = get_db()
    with db.cursor() as cur:
        if session['role'] in ['student','employee']:
            logs = cur.execute("""
                SELECT t.*, u.fullname, u.department, u.section, h.name as hname, h.category FROM transactions t
                JOIN users u ON u.id=t.user_id JOIN hardware h ON h.id=t.hardware_id
                WHERE t.user_id=%s ORDER BY t.date_created DESC
            """, (session['user_id'],)).fetchall()
        else:
            logs = cur.execute("""
                SELECT t.*, u.fullname, u.course, u.section, u.department, h.name as hname, h.category FROM transactions t
                JOIN users u ON u.id=t.user_id JOIN hardware h ON h.id=t.hardware_id
                ORDER BY t.date_created DESC
            """).fetchall()
    return render_template('transactions.html', logs=logs, borrows=logs)

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
                lab.update_profile_pic(session['user_id'], filename)
                flash('Profile photo updated!', 'success')
                return redirect('/profile')
    db = get_db()
    with db.cursor() as cur:
        user = cur.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],)).fetchone()
        stats = cur.execute("SELECT COUNT(*) as total, SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) as pending FROM transactions WHERE user_id=%s", (session['user_id'],)).fetchone()
    return render_template('profile.html', user=user, stats=stats)

@app.route('/reset_password', methods=['GET','POST'])
def reset_password():
    if 'user_id' not in session:
        return redirect('/login')
    if request.method == 'POST':
        db = get_db()
        with db.cursor() as cur:
            user = cur.execute("SELECT * FROM users WHERE id=%s", (session['user_id'],)).fetchone()
        if not check_password_hash(user['password'], request.form['current_password']):
            flash('Current password is incorrect', 'danger')
        elif request.form['new_password'] != request.form['confirm_password']:
            flash('New passwords do not match', 'danger')
        elif len(request.form['new_password']) < 8:
            flash('Password must be at least 8 characters (standard)', 'danger')
        else:
            hashed = generate_password_hash(request.form['new_password'])
            lab.update_password(session['user_id'], hashed)
            flash('Password updated! Please login again. (8 chars OK)', 'success')
            return redirect('/logout')
    return render_template('reset_password.html')

@app.route('/reset')
def reset_alias():
    return redirect('/reset_password')

@app.route('/forgot', methods=['GET','POST'])
def forgot():
    db = get_db()
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        new_pass = request.form.get('new_password','')
        confirm = request.form.get('confirm_password','')

        if len(new_pass) < 8:
            flash('Password must be at least 8 characters (standard)', 'danger')
            return render_template('forgot.html')
        if new_pass != confirm:
            flash('Passwords do not match', 'danger')
            return render_template('forgot.html')

        with db.cursor() as cur:
            user = cur.execute("SELECT * FROM users WHERE email=%s", (email,)).fetchone()
            if not user:
                flash('Email not found', 'danger')
                return render_template('forgot.html')

            hashed = generate_password_hash(new_pass)
            cur.execute("UPDATE users SET password=%s WHERE email=%s", (hashed, email))
            db.commit()
        flash('Password reset success! You can now login.', 'success')
        return redirect('/login')
    return render_template('forgot.html')

@app.route('/forgot_password')
def forgot_password_alias():
    return redirect('/forgot')

@app.route('/borrow', methods=['POST'])
def borrow():
    ok, msg = lab.request_borrow(session['user_id'], request.form['hw_id'], int(request.form['qty']), int(request.form['days']), request.form['remarks'])
    flash(msg, 'success' if ok else 'danger')
    return redirect('/dashboard')

@app.route('/user/return/<int:id>')
def user_return(id):
    lab.request_return(id)
    flash('Return request submitted for checking.', 'info')
    return redirect('/dashboard')

@app.route('/user/pay/<int:id>')
def user_pay(id):
    lab.pay_damage(id)
    flash('Payment Paid!', 'success')
    return redirect('/dashboard')

@app.route('/admin/approve/<int:id>')
def approve(id):
    ok, msg = lab.approve_borrow(id, session['user_id'])
    flash(msg, 'success' if ok else 'danger')
    return redirect('/dashboard')

@app.route('/admin/check_return/<int:id>', methods=['POST'])
def check_return(id):
    lab.admin_check_return(id, request.form['condition'], request.form.get('damage_remarks',''), float(request.form.get('payment',0)))
    flash(f"Return checked as {request.form['condition']}", 'success')
    return redirect('/dashboard')

@app.route('/admin/add_stock', methods=['POST'])
def add_stock():
    qty = int(request.form.get('quantity', 0) or 0)
    if qty < 0:
        flash("Quantity cannot be negative, but 0 allowed!", "danger")
        return redirect('/dashboard')
    lab.add_or_restock_hardware(request.form['name'], request.form['category'], qty, request.form['location'], float(request.form.get('unit_price',0) or 0), session['user_id'])
    flash(f'Stock added! Qty: {qty}', 'success')
    return redirect('/dashboard')

@app.route('/admin/edit/<int:id>', methods=['POST'])
def edit_item(id):
    if session.get('role') in ['student','employee']:
        return redirect('/dashboard')
    db = get_db()
    with db.cursor() as cur:
        old = cur.execute("SELECT * FROM hardware WHERE id=%s", (id,)).fetchone()
        if not old:
            flash("Item not found", "danger")
            return redirect('/dashboard')
        name = request.form.get('name', old['name'])
        category = request.form.get('category', old['category'])
        location = request.form.get('location', old['location'])
        unit_price = float(request.form.get('unit_price', old['unit_price']) or 0)
        total_qty = int(request.form.get('total_quantity', old['total_quantity']) or 0)
        avail = int(request.form.get('available', old['available']) or 0)
        if total_qty < 0 or avail < 0:
            flash("0 is allowed, negative not!", "danger")
            return redirect('/dashboard')
        if total_qty < old['borrowed']:
            flash(f"Cannot set Beg to {total_qty}, may {old['borrowed']} pa borrowed!", "danger")
            return redirect('/dashboard')
        if avail > total_qty:
            flash("Ending cannot be > Beginning", "danger")
            return redirect('/dashboard')
        new_borrowed = total_qty - avail
        cur.execute("UPDATE hardware SET name=%s, category=%s, location=%s, unit_price=%s, total_quantity=%s, available=%s, borrowed=%s WHERE id=%s",
                    (name, category, location, unit_price, total_qty, avail, new_borrowed, id))
        db.commit()
    flash(f'Updated! Beg:{total_qty} End:{avail} (0=Out of Stock)', 'success')
    return redirect('/dashboard')

@app.route('/admin/delete/<int:id>')
def delete_item(id):
    lab.delete_hardware(id)
    flash('Item deleted!', 'danger')
    return redirect('/dashboard')

@app.route('/export_csv')
def export_csv():
    db = get_db()
    with db.cursor() as cur:
        hw = cur.execute("SELECT * FROM hardware").fetchall()
    si = StringIO()
    w = csv.writer(si)
    w.writerow(['ID','Equipment','Category','Beginning','Borrowed','Ending','Unit Price','Location'])
    for h in hw:
        w.writerow([h['id'], h['name'], h['category'], h['total_quantity'], h['borrowed'], h['available'], h['unit_price'], h['location']])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=inventory.csv"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)