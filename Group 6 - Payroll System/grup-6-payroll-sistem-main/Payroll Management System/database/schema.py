from __future__ import annotations

SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'employee',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS departments (
        department_id INTEGER PRIMARY KEY AUTOINCREMENT,
        department_name TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS employees (
        employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        middle_name TEXT,
        gender TEXT,
        birth_date TEXT,
        department_id INTEGER,
        position TEXT,
        salary_type TEXT,
        daily_rate REAL,
        monthly_salary REAL,
        hourly_rate REAL,
        scheduled_start_time TEXT NOT NULL DEFAULT '09:00',
        hire_date TEXT,
        contact_number TEXT,
        email TEXT,
        address TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        FOREIGN KEY (department_id) REFERENCES departments(department_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance (
        attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        time_in TEXT,
        time_out TEXT,
        hours_worked REAL DEFAULT 0,
        overtime_hours REAL DEFAULT 0,
        late_minutes INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deductions (
        deduction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        sss REAL DEFAULT 0,
        philhealth REAL DEFAULT 0,
        pagibig REAL DEFAULT 0,
        tax REAL DEFAULT 0,
        other REAL DEFAULT 0,
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS leave_records (
        leave_id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        leave_type TEXT NOT NULL CHECK (leave_type IN ('Paid leave', 'Maternity leave', 'Travel order')),
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending', 'Approved', 'Rejected')),
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payroll (
        payroll_id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        gross_pay REAL NOT NULL,
        deductions REAL NOT NULL DEFAULT 0,
        sss_deduction REAL NOT NULL DEFAULT 0,
        philhealth_deduction REAL NOT NULL DEFAULT 0,
        pagibig_deduction REAL NOT NULL DEFAULT 0,
        tax_withheld REAL NOT NULL DEFAULT 0,
        other_deductions REAL NOT NULL DEFAULT 0,
        paid_leave_hours REAL NOT NULL DEFAULT 0,
        tardiness_minutes INTEGER NOT NULL DEFAULT 0,
        tardiness_deduction REAL NOT NULL DEFAULT 0,
        net_pay REAL NOT NULL,
        generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL
    )
    """,
]
