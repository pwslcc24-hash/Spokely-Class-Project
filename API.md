# Spokely REST API (v1)

Base URL prefix: **`/api/v1`**

Authentication uses the same **Flask session** as the web app. Callers must send the session cookie received after logging in via `POST /login` (e.g. browser, or `curl` with a cookie jar).

### Logged in vs logged out (browser)

| Situation | What you get |
|-----------|----------------|
| **Logged in** in the **same** browser tab/window (session cookie present) | **200** + JSON with your `work_orders`. |
| **Logged out**, incognito, or **no cookie** sent | **401** + JSON `{"success": false, "code": "unauthorized", ...}`. |

**Important:** The embedded / Simple Browser preview in some editors uses a **separate cookie store** from your normal browser tab. If you log in on `http://127.0.0.1:5000/login` in Chrome but open `/api/v1/workorders` in the built-in preview, you may look “logged out” and get **401** (or a generic “invalid response” page that still corresponds to 401 in the server log). To test like a user: log in, then paste the API URL in the **same** browser where you logged in, or use **curl** with a cookie file as below.

## Endpoints

### `GET /api/v1/workorders`

Returns a JSON list of all work orders for the **currently authenticated user**.

| Status | Meaning |
|--------|---------|
| **200** | Success — body includes `work_orders` array |
| **401** | Not logged in |

Example success body:

```json
{
  "success": true,
  "api_version": "v1",
  "count": 2,
  "work_orders": [ { ... }, { ... } ]
}
```

---

### `GET /api/v1/workorders/<id>`

Returns a single work order by numeric **id**, only if it belongs to the current user.

| Status | Meaning |
|--------|---------|
| **200** | Found — body includes `work_order` object |
| **401** | Not logged in |
| **404** | No such work order for this user (includes missing id or another user’s id) |

Example success body:

```json
{
  "success": true,
  "api_version": "v1",
  "work_order": {
    "id": 1,
    "user_id": 1,
    "owner_email": "user@example.com",
    "customer": "...",
    "item": "...",
    "status": "in progress",
    "total": 0.0,
    "notification_sent": false
  }
}
```

## Try with curl

```bash
# 1) Log in and save cookies
curl -c cookies.txt -b cookies.txt -X POST http://127.0.0.1:5000/login \
  -d "email=you@example.com&password=yourpassword" -L -s -o /dev/null

# 2) List work orders
curl -b cookies.txt http://127.0.0.1:5000/api/v1/workorders

# 3) One work order
curl -b cookies.txt http://127.0.0.1:5000/api/v1/workorders/1
```
