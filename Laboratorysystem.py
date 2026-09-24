import psycopg
from psycopg.rows import dict_row
import os
from datetime import datetime, timedelta

# Default Database URL (gagamitin ang environment variable kung naka-set sa hosting platform)
DATABASE_URL = os.environ.get(
    'DATABASE_URL',
    'postgresql://postgres.hudetzzomizjnygxkjqu:Cinley%40063004@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres?sslmode=require'
)

def get_db():
    """Nagbubukas ng bagong koneksyon sa PostgreSQL database."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

def init_system():
    """Awtomatikong gumagawa ng kinakailangang database tables kapag unang ginamit."""
    with get_db() as conn:
        with conn.cursor() as cur:
            # Table para sa mga Users
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    student_id VARCHAR(50) UNIQUE NOT NULL,
                    fullname VARCHAR(100) NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    course VARCHAR(100) DEFAULT '',
                    section VARCHAR(50) DEFAULT '',
                    department VARCHAR(100) DEFAULT '',
                    profile_pic VARCHAR(255) DEFAULT 'default.png',
                    date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Table para sa Hardware / Inventory
            cur.execute("""
                CREATE TABLE IF NOT EXISTS hardware (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    category VARCHAR(50) NOT NULL,
                    total_quantity INT DEFAULT 0,
                    borrowed INT DEFAULT 0,
                    available INT DEFAULT 0,
                    unit_price NUMERIC(10, 2) DEFAULT 0.00,
                    location VARCHAR(100) DEFAULT '',
                    date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Table para sa Borrowing and Returning Transactions
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    user_id INT REFERENCES users(id) ON DELETE CASCADE,
                    hardware_id INT REFERENCES hardware(id) ON DELETE CASCADE,
                    quantity INT NOT NULL,
                    days INT DEFAULT 1,
                    remarks TEXT DEFAULT '',
                    type VARCHAR(20) DEFAULT 'BORROW',
                    status VARCHAR(50) DEFAULT 'Pending',
                    return_status VARCHAR(50) DEFAULT '',
                    condition VARCHAR(50) DEFAULT '',
                    damage_remarks TEXT DEFAULT '',
                    payment NUMERIC(10, 2) DEFAULT 0.00,
                    payment_status VARCHAR(50) DEFAULT 'Unpaid',
                    approved_by INT REFERENCES users(id) ON DELETE SET NULL,
                    due_date TIMESTAMP,
                    date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

def update_profile_pic(user_id, filename):
    """Inaupdate ang profile picture ng user."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET profile_pic=%s WHERE id=%s", (filename, user_id))
            conn.commit()

def update_password(user_id, hashed_password):
    """Inaupdate ang hashed password ng user."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password=%s WHERE id=%s", (hashed_password, user_id))
            conn.commit()

def request_borrow(user_id, hw_id, qty, days, remarks):
    """Pagproseso ng paghingi ng hiram mula sa estudyante o empleyado."""
    with get_db() as conn:
        with conn.cursor() as cur:
            hw = cur.execute("SELECT * FROM hardware WHERE id=%s", (hw_id,)).fetchone()
            if not hw:
                return False, "Equipment hindi nahanap sa system."
            if qty <= 0:
                return False, "Dapat mas mataas sa 0 ang hihiraming dami."
            if hw['available'] < qty:
                return False, f"Kulang ang available stock! ({hw['available']} na lang ang natitira)"

            cur.execute("""
                INSERT INTO transactions (user_id, hardware_id, quantity, days, remarks, type, status)
                VALUES (%s, %s, %s, %s, %s, 'BORROW', 'Pending')
            """, (user_id, hw_id, qty, days, remarks))
            conn.commit()
            return True, "Borrow request successfully submitted!"

