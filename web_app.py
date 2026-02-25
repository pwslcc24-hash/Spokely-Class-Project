"""
Spokely Work Order Tracking — Web Prototype (production-shaped)
Single route / returns HTML: work orders, event log (last 10), and optional SMS banner.
"""

import json
import os
from datetime import datetime
from flask import Flask, request, redirect, url_for

app = Flask(__name__)
DATA_FILE = "workorders.json"
SNAPSHOT_FILE = "last_snapshot.json"
EVENT_LOG_FILE = "event_log.json"


# -----------------------------------------------------------------------------
# Data adapter: work orders source (JSON now; Lightspeed API later)
# -----------------------------------------------------------------------------

def get_workorders(source="json"):
    """Load work orders. source='json' reads workorders.json.
    TODO: replace with Lightspeed API later — e.g. fetch from API, normalize to same list-of-dict shape (id, customer, item, status, total, ...).
    """
    if source == "json":
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return []
        return []
    # TODO: elif source == "lightspeed": ... API call
    return []


def save_workorders(work_orders):
    """Persist work orders to workorders.json."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(work_orders, f, indent=2)
    except OSError:
        pass


def load_snapshot():
    """Load previous work order snapshot for diffing."""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_snapshot(work_orders):
    """Persist current work orders as snapshot for next request."""
    try:
        with open(SNAPSHOT_FILE, "w") as f:
            json.dump(work_orders, f, indent=2)
    except OSError:
        pass


# -----------------------------------------------------------------------------
# Event log: timestamp, workorder_id, event_type, message
# -----------------------------------------------------------------------------

def _read_event_log():
    if os.path.exists(EVENT_LOG_FILE):
        try:
            with open(EVENT_LOG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _write_event_log(events):
    try:
        with open(EVENT_LOG_FILE, "w") as f:
            json.dump(events, f, indent=2)
    except OSError:
        pass


def append_event(workorder_id, event_type, message):
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workorder_id": workorder_id,
        "event_type": event_type,
        "message": message,
    }
    events = _read_event_log()
    events.append(entry)
    _write_event_log(events)


def get_recent_events(limit=10):
    """Return last `limit` events (newest last for display)."""
    events = _read_event_log()
    return events[-limit:] if len(events) > limit else events


# -----------------------------------------------------------------------------
# Workflow engine: detect newly finished work orders and “notify” (simulate SMS)
# TODO: replace simulated SMS with Twilio/real SMS later.
# -----------------------------------------------------------------------------

def _status_finished(status):
    return (status or "").strip().lower() in ("finished", "complete", "completed")


def detect_finished_and_notify(old_list, new_list):
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
            append_event(wid, "sms_simulated", message)
            # Simulate SMS: log/print (replace with Twilio later)
            print(f"[SMS simulated] {message}")
            notified.append((wid, customer, item))
    return notified


# -----------------------------------------------------------------------------
# Single route: / — GET returns HTML; POST handles Add Work Order / Mark Finished
# -----------------------------------------------------------------------------

def _next_id(work_orders):
    """Next work order id."""
    return max((wo.get("id", 0) for wo in work_orders), default=0) + 1


def _escape(s):
    """Escape for HTML text content."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@app.route("/", methods=["GET", "POST"])
def index():
    """Single route: POST for add/mark-finished then redirect; GET renders full page."""
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
            work_orders = get_workorders(source="json")
            new_wo = {
                "id": _next_id(work_orders),
                "customer": customer,
                "item": item,
                "status": status,
                "total": total,
                "notification_sent": False,
            }
            work_orders.append(new_wo)
            save_workorders(work_orders)
        return redirect(url_for("index"))

    # --- POST: Mark Finished ---
    if request.method == "POST" and request.form.get("action") == "mark_finished":
        try:
            wid = int(request.form.get("workorder_id"))
        except (TypeError, ValueError):
            wid = None
        if wid is not None:
            work_orders = get_workorders(source="json")
            for wo in work_orders:
                if wo.get("id") == wid:
                    wo["status"] = "Finished"
                    if "notification_sent" in wo:
                        wo["notification_sent"] = True
                    break
            save_workorders(work_orders)
        return redirect(url_for("index"))

    # --- GET: load data, run workflow, build HTML ---
    new_list = get_workorders(source="json")
    old_list = load_snapshot()
    notified = detect_finished_and_notify(old_list, new_list)
    save_snapshot(new_list)
    recent_events = get_recent_events(10)

    html = [_build_page(new_list, notified, recent_events)]
    return "\n".join(html)


def _build_page(work_orders, notified, recent_events):
    """Build full HTML page with embedded CSS, header, form, table, banner, event log."""
    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Spokely Work Orders</title>",
        "<style>",
        "*,*::before,*::after{box-sizing:border-box;}",
        "body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f5f5f5;color:#222;}",
        ".app{max-width:900px;margin:0 auto;padding:24px;}",
        "header{background:#1a1a2e;color:#eee;padding:16px 20px;margin:-24px -24px 24px -24px;border-radius:0 0 8px 8px;}",
        "header h1{margin:0;font-size:1.5rem;font-weight:600;}",
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
        "<header><h1>Spokely Work Orders</h1></header>",
    ]

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
                f"<td><span class='badge {badge_class}'>{_escape(badge_text)}</span></td><td>{_escape(total_str)}</td><td>"
            )
            if not is_finished:
                parts.append(
                    f"<form method='post' action='/' style='display:inline;'>"
                    f"<input type='hidden' name='action' value='mark_finished'><input type='hidden' name='workorder_id' value='{wid}'>"
                    f"<button type='submit' class='btn btn-primary btn-sm'>Mark Finished</button></form>"
                )
            else:
                parts.append("—")
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
