# Week 4 CLI Prototype - Spokely Work Order Tracking System

import json
import os

# File for persistent storage of work orders
DATA_FILE = "workorders.json"

# Global list of work orders (each is a dict: id, customer, item, status, total)
work_orders = []


def load_work_orders():
    """Load work orders from workorders.json at startup."""
    global work_orders
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                work_orders = json.load(f)
            # Ensure each work order has notification_sent (for backward compatibility)
            for wo in work_orders:
                if "notification_sent" not in wo:
                    wo["notification_sent"] = wo.get("status") == "finished"
        except (json.JSONDecodeError, OSError):
            work_orders = []
    else:
        work_orders = []


def save_work_orders():
    """Save work orders to workorders.json after changes."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(work_orders, f, indent=2)
    except OSError:
        print("Error: Could not save work orders to file.")


def add_work_order():
    """Add a new work order to the system."""
    print("\n--- Add Work Order ---")
    
    # Generate ID as max existing ID + 1 (works after loading from file)
    work_order_id = max((wo["id"] for wo in work_orders), default=0) + 1
    
    # Get customer name
    customer = input("Enter customer name: ").strip()
    if not customer:
        print("Error: Customer name cannot be empty.")
        return
    
    # Get item/service description
    item = input("Enter item/service description: ").strip()
    if not item:
        print("Error: Item description cannot be empty.")
        return
    
    # Get total price
    try:
        total = float(input("Enter total price ($): "))
        if total < 0:
            print("Error: Total must be non-negative.")
            return
    except ValueError:
        print("Error: Invalid price format.")
        return
    
    # Get status (optional, defaults to "in progress")
    status = input("Enter status (press Enter for 'in progress'): ").strip()
    if not status:
        status = "in progress"
    
    # Create work order dictionary with all required fields
    work_order = {
        "id": work_order_id,
        "customer": customer,
        "item": item,
        "status": status,
        "total": total,
        "notification_sent": False  # Track if notification already sent
    }
    
    work_orders.append(work_order)
    save_work_orders()
    print(f"✓ Work order #{work_order_id} created successfully!")


def list_work_orders():
    """Display all work orders in the system."""
    print("\n--- Work Orders ---")
    
    if not work_orders:
        print("No work orders found.")
        return
    
    # Display each work order on one line with all fields
    for wo in work_orders:
        print(f"ID: {wo['id']} | Customer: {wo['customer']} | Item: {wo['item']} | Status: {wo['status']} | Total: ${wo['total']:.2f}")


def finish_work_order():
    """Mark a work order as finished and trigger SMS notification."""
    print("\n--- Mark Work Order as Finished ---")
    
    if not work_orders:
        print("No work orders available.")
        return
    
    # Get work order ID from user
    try:
        work_order_id = int(input("Enter work order ID: "))
    except ValueError:
        print("Error: Invalid ID format.")
        return
    
    # Find the work order by ID
    work_order = None
    for wo in work_orders:
        if wo["id"] == work_order_id:
            work_order = wo
            break
    
    if work_order is None:
        print(f"Error: Work order #{work_order_id} not found.")
        return
    
    # Check if notification was already sent (prevent double notifications)
    if work_order["notification_sent"]:
        print(f"Work order #{work_order_id} is already finished. Notification already sent.")
        return
    
    # Update status to finished
    work_order["status"] = "finished"
    work_order["notification_sent"] = True
    
    # Simulate SMS notification to customer
    customer = work_order["customer"]
    item = work_order["item"]
    save_work_orders()
    print(f"\nNotification triggered: Text sent to {customer} for Work Order #{work_order_id} (Item: {item}).")
    print(f"✓ Work order #{work_order_id} marked as finished!")


def main():
    """Main menu loop for the CLI application."""
    load_work_orders()
    print("=" * 60)
    print("SPOKELY - Work Order Tracking System")
    print("Week 4 CLI Prototype")
    print("=" * 60)
    
    while True:
        # Display menu
        print("\n--- Main Menu ---")
        print("1. Add work order")
        print("2. List work orders")
        print("3. Mark work order as finished")
        print("4. Exit")
        
        # Get user choice with input validation
        choice = input("\nEnter your choice (1-4): ").strip()
        
        # Process menu choice
        if choice == "1":
            add_work_order()
        elif choice == "2":
            list_work_orders()
        elif choice == "3":
            finish_work_order()
        elif choice == "4":
            print("\nThank you for using Spokely. Goodbye!")
            break
        else:
            print("Error: Invalid choice. Please enter 1, 2, 3, or 4.")


if __name__ == "__main__":
    main()
