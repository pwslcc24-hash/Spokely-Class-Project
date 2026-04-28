"""
SQLAlchemy models for Spokely — Users and WorkOrders in SQLite (project.db).
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    """Staff account: email + hashed password. Work orders belong to this user."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)

    work_orders = db.relationship(
        "WorkOrder",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User {self.email!r}>"


class WorkOrder(db.Model):
    """Repair/work order owned by a User."""

    __tablename__ = "work_orders"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Legacy NOT NULL column in existing SQLite DBs (predates user_id); keep in sync with User.email.
    owner_email = db.Column(db.String(255), nullable=False)
    customer = db.Column(db.String(255), nullable=False)
    item = db.Column(db.String(512), nullable=False)
    status = db.Column(db.String(64), nullable=False, default="in progress")
    total = db.Column(db.Float, nullable=False, default=0.0)
    notification_sent = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        """Dict for templates and snapshot / workflow."""
        return {
            "id": self.id,
            "owner_email": self.owner_email,
            "customer": self.customer,
            "item": self.item,
            "status": self.status,
            "total": self.total,
            "notification_sent": self.notification_sent,
        }