def approve_borrow(transaction_id, approved_by):
    """Ina-approve ng Admin/Custodian ang hirap request at binabawasan ang available stock."""
    with get_db() as conn:
        with conn.cursor() as cur:
            txn = cur.execute("SELECT * FROM transactions WHERE id=%s", (transaction_id,)).fetchone()
            if not txn or txn['status'] != 'Pending':
                return False, "Invalid o naiproseso na ang transaction na ito."

            hw = cur.execute("SELECT * FROM hardware WHERE id=%s", (txn['hardware_id'],)).fetchone()
            if hw['available'] < txn['quantity']:
                return False, "Hindi sapat ang available stock para ma-approve ang request."

            due = datetime.now() + timedelta(days=txn['days'])
            
            # Update ng stock sa hardware table
            new_avail = hw['available'] - txn['quantity']
            new_borrowed = hw['borrowed'] + txn['quantity']
            cur.execute("UPDATE hardware SET available=%s, borrowed=%s WHERE id=%s", (new_avail, new_borrowed, hw['id']))

            # Update ng transaction record
            cur.execute("""
                UPDATE transactions 
                SET status='Approved', approved_by=%s, due_date=%s 
                WHERE id=%s
            """, (approved_by, due, transaction_id))
            
            conn.commit()
            return True, "Borrow request successfully approved!"

def request_return(transaction_id):
    """Inilalagay ang item status sa 'For Checking' kapag ibinabalik na ng user."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE transactions 
                SET return_status='For Checking' 
                WHERE id=%s
            """, (transaction_id,))
            conn.commit()

def admin_check_return(transaction_id, condition, damage_remarks, payment):
    """Pagsusuri ng Admin/Custodian sa ibinalik na item at pagbabalik ng stock."""
    with get_db() as conn:
        with conn.cursor() as cur:
            txn = cur.execute("SELECT * FROM transactions WHERE id=%s", (transaction_id,)).fetchone()
            if not txn:
                return

            hw = cur.execute("SELECT * FROM hardware WHERE id=%s", (txn['hardware_id'],)).fetchone()
            
            # Ibabalik ang dami ng hinaram pabalik sa available status
            if hw:
                new_avail = hw['available'] + txn['quantity']
                new_borrowed = max(0, hw['borrowed'] - txn['quantity'])
                cur.execute("UPDATE hardware SET available=%s, borrowed=%s WHERE id=%s", (new_avail, new_borrowed, hw['id']))

            p_status = 'Paid' if payment <= 0 else 'Pending Payment'

            cur.execute("""
                UPDATE transactions 
                SET status='Returned', return_status='Returned', condition=%s, damage_remarks=%s, payment=%s, payment_status=%s 
                WHERE id=%s
            """, (condition, damage_remarks, payment, p_status, transaction_id))
            conn.commit()

def pay_damage(transaction_id):
    """I-mark bilang bayad na ang multa o damage fee."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE transactions SET payment_status='Paid' WHERE id=%s", (transaction_id,))
            conn.commit()

def add_or_restock_hardware(name, category, qty, location, unit_price, user_id):
    """Magdagdag ng bagong kagamitan o mag-restock kapag may umiiral nang pangalan at kategorya."""
    with get_db() as conn:
        with conn.cursor() as cur:
            existing = cur.execute(
                "SELECT * FROM hardware WHERE LOWER(name)=LOWER(%s) AND LOWER(category)=LOWER(%s)", 
                (name.strip(), category.strip())
            ).fetchone()
            
            if existing:
                new_total = existing['total_quantity'] + qty
                new_avail = existing['available'] + qty
                cur.execute("""
                    UPDATE hardware 
                    SET total_quantity=%s, available=%s, location=%s, unit_price=%s 
                    WHERE id=%s
                """, (new_total, new_avail, location, unit_price, existing['id']))
            else:
                cur.execute("""
                    INSERT INTO hardware (name, category, total_quantity, borrowed, available, unit_price, location)
                    VALUES (%s, %s, %s, 0, %s, %s, %s)
                """, (name, category, qty, qty, unit_price, location))
            conn.commit()

def delete_hardware(hw_id):
    """Pagtanggal ng item sa inventory list."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM hardware WHERE id=%s", (hw_id,))
            conn.commit()