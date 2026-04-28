"""
Spokely Work Order Tracking — Web Prototype (production-shaped)
Single route / returns HTML: work orders, event log (last 10), and optional SMS banner.
"""

import json
import os
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "spokely-dev-secret-change-in-production")
DATA_FILE = "workorders.json"
SNAPSHOT_FILE = "last_snapshot.json"
EVENT_LOG_FILE = "event_log.json"
STAFF_FILE = "staff.json"


# -----------------------------------------------------------------------------
# Data adapter: work orders per user (JSON now; Lightspeed API later)
# -----------------------------------------------------------------------------

def _norm_email(email):
    """Normalize email for storage key (lowercase)."""
    return (email or "").strip().lower()


def _load_workorders_raw():
    """Load full workorders file. Returns dict keyed by user email. Legacy list format → empty dict."""
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def _save_workorders_raw(data):
    """Save full workorders file (dict keyed by user email)."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


SAMPLE_WORK_ORDER = [
    {
        "id": 1,
        "customer": "Sample Customer",
        "item": "Sample repair",
        "status": "in progress",
        "total": 0.0,
        "notification_sent": False,
    }
]


def get_workorders(source="json", user_email=None):
    """Load work orders for the given user. If user has none, return one sample and save it.
    TODO: replace with Lightspeed API later — normalize to same list-of-dict shape.
    """
    if source != "json" or not user_email:
        return []
    key = _norm_email(user_email)
    data = _load_workorders_raw()
    work_orders = data.get(key)
    if not work_orders or not isinstance(work_orders, list):
        work_orders = list(SAMPLE_WORK_ORDER)
        data[key] = work_orders
        _save_workorders_raw(data)
    return work_orders


def save_workorders(work_orders, user_email):
    """Persist this user's work orders to workorders.json."""
    if not user_email:
        return
    key = _norm_email(user_email)
    data = _load_workorders_raw()
    data[key] = work_orders
    _save_workorders_raw(data)


# -----------------------------------------------------------------------------
# Staff login: store and retrieve staff (email + password hash)
# -----------------------------------------------------------------------------

