# Spokely – Work Order Tracking System

CLI prototype for tracking work orders. Add orders, list them, and mark them as finished (with a simulated SMS notification). Data is stored in `workorders.json` so it persists between runs.

## How to run

**Run the program with:**

```bash
python app.py
```

Or, if your system uses `python3`:

```bash
python3 app.py
```

Use the menu in the terminal: **1** Add work order, **2** List work orders, **3** Mark work order as finished, **4** Exit.

## Dependencies

See `requirements.txt`. This project uses only the Python standard library (`json`, `os`); no extra packages are required.
