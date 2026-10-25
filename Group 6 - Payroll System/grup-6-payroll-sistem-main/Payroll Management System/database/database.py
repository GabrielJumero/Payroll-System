from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path
from typing import Optional

from config import DATABASE_PATH, ensure_directories
from database.schema import SCHEMA_STATEMENTS


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            iteration_count = int(iterations)
            if not 100_000 <= iteration_count <= 2_000_000:
                return False
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iteration_count
            )
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, stored_hash)


class DatabaseManager:
    """Manage SQLite connectivity and initial application setup."""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DATABASE_PATH

    def connect(self) -> sqlite3.Connection:
        """Create a SQLite connection with row factory support."""
        ensure_directories()
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Create tables and seed default records if absent."""
        connection = self.connect()
        try:
            with connection:
                for statement in SCHEMA_STATEMENTS:
                    connection.execute(statement)
                employee_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(employees)").fetchall()
                }
                if "hourly_rate" not in employee_columns:
                    connection.execute("ALTER TABLE employees ADD COLUMN hourly_rate REAL")
                if "scheduled_start_time" not in employee_columns:
                    connection.execute(
                        "ALTER TABLE employees ADD COLUMN scheduled_start_time TEXT NOT NULL DEFAULT '09:00'"
                    )
                attendance_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(attendance)").fetchall()
                }
                if "late_minutes" not in attendance_columns:
                    connection.execute(
                        "ALTER TABLE attendance ADD COLUMN late_minutes INTEGER NOT NULL DEFAULT 0"
                    )
                    connection.execute(
                        "UPDATE attendance SET late_minutes = MAX(0, "
                        "(CAST(substr(time_in, 1, instr(time_in, ':') - 1) AS INTEGER) * 60 + "
                        "CAST(substr(time_in, instr(time_in, ':') + 1, 2) AS INTEGER)) - "
                        "(CAST(substr(e.scheduled_start_time, 1, 2) AS INTEGER) * 60 + "
                        "CAST(substr(e.scheduled_start_time, 4, 2) AS INTEGER))) "
                        "FROM employees e WHERE attendance.employee_id = e.employee_id "
                        "AND time_in IS NOT NULL AND length(time_in) >= 4 AND instr(time_in, ':') > 0"
                    )
                payroll_columns = {
                    str(row["name"])
                    for row in connection.execute("PRAGMA table_info(payroll)").fetchall()
                }
                has_legacy_payroll_deductions = not any(
                    column in payroll_columns
                    for column in (
                        "sss_deduction",
                        "philhealth_deduction",
                        "pagibig_deduction",
                        "tax_withheld",
                        "other_deductions",
                        "paid_leave_hours",
                    )
                )
                for column in (
                    "sss_deduction",
                    "philhealth_deduction",
                    "pagibig_deduction",
                    "tax_withheld",
                    "other_deductions",
                    "paid_leave_hours",
                ):
                    if column not in payroll_columns:
                        connection.execute(
                            f"ALTER TABLE payroll ADD COLUMN {column} REAL NOT NULL DEFAULT 0"
                        )
                        if column == "other_deductions" and has_legacy_payroll_deductions:
                            connection.execute(
                                "UPDATE payroll SET other_deductions = deductions"
                            )
                if "tardiness_deduction" not in payroll_columns:
                    connection.execute(
                        "ALTER TABLE payroll ADD COLUMN tardiness_deduction REAL NOT NULL DEFAULT 0"
                    )
                if "tardiness_minutes" not in payroll_columns:
                    connection.execute(
                        "ALTER TABLE payroll ADD COLUMN tardiness_minutes INTEGER NOT NULL DEFAULT 0"
                    )
                connection.execute(
                    "UPDATE employees SET "
                    "hourly_rate = CASE "
                    "WHEN LOWER(salary_type) = 'monthly' THEN monthly_salary / 176.0 "
                    "WHEN LOWER(salary_type) = 'daily' THEN daily_rate / 8.0 "
                    "ELSE hourly_rate END, "
                    "salary_type = 'hourly' "
                    "WHERE LOWER(salary_type) IN ('monthly', 'daily')"
                )
                self._seed_default_data(connection)
        finally:
            connection.close()

    def _seed_default_data(self, connection: sqlite3.Connection) -> None:
        """Create an admin user and basic departments when the database is empty."""
        user_exists = connection.execute(
            "SELECT 1 FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()
        if user_exists is None:
            password_hash = hash_password("admin123")
            connection.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", password_hash, "admin"),
            )

        department_exists = connection.execute(
            "SELECT 1 FROM departments WHERE department_name = ?",
            ("Administration",),
        ).fetchone()
        if department_exists is None:
            connection.execute(
                "INSERT INTO departments (department_name) VALUES (?)",
                ("Administration",),
            )

    def get_connection(self) -> sqlite3.Connection:
        """Return a connected SQLite session for use by controllers."""
        return self.connect()
