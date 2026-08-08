from __future__ import annotations

import functools
import hashlib
import os
import secrets
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "trekking.db")

ADMIN_EMAIL = "admin@trek.local"
ADMIN_PASSWORD = "admin123"
DEMO_STAFF_EMAIL = "staff@trek.local"
DEMO_STAFF_PASSWORD = "staff123"
DEMO_USER_EMAIL = "user@trek.local"
DEMO_USER_PASSWORD = "user123"
TREK_STATUSES = ("Pending", "Approved", "Open", "Ongoing", "Closed", "Completed")


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["DATABASE"] = DB_PATH

    os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

    @app.before_request
    def before_request() -> None:
        get_db()

    @app.teardown_appcontext
    def close_db(_error: Exception | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    register_routes(app)

    with app.app_context():
        init_db()
        seed_data()

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'user')),
            contact TEXT,
            status TEXT NOT NULL DEFAULT 'approved'
                CHECK (status IN ('pending', 'approved', 'blacklisted')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS treks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            difficulty TEXT NOT NULL CHECK (difficulty IN ('Easy', 'Moderate', 'Hard')),
            duration_days INTEGER NOT NULL CHECK (duration_days > 0),
            available_slots INTEGER NOT NULL CHECK (available_slots >= 0),
            assigned_staff_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK (status IN ('Pending', 'Approved', 'Open', 'Ongoing', 'Closed', 'Completed')),
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (assigned_staff_id) REFERENCES users (id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            trek_id INTEGER NOT NULL,
            booking_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Booked'
                CHECK (status IN ('Booked', 'Cancelled', 'Completed')),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (trek_id) REFERENCES treks (id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_users_role_status ON users (role, status);
        CREATE INDEX IF NOT EXISTS idx_treks_search ON treks (name, location, difficulty, status);
        CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings (user_id, status);
        CREATE INDEX IF NOT EXISTS idx_bookings_trek ON bookings (trek_id, status);
        """
    )
    db.commit()
    migrate_trek_statuses()


def migrate_trek_statuses() -> None:
    db = get_db()
    table = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'treks'"
    ).fetchone()
    if table is None or "Ongoing" in table["sql"]:
        return

    db.executescript(
        """
        PRAGMA foreign_keys = OFF;

        CREATE TABLE treks_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            difficulty TEXT NOT NULL CHECK (difficulty IN ('Easy', 'Moderate', 'Hard')),
            duration_days INTEGER NOT NULL CHECK (duration_days > 0),
            available_slots INTEGER NOT NULL CHECK (available_slots >= 0),
            assigned_staff_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK (status IN ('Pending', 'Approved', 'Open', 'Ongoing', 'Closed', 'Completed')),
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (assigned_staff_id) REFERENCES users (id) ON DELETE SET NULL
        );

        INSERT INTO treks_new
            (id, name, location, difficulty, duration_days, available_slots,
             assigned_staff_id, status, start_date, end_date, description, created_at)
        SELECT id, name, location, difficulty, duration_days, available_slots,
               assigned_staff_id, status, start_date, end_date, description, created_at
        FROM treks;

        DROP TABLE treks;
        ALTER TABLE treks_new RENAME TO treks;
        CREATE INDEX IF NOT EXISTS idx_treks_search ON treks (name, location, difficulty, status);

        PRAGMA foreign_keys = ON;
        """
    )
    db.commit()


def seed_data() -> None:
    db = get_db()
    admin = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()
    if admin is None:
        db.execute(
            """
            INSERT INTO users (name, email, password_hash, role, contact, status, created_at)
            VALUES (?, ?, ?, 'admin', ?, 'approved', ?)
            """,
            (
                "System Admin",
                ADMIN_EMAIL,
                hash_password(ADMIN_PASSWORD),
                "9999999999",
                now_text(),
            ),
        )

    demo_staff_id = ensure_user(
        name="Demo Staff",
        email=DEMO_STAFF_EMAIL,
        password=DEMO_STAFF_PASSWORD,
        role="staff",
        contact="8888888888",
        status="approved",
    )
    ensure_user(
        name="Demo Trekker",
        email=DEMO_USER_EMAIL,
        password=DEMO_USER_PASSWORD,
        role="user",
        contact="7777777777",
        status="approved",
    )

    trek_count = db.execute("SELECT COUNT(*) AS total FROM treks").fetchone()["total"]
    if trek_count == 0:
        sample_treks = [
            (
                "Valley Sunrise Trail",
                "Himachal Pradesh",
                "Easy",
                2,
                18,
                "Open",
                "2026-07-08",
                "2026-07-09",
                "A beginner friendly trek with ridge views and campsite orientation.",
            ),
            (
                "Monsoon Ridge Expedition",
                "Maharashtra",
                "Moderate",
                3,
                12,
                "Approved",
                "2026-08-14",
                "2026-08-16",
                "A guided ridge route with forest sections and waterfall crossings.",
            ),
            (
                "Snowline Base Challenge",
                "Uttarakhand",
                "Hard",
                5,
                8,
                "Pending",
                "2026-10-02",
                "2026-10-06",
                "A demanding high-altitude trek for experienced participants.",
            ),
        ]
        db.executemany(
            """
            INSERT INTO treks
                (name, location, difficulty, duration_days, available_slots, status,
                 start_date, end_date, description, assigned_staff_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (*trek, demo_staff_id if index == 0 else None, now_text())
                for index, trek in enumerate(sample_treks)
            ],
        )
    else:
        db.execute(
            """
            UPDATE treks
            SET assigned_staff_id = ?
            WHERE id = (
                SELECT id FROM treks
                WHERE assigned_staff_id IS NULL
                ORDER BY CASE WHEN status = 'Open' THEN 0 ELSE 1 END, start_date
                LIMIT 1
            )
            """,
            (demo_staff_id,),
        )
    db.commit()


def ensure_user(
    name: str,
    email: str,
    password: str,
    role: str,
    contact: str,
    status: str,
) -> int:
    db = get_db()
    user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if user is not None:
        return int(user["id"])

    cursor = db.execute(
        """
        INSERT INTO users (name, email, password_hash, role, contact, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (name, email, hash_password(password), role, contact, status, now_text()),
    )
    return int(cursor.lastrowid)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def check_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return secrets.compare_digest(candidate.hex(), digest)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text() -> str:
    return date.today().isoformat()


def current_user() -> sqlite3.Row | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(role: str | tuple[str, ...] | None = None):
    def decorator(view):
        @functools.wraps(view)
        def wrapped_view(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            if user["status"] == "blacklisted":
                session.clear()
                flash("Your account has been blacklisted. Contact the administrator.", "danger")
                return redirect(url_for("login"))
            if user["role"] == "staff" and user["status"] == "pending":
                if request.endpoint != "pending_approval":
                    return redirect(url_for("pending_approval"))
            allowed_roles = (role,) if isinstance(role, str) else role
            if allowed_roles and user["role"] not in allowed_roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            g.user = user
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    @app.route("/")
    def index():
        if current_user():
            return redirect(url_for("dashboard"))
        featured = get_db().execute(
            """
            SELECT t.*, COALESCE(b.booked_count, 0) AS booked_count
            FROM treks t
            LEFT JOIN (
                SELECT trek_id, COUNT(*) AS booked_count
                FROM bookings
                WHERE status = 'Booked'
                GROUP BY trek_id
            ) b ON b.trek_id = t.id
            WHERE t.status = 'Open'
            ORDER BY t.start_date
            LIMIT 3
            """
        ).fetchall()
        return render_template("index.html", featured=featured)

    @app.route("/dashboard")
    @login_required()
    def dashboard():
        user = g.user
        if user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        if user["role"] == "staff":
            return redirect(url_for("staff_dashboard"))
        return redirect(url_for("user_dashboard"))

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user is None or not check_password(password, user["password_hash"]):
                flash("Invalid email or password.", "danger")
                return render_template("login.html")
            if user["status"] == "blacklisted":
                flash("This account is blacklisted.", "danger")
                return render_template("login.html")

            session.clear()
            session["user_id"] = user["id"]
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/register/user", methods=("GET", "POST"))
    def register_user():
        return register_account("user")

    @app.route("/register/staff", methods=("GET", "POST"))
    def register_staff():
        return register_account("staff")

    def register_account(role: str):
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            contact = request.form.get("contact", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not name or not email or not password:
                flash("Name, email, and password are required.", "danger")
                return render_template("register.html", role=role)
            if password != confirm_password:
                flash("Passwords do not match.", "danger")
                return render_template("register.html", role=role)
            if len(password) < 6:
                flash("Password must be at least 6 characters.", "danger")
                return render_template("register.html", role=role)

            status = "pending" if role == "staff" else "approved"
            try:
                get_db().execute(
                    """
                    INSERT INTO users (name, email, password_hash, role, contact, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, email, hash_password(password), role, contact, status, now_text()),
                )
                get_db().commit()
            except sqlite3.IntegrityError:
                flash("An account with this email already exists.", "danger")
                return render_template("register.html", role=role)

            if role == "staff":
                flash("Staff registration submitted. Admin approval is required.", "info")
            else:
                flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("register.html", role=role)

    @app.route("/pending-approval")
    @login_required("staff")
    def pending_approval():
        if g.user["status"] == "approved":
            return redirect(url_for("staff_dashboard"))
        return render_template("pending_approval.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    @app.route("/admin")
    @login_required("admin")
    def admin_dashboard():
        db = get_db()
        stats = {
            "treks": db.execute("SELECT COUNT(*) AS total FROM treks").fetchone()["total"],
            "users": db.execute("SELECT COUNT(*) AS total FROM users WHERE role = 'user'").fetchone()["total"],
            "staff": db.execute("SELECT COUNT(*) AS total FROM users WHERE role = 'staff'").fetchone()["total"],
            "bookings": db.execute("SELECT COUNT(*) AS total FROM bookings").fetchone()["total"],
        }
        pending_staff = db.execute(
            "SELECT * FROM users WHERE role = 'staff' AND status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        recent_bookings = db.execute(
            """
            SELECT b.*, u.name AS user_name, t.name AS trek_name
            FROM bookings b
            JOIN users u ON u.id = b.user_id
            JOIN treks t ON t.id = b.trek_id
            ORDER BY b.booking_date DESC, b.id DESC
            LIMIT 8
            """
        ).fetchall()
        return render_template(
            "admin/dashboard.html",
            stats=stats,
            pending_staff=pending_staff,
            recent_bookings=recent_bookings,
        )

    @app.route("/admin/treks")
    @login_required("admin")
    def admin_treks():
        q = request.args.get("q", "").strip()
        params: list[str] = []
        where = ""
        if q:
            where = "WHERE t.name LIKE ? OR t.location LIKE ? OR CAST(t.id AS TEXT) = ? OR u.name LIKE ?"
            params = [f"%{q}%", f"%{q}%", q, f"%{q}%"]
        treks = get_db().execute(
            f"""
            SELECT t.*, u.name AS staff_name, COALESCE(b.booked_count, 0) AS booked_count
            FROM treks t
            LEFT JOIN users u ON u.id = t.assigned_staff_id
            LEFT JOIN (
                SELECT trek_id, COUNT(*) AS booked_count
                FROM bookings
                WHERE status = 'Booked'
                GROUP BY trek_id
            ) b ON b.trek_id = t.id
            {where}
            ORDER BY t.start_date DESC
            """,
            params,
        ).fetchall()
        return render_template("admin/treks.html", treks=treks, q=q)

    @app.route("/admin/treks/new", methods=("GET", "POST"))
    @login_required("admin")
    def create_trek():
        if request.method == "POST":
            form = trek_form_data()
            error = validate_trek_form(form)
            if error:
                flash(error, "danger")
                return render_template("admin/trek_form.html", trek=form, title="Create Trek")
            get_db().execute(
                """
                INSERT INTO treks
                    (name, location, difficulty, duration_days, available_slots,
                     status, start_date, end_date, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    form["name"],
                    form["location"],
                    form["difficulty"],
                    form["duration_days"],
                    form["available_slots"],
                    form["status"],
                    form["start_date"],
                    form["end_date"],
                    form["description"],
                    now_text(),
                ),
            )
            get_db().commit()
            flash("Trek created successfully.", "success")
            return redirect(url_for("admin_treks"))
        return render_template("admin/trek_form.html", trek={}, title="Create Trek")

    @app.route("/admin/treks/<int:trek_id>/edit", methods=("GET", "POST"))
    @login_required("admin")
    def edit_trek(trek_id: int):
        trek = get_trek_or_404(trek_id)
        if request.method == "POST":
            form = trek_form_data()
            error = validate_trek_form(form)
            if error:
                flash(error, "danger")
                return render_template("admin/trek_form.html", trek={**dict(trek), **form}, title="Edit Trek")
            get_db().execute(
                """
                UPDATE treks
                SET name = ?, location = ?, difficulty = ?, duration_days = ?,
                    available_slots = ?, status = ?, start_date = ?, end_date = ?,
                    description = ?
                WHERE id = ?
                """,
                (
                    form["name"],
                    form["location"],
                    form["difficulty"],
                    form["duration_days"],
                    form["available_slots"],
                    form["status"],
                    form["start_date"],
                    form["end_date"],
                    form["description"],
                    trek_id,
                ),
            )
            get_db().commit()
            flash("Trek updated successfully.", "success")
            return redirect(url_for("admin_treks"))
        return render_template("admin/trek_form.html", trek=trek, title="Edit Trek")

    @app.route("/admin/treks/<int:trek_id>/delete", methods=("POST",))
    @login_required("admin")
    def delete_trek(trek_id: int):
        get_trek_or_404(trek_id)
        get_db().execute("DELETE FROM treks WHERE id = ?", (trek_id,))
        get_db().commit()
        flash("Trek removed.", "info")
        return redirect(url_for("admin_treks"))

    @app.route("/admin/treks/<int:trek_id>/assign", methods=("GET", "POST"))
    @login_required("admin")
    def assign_staff(trek_id: int):
        trek = get_trek_or_404(trek_id)
        staff = get_db().execute(
            "SELECT * FROM users WHERE role = 'staff' AND status = 'approved' ORDER BY name"
        ).fetchall()
        if request.method == "POST":
            staff_id = request.form.get("staff_id") or None
            if staff_id:
                selected = get_db().execute(
                    "SELECT id FROM users WHERE id = ? AND role = 'staff' AND status = 'approved'",
                    (staff_id,),
                ).fetchone()
                if selected is None:
                    flash("Select an approved staff member.", "danger")
                    return render_template("admin/assign_staff.html", trek=trek, staff=staff)
            get_db().execute("UPDATE treks SET assigned_staff_id = ? WHERE id = ?", (staff_id, trek_id))
            get_db().commit()
            flash("Staff assignment updated.", "success")
            return redirect(url_for("admin_treks"))
        return render_template("admin/assign_staff.html", trek=trek, staff=staff)

    @app.route("/admin/users")
    @login_required("admin")
    def admin_users():
        q = request.args.get("q", "").strip()
        role = request.args.get("role", "").strip()
        clauses = ["role != 'admin'"]
        params: list[str] = []
        if q:
            clauses.append("(name LIKE ? OR email LIKE ? OR CAST(id AS TEXT) = ?)")
            params.extend([f"%{q}%", f"%{q}%", q])
        if role in {"user", "staff"}:
            clauses.append("role = ?")
            params.append(role)
        users = get_db().execute(
            f"SELECT * FROM users WHERE {' AND '.join(clauses)} ORDER BY role, name",
            params,
        ).fetchall()
        return render_template("admin/users.html", users=users, q=q, role=role)

    @app.route("/admin/users/<int:user_id>/status", methods=("POST",))
    @login_required("admin")
    def update_user_status(user_id: int):
        status = request.form.get("status")
        if status not in {"pending", "approved", "blacklisted"}:
            flash("Invalid status.", "danger")
            return redirect(url_for("admin_users"))
        user = get_db().execute("SELECT * FROM users WHERE id = ? AND role != 'admin'", (user_id,)).fetchone()
        if user is None:
            flash("User not found.", "danger")
            return redirect(url_for("admin_users"))
        get_db().execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
        if status == "blacklisted":
            get_db().execute(
                "UPDATE treks SET assigned_staff_id = NULL WHERE assigned_staff_id = ?",
                (user_id,),
            )
        get_db().commit()
        flash(f"{user['name']} status changed to {status}.", "success")
        return redirect(request.referrer or url_for("admin_users"))

    @app.route("/admin/bookings")
    @login_required("admin")
    def admin_bookings():
        q = request.args.get("q", "").strip()
        params: list[str] = []
        where = ""
        if q:
            where = """
                WHERE u.name LIKE ? OR t.name LIKE ? OR CAST(b.id AS TEXT) = ?
                   OR CAST(u.id AS TEXT) = ? OR CAST(t.id AS TEXT) = ?
            """
            params = [f"%{q}%", f"%{q}%", q, q, q]
        bookings = get_db().execute(
            f"""
            SELECT b.*, u.name AS user_name, u.email AS user_email, t.name AS trek_name, t.location
            FROM bookings b
            JOIN users u ON u.id = b.user_id
            JOIN treks t ON t.id = b.trek_id
            {where}
            ORDER BY b.booking_date DESC, b.id DESC
            """,
            params,
        ).fetchall()
        return render_template("admin/bookings.html", bookings=bookings, q=q)

    @app.route("/staff")
    @login_required("staff")
    def staff_dashboard():
        treks = get_db().execute(
            """
            SELECT t.*, COALESCE(b.booked_count, 0) AS booked_count
            FROM treks t
            LEFT JOIN (
                SELECT trek_id, COUNT(*) AS booked_count
                FROM bookings
                WHERE status = 'Booked'
                GROUP BY trek_id
            ) b ON b.trek_id = t.id
            WHERE t.assigned_staff_id = ?
            ORDER BY t.start_date
            """,
            (g.user["id"],),
        ).fetchall()
        return render_template("staff/dashboard.html", treks=treks)

    @app.route("/staff/treks/<int:trek_id>", methods=("GET", "POST"))
    @login_required("staff")
    def staff_manage_trek(trek_id: int):
        trek = get_assigned_trek_or_404(trek_id, g.user["id"])
        if request.method == "POST":
            available_slots = request.form.get("available_slots", "").strip()
            status = request.form.get("status", "").strip()
            if not available_slots.isdigit() or int(available_slots) < 0:
                flash("Slots must be a non-negative number.", "danger")
            elif status not in {"Open", "Ongoing", "Closed", "Completed"}:
                flash("Staff can only set status to Open, Ongoing, Closed, or Completed.", "danger")
            else:
                get_db().execute(
                    "UPDATE treks SET available_slots = ?, status = ? WHERE id = ?",
                    (int(available_slots), status, trek_id),
                )
                if status == "Completed":
                    get_db().execute(
                        "UPDATE bookings SET status = 'Completed' WHERE trek_id = ? AND status = 'Booked'",
                        (trek_id,),
                    )
                get_db().commit()
                flash("Trek details updated.", "success")
                return redirect(url_for("staff_dashboard"))
        participants = get_db().execute(
            """
            SELECT b.*, u.name, u.email, u.contact
            FROM bookings b
            JOIN users u ON u.id = b.user_id
            WHERE b.trek_id = ?
            ORDER BY b.booking_date DESC
            """,
            (trek_id,),
        ).fetchall()
        return render_template("staff/manage_trek.html", trek=trek, participants=participants)

    @app.route("/user")
    @login_required("user")
    def user_dashboard():
        q = request.args.get("q", "").strip()
        difficulty = request.args.get("difficulty", "").strip()
        location = request.args.get("location", "").strip()
        clauses = ["t.status = 'Open'"]
        params: list[str] = []
        if q:
            clauses.append("(t.name LIKE ? OR t.location LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        if difficulty in {"Easy", "Moderate", "Hard"}:
            clauses.append("t.difficulty = ?")
            params.append(difficulty)
        if location:
            clauses.append("t.location LIKE ?")
            params.append(f"%{location}%")
        treks = get_db().execute(
            f"""
            SELECT t.*, u.name AS staff_name, COALESCE(b.booked_count, 0) AS booked_count
            FROM treks t
            LEFT JOIN users u ON u.id = t.assigned_staff_id
            LEFT JOIN (
                SELECT trek_id, COUNT(*) AS booked_count
                FROM bookings
                WHERE status = 'Booked'
                GROUP BY trek_id
            ) b ON b.trek_id = t.id
            WHERE {' AND '.join(clauses)}
            ORDER BY t.start_date
            """,
            params,
        ).fetchall()
        my_bookings = get_db().execute(
            """
            SELECT b.*, t.name AS trek_name, t.location, t.start_date, t.end_date
            FROM bookings b
            JOIN treks t ON t.id = b.trek_id
            WHERE b.user_id = ?
            ORDER BY b.booking_date DESC, b.id DESC
            LIMIT 6
            """,
            (g.user["id"],),
        ).fetchall()
        booked_trek_ids = {
            row["trek_id"]
            for row in get_db().execute(
                "SELECT trek_id FROM bookings WHERE user_id = ? AND status = 'Booked'",
                (g.user["id"],),
            ).fetchall()
        }
        return render_template(
            "user/dashboard.html",
            treks=treks,
            bookings=my_bookings,
            booked_trek_ids=booked_trek_ids,
            q=q,
            difficulty=difficulty,
            location=location,
        )

    @app.route("/user/treks/<int:trek_id>/book", methods=("POST",))
    @login_required("user")
    def book_trek(trek_id: int):
        trek = get_trek_or_404(trek_id)
        if trek["status"] != "Open":
            flash("Only open treks can be booked.", "danger")
            return redirect(url_for("user_dashboard"))
        existing = get_db().execute(
            """
            SELECT id FROM bookings
            WHERE user_id = ? AND trek_id = ? AND status = 'Booked'
            """,
            (g.user["id"], trek_id),
        ).fetchone()
        if existing:
            flash("You already have an active booking for this trek.", "warning")
            return redirect(url_for("user_dashboard"))
        if remaining_slots(trek_id) <= 0:
            flash("This trek is fully booked.", "danger")
            return redirect(url_for("user_dashboard"))
        slot_update = get_db().execute(
            "UPDATE treks SET available_slots = available_slots - 1 WHERE id = ? AND available_slots > 0",
            (trek_id,),
        )
        if slot_update.rowcount != 1:
            get_db().rollback()
            flash("This trek is fully booked.", "danger")
            return redirect(url_for("user_dashboard"))
        get_db().execute(
            """
            INSERT INTO bookings (user_id, trek_id, booking_date, status)
            VALUES (?, ?, ?, 'Booked')
            """,
            (g.user["id"], trek_id, today_text()),
        )
        get_db().commit()
        flash("Trek booked successfully.", "success")
        return redirect(url_for("user_history"))

    @app.route("/user/bookings")
    @login_required("user")
    def user_history():
        bookings = get_db().execute(
            """
            SELECT b.*, t.name AS trek_name, t.location, t.difficulty, t.start_date, t.end_date, t.status AS trek_status
            FROM bookings b
            JOIN treks t ON t.id = b.trek_id
            WHERE b.user_id = ?
            ORDER BY b.booking_date DESC, b.id DESC
            """,
            (g.user["id"],),
        ).fetchall()
        return render_template("user/history.html", bookings=bookings)

    @app.route("/user/bookings/<int:booking_id>/cancel", methods=("POST",))
    @login_required("user")
    def cancel_booking(booking_id: int):
        booking = get_db().execute(
            "SELECT * FROM bookings WHERE id = ? AND user_id = ?",
            (booking_id, g.user["id"]),
        ).fetchone()
        if booking is None:
            flash("Booking not found.", "danger")
        elif booking["status"] != "Booked":
            flash("Only active bookings can be cancelled.", "warning")
        else:
            get_db().execute(
                "UPDATE bookings SET status = 'Cancelled' WHERE id = ?",
                (booking_id,),
            )
            get_db().execute(
                "UPDATE treks SET available_slots = available_slots + 1 WHERE id = ?",
                (booking["trek_id"],),
            )
            get_db().commit()
            flash("Booking cancelled.", "info")
        return redirect(url_for("user_history"))

    @app.route("/user/profile", methods=("GET", "POST"))
    @login_required("user")
    def edit_profile():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            contact = request.form.get("contact", "").strip()
            if not name:
                flash("Name is required.", "danger")
            else:
                get_db().execute(
                    "UPDATE users SET name = ?, contact = ? WHERE id = ?",
                    (name, contact, g.user["id"]),
                )
                get_db().commit()
                flash("Profile updated.", "success")
                return redirect(url_for("user_dashboard"))
        return render_template("user/profile.html")


def trek_form_data() -> dict[str, str | int]:
    return {
        "name": request.form.get("name", "").strip(),
        "location": request.form.get("location", "").strip(),
        "difficulty": request.form.get("difficulty", "").strip(),
        "duration_days": request.form.get("duration_days", "").strip(),
        "available_slots": request.form.get("available_slots", "").strip(),
        "status": request.form.get("status", "").strip(),
        "start_date": request.form.get("start_date", "").strip(),
        "end_date": request.form.get("end_date", "").strip(),
        "description": request.form.get("description", "").strip(),
    }


def validate_trek_form(form: dict[str, str | int]) -> str | None:
    required = ["name", "location", "difficulty", "duration_days", "available_slots", "status", "start_date", "end_date"]
    if any(not form[field] for field in required):
        return "All trek fields except description are required."
    if form["difficulty"] not in {"Easy", "Moderate", "Hard"}:
        return "Select a valid difficulty."
    if form["status"] not in set(TREK_STATUSES):
        return "Select a valid status."
    if not str(form["duration_days"]).isdigit() or int(form["duration_days"]) <= 0:
        return "Duration must be a positive number."
    if not str(form["available_slots"]).isdigit() or int(form["available_slots"]) < 0:
        return "Available slots must be zero or more."
    if form["end_date"] < form["start_date"]:
        return "End date cannot be before start date."
    form["duration_days"] = int(str(form["duration_days"]))
    form["available_slots"] = int(str(form["available_slots"]))
    return None


def get_trek_or_404(trek_id: int) -> sqlite3.Row:
    trek = get_db().execute("SELECT * FROM treks WHERE id = ?", (trek_id,)).fetchone()
    if trek is None:
        from flask import abort

        abort(404)
    return trek


def get_assigned_trek_or_404(trek_id: int, staff_id: int) -> sqlite3.Row:
    trek = get_db().execute(
        "SELECT * FROM treks WHERE id = ? AND assigned_staff_id = ?",
        (trek_id, staff_id),
    ).fetchone()
    if trek is None:
        from flask import abort

        abort(404)
    return trek


def booked_count(trek_id: int) -> int:
    return get_db().execute(
        "SELECT COUNT(*) AS total FROM bookings WHERE trek_id = ? AND status = 'Booked'",
        (trek_id,),
    ).fetchone()["total"]


def remaining_slots(trek_id: int) -> int:
    trek = get_trek_or_404(trek_id)
    return int(trek["available_slots"])


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
