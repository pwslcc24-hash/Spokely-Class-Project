"""
Spokely Work Order Tracking — multi-user app with SQLite, sessions, and hashed passwords.
"""

import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask, request, redirect, url_for, render_template, session, abort, g
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, WorkOrder
from routes.api_routes import api_v1_bp

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


def _database_uri():
    """SQLAlchemy DB URI from DATABASE_URL, or local SQLite in the project directory."""
    uri = (os.environ.get("DATABASE_URL") or "").strip()
    if uri:
        return uri
    return "sqlite:///" + os.path.join(basedir, "project.db")


def _secret_key():
    key = (os.environ.get("SECRET_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "SECRET_KEY is not set. Copy .env.example to .env and set SECRET_KEY, "
            "or export SECRET_KEY in the environment."
        )
    return key


app = Flask(__name__)
app.secret_key = _secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
app.register_blueprint(api_v1_bp)

SNAPSHOT_FILE = "last_snapshot.json"
EVENT_LOG_FILE = "event_log.json"
STAFF_FILE = "staff.json"  # legacy: one-time import into users table if empty

MIN_PASSWORD_LENGTH = 8
MAX_FIELD_LEN = {"customer": 255, "item": 512, "status": 64}


# -----------------------------------------------------------------------------
# Input validation
# -----------------------------------------------------------------------------

def _norm_email(email):
    return (email or "").strip().lower()


def validate_email_format(email):
    """Basic RFC-like check for login/register."""
    if not email or len(email) > 255:
        return "Enter a valid email address."
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return "Enter a valid email address."
    return None


def validate_password_new(password):
    """Registration password rules."""
    if not password:
        return "Password is required."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 128:
        return "Password is too long."
    return None


def _safe_user_id(uid):
    """Normalize session / form user ids to int (Flask session JSON may use str)."""
    if uid is None:
        return None
    try:
        i = int(uid)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def validate_work_order_fields(customer, item, status):
    """Sanitize length for work order text fields."""
    customer = (customer or "").strip()
    item = (item or "").strip()
    status = (status or "in progress").strip() or "in progress"
    if not customer or not item:
        return None, None, None, "Customer and item are required."
    if len(customer) > MAX_FIELD_LEN["customer"] or len(item) > MAX_FIELD_LEN["item"]:
        return None, None, None, "Input too long."
    if len(status) > MAX_FIELD_LEN["status"]:
        status = status[: MAX_FIELD_LEN["status"]]
    return customer, item, status, None


# -----------------------------------------------------------------------------
# Schema migration (legacy owner_email / staff.json)
# -----------------------------------------------------------------------------

def _ensure_schema_and_migrate():
    """Create tables; migrate legacy staff.json and work_orders.owner_email → user_id."""
    db.create_all()
    insp = inspect(db.engine)
    tables = insp.get_table_names()

    if "users" not in tables:
        db.create_all()

    # Import legacy staff.json into users if DB has no users
    if User.query.count() == 0 and os.path.exists(STAFF_FILE):
        try:
            with open(STAFF_FILE, "r", encoding="utf-8") as f:
                staff = json.load(f)
            for s in staff:
                em = _norm_email(s.get("email"))
                ph = s.get("password_hash")
                if em and ph and not User.query.filter_by(email=em).first():
                    db.session.add(User(email=em, password_hash=ph))
            db.session.commit()
        except (json.JSONDecodeError, OSError, Exception):
            db.session.rollback()

    if "work_orders" not in tables:
        return

    cols = {c["name"] for c in insp.get_columns("work_orders")}
    if "owner_email" in cols and "user_id" not in cols:
        try:
            db.session.execute(text("ALTER TABLE work_orders ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            db.session.commit()
        except Exception:
            db.session.rollback()
            cols = {c["name"] for c in inspect(db.engine).get_columns("work_orders")}
            if "user_id" not in cols:
                return
        rows = db.session.execute(text("SELECT id, owner_email FROM work_orders")).fetchall()
        for rid, oem in rows:
            u = User.query.filter_by(email=_norm_email(oem)).first()
            if u:
                db.session.execute(
                    text("UPDATE work_orders SET user_id = :uid WHERE id = :rid"),
                    {"uid": u.id, "rid": rid},
                )
        db.session.commit()
    elif "user_id" in cols and "owner_email" in cols:
        rows = db.session.execute(
            text("SELECT id, owner_email FROM work_orders WHERE user_id IS NULL")
        ).fetchall()
        for rid, oem in rows:
            u = User.query.filter_by(email=_norm_email(oem)).first()
            if u:
                db.session.execute(
                    text("UPDATE work_orders SET user_id = :uid WHERE id = :rid"),
                    {"uid": u.id, "rid": rid},
                )
        db.session.commit()


# -----------------------------------------------------------------------------
# Data layer: work orders scoped by user_id (FK to User)
# -----------------------------------------------------------------------------

def get_workorders(user_id):
    """Load work orders for the logged-in user."""
    user_id = _safe_user_id(user_id)
    if not user_id:
        return []
    rows = WorkOrder.query.filter_by(user_id=user_id).order_by(WorkOrder.id).all()
    if not rows:
        owner = db.session.get(User, user_id)
        if owner is None:
            return []
        sample = WorkOrder(
            user_id=user_id,
            owner_email=owner.email,
            customer="Sample Customer",
            item="Sample repair",
            status="in progress",
            total=0.0,
            notification_sent=False,
        )
        db.session.add(sample)
        db.session.commit()
        rows = WorkOrder.query.filter_by(user_id=user_id).order_by(WorkOrder.id).all()
    return [r.to_dict() for r in rows]


def add_work_order_db(user_id, customer, item, status, total, explicit_id=None):
    """Insert work order; requires a valid user_id that exists in users (FK)."""
    user_id = _safe_user_id(user_id)
    owner = db.session.get(User, user_id) if user_id else None
    if not user_id or owner is None:
        return
    kwargs = {
        "user_id": user_id,
        "owner_email": owner.email,
        "customer": customer,
        "item": item,
        "status": status or "in progress",
        "total": float(total or 0),
        "notification_sent": False,
    }
    if explicit_id is not None and explicit_id > 0 and db.session.get(WorkOrder, explicit_id) is None:
        kwargs["id"] = explicit_id
    wo = WorkOrder(**kwargs)
    db.session.add(wo)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def mark_work_order_finished_db(user_id, workorder_id):
    user_id = _safe_user_id(user_id)
    if not user_id:
        return
    wo = WorkOrder.query.filter_by(id=workorder_id, user_id=user_id).first()
    if wo:
        wo.status = "Finished"
        wo.notification_sent = True
        db.session.commit()


def delete_work_order_db(user_id, workorder_id):
    user_id = _safe_user_id(user_id)
    if not user_id:
        return
    wo = WorkOrder.query.filter_by(id=workorder_id, user_id=user_id).first()
    if wo:
        db.session.delete(wo)
        db.session.commit()


def update_work_order_db(user_id, workorder_id, customer, item, status, total):
    user_id = _safe_user_id(user_id)
    if not user_id:
        return False
    wo = WorkOrder.query.filter_by(id=workorder_id, user_id=user_id).first()
    if not wo:
        return False
    wo.customer = customer
    wo.item = item
    wo.status = status or "in progress"
    wo.total = float(total or 0)
    st = (wo.status or "").strip().lower()
    wo.notification_sent = st in ("finished", "complete", "completed")
    db.session.commit()
    return True


def get_work_order_for_user(user_id, item_id):
    user_id = _safe_user_id(user_id)
    if not user_id:
        return None
    return WorkOrder.query.filter_by(id=item_id, user_id=user_id).first()


# -----------------------------------------------------------------------------
# Authentication (User table + Flask session)
# -----------------------------------------------------------------------------

def register_user(email, password):
    """Create user with hashed password. Returns (True, None) or (False, error_message)."""
    email = _norm_email(email)
    err = validate_email_format(email)
    if err:
        return False, err
    err = validate_password_new(password)
    if err:
        return False, err
    if User.query.filter_by(email=email).first():
        return False, "An account with this email already exists."
    u = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(u)
    db.session.commit()
    return True, None


def verify_user_login(email, password):
    """Return User if credentials valid, else None."""
    email = _norm_email(email)
    if not email or not password:
        return None
    u = User.query.filter_by(email=email).first()
    if not u or not check_password_hash(u.password_hash, password):
        return None
    return u


def resolve_current_user():
    """Load User from session; repair stale sessions (missing user_id, or user_id not in DB)."""
    raw_uid = session.get("user_id")
    uid = _safe_user_id(raw_uid)
    if raw_uid is not None and uid is None:
        session.pop("user_id", None)
    email = session.get("user")
    if uid is not None:
        u = db.session.get(User, uid)
        if u is not None:
            if session.get("user_id") != uid:
                session["user_id"] = uid
            if email and _norm_email(email) != u.email:
                session["user"] = u.email
            return u
        session.pop("user_id", None)
    if email:
        u = User.query.filter_by(email=_norm_email(email)).first()
        if u is not None:
            session["user_id"] = int(u.id)
            session["user"] = u.email
            return u
    return None


def _current_user_id():
    """Logged-in user id (after session resolution)."""
    u = getattr(g, "current_user", None)
    return u.id if u else None


def _current_user_email():
    u = getattr(g, "current_user", None)
    return u.email if u else session.get("user")


def _set_session_user(user):
    """Store user id and email in signed session."""
    session.clear()
    session["user_id"] = int(user.id)
    session["user"] = user.email


def _require_login():
    if getattr(g, "current_user", None) is not None:
        return None
    session.clear()
    return redirect(url_for("login"))


@app.before_request
def _attach_current_user():
    """Resolve login on every request so FK always matches a real User row."""
    g.current_user = None
    if request.endpoint == "static":
        return
    g.current_user = resolve_current_user()


# -----------------------------------------------------------------------------
# Snapshot & event log (keyed by normalized email for compatibility)
# -----------------------------------------------------------------------------

def _load_snapshot_raw():
    if not os.path.exists(SNAPSHOT_FILE):
        return {}
    try:
        with open(SNAPSHOT_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_snapshot(user_email):
    if not user_email:
        return []
    key = _norm_email(user_email)
    return _load_snapshot_raw().get(key, [])


def save_snapshot(work_orders, user_email):
    if not user_email:
        return
    key = _norm_email(user_email)
    data = _load_snapshot_raw()
    data[key] = work_orders
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def _read_event_log_raw():
    if not os.path.exists(EVENT_LOG_FILE):
        return {}
    try:
        with open(EVENT_LOG_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_event_log_raw(data):
    try:
        with open(EVENT_LOG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def append_event(workorder_id, event_type, message, user_email=None):
    if not user_email:
        return
    key = _norm_email(user_email)
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workorder_id": workorder_id,
        "event_type": event_type,
        "message": message,
    }
    data = _read_event_log_raw()
    events = data.get(key, [])
    events.append(entry)
    data[key] = events
    _write_event_log_raw(data)


def get_recent_events(limit=10, user_email=None):
    if not user_email:
        return []
    key = _norm_email(user_email)
    events = _read_event_log_raw().get(key, [])
    return events[-limit:] if len(events) > limit else events


# -----------------------------------------------------------------------------
# Workflow: finished → simulated SMS
# -----------------------------------------------------------------------------

def _status_finished(status):
    return (status or "").strip().lower() in ("finished", "complete", "completed")


def detect_finished_and_notify(old_list, new_list, user_email=None):
    old_by_id = {wo.get("id"): wo for wo in (old_list or [])}
    notified = []
    for wo in new_list or []:
        wid = wo.get("id")
        new_finished = _status_finished(wo.get("status"))
        old_wo = old_by_id.get(wid)
        old_finished = _status_finished(old_wo.get("status")) if old_wo else False
        if new_finished and not old_finished:
            customer = wo.get("customer", "")
            item = wo.get("item", "")
            message = f"SMS would be sent to {customer} for work order #{wid} ({item})"
            append_event(wid, "sms_simulated", message, user_email)
            print(f"[SMS simulated] {message}")
            notified.append((wid, customer, item))
    return notified


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        if not email:
            return render_template("login.html", error="Email is required.")
        err = validate_email_format(_norm_email(email))
        if err:
            return render_template("login.html", error=err)
        u = verify_user_login(email, password)
        if u:
            _set_session_user(u)
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid email or password.")
    if _current_user_id() is not None:
        return redirect(url_for("index"))
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not email:
            return render_template("register.html", error="Email is required.")
        err = validate_email_format(_norm_email(email))
        if err:
            return render_template("register.html", error=err)
        if password != confirm:
            return render_template("register.html", error="Passwords do not match.")
        ok, msg = register_user(email, password)
        if not ok:
            return render_template("register.html", error=msg)
        return redirect(url_for("login"))
    if _current_user_id() is not None:
        return redirect(url_for("index"))
    return render_template("register.html", error=None)


@app.route("/", methods=["GET", "POST"])
def index():
    redirect_resp = _require_login()
    if redirect_resp is not None:
        return redirect_resp
    uid = _current_user_id()
    user_email = _current_user_email()

    if request.method == "POST" and request.form.get("action") == "add":
        customer = (request.form.get("customer") or "").strip()
        item = (request.form.get("item") or "").strip()
        try:
            total = float(request.form.get("total") or "0")
        except ValueError:
            total = 0
        status = (request.form.get("status") or "in progress").strip() or "in progress"
        c, i, st, verr = validate_work_order_fields(customer, item, status)
        if verr:
            pass  # could flash; redirect keeps UX simple
        elif c and i:
            add_work_order_db(uid, c, i, st, total)
        return redirect(url_for("index"))

    if request.method == "POST" and request.form.get("action") == "mark_finished":
        try:
            wid = int(request.form.get("workorder_id"))
        except (TypeError, ValueError):
            wid = None
        if wid is not None:
            mark_work_order_finished_db(uid, wid)
        return redirect(url_for("index"))

    new_list = get_workorders(uid)
    old_list = load_snapshot(user_email)
    notified = detect_finished_and_notify(old_list, new_list, user_email)
    save_snapshot(new_list, user_email)
    recent_events = get_recent_events(10, user_email)
    return render_template(
        "index.html",
        work_orders=new_list,
        notified=notified,
        recent_events=recent_events,
        user_email=user_email,
    )


@app.route("/edit/<int:item_id>", methods=["GET", "POST"])
def edit_workorder(item_id):
    redirect_resp = _require_login()
    if redirect_resp is not None:
        return redirect_resp
    uid = _current_user_id()
    wo = get_work_order_for_user(uid, item_id)
    if not wo:
        abort(404)
    if request.method == "POST":
        customer = (request.form.get("customer") or "").strip()
        item = (request.form.get("item") or "").strip()
        status = (request.form.get("status") or "in progress").strip() or "in progress"
        try:
            total = float(request.form.get("total") or "0")
        except ValueError:
            total = 0.0
        c, i, st, verr = validate_work_order_fields(customer, item, status)
        if c and i and not verr:
            update_work_order_db(uid, item_id, c, i, st, total)
        return redirect(url_for("index"))
    return render_template("edit_workorder.html", wo=wo)


@app.route("/delete/<int:item_id>", methods=["POST"])
def delete_workorder(item_id):
    redirect_resp = _require_login()
    if redirect_resp is not None:
        return redirect_resp
    delete_work_order_db(_current_user_id(), item_id)
    return redirect(url_for("index"))


@app.route("/add_workorder", methods=["GET", "POST"])
def add_workorder():
    redirect_resp = _require_login()
    if redirect_resp is not None:
        return redirect_resp
    uid = _current_user_id()
    if request.method == "POST":
        raw_id = request.form.get("id")
        try:
            form_id = int(raw_id) if raw_id and str(raw_id).strip() else None
        except ValueError:
            form_id = None
        customer = (request.form.get("customer") or "").strip()
        item = (request.form.get("item") or "").strip()
        status = (request.form.get("status") or "in progress").strip() or "in progress"
        try:
            total = float(request.form.get("total") or "0")
        except ValueError:
            total = 0.0
        c, i, st, verr = validate_work_order_fields(customer, item, status)
        if not c or not i or verr:
            return redirect(url_for("add_workorder"))
        explicit_id = form_id if form_id is not None and form_id > 0 else None
        add_work_order_db(uid, c, i, st, total, explicit_id=explicit_id)
        return redirect(url_for("index"))
    return render_template("add_workorder.html")


with app.app_context():
    _ensure_schema_and_migrate()


if __name__ == "__main__":
    _d = (os.environ.get("FLASK_DEBUG") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    _host = (os.environ.get("FLASK_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    _port = int((os.environ.get("FLASK_PORT") or "5000").strip() or "5000")
    app.run(host=_host, port=_port, debug=_d)