def _load_staff():
    """Load staff list from staff.json."""
    if os.path.exists(STAFF_FILE):
        try:
            with open(STAFF_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_staff(staff_list):
    """Save staff list to staff.json."""
    try:
        with open(STAFF_FILE, "w") as f:
            json.dump(staff_list, f, indent=2)
    except OSError:
        pass


def _find_staff_by_email(email):
    """Return staff dict for email or None. Email comparison is case-insensitive."""
    email = (email or "").strip().lower()
    if not email:
        return None
    for s in _load_staff():
        if (s.get("email") or "").strip().lower() == email:
            return s
    return None


def register_staff(email, password):
    """Register a new staff member. Returns True if created, False if email already exists."""
    email = (email or "").strip().lower()
    if not email or not password:
        return False
    staff_list = _load_staff()
    if _find_staff_by_email(email):
        return False
    staff_list.append({
        "email": email,
        "password_hash": generate_password_hash(password),
    })
    _save_staff(staff_list)
    return True


def verify_staff(email, password):
    """Verify email + password. Returns True if valid."""
    s = _find_staff_by_email(email)
    if not s or not s.get("password_hash"):
        return False
    return check_password_hash(s["password_hash"], password)


def _current_user_email():
    """Return logged-in staff email or None."""
    return session.get("user")


def _require_login():
    """Redirect to login if not logged in. Return None if logged in, else redirect response."""
    if _current_user_email():
        return None
    return redirect(url_for("login"))


def _load_snapshot_raw():
    """Load full snapshot file (dict keyed by user email)."""
    if not os.path.exists(SNAPSHOT_FILE):
        return {}
    try:
        with open(SNAPSHOT_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_snapshot(user_email):
    """Load previous work order snapshot for this user."""
    if not user_email:
        return []
    key = _norm_email(user_email)
    return _load_snapshot_raw().get(key, [])


def save_snapshot(work_orders, user_email):
    """Persist this user's snapshot for next request."""
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


# -----------------------------------------------------------------------------
# Event log per user: timestamp, workorder_id, event_type, message
# -----------------------------------------------------------------------------

def _read_event_log_raw():
    """Load full event log file (dict keyed by user email)."""
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
    """Return last `limit` events for this user (newest last for display)."""
    if not user_email:
        return []
    key = _norm_email(user_email)
    events = _read_event_log_raw().get(key, [])
    return events[-limit:] if len(events) > limit else events


# -----------------------------------------------------------------------------
# Workflow engine: detect newly finished work orders and “notify” (simulate SMS)
# TODO: replace simulated SMS with Twilio/real SMS later.
# -----------------------------------------------------------------------------

def _status_finished(status):
    return (status or "").strip().lower() in ("finished", "complete", "completed")


def detect_finished_and_notify(old_list, new_list, user_email=None):
    """Compare old vs new; for any work order that became finished, log event and simulate SMS.
    Returns list of (workorder_id, customer, item) that were “notified” this run (for banner).
    """
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
            # Simulate SMS: log/print (replace with Twilio later)
            print(f"[SMS simulated] {message}")
            notified.append((wid, customer, item))
    return notified


# -----------------------------------------------------------------------------
# Routes: / (dashboard), /add_workorder (submission form)
# -----------------------------------------------------------------------------

def _next_id(work_orders):
    """Next work order id."""
    return max((wo.get("id", 0) for wo in work_orders), default=0) + 1


def _escape(s):
    """Escape for HTML text content."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@app.route("/login", methods=["GET", "POST"])
def login():
    """Staff login: GET shows form; POST verifies email/password and redirects to dashboard."""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        if email and verify_staff(email, password):
            session["user"] = email
            return redirect(url_for("index"))
        # Invalid login: re-show form with message
        return render_template("login.html", error="Invalid email or password.")
    if _current_user_email():
        return redirect(url_for("index"))
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    """Clear session and redirect to login."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    """Create staff account: GET form; POST save to staff.json and redirect to login."""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not email or not password:
            return render_template("register.html", error="Email and password are required.")
        if password != confirm:
            return render_template("register.html", error="Passwords do not match.")
        if _find_staff_by_email(email):
            return render_template("register.html", error="An account with this email already exists.")
        register_staff(email, password)
        return redirect(url_for("login"))
    if _current_user_email():
        return redirect(url_for("index"))
    return render_template("register.html", error=None)


@app.route("/", methods=["GET", "POST"])
def index():
    """Dashboard: requires login. POST for add/mark-finished/delete; GET shows this user's work orders and events."""
    redirect_resp = _require_login()
    if redirect_resp is not None:
        return redirect_resp
    user_email = _current_user_email()

    # --- POST: Add Work Order ---
    if request.method == "POST" and request.form.get("action") == "add":
        customer = (request.form.get("customer") or "").strip()
        item = (request.form.get("item") or "").strip()
        try:
            total = float(request.form.get("total") or "0")
        except ValueError:
            total = 0
        status = (request.form.get("status") or "in progress").strip() or "in progress"
        if customer and item:
            work_orders = get_workorders(source="json", user_email=user_email)
            new_wo = {
                "id": _next_id(work_orders),
                "customer": customer,
                "item": item,
                "status": status,
                "total": total,
                "notification_sent": False,
            }
            work_orders.append(new_wo)
            save_workorders(work_orders, user_email)
        return redirect(url_for("index"))

    # --- POST: Mark Finished ---
    if request.method == "POST" and request.form.get("action") == "mark_finished":
        try:
            wid = int(request.form.get("workorder_id"))
        except (TypeError, ValueError):
            wid = None
        if wid is not None:
            work_orders = get_workorders(source="json", user_email=user_email)
            for wo in work_orders:
                if wo.get("id") == wid:
                    wo["status"] = "Finished"
                    if "notification_sent" in wo:
                        wo["notification_sent"] = True
                    break
            save_workorders(work_orders, user_email)
        return redirect(url_for("index"))

    # --- POST: Delete Work Order ---
    if request.method == "POST" and request.form.get("action") == "delete":
        try:
            wid = int(request.form.get("workorder_id"))
        except (TypeError, ValueError):
            wid = None
        if wid is not None:
            work_orders = get_workorders(source="json", user_email=user_email)
            work_orders[:] = [wo for wo in work_orders if wo.get("id") != wid]
            save_workorders(work_orders, user_email)
        return redirect(url_for("index"))

    # --- GET: load this user's data, run workflow, build HTML ---
    new_list = get_workorders(source="json", user_email=user_email)
    old_list = load_snapshot(user_email)
    notified = detect_finished_and_notify(old_list, new_list, user_email)
    save_snapshot(new_list, user_email)
    recent_events = get_recent_events(10, user_email)

    html = [_build_page(new_list, notified, recent_events, user_email)]
    return "\n".join(html)


@app.route("/add_workorder", methods=["GET", "POST"])
def add_workorder():
    """Work order submission form: requires login. GET form; POST save and redirect to dashboard."""
    redirect_resp = _require_login()
    if redirect_resp is not None:
        return redirect_resp
    user_email = _current_user_email()
    if request.method == "POST":
        # Extract submitted form data (structured as dictionary for the data model)
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
        if not customer or not item:
            return redirect(url_for("add_workorder"))
        work_orders = get_workorders(source="json", user_email=user_email)
        # Use form ID only if provided and positive; otherwise assign next available
        if form_id is not None and form_id > 0 and not any(wo.get("id") == form_id for wo in work_orders):
            wo_id = form_id
        else:
            wo_id = _next_id(work_orders)
        new_work_order = {
            "id": wo_id,
            "customer": customer,
            "item": item,
            "status": status,
            "total": total,
            "notification_sent": False,
        }
        work_orders.append(new_work_order)
        save_workorders(work_orders, user_email)
        return redirect(url_for("index"))
    return render_template("add_workorder.html")


def _build_page(work_orders, notified, recent_events, user_email=None):
    """Build full HTML page: personalized dashboard with work orders and workflow events."""
    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Spokely Work Orders</title>",
        "<style>",
        "*,*::before,*::after{box-sizing:border-box;}",
        "body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f5f5f5;color:#222;}",
        ".app{max-width:900px;margin:0 auto;padding:24px;}",
        "header{background:#1a1a2e;color:#eee;padding:16px 20px;margin:-24px -24px 24px -24px;border-radius:0 0 8px 8px;}",
        "header h1{margin:0;font-size:1.5rem;font-weight:600;}",
        "header .header-links{margin:8px 0 0 0;}",
        "header .header-links a{color:#8ab4f8;}",
        "header .header-links a:hover{text-decoration:underline;}",
        ".banner{background:#e7f3ff;border:1px solid #0066cc;border-radius:6px;padding:12px 16px;margin-bottom:20px;}",
        ".banner strong{color:#004080;}",
        "h2{font-size:1.1rem;color:#333;margin:0 0 12px 0;}",
        "table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);}",
        "th,td{padding:12px 16px;text-align:left;border-bottom:1px solid #eee;}",
        "th{background:#f8f9fa;font-weight:600;color:#444;}",
        "tr:last-child td{border-bottom:0;}",
        ".badge{padding:4px 10px;border-radius:20px;font-size:0.85rem;font-weight:500;}",
        ".badge.inprogress{background:#fff3cd;color:#856404;}",
        ".badge.finished{background:#d4edda;color:#155724;}",
        ".btn{padding:8px 14px;border-radius:6px;border:none;cursor:pointer;font-size:0.9rem;}",
        ".btn-primary{background:#1a1a2e;color:#fff;}",
        ".btn-primary:hover{background:#2d2d44;}",
        ".btn-sm{padding:6px 10px;font-size:0.85rem;}",
        ".btn-danger{background:#dc3545;color:#fff;}",
        ".btn-danger:hover{background:#c82333;}",
        ".action-cell form{display:inline;margin-right:6px;}",
        ".card{background:#fff;border-radius:8px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);}",
        ".form-row{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:8px;}",
        ".form-group{min-width:120px;}",
        ".form-group label{display:block;font-size:0.85rem;color:#555;margin-bottom:4px;}",
        ".form-group input,.form-group select{width:100%;padding:8px 10px;border:1px solid #ccc;border-radius:6px;}",
        ".event-log{background:#f8f9fa;border:1px solid #dee2e6;border-radius:6px;padding:12px;max-height:280px;overflow-y:auto;}",
        ".event-log ul{margin:0;padding-left:20px;}",
        ".event-log li{margin:4px 0;font-size:0.9rem;color:#444;}",
        ".event-log .meta{color:#666;font-size:0.8rem;}",
        "</style>",
        "</head><body><div class='app'>",
        "<header><h1>Spokely Work Orders</h1>",
        "<p class='header-links'>",
    ]
    if user_email:
        parts.append(f"<span>Welcome, {_escape(user_email)}</span> &middot; ")
    parts.append("<a href='/add_workorder'>Add Work Order (form)</a> &middot; <a href='/logout'>Log out</a></p></header>")

    # Notification banner
    if notified:
        lines = [f"Work order #{wid} ({_escape(customer)} – {_escape(item)}) marked finished; SMS simulated." for wid, customer, item in notified]
        parts.append("<div class='banner'><strong>Notification:</strong> " + " ".join(lines) + "</div>")

    # Add Work Order form
    parts.append("<div class='card'><h2>Add Work Order</h2>")
    parts.append("<form method='post' action='/'>")
    parts.append("<input type='hidden' name='action' value='add'>")
    parts.append("<div class='form-row'>")
    parts.append("<div class='form-group'><label>Customer</label><input type='text' name='customer' required></div>")
    parts.append("<div class='form-group'><label>Item</label><input type='text' name='item' required></div>")
    parts.append("<div class='form-group'><label>Total ($)</label><input type='number' name='total' step='0.01' value='0'></div>")
    parts.append("<div class='form-group'><label>Status</label><select name='status'><option value='in progress' selected>in progress</option><option value='Finished'>Finished</option></select></div>")
    parts.append("<div class='form-group'><label>&nbsp;</label><button type='submit' class='btn btn-primary'>Add Work Order</button></div>")
    parts.append("</div></form></div>")

    # Work orders table
    parts.append("<div class='card'><h2>Work Orders</h2>")
    if not work_orders:
        parts.append("<p>No work orders yet. Add one above.</p>")
    else:
        parts.append("<table><thead><tr><th>ID</th><th>Customer</th><th>Item</th><th>Status</th><th>Total</th><th>Action</th></tr></thead><tbody>")
        for wo in work_orders:
            total = wo.get("total", 0)
            total_str = f"${total:.2f}" if isinstance(total, (int, float)) else str(total)
            status_val = (wo.get("status") or "").strip()
            is_finished = _status_finished(status_val)
            badge_class = "finished" if is_finished else "inprogress"
            badge_text = "Finished" if is_finished else "In progress"
            wid = wo.get("id")
            parts.append(
                f"<tr><td>{wid}</td><td>{_escape(wo.get('customer'))}</td><td>{_escape(wo.get('item'))}</td>"
                f"<td><span class='badge {badge_class}'>{_escape(badge_text)}</span></td><td>{_escape(total_str)}</td><td class='action-cell'>"
            )
            if not is_finished:
                parts.append(
                    f"<form method='post' action='/'>"
                    f"<input type='hidden' name='action' value='mark_finished'><input type='hidden' name='workorder_id' value='{wid}'>"
                    f"<button type='submit' class='btn btn-primary btn-sm'>Mark Finished</button></form>"
                )
            parts.append(
                f"<form method='post' action='/'>"
                f"<input type='hidden' name='action' value='delete'><input type='hidden' name='workorder_id' value='{wid}'>"
                f"<button type='submit' class='btn btn-danger btn-sm'>Delete</button></form>"
            )
            parts.append("</td></tr>")
        parts.append("</tbody></table>")
    parts.append("</div>")

    # Event log panel
    parts.append("<div class='card'><h2>Event log (last 10)</h2><div class='event-log'>")
    if not recent_events:
        parts.append("<p>No events yet.</p>")
    else:
        parts.append("<ul>")
        for e in recent_events:
            parts.append(
                f"<li><span class='meta'>{_escape(e.get('timestamp'))}</span> WO #{e.get('workorder_id')} "
                f"{_escape(e.get('event_type'))}: {_escape(e.get('message'))}</li>"
            )
        parts.append("</ul>")
    parts.append("</div></div>")

    parts.append("</div></body></html>")
    return "".join(parts)


if __name__ == "__main__":
    app.run(debug=True)
