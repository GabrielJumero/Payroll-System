from __future__ import annotations

import calendar
import csv
import sqlite3
from collections.abc import Collection
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from typing import Any, Callable

from config import (
    ACCENT_BLUE,
    APP_NAME,
    APP_VERSION,
    BACKGROUND_COLOR,
    DEFAULT_FONT,
    DANGER_COLOR,
    GOLD_COLOR,
    HEADING_FONT,
    LARGE_NUM_FONT,
    MUTED_COLOR,
    PRIMARY_COLOR,
    SECONDARY_COLOR,
    SUCCESS_COLOR,
    TEXT_COLOR,
    TITLE_FONT,
    WHITE,
    ensure_directories,
)
from database.database import DatabaseManager, hash_password, verify_password


def calculate_hourly_gross(hourly_rate: float, regular_hours: float, overtime_hours: float) -> float:
    if (
        not all(isfinite(value) for value in (hourly_rate, regular_hours, overtime_hours))
        or hourly_rate <= 0
        or regular_hours < 0
        or overtime_hours < 0
    ):
        raise ValueError("Hourly pay inputs must be finite and non-negative, with a positive rate.")
    gross = hourly_rate * (regular_hours + overtime_hours * 1.5)
    if not isfinite(gross):
        raise ValueError("Calculated gross pay is not finite.")
    return gross


def calculate_philippine_deductions(
    monthly_basic_pay: float, gross_pay: float
) -> tuple[float, float, float, float]:
    if (
        not all(isfinite(value) for value in (monthly_basic_pay, gross_pay))
        or monthly_basic_pay < 0
        or gross_pay < 0
    ):
        raise ValueError("Monthly basic pay and gross pay must be finite and non-negative.")
    if gross_pay == 0:
        return 0.0, 0.0, 0.0, 0.0

    salary_credit = min(35_000, max(5_000, int((monthly_basic_pay + 250) // 500) * 500))
    sss = round(salary_credit * 0.05, 2)

    philhealth_base = min(100_000, max(10_000, monthly_basic_pay))
    philhealth = round(philhealth_base * 0.025, 2)

    pagibig_base = min(10_000, monthly_basic_pay)
    pagibig_rate = 0.01 if monthly_basic_pay <= 1_500 else 0.02
    pagibig = round(pagibig_base * pagibig_rate, 2)

    taxable_compensation = max(0.0, gross_pay - sss - philhealth - pagibig)
    if taxable_compensation <= 20_833:
        tax = 0.0
    elif taxable_compensation <= 33_333:
        tax = (taxable_compensation - 20_833) * 0.15
    elif taxable_compensation <= 66_667:
        tax = 1_875 + (taxable_compensation - 33_333) * 0.20
    elif taxable_compensation <= 166_667:
        tax = 8_541.67 + (taxable_compensation - 66_667) * 0.25
    elif taxable_compensation <= 666_667:
        tax = 33_541.67 + (taxable_compensation - 166_667) * 0.30
    else:
        tax = 183_541.67 + (taxable_compensation - 666_667) * 0.35

    return sss, philhealth, pagibig, round(max(0.0, tax), 2)


def calculate_late_minutes(scheduled_start: str, time_in: str | None) -> int:
    if not time_in:
        return 0
    scheduled = datetime.strptime(scheduled_start, "%H:%M").time()
    actual = datetime.strptime(time_in, "%H:%M").time()
    scheduled_minutes = scheduled.hour * 60 + scheduled.minute
    actual_minutes = actual.hour * 60 + actual.minute
    return max(0, actual_minutes - scheduled_minutes)


def is_full_calendar_month(period_start: date, period_end: date) -> bool:
    return (
        period_start.day == 1
        and period_start.year == period_end.year
        and period_start.month == period_end.month
        and period_end.day == calendar.monthrange(period_start.year, period_start.month)[1]
    )


def calculate_paid_leave_hours(
    leave_records: list[tuple[str, str]],
    attendance_dates: set[str],
    period_start: date,
    period_end: date,
) -> float:
    paid_dates: set[date] = set()
    for start_value, end_value in leave_records:
        current = max(date.fromisoformat(start_value), period_start)
        end = min(date.fromisoformat(end_value), period_end)
        while current <= end:
            if current.weekday() < 5 and current.isoformat() not in attendance_dates:
                paid_dates.add(current)
            current += timedelta(days=1)
    return float(len(paid_dates) * 8)


class DatePicker(ttk.Frame):
    """A date field that opens a month calendar instead of accepting typed input."""

    def __init__(
        self,
        master: tk.Misc,
        value: str = "",
        *,
        allow_empty: bool = False,
        on_change: Callable[[], None] | None = None,
        width: int = 18,
    ) -> None:
        super().__init__(master)
        self.allow_empty = allow_empty
        self.on_change = on_change
        self._value = ""
        self._popup: tk.Toplevel | None = None
        self._calendar_year = date.today().year
        self._calendar_month = date.today().month
        self.button = ttk.Button(self, width=width, style="Secondary.TButton", command=self._open_calendar)
        self.button.pack(fill="x")
        self.set(value)

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        value = value.strip()
        if value:
            parsed = date.fromisoformat(value)
            self._value = parsed.isoformat()
            display = parsed.strftime("%B %d, %Y")
        else:
            self._value = ""
            display = "Select date"
        self.button.configure(text=display)

    def _open_calendar(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.lift()
            return

        selected = date.fromisoformat(self._value) if self._value else date.today()
        self._calendar_year, self._calendar_month = selected.year, selected.month
        popup = tk.Toplevel(self.winfo_toplevel())
        self._popup = popup
        popup.title("Select date")
        popup.transient(self.winfo_toplevel())
        popup.resizable(False, False)
        body = ttk.Frame(popup, padding=10)
        body.pack()

        header = ttk.Frame(body)
        header.pack(fill="x", pady=(0, 6))
        ttk.Button(header, text="‹", width=3, command=lambda: self._change_month(-1)).pack(side="left")
        self._month_label = ttk.Label(header, anchor="center", width=18)
        self._month_label.pack(side="left", expand=True)
        ttk.Button(header, text="›", width=3, command=lambda: self._change_month(1)).pack(side="right")
        self._days_frame = ttk.Frame(body)
        self._days_frame.pack()
        if self.allow_empty:
            ttk.Button(body, text="Clear date", command=lambda: self._select_date("")).pack(anchor="e", pady=(6, 0))

        self._render_calendar()
        popup.update_idletasks()
        popup.geometry(f"+{self.winfo_rootx()}+{self.winfo_rooty() + self.winfo_height()}")
        popup.protocol("WM_DELETE_WINDOW", self._close_calendar)

    def _change_month(self, offset: int) -> None:
        month_index = (self._calendar_year - 1) * 12 + self._calendar_month - 1 + offset
        if not 0 <= month_index < 9999 * 12:
            return
        year_index, month = divmod(month_index, 12)
        self._calendar_year = year_index + 1
        self._calendar_month = month + 1
        self._render_calendar()

    def _render_calendar(self) -> None:
        self._month_label.configure(
            text=f"{calendar.month_name[self._calendar_month]} {self._calendar_year}"
        )
        for child in self._days_frame.winfo_children():
            child.destroy()
        for column, weekday in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            ttk.Label(self._days_frame, text=weekday, anchor="center", width=4).grid(
                row=0, column=column, padx=1, pady=1
            )
        for row_index, week in enumerate(
            calendar.monthcalendar(self._calendar_year, self._calendar_month), start=1
        ):
            for column, day_number in enumerate(week):
                if day_number:
                    ttk.Button(
                        self._days_frame,
                        text=str(day_number),
                        width=3,
                        command=lambda day=day_number: self._select_date(
                            date(self._calendar_year, self._calendar_month, day).isoformat()
                        ),
                    ).grid(row=row_index, column=column, padx=1, pady=1)

    def _select_date(self, value: str) -> None:
        self.set(value)
        self._close_calendar()
        if self.on_change is not None:
            self.on_change()

    def _close_calendar(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.destroy()
        self._popup = None


class RoundedCard(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        padding: int = 18,
        fill: str = WHITE,
        content_style: str = "CardContent.TFrame",
    ) -> None:
        super().__init__(master, background=BACKGROUND_COLOR, borderwidth=0, highlightthickness=0)
        self._fill = fill
        self._canvas = tk.Canvas(
            self,
            background=BACKGROUND_COLOR,
            borderwidth=0,
            highlightthickness=0,
            takefocus=False,
        )
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.content = ttk.Frame(self, style=content_style, padding=padding)
        self.content.pack(fill="both", expand=True, padx=6, pady=6)
        self.bind("<Configure>", self._draw_background)

    def _draw_background(self, _event: tk.Event[tk.Misc]) -> None:
        width, height = self.winfo_width(), self.winfo_height()
        self._canvas.delete("card")
        if width < 2 or height < 2:
            return
        radius = min(16, width // 2, height // 2)
        points = (
            radius, 0, width - radius, 0, width, 0, width, radius,
            width, height - radius, width, height, width - radius, height,
            radius, height, 0, height, 0, height - radius, 0, radius, 0, 0,
        )
        self._canvas.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            fill=self._fill,
            outline="#E4EAF1",
            width=1,
            tags="card",
        )


class PayrollApp(tk.Tk):
    """Main application window for the payroll system."""

    ROLE_PAGES = {
        "admin": frozenset(("Dashboard", "Employees", "Attendance", "Leaves", "Payroll", "Reports", "Settings")),
        "hr": frozenset(("Dashboard", "Employees", "Attendance", "Leaves")),
        "viewer": frozenset(("Dashboard", "Reports")),
    }
    ROLE_LABELS = {"admin": "Admin", "hr": "HR", "viewer": "Viewer"}
    EDIT_ROLES = frozenset(("admin", "hr"))

    NAV_ITEMS = (
        ("Dashboard", "Overview"),
        ("Employees", "People directory"),
        ("Attendance", "Daily time records"),
        ("Leaves", "Leave and travel records"),
        ("Payroll", "Payroll processing"),
        ("Reports", "Payroll & workforce reports"),
        ("Settings", "Organization preferences"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1360x860")
        self.minsize(1080, 720)
        self.state("zoomed")
        self.configure(bg=BACKGROUND_COLOR)

        self.db_manager = DatabaseManager()
        self.current_page = "Dashboard"
        self.current_user: dict[str, str] | None = None
        self.settings: dict[str, str] = {
            "organization_name": "Biringan National University",
            "organization_tagline": "Human Resource & Payroll Control Center",
            "currency_symbol": "₱",
        }
        self._configure_styles()
        self._build_shell()

        try:
            self.db_manager.initialize()
            self._load_settings()
            self.status_var.set("Ready  •  Database connected")
            self._show_login()
        except (sqlite3.Error, OSError) as exc:
            self.status_var.set(f"Database initialization failed: {exc}")
            messagebox.showerror("Initialization Error", str(exc), parent=self)

    def _configure_styles(self) -> None:
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background=BACKGROUND_COLOR)
        self.style.configure(
            "Card.TFrame",
            background=WHITE,
            relief="solid",
            borderwidth=1,
            bordercolor="#E4EAF1",
        )
        self.style.configure("CardContent.TFrame", background=WHITE)
        self.style.configure("Header.TFrame", background=WHITE)
        self.style.configure("HeroContent.TFrame", background="#EAF3FB")
        self.style.configure("MetricBlue.TFrame", background="#F1F7FD", relief="solid", borderwidth=1, bordercolor="#DFEAF5")
        self.style.configure("MetricGreen.TFrame", background="#ECF8F2", relief="solid", borderwidth=1, bordercolor="#D8EEE2")
        self.style.configure("MetricBlueContent.TFrame", background="#F1F7FD")
        self.style.configure("MetricGreenContent.TFrame", background="#ECF8F2")
        self.style.configure("Sidebar.TFrame", background=PRIMARY_COLOR)
        self.style.configure("TLabel", font=DEFAULT_FONT, background=BACKGROUND_COLOR, foreground=TEXT_COLOR)
        self.style.configure("Title.TLabel", font=TITLE_FONT, background=BACKGROUND_COLOR, foreground=PRIMARY_COLOR)
        self.style.configure("HeaderTitle.TLabel", font=("Segoe UI", 24, "bold"), background=WHITE, foreground=PRIMARY_COLOR)
        self.style.configure("Section.TLabel", font=HEADING_FONT, background=BACKGROUND_COLOR, foreground=TEXT_COLOR)
        self.style.configure("CardTitle.TLabel", font=("Segoe UI", 10, "bold"), background=WHITE, foreground=MUTED_COLOR)
        self.style.configure("Muted.TLabel", font=("Segoe UI", 10), background=BACKGROUND_COLOR, foreground=MUTED_COLOR)
        self.style.configure("CardMuted.TLabel", font=("Segoe UI", 9), background=WHITE, foreground=MUTED_COLOR)
        self.style.configure("MetricBlueTitle.TLabel", font=("Segoe UI", 9, "bold"), background="#F1F7FD", foreground=MUTED_COLOR)
        self.style.configure("MetricGreenTitle.TLabel", font=("Segoe UI", 9, "bold"), background="#ECF8F2", foreground=MUTED_COLOR)
        self.style.configure("MetricBlueValue.TLabel", font=LARGE_NUM_FONT, background="#F1F7FD", foreground=ACCENT_BLUE)
        self.style.configure("MetricGreenValue.TLabel", font=LARGE_NUM_FONT, background="#ECF8F2", foreground=SUCCESS_COLOR)
        self.style.configure("MetricBlueDetail.TLabel", font=("Segoe UI", 9), background="#F1F7FD", foreground=MUTED_COLOR)
        self.style.configure("MetricGreenDetail.TLabel", font=("Segoe UI", 9), background="#ECF8F2", foreground=MUTED_COLOR)
        self.style.configure("SidebarTitle.TLabel", font=("Segoe UI", 14, "bold"), background=PRIMARY_COLOR, foreground=WHITE)
        self.style.configure("SidebarSub.TLabel", font=("Segoe UI", 9), background=PRIMARY_COLOR, foreground="#C8D7EE")
        self.style.configure("HeroTitle.TLabel", font=("Segoe UI", 16, "bold"), background="#EAF3FB", foreground=PRIMARY_COLOR)
        self.style.configure("HeroSub.TLabel", font=("Segoe UI", 10), background="#EAF3FB", foreground=MUTED_COLOR)
        self.style.configure("TButton", font=DEFAULT_FONT, padding=(12, 8), borderwidth=0)
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(13, 9), background=ACCENT_BLUE, foreground=WHITE)
        self.style.map("Primary.TButton", background=[("active", PRIMARY_COLOR), ("disabled", "#9EB4CC")])
        self.style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(11, 8), background="#E8F0FA", foreground=PRIMARY_COLOR)
        self.style.map("Secondary.TButton", background=[("active", "#D6E5F6")])
        self.style.configure("Danger.TButton", font=("Segoe UI", 10, "bold"), padding=(11, 8), background=DANGER_COLOR, foreground=WHITE)
        self.style.map("Danger.TButton", background=[("active", "#A93226")])
        self.style.configure("Nav.TButton", font=("Segoe UI", 10), padding=(14, 11), anchor="w", background=PRIMARY_COLOR, foreground="#D9E5F5", focuscolor=PRIMARY_COLOR)
        self.style.map("Nav.TButton", background=[("active", "#1A3A6B")], foreground=[("active", WHITE)])
        self.style.configure("NavActive.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 11), anchor="w", background="#1D6C5A", foreground=WHITE, focuscolor="#1D6C5A")
        self.style.configure(
            "Treeview",
            background=WHITE,
            fieldbackground=WHITE,
            foreground=TEXT_COLOR,
            rowheight=34,
            font=("Segoe UI", 10),
            borderwidth=0,
            relief="flat",
        )
        self.style.configure(
            "Treeview.Heading",
            background="#EDF3F9",
            foreground=PRIMARY_COLOR,
            font=("Segoe UI", 9, "bold"),
            padding=(8, 9),
            relief="flat",
        )
        self.style.map("Treeview", background=[("selected", "#D6EAF8")], foreground=[("selected", PRIMARY_COLOR)])
        self.style.configure("TEntry", padding=(9, 8), fieldbackground=WHITE, bordercolor="#C8D6E5")
        self.style.configure("TCombobox", padding=(8, 6), fieldbackground=WHITE, bordercolor="#C8D6E5")

    def _build_shell(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self.sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=(18, 22))
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="ns")
        self.sidebar.configure(width=246)
        self.sidebar.grid_propagate(False)

        self.brand_label = ttk.Label(
            self.sidebar,
            text="BNU PAYROLL",
            style="SidebarTitle.TLabel",
            wraplength=205,
        )
        self.brand_label.pack(anchor="w", pady=(2, 3))
        self.brand_subtitle = ttk.Label(
            self.sidebar,
            text=self.settings["organization_tagline"],
            style="SidebarSub.TLabel",
            wraplength=205,
        )
        self.brand_subtitle.pack(anchor="w", pady=(0, 28))
        ttk.Label(
            self.sidebar,
            text="WORKSPACE",
            style="SidebarSub.TLabel",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor="w", pady=(0, 9))

        self.navigation = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        self.navigation.pack(fill="x")
        self.navigation.columnconfigure(0, weight=1)
        self.nav_buttons: dict[str, ttk.Button] = {}
        self.employee_nav_expanded = True
        employee_pages = {"Employees", "Attendance", "Leaves"}
        nav_row = 0
        for title, _ in self.NAV_ITEMS:
            if title in employee_pages:
                if title == "Employees":
                    self.employee_nav_group = ttk.Frame(
                        self.navigation, style="Sidebar.TFrame"
                    )
                    self.employee_nav_group.grid(
                        row=nav_row, column=0, sticky="ew", pady=3
                    )
                    self.employee_nav_button = ttk.Button(
                        self.employee_nav_group,
                        text="   Manage employees   v",
                        style="Nav.TButton",
                        command=self._toggle_employee_navigation,
                    )
                    self.employee_nav_button.pack(fill="x")
                    self.employee_navigation = ttk.Frame(
                        self.employee_nav_group, style="Sidebar.TFrame"
                    )
                    self.employee_navigation.pack(fill="x", padx=(12, 0))
                    for employee_page in ("Employees", "Attendance", "Leaves"):
                        employee_button = ttk.Button(
                            self.employee_navigation,
                            text=f"   {employee_page}",
                            style="Nav.TButton",
                            command=lambda page=employee_page: self._show_page(page),
                        )
                        employee_button.pack(fill="x", pady=2)
                        self.nav_buttons[employee_page] = employee_button
                    nav_row += 1
                continue
            button = ttk.Button(
                self.navigation,
                text=f"   {title}",
                style="Nav.TButton",
                command=lambda page=title: self._show_page(page),
            )
            button.grid(row=nav_row, column=0, sticky="ew", pady=3)
            self.nav_buttons[title] = button
            nav_row += 1

        self.sidebar_footer = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        self.sidebar_footer.pack(side="bottom", fill="x")
        ttk.Separator(self.sidebar_footer).grid(row=0, column=0, sticky="ew", pady=(0, 13))
        ttk.Label(
            self.sidebar_footer, text=f"Version {APP_VERSION}", style="SidebarSub.TLabel"
        ).grid(row=1, column=0, sticky="w")
        ttk.Label(
            self.sidebar_footer, text="Secure local workspace", style="SidebarSub.TLabel"
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.account_button = ttk.Button(
            self.sidebar_footer,
            text="Accounts  •  Sign in",
            style="Nav.TButton",
            command=self._open_account_menu,
        )
        self.account_button.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.sidebar_footer.columnconfigure(0, weight=1)
        ttk.Frame(self.sidebar, style="Sidebar.TFrame").pack(fill="both", expand=True)

        self.header = ttk.Frame(self, style="Header.TFrame", padding=(32, 20, 32, 18))
        self.header.grid(row=0, column=1, sticky="ew")
        self.header.columnconfigure(0, weight=1)
        self.page_title_var = tk.StringVar(value="Dashboard")
        self.page_subtitle_var = tk.StringVar(value="Your payroll operations at a glance.")
        ttk.Label(self.header, textvariable=self.page_title_var, style="HeaderTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.header,
            textvariable=self.page_subtitle_var,
            font=("Segoe UI", 10),
            foreground=MUTED_COLOR,
            background=WHITE,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.header_user_var = tk.StringVar(
            value=f"{date.today().strftime('%A, %B %d, %Y')}   •   SIGN IN"
        )
        ttk.Label(
            self.header,
            textvariable=self.header_user_var,
            font=("Segoe UI", 9, "bold"),
            foreground="#126B4E",
            background="#EAF6F0",
            padding=(12, 8),
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))

        self.page_host = ttk.Frame(self, padding=(28, 0, 28, 20))
        self.page_host.grid(row=1, column=1, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Initializing database...")
        ttk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            padding=(18, 9),
            background=SECONDARY_COLOR,
            foreground=MUTED_COLOR,
            font=("Segoe UI", 9),
        ).grid(row=2, column=1, sticky="ew")

    def _show_login(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Sign in")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", self.destroy)

        body = ttk.Frame(dialog, padding=28)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Welcome back", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Sign in to access the payroll workspace.", style="Muted.TLabel").pack(
            anchor="w", pady=(4, 18)
        )

        username_var = tk.StringVar(value="admin")
        password_var = tk.StringVar()
        ttk.Label(body, text="Username", style="Muted.TLabel").pack(anchor="w")
        username_entry = ttk.Entry(body, textvariable=username_var, width=34)
        username_entry.pack(fill="x", pady=(4, 12))
        ttk.Label(body, text="Password", style="Muted.TLabel").pack(anchor="w")
        password_entry = ttk.Entry(body, textvariable=password_var, show="•", width=34)
        password_entry.pack(fill="x", pady=(4, 10))
        ttk.Label(
            body,
            text="First run: admin / admin123. Change this password after signing in.",
            style="Muted.TLabel",
            wraplength=300,
        ).pack(anchor="w", pady=(0, 14))

        def sign_in() -> None:
            username = username_var.get().strip()
            try:
                user = self._fetchone(
                    "SELECT id, username, password_hash, role FROM users WHERE username = ?",
                    (username,),
                ) if username else None
                if user is None or not verify_password(password_var.get(), str(user["password_hash"])):
                    messagebox.showerror("Sign-in failed", "The username or password is incorrect.", parent=dialog)
                    password_var.set("")
                    password_entry.focus_set()
                    return
                stored_hash = str(user["password_hash"])
                if not stored_hash.startswith("pbkdf2_sha256$"):
                    self._execute(
                        "UPDATE users SET password_hash = ? WHERE id = ?",
                        (hash_password(password_var.get()), user["id"]),
                    )
            except sqlite3.Error as exc:
                messagebox.showerror("Sign-in failed", f"Could not verify the account:\n{exc}", parent=dialog)
                return

            self.current_user = {
                "id": str(user["id"]),
                "username": str(user["username"]),
                "role": str(user["role"]),
            }
            if self.current_user["role"] not in self.ROLE_PAGES:
                self.current_user = None
                messagebox.showerror(
                    "Sign-in failed",
                    "This account has an unsupported role. Ask an administrator to update it.",
                    parent=dialog,
                )
                return
            self.account_button.configure(
                text=f"Accounts  •  {self.current_user['username']}"
            )
            self.header_user_var.set(
                f"{date.today().strftime('%A, %B %d, %Y')}   •   {self.current_user['role'].upper()}"
            )
            dialog.grab_release()
            dialog.destroy()
            self.deiconify()
            self._update_role_navigation()
            self._show_page("Dashboard")

        ttk.Button(body, text="Sign in", style="Primary.TButton", command=sign_in).pack(
            fill="x"
        )
        dialog.bind("<Return>", lambda _event: sign_in())
        dialog.update_idletasks()
        dialog.geometry(
            f"+{self.winfo_rootx() + 400}+{self.winfo_rooty() + 220}"
        )
        username_entry.focus_set()

    def _open_account_menu(self) -> None:
        if self.current_user is None:
            return
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Account details", command=self._show_account_details)
        menu.add_command(label="Change password", command=self._change_password)
        if self.current_user["role"] == "admin":
            menu.add_command(label="Create user account", command=self._create_user_account)
        menu.add_separator()
        menu.add_command(label="Log out", command=self._logout)
        try:
            menu.update_idletasks()
            menu_y = self.account_button.winfo_rooty() - menu.winfo_reqheight()
            menu.tk_popup(
                self.account_button.winfo_rootx(),
                max(0, menu_y),
            )
        finally:
            menu.grab_release()

    def _show_account_details(self) -> None:
        if self.current_user is None:
            return
        messagebox.showinfo(
            "Account details",
            f"Username: {self.current_user['username']}\nRole: {self.current_user['role'].title()}",
            parent=self,
        )

    def _create_user_account(self) -> None:
        if not self._require_roles(("admin",), "create user accounts"):
            return
        dialog = tk.Toplevel(self)
        dialog.title("Create user account")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Create user account", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            body,
            text="New accounts start with Viewer access.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

        username_var = tk.StringVar()
        password_var = tk.StringVar()
        confirm_var = tk.StringVar()
        role_var = tk.StringVar(value="Viewer")
        fields = (
            ("Username", ttk.Entry(body, textvariable=username_var, width=32)),
            ("Password", ttk.Entry(body, textvariable=password_var, show="•", width=32)),
            ("Confirm password", ttk.Entry(body, textvariable=confirm_var, show="•", width=32)),
            (
                "Role",
                ttk.Combobox(
                    body,
                    textvariable=role_var,
                    values=("Viewer", "HR", "Admin"),
                    state="readonly",
                    width=29,
                ),
            ),
        )
        for row, (label, widget) in enumerate(fields, start=2):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            widget.grid(row=row, column=1, sticky="ew", pady=6)
        body.columnconfigure(1, weight=1)

        def save() -> None:
            username = username_var.get().strip()
            password = password_var.get()
            role = role_var.get().lower()
            if not username:
                messagebox.showerror("Username required", "Enter a username.", parent=dialog)
                return
            if len(password) < 8:
                messagebox.showerror(
                    "Password too short",
                    "Use at least 8 characters for the password.",
                    parent=dialog,
                )
                return
            if password != confirm_var.get():
                messagebox.showerror(
                    "Passwords do not match",
                    "Enter the same password in both fields.",
                    parent=dialog,
                )
                return
            if role not in self.ROLE_PAGES:
                messagebox.showerror("Invalid role", "Select a valid account role.", parent=dialog)
                return
            try:
                self._execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, hash_password(password), role),
                )
            except sqlite3.IntegrityError:
                messagebox.showerror(
                    "Username already exists",
                    "Choose a different username.",
                    parent=dialog,
                )
                return
            except sqlite3.Error as exc:
                messagebox.showerror(
                    "Could not create account", str(exc), parent=dialog
                )
                return
            dialog.destroy()
            self.status_var.set(f"Created {self.ROLE_LABELS[role]} account: {username}")
            messagebox.showinfo(
                "Account created",
                f"{self.ROLE_LABELS[role]} account '{username}' is ready to sign in.",
                parent=self,
            )

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(
            buttons, text="Cancel", style="Secondary.TButton", command=dialog.destroy
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            buttons, text="Create account", style="Primary.TButton", command=save
        ).pack(side="right")
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 340}+{self.winfo_rooty() + 210}")

    def _change_password(self) -> None:
        if self.current_user is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Change password")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Change password", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        current_var = tk.StringVar()
        new_var = tk.StringVar()
        confirm_var = tk.StringVar()
        password_fields = (
            ("Current password", current_var),
            ("New password", new_var),
            ("Confirm password", confirm_var),
        )
        for row, (label, variable) in enumerate(password_fields, start=1):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=6
            )
            ttk.Entry(body, textvariable=variable, show="•", width=30).grid(
                row=row, column=1, sticky="ew", pady=6
            )
        body.columnconfigure(1, weight=1)

        def save_password() -> None:
            if len(new_var.get()) < 8:
                messagebox.showerror(
                    "Password too short",
                    "Use at least 8 characters for the new password.",
                    parent=dialog,
                )
                return
            if new_var.get() != confirm_var.get():
                messagebox.showerror(
                    "Passwords do not match",
                    "Enter the same new password in both fields.",
                    parent=dialog,
                )
                return
            try:
                user = self._fetchone(
                    "SELECT password_hash FROM users WHERE id = ?",
                    (self.current_user["id"],),
                )
                if user is None or not verify_password(
                    current_var.get(), str(user["password_hash"])
                ):
                    messagebox.showerror(
                        "Current password incorrect",
                        "Check your current password and try again.",
                        parent=dialog,
                    )
                    return
                self._execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(new_var.get()), self.current_user["id"]),
                )
            except sqlite3.Error as exc:
                messagebox.showerror(
                    "Password was not changed", str(exc), parent=dialog
                )
                return
            dialog.destroy()
            messagebox.showinfo(
                "Password changed", "Your password has been updated.", parent=self
            )

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(
            buttons, text="Cancel", style="Secondary.TButton", command=dialog.destroy
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            buttons, text="Save password", style="Primary.TButton", command=save_password
        ).pack(side="right")
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 360}+{self.winfo_rooty() + 230}")

    def _logout(self) -> None:
        if self.current_user is None:
            return
        self.current_user = None
        self.account_button.configure(text="Accounts  •  Sign in")
        self.header_user_var.set(
            f"{date.today().strftime('%A, %B %d, %Y')}   •   SIGN IN"
        )
        self._update_role_navigation()
        for child in self.page_host.winfo_children():
            child.destroy()
        self._show_login()

    def _role_allows(self, page: str) -> bool:
        return bool(
            self.current_user
            and page in self.ROLE_PAGES.get(self.current_user["role"], frozenset())
        )

    def _require_roles(self, roles: Collection[str], action: str) -> bool:
        if self.current_user and self.current_user["role"] in roles:
            return True
        messagebox.showerror(
            "Access denied",
            f"Your account does not have permission to {action}.",
            parent=self,
        )
        return False

    def _update_role_navigation(self) -> None:
        for title, button in self.nav_buttons.items():
            if title in ("Employees", "Attendance", "Leaves"):
                button.pack_forget()
                if self._role_allows(title):
                    button.pack(fill="x", pady=2)
            else:
                button.grid_remove()
                if self._role_allows(title):
                    button.grid()
        employee_pages_allowed = any(
            self._role_allows(page) for page in ("Employees", "Attendance", "Leaves")
        )
        self.employee_nav_group.grid_remove()
        if employee_pages_allowed:
            self.employee_nav_group.grid()

    def _fetchall(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        connection = self.db_manager.get_connection()
        try:
            return list(connection.execute(query, parameters).fetchall())
        finally:
            connection.close()

    def _fetchone(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        connection = self.db_manager.get_connection()
        try:
            return connection.execute(query, parameters).fetchone()
        finally:
            connection.close()

    def _execute(self, query: str, parameters: tuple[Any, ...] = ()) -> int:
        connection = self.db_manager.get_connection()
        try:
            cursor = connection.execute(query, parameters)
            connection.commit()
            return int(cursor.lastrowid or 0)
        finally:
            connection.close()

    def _load_settings(self) -> None:
        rows = self._fetchall("SELECT setting_key, setting_value FROM app_settings")
        self.settings.update({str(row["setting_key"]): str(row["setting_value"]) for row in rows})
        self.brand_label.configure(text=self.settings.get("organization_name", APP_NAME).upper())
        self.brand_subtitle.configure(text=self.settings.get("organization_tagline", "Payroll Control Center"))

    def _show_page(self, page: str) -> None:
        builders = {
            "Dashboard": (self._build_dashboard, "Your payroll operations at a glance."),
            "Employees": (self._build_employees, "Manage employee records, departments, and compensation."),
            "Attendance": (self._build_attendance, "Review time records and keep daily attendance up to date."),
            "Leaves": (self._build_leaves, "Track leave approvals and travel orders."),
            "Payroll": (self._build_payroll, "Calculate pay from employee rates, attendance, and deductions."),
            "Reports": (self._build_reports, "Explore payroll totals and export period reports."),
            "Settings": (self._build_settings, "Set the organization details and currency used across the app."),
        }
        if page not in builders:
            return
        if not self._role_allows(page):
            messagebox.showerror(
                "Access denied",
                "Your account does not have access to that section.",
                parent=self,
            )
            return
        builder, subtitle = builders[page]
        self.current_page = page
        self.page_title_var.set(page)
        self.page_subtitle_var.set(subtitle)
        for title, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if title == page else "Nav.TButton")
        self.employee_nav_button.configure(
            style="NavActive.TButton" if page in ("Employees", "Attendance", "Leaves") else "Nav.TButton"
        )
        for child in self.page_host.winfo_children():
            child.destroy()
        builder()

    def _toggle_employee_navigation(self) -> None:
        self.employee_nav_expanded = not self.employee_nav_expanded
        if self.employee_nav_expanded:
            self.employee_navigation.pack(fill="x", padx=(12, 0))
            self.employee_nav_button.configure(text="   Manage employees   v")
        else:
            self.employee_navigation.pack_forget()
            self.employee_nav_button.configure(text="   Manage employees   >")

    def _money(self, amount: float | int | None) -> str:
        symbol = self.settings.get("currency_symbol", "₱")
        return f"{symbol}{float(amount or 0):,.2f}"

    def _card(self, parent: ttk.Frame, padding: int = 18) -> RoundedCard:
        return RoundedCard(parent, padding=padding)

    def _page_toolbar(self, parent: ttk.Frame, title: str, subtitle: str | None = None) -> ttk.Frame:
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 15))
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(toolbar, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        if subtitle:
            ttk.Label(toolbar, text=subtitle, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))
        return toolbar

    def _make_tree(
        self,
        parent: ttk.Frame,
        columns: tuple[str, ...],
        headings: dict[str, str],
        widths: dict[str, int],
        *,
        height: int = 12,
        use_grid: bool = False,
    ) -> ttk.Treeview:
        wrapper = ttk.Frame(parent, style="Card.TFrame")
        if use_grid:
            wrapper.grid(row=1, column=0, sticky="nsew")
        else:
            wrapper.pack(fill="both", expand=True)
        wrapper.rowconfigure(0, weight=1)
        wrapper.columnconfigure(0, weight=1)
        tree = ttk.Treeview(wrapper, columns=columns, show="headings", height=height, selectmode="browse")
        vertical = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(wrapper, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        for column in columns:
            tree.heading(column, text=headings.get(column, column))
            tree.column(column, width=widths.get(column, 130), anchor="w", stretch=True)
        tree.tag_configure("inactive", foreground=MUTED_COLOR)
        return tree

    def _empty_state(self, parent: ttk.Frame, message: str) -> None:
        ttk.Label(parent, text=message, style="Muted.TLabel", padding=(18, 24)).pack(anchor="center")

    def _metric_card(self, parent: ttk.Frame, column: int, title: str, value: str, detail: str, accent: str = ACCENT_BLUE) -> None:
        is_green = accent == SUCCESS_COLOR
        content_style = "MetricGreenContent.TFrame" if is_green else "MetricBlueContent.TFrame"
        label_variant = "MetricGreen" if is_green else "MetricBlue"
        card = RoundedCard(
            parent,
            padding=0,
            fill="#ECF8F2" if is_green else "#F1F7FD",
            content_style=content_style,
        )
        card.grid(
            row=0,
            column=column,
            sticky="nsew",
            padx=(0 if column == 0 else 8, 0 if column == 3 else 8),
        )
        tk.Frame(card.content, background=accent, width=5).pack(side="left", fill="y")
        content = ttk.Frame(card.content, style=content_style, padding=(16, 15))
        content.pack(side="left", fill="both", expand=True)
        ttk.Label(content, text=title.upper(), style=f"{label_variant}Title.TLabel").pack(anchor="w")
        ttk.Label(content, text=value, style=f"{label_variant}Value.TLabel").pack(anchor="w", pady=(8, 1))
        ttk.Label(content, text=detail, style=f"{label_variant}Detail.TLabel").pack(anchor="w")

    def _build_dashboard(self) -> None:
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)

        today = date.today()
        month_start = today.replace(day=1).isoformat()
        employee_count = int(self._fetchone("SELECT COUNT(*) AS count FROM employees WHERE status = 'active'")["count"])
        department_count = int(self._fetchone("SELECT COUNT(*) AS count FROM departments")["count"])
        attendance_count = int(
            self._fetchone("SELECT COUNT(*) AS count FROM attendance WHERE date = ?", (today.isoformat(),))["count"]
        )
        is_admin = self.current_user is not None and self.current_user["role"] == "admin"
        month_payroll = (
            self._fetchone(
                "SELECT COUNT(*) AS count, COALESCE(SUM(net_pay), 0) AS total "
                "FROM payroll WHERE period_end >= ? AND period_end <= ?",
                (month_start, today.isoformat()),
            )
            if is_admin
            else None
        )

        welcome_panel = RoundedCard(
            page,
            padding=(22, 14),
            fill="#EAF3FB",
            content_style="HeroContent.TFrame",
        )
        welcome_panel.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        greeting_name = self.current_user["username"] if self.current_user else "there"
        ttk.Label(
            welcome_panel.content,
            text=f"Welcome back, {greeting_name}",
            style="HeroTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            welcome_panel.content,
            text=f"Here is your payroll workspace at a glance.  •  {today.strftime('%A, %B %d, %Y')}",
            style="HeroSub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        metrics = ttk.Frame(page)
        metrics.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        for column in range(4):
            metrics.columnconfigure(column, weight=1, uniform="metric")
        self._metric_card(metrics, 0, "Active employees", f"{employee_count:,}", "Current active workforce")
        self._metric_card(metrics, 1, "Departments", f"{department_count:,}", "Organization units", ACCENT_BLUE)
        self._metric_card(metrics, 2, "Attendance today", f"{attendance_count:,}", today.strftime("%b %d, %Y"), SUCCESS_COLOR)
        if is_admin and month_payroll is not None:
            self._metric_card(
                metrics,
                3,
                "Payroll this month",
                self._money(month_payroll["total"]),
                f"{month_payroll['count']} processed records",
                SUCCESS_COLOR,
            )
        else:
            self._metric_card(
                metrics,
                3,
                "Your role",
                self.ROLE_LABELS.get(self.current_user["role"], "Viewer") if self.current_user else "Signed out",
                "Available sections",
            )

        if self.current_user and self.current_user["role"] in self.EDIT_ROLES:
            actions = ttk.Frame(page)
            actions.grid(row=2, column=0, sticky="ew", pady=(0, 18))
            ttk.Label(actions, text="Quick actions", style="Section.TLabel").pack(side="left", padx=(0, 14))
            ttk.Button(actions, text="+  Add employee", style="Primary.TButton", command=self._open_employee_form).pack(side="left", padx=(0, 8))
            ttk.Button(actions, text="+  Record attendance", style="Secondary.TButton", command=self._open_attendance_form).pack(side="left", padx=4)
            if is_admin:
                ttk.Button(actions, text="Process payroll  →", style="Secondary.TButton", command=lambda: self._show_page("Payroll")).pack(side="left", padx=4)

        lower = ttk.Frame(page)
        lower.grid(row=3, column=0, sticky="nsew")
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(0, weight=1)

        recent_card = self._card(lower)
        recent_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        if is_admin:
            recent_header = ttk.Frame(recent_card.content, style="CardContent.TFrame")
            recent_header.pack(fill="x", pady=(0, 12))
            ttk.Label(recent_header, text="Recent payroll", font=HEADING_FONT, background=WHITE, foreground=TEXT_COLOR).pack(side="left")
            ttk.Button(recent_header, text="View all  →", style="Secondary.TButton", command=lambda: self._show_page("Payroll")).pack(side="right")
            tree = self._make_tree(
                recent_card.content,
                ("employee", "period", "gross", "net"),
                {"employee": "EMPLOYEE", "period": "PERIOD END", "gross": "GROSS PAY", "net": "NET PAY"},
                {"employee": 190, "period": 115, "gross": 115, "net": 115},
                height=8,
            )
            records = self._fetchall(
                "SELECT e.first_name, e.last_name, p.period_end, p.gross_pay, p.net_pay "
                "FROM payroll p JOIN employees e ON e.employee_id = p.employee_id "
                "ORDER BY p.generated_at DESC, p.payroll_id DESC LIMIT 8"
            )
            for record in records:
                tree.insert("", "end", values=(
                    f"{record['first_name']} {record['last_name']}",
                    record["period_end"],
                    self._money(record["gross_pay"]),
                    self._money(record["net_pay"]),
                ))
            if not records:
                self._empty_state(recent_card.content, "No payroll has been processed yet.")
        else:
            ttk.Label(
                recent_card.content,
                text="Payroll details are available to administrators only.",
                style="CardMuted.TLabel",
                wraplength=430,
            ).pack(anchor="w", pady=12)

        insight = self._card(lower)
        insight.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        ttk.Label(insight.content, text="Workspace snapshot", font=HEADING_FONT, background=WHITE, foreground=TEXT_COLOR).pack(anchor="w")
        ttk.Label(
            insight.content,
            text="A quick pulse on records that may need attention.",
            style="CardMuted.TLabel",
            wraplength=300,
        ).pack(anchor="w", pady=(4, 14))
        no_attendance = int(self._fetchone(
            "SELECT COUNT(*) AS count FROM employees e WHERE e.status = 'active' "
            "AND NOT EXISTS (SELECT 1 FROM attendance a WHERE a.employee_id = e.employee_id AND a.date = ?)",
            (today.isoformat(),),
        )["count"])
        self._snapshot_line(insight.content, "Active employees", str(employee_count), ACCENT_BLUE)
        if is_admin:
            missing_salary = int(self._fetchone(
                "SELECT COUNT(*) AS count FROM employees WHERE status = 'active' "
                "AND COALESCE(hourly_rate, 0) <= 0"
            )["count"])
            self._snapshot_line(insight.content, "Missing pay rate", str(missing_salary), DANGER_COLOR if missing_salary else SUCCESS_COLOR)
        self._snapshot_line(insight.content, "No record today", str(no_attendance), GOLD_COLOR)
        if self._role_allows("Attendance"):
            ttk.Button(insight.content, text="Review attendance  →", style="Secondary.TButton", command=lambda: self._show_page("Attendance")).pack(anchor="w", pady=(16, 0))

    def _snapshot_line(self, parent: ttk.Frame, label: str, value: str, color: str) -> None:
        row = ttk.Frame(parent, style="CardContent.TFrame")
        row.pack(fill="x", pady=7)
        ttk.Label(row, text=label, style="CardMuted.TLabel").pack(side="left")
        ttk.Label(row, text=value, font=("Segoe UI", 13, "bold"), foreground=color, background=WHITE).pack(side="right")

    def _build_employees(self) -> None:
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.rowconfigure(1, weight=1)
        page.columnconfigure(0, weight=1)
        toolbar = self._page_toolbar(page, "Employee directory", "Create and maintain employee profiles and pay rates.")
        if self.current_user and self.current_user["role"] in self.EDIT_ROLES:
            ttk.Button(toolbar, text="+  Add department", style="Secondary.TButton", command=self._open_department_form).grid(row=0, column=1, rowspan=2, padx=(0, 8), sticky="e")
            ttk.Button(toolbar, text="+  Add employee", style="Primary.TButton", command=self._open_employee_form).grid(row=0, column=2, rowspan=2, sticky="e")

        controls = ttk.Frame(page)
        controls.pack(fill="both", expand=True)
        controls.rowconfigure(1, weight=1)
        controls.columnconfigure(0, weight=1)
        filter_row = ttk.Frame(controls)
        filter_row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.employee_search_var = tk.StringVar()
        search = ttk.Entry(filter_row, textvariable=self.employee_search_var, width=34)
        search.pack(side="left")
        search.insert(0, "")
        self.employee_search_var.trace_add("write", lambda *_: self._refresh_employees())
        ttk.Label(filter_row, text="Search name, department, or position", style="Muted.TLabel").pack(side="left", padx=10)
        if self.current_user and self.current_user["role"] in self.EDIT_ROLES:
            ttk.Button(filter_row, text="Edit selected", style="Secondary.TButton", command=self._edit_selected_employee).pack(side="right", padx=(8, 0))
            ttk.Button(filter_row, text="Activate / deactivate", style="Secondary.TButton", command=self._toggle_employee_status).pack(side="right")

        self.employee_tree = self._make_tree(
            controls,
            ("id", "name", "department", "position", "rate", "status"),
            {"id": "ID", "name": "EMPLOYEE", "department": "DEPARTMENT", "position": "POSITION", "rate": "HOURLY RATE", "status": "STATUS"},
            {"id": 55, "name": 185, "department": 155, "position": 150, "rate": 140, "status": 90},
            use_grid=True,
        )
        self.employee_tree.bind("<Double-1>", lambda _event: self._edit_selected_employee())
        self._refresh_employees()

    def _refresh_employees(self) -> None:
        if not hasattr(self, "employee_tree") or not self.employee_tree.winfo_exists():
            return
        for item in self.employee_tree.get_children():
            self.employee_tree.delete(item)
        term = f"%{self.employee_search_var.get().strip()}%"
        rows = self._fetchall(
            "SELECT e.employee_id, e.first_name, e.middle_name, e.last_name, e.position, e.hourly_rate, "
            "e.status, COALESCE(d.department_name, 'Unassigned') AS department "
            "FROM employees e LEFT JOIN departments d ON d.department_id = e.department_id "
            "WHERE e.first_name LIKE ? OR e.middle_name LIKE ? OR e.last_name LIKE ? "
            "OR e.position LIKE ? OR d.department_name LIKE ? ORDER BY e.last_name, e.first_name",
            (term, term, term, term, term),
        )
        for row in rows:
            full_name = " ".join(part for part in (row["first_name"], row["middle_name"], row["last_name"]) if part)
            hourly_rate = row["hourly_rate"]
            rate = f"{self._money(hourly_rate)} / hr" if hourly_rate is not None else "Not set"
            tag = () if row["status"] == "active" else ("inactive",)
            self.employee_tree.insert("", "end", iid=str(row["employee_id"]), values=(
                row["employee_id"], full_name, row["department"], row["position"] or "—", rate, row["status"].title()
            ), tags=tag)
        self.status_var.set(f"Showing {len(rows)} employee record(s)")

    def _selected_employee_id(self) -> int | None:
        if not hasattr(self, "employee_tree"):
            return None
        selection = self.employee_tree.selection()
        return int(selection[0]) if selection else None

    def _edit_selected_employee(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "edit employee records"):
            return
        employee_id = self._selected_employee_id()
        if employee_id is None:
            messagebox.showinfo("Select an employee", "Choose an employee row first.", parent=self)
            return
        self._open_employee_form(employee_id)

    def _toggle_employee_status(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "change employee status"):
            return
        employee_id = self._selected_employee_id()
        if employee_id is None:
            messagebox.showinfo("Select an employee", "Choose an employee row first.", parent=self)
            return
        row = self._fetchone("SELECT status, first_name, last_name FROM employees WHERE employee_id = ?", (employee_id,))
        if row is None:
            messagebox.showerror("Employee not found", "Refresh the directory and try again.", parent=self)
            return
        next_status = "inactive" if row["status"] == "active" else "active"
        if messagebox.askyesno("Update employee status", f"Mark {row['first_name']} {row['last_name']} as {next_status}?", parent=self):
            self._execute("UPDATE employees SET status = ? WHERE employee_id = ?", (next_status, employee_id))
            self._refresh_employees()

    def _open_department_form(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "manage departments"):
            return
        dialog = tk.Toplevel(self)
        dialog.title("Add department")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="New department", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Add a department for employee profiles.", style="Muted.TLabel").pack(anchor="w", pady=(4, 13))
        department_var = tk.StringVar()
        entry = ttk.Entry(body, textvariable=department_var, width=38)
        entry.pack(fill="x")
        entry.focus_set()

        def save() -> None:
            name = department_var.get().strip()
            if not name:
                messagebox.showerror("Department required", "Enter a department name.", parent=dialog)
                return
            try:
                self._execute("INSERT INTO departments (department_name) VALUES (?)", (name,))
            except sqlite3.IntegrityError:
                messagebox.showerror("Department exists", "A department with that name already exists.", parent=dialog)
                return
            except sqlite3.Error as exc:
                messagebox.showerror("Could not save department", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.status_var.set(f"Department added: {name}")

        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Cancel", style="Secondary.TButton", command=dialog.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="Save department", style="Primary.TButton", command=save).pack(side="right")
        dialog.bind("<Return>", lambda _event: save())
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 300}+{self.winfo_rooty() + 220}")

    def _open_employee_form(self, employee_id: int | None = None) -> None:
        if not self._require_roles(self.EDIT_ROLES, "create or edit employee records"):
            return
        employee = self._fetchone("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)) if employee_id is not None else None
        departments = self._fetchall("SELECT department_id, department_name FROM departments ORDER BY department_name")
        dialog = tk.Toplevel(self)
        dialog.title("Edit employee" if employee else "Add employee")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Edit employee" if employee else "New employee", style="Title.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 3))
        ttk.Label(body, text="Fields marked * are required. Select the scheduled start in 24-hour time.", style="Muted.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 18))

        fields: dict[str, tk.StringVar | DatePicker] = {}
        entries = (
            ("first_name", "First name *", 0),
            ("middle_name", "Middle name", 1),
            ("last_name", "Last name *", 2),
            ("gender", "Gender", 3),
            ("birth_date", "Birth date", 4),
            ("position", "Position", 5),
            ("hire_date", "Hire date", 6),
            ("contact_number", "Contact number", 7),
            ("email", "Email", 8),
            ("address", "Address", 9),
        )
        for index, (key, label, row_index) in enumerate(entries):
            column = 0 if index < 5 else 2
            row_index = index + 2 if index < 5 else index - 3
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=row_index, column=column, sticky="w", padx=(0, 12), pady=5)
            if key in ("birth_date", "hire_date"):
                field: tk.StringVar | DatePicker = DatePicker(
                    body,
                    str(employee[key] or "") if employee else "",
                    allow_empty=True,
                    width=20,
                )
            else:
                field = tk.StringVar(value=str(employee[key] or "") if employee else "")
            fields[key] = field
            if isinstance(field, DatePicker):
                field.grid(row=row_index, column=column + 1, sticky="ew", pady=5)
            else:
                ttk.Entry(body, textvariable=field, width=27).grid(
                    row=row_index, column=column + 1, sticky="ew", pady=5
                )
        department_names = {str(row["department_name"]): int(row["department_id"]) for row in departments}
        ttk.Label(body, text="Department", style="Muted.TLabel").grid(row=7, column=0, sticky="w", pady=5)
        department_var = tk.StringVar()
        department_combo = ttk.Combobox(body, textvariable=department_var, values=tuple(department_names), state="readonly", width=25)
        department_combo.grid(row=7, column=1, sticky="ew", pady=5)
        if employee and employee["department_id"] is not None:
            department_var.set(next((name for name, value in department_names.items() if value == employee["department_id"]), ""))
        ttk.Label(body, text="Hourly rate *", style="Muted.TLabel").grid(row=8, column=0, sticky="w", pady=5)
        hourly_var = tk.StringVar(value=str(employee["hourly_rate"] or "") if employee else "")
        ttk.Entry(body, textvariable=hourly_var, width=27).grid(row=8, column=1, sticky="ew", pady=5)
        ttk.Label(body, text="Status", style="Muted.TLabel").grid(row=8, column=2, sticky="w", padx=(18, 12), pady=5)
        status_var = tk.StringVar(value=(employee["status"] or "active").title() if employee else "Active")
        ttk.Combobox(body, textvariable=status_var, values=("Active", "Inactive"), state="readonly", width=25).grid(row=8, column=3, sticky="ew", pady=5)
        ttk.Label(body, text="Scheduled start *", style="Muted.TLabel").grid(row=9, column=0, sticky="w", pady=5)
        scheduled_start = str(employee["scheduled_start_time"] or "09:00") if employee else "09:00"
        try:
            scheduled_start = datetime.strptime(scheduled_start, "%H:%M").strftime("%H:%M")
        except ValueError:
            messagebox.showerror(
                "Invalid schedule",
                "This employee has an invalid scheduled start time. Correct it in the database before editing the profile.",
                parent=self,
            )
            dialog.destroy()
            return
        shift_hour_var = tk.StringVar(value=scheduled_start[:2])
        shift_minute_var = tk.StringVar(value=scheduled_start[3:])
        shift_time_fields = ttk.Frame(body)
        shift_time_fields.grid(row=9, column=1, sticky="w", pady=5)
        ttk.Combobox(
            shift_time_fields,
            textvariable=shift_hour_var,
            values=tuple(f"{hour:02d}" for hour in range(24)),
            state="readonly",
            width=5,
        ).pack(side="left")
        ttk.Label(shift_time_fields, text=":").pack(side="left", padx=3)
        ttk.Combobox(
            shift_time_fields,
            textvariable=shift_minute_var,
            values=tuple(f"{minute:02d}" for minute in range(60)),
            state="readonly",
            width=5,
        ).pack(side="left")
        ttk.Label(shift_time_fields, text="(24-hour time)", style="Muted.TLabel").pack(side="left", padx=(8, 0))

        body.columnconfigure(1, weight=1)
        body.columnconfigure(3, weight=1)

        def save() -> None:
            if not fields["first_name"].get().strip() or not fields["last_name"].get().strip():
                messagebox.showerror("Required information", "First name and last name are required.", parent=dialog)
                return
            try:
                hourly_rate = float(hourly_var.get())
                if not isfinite(hourly_rate) or hourly_rate <= 0:
                    raise ValueError
                scheduled_start_time = datetime.strptime(
                    f"{shift_hour_var.get()}:{shift_minute_var.get()}", "%H:%M"
                ).strftime("%H:%M")
                for key in ("birth_date", "hire_date"):
                    if fields[key].get().strip():
                        date.fromisoformat(fields[key].get().strip())
            except ValueError:
                messagebox.showerror("Invalid information", "Select valid dates, enter a positive hourly rate, and choose a valid scheduled start time.", parent=dialog)
                return
            values = (
                fields["first_name"].get().strip(),
                fields["last_name"].get().strip(),
                fields["middle_name"].get().strip() or None,
                fields["gender"].get().strip() or None,
                fields["birth_date"].get().strip() or None,
                department_names.get(department_var.get()),
                fields["position"].get().strip() or None,
                "hourly",
                None,
                None,
                hourly_rate,
                scheduled_start_time,
                fields["hire_date"].get().strip() or None,
                fields["contact_number"].get().strip() or None,
                fields["email"].get().strip() or None,
                fields["address"].get().strip() or None,
                status_var.get().lower(),
            )
            try:
                if employee_id is None:
                    self._execute(
                        "INSERT INTO employees (first_name,last_name,middle_name,gender,birth_date,department_id,position,"
                        "salary_type,daily_rate,monthly_salary,hourly_rate,scheduled_start_time,hire_date,contact_number,email,address,status) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        values,
                    )
                else:
                    self._execute(
                        "UPDATE employees SET first_name=?,last_name=?,middle_name=?,gender=?,birth_date=?,department_id=?,"
                        "position=?,salary_type=?,daily_rate=?,monthly_salary=?,hourly_rate=?,scheduled_start_time=?,hire_date=?,contact_number=?,email=?,address=?,status=? "
                        "WHERE employee_id=?",
                        values + (employee_id,),
                    )
            except sqlite3.Error as exc:
                messagebox.showerror("Could not save employee", str(exc), parent=dialog)
                return
            dialog.destroy()
            if self.current_page == "Employees":
                self._refresh_employees()
            else:
                self._show_page(self.current_page)
            self.status_var.set("Employee profile saved")

        buttons = ttk.Frame(body)
        buttons.grid(row=11, column=0, columnspan=4, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Save employee", style="Primary.TButton", command=save).pack(side="left")
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 180}+{self.winfo_rooty() + 90}")

    def _build_attendance(self) -> None:
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.rowconfigure(1, weight=1)
        page.columnconfigure(0, weight=1)
        toolbar = self._page_toolbar(page, "Attendance records", "Record hours worked and overtime for each employee.")
        if self.current_user and self.current_user["role"] in self.EDIT_ROLES:
            ttk.Button(toolbar, text="+  Record attendance", style="Primary.TButton", command=self._open_attendance_form).grid(row=0, column=1, rowspan=2, sticky="e")

        controls = ttk.Frame(page)
        controls.pack(fill="both", expand=True)
        controls.rowconfigure(1, weight=1)
        controls.columnconfigure(0, weight=1)
        filter_row = ttk.Frame(controls)
        filter_row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(filter_row, text="Work date", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.attendance_date_picker = DatePicker(
            filter_row,
            date.today().isoformat(),
            allow_empty=True,
            on_change=self._refresh_attendance,
            width=17,
        )
        self.attendance_date_picker.pack(side="left")
        ttk.Button(filter_row, text="Apply", style="Secondary.TButton", command=self._refresh_attendance).pack(side="left", padx=8)
        ttk.Button(filter_row, text="Show all", style="Secondary.TButton", command=self._show_all_attendance).pack(side="left")
        if self.current_user and self.current_user["role"] in self.EDIT_ROLES:
            ttk.Button(filter_row, text="Edit selected", style="Secondary.TButton", command=self._edit_selected_attendance).pack(side="right")
            ttk.Button(filter_row, text="Delete selected", style="Danger.TButton", command=self._delete_selected_attendance).pack(side="right", padx=(0, 8))
        self.attendance_tree = self._make_tree(
            controls,
            ("id", "date", "employee", "department", "in", "out", "hours", "overtime", "late"),
            {"id": "ID", "date": "DATE", "employee": "EMPLOYEE", "department": "DEPARTMENT", "in": "TIME IN", "out": "TIME OUT", "hours": "HOURS", "overtime": "OVERTIME", "late": "LATE (MIN)"},
            {"id": 55, "date": 105, "employee": 180, "department": 145, "in": 90, "out": 90, "hours": 85, "overtime": 90, "late": 90},
            use_grid=True,
        )
        self._refresh_attendance()

    def _show_all_attendance(self) -> None:
        self.attendance_date_picker.set("")
        self._refresh_attendance()

    def _refresh_attendance(self) -> None:
        if not hasattr(self, "attendance_tree") or not self.attendance_tree.winfo_exists():
            return
        for item in self.attendance_tree.get_children():
            self.attendance_tree.delete(item)
        filter_date = self.attendance_date_picker.get()
        if filter_date:
            try:
                date.fromisoformat(filter_date)
            except ValueError:
                messagebox.showerror("Invalid date", "Select a valid work date.", parent=self)
                return
        query = (
            "SELECT a.attendance_id, a.date, e.first_name, e.last_name, d.department_name, "
            "a.time_in, a.time_out, a.hours_worked, a.overtime_hours, a.late_minutes FROM attendance a "
            "JOIN employees e ON e.employee_id = a.employee_id "
            "LEFT JOIN departments d ON d.department_id = e.department_id "
        )
        parameters: tuple[Any, ...] = ()
        if filter_date:
            query += "WHERE a.date = ? "
            parameters = (filter_date,)
        query += "ORDER BY a.date DESC, e.last_name, e.first_name"
        rows = self._fetchall(query, parameters)
        for row in rows:
            self.attendance_tree.insert("", "end", iid=str(row["attendance_id"]), values=(
                row["attendance_id"], row["date"], f"{row['first_name']} {row['last_name']}",
                row["department_name"] or "Unassigned", row["time_in"] or "—", row["time_out"] or "—",
                f"{float(row['hours_worked'] or 0):.2f}", f"{float(row['overtime_hours'] or 0):.2f}",
                int(row["late_minutes"] or 0),
            ))
        self.status_var.set(f"Showing {len(rows)} attendance record(s)")

    def _open_attendance_form(self, attendance_id: int | None = None) -> None:
        if not self._require_roles(self.EDIT_ROLES, "create or edit attendance records"):
            return
        record = self._fetchone("SELECT * FROM attendance WHERE attendance_id = ?", (attendance_id,)) if attendance_id else None
        employees = self._fetchall(
            "SELECT employee_id, first_name, last_name FROM employees WHERE status = 'active' ORDER BY last_name, first_name"
        )
        if not employees:
            messagebox.showinfo("No active employees", "Add an active employee before recording attendance.", parent=self)
            return
        employee_options = {
            f"{row['last_name']}, {row['first_name']}  (#{row['employee_id']})": int(row["employee_id"])
            for row in employees
        }
        dialog = tk.Toplevel(self)
        dialog.title("Edit attendance" if record else "Record attendance")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Attendance entry", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Times use 24-hour HH:MM. Late minutes are based on the employee's scheduled start.", style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 15))
        employee_var = tk.StringVar()
        employee_combo = ttk.Combobox(body, textvariable=employee_var, values=tuple(employee_options), state="readonly", width=36)
        if record:
            employee_var.set(next((name for name, value in employee_options.items() if value == record["employee_id"]), ""))
        else:
            employee_var.set(next(iter(employee_options)))
        date_picker = DatePicker(body, str(record["date"]) if record else date.today().isoformat(), width=20)
        time_in_var = tk.StringVar(value=str(record["time_in"] or "") if record else "")
        time_out_var = tk.StringVar(value=str(record["time_out"] or "") if record else "")
        hours_var = tk.StringVar(value=str(record["hours_worked"] or 0) if record else "8")
        overtime_var = tk.StringVar(value=str(record["overtime_hours"] or 0) if record else "0")
        fields = (
            ("Employee", employee_combo),
            ("Work date", date_picker),
            ("Time in", ttk.Entry(body, textvariable=time_in_var, width=39)),
            ("Time out", ttk.Entry(body, textvariable=time_out_var, width=39)),
            ("Total hours worked", ttk.Entry(body, textvariable=hours_var, width=39)),
            ("Overtime hours", ttk.Entry(body, textvariable=overtime_var, width=39)),
        )
        for row_index, (label, widget) in enumerate(fields, start=2):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(row=row_index, column=0, sticky="w", pady=6, padx=(0, 15))
            widget.grid(row=row_index, column=1, sticky="ew", pady=6)
        body.columnconfigure(1, weight=1)

        def save() -> None:
            if not employee_var.get():
                messagebox.showerror("Missing employee", "Select an employee.", parent=dialog)
                return
            try:
                date.fromisoformat(date_picker.get())
                hours = float(hours_var.get())
                overtime = float(overtime_var.get())
                if not isfinite(hours) or not isfinite(overtime) or hours < 0 or overtime < 0 or overtime > hours:
                    raise ValueError
                time_in_value = time_in_var.get().strip()
                time_out_value = time_out_var.get().strip()
                time_in_value = (
                    datetime.strptime(time_in_value, "%H:%M").strftime("%H:%M")
                    if time_in_value else None
                )
                time_out_value = (
                    datetime.strptime(time_out_value, "%H:%M").strftime("%H:%M")
                    if time_out_value else None
                )
            except ValueError:
                messagebox.showerror("Invalid attendance", "Enter a valid date, HH:MM time, and non-negative hours (overtime cannot exceed total hours).", parent=dialog)
                return
            employee_id = employee_options[employee_var.get()]
            employee_schedule = self._fetchone(
                "SELECT scheduled_start_time FROM employees WHERE employee_id = ?",
                (employee_id,),
            )
            if employee_schedule is None:
                messagebox.showerror("Employee not found", "Select an active employee and try again.", parent=dialog)
                return
            try:
                late_minutes = calculate_late_minutes(
                    str(employee_schedule["scheduled_start_time"] or "09:00"),
                    time_in_value,
                )
            except ValueError:
                messagebox.showerror(
                    "Invalid scheduled start",
                    "Update this employee's scheduled start time to HH:MM before recording attendance.",
                    parent=dialog,
                )
                return
            values = (
                employee_id,
                date_picker.get(),
                time_in_value,
                time_out_value,
                hours,
                overtime,
                late_minutes,
            )
            try:
                duplicate = self._fetchone(
                    "SELECT attendance_id FROM attendance WHERE employee_id = ? AND date = ? AND attendance_id != ?",
                    (employee_id, date_picker.get(), attendance_id or -1),
                )
                if duplicate:
                    messagebox.showerror("Duplicate record", "This employee already has an attendance record for that date.", parent=dialog)
                    return
                if attendance_id:
                    self._execute(
                        "UPDATE attendance SET employee_id=?,date=?,time_in=?,time_out=?,hours_worked=?,overtime_hours=?,late_minutes=? WHERE attendance_id=?",
                        values + (attendance_id,),
                    )
                else:
                    self._execute(
                        "INSERT INTO attendance (employee_id,date,time_in,time_out,hours_worked,overtime_hours,late_minutes) VALUES (?,?,?,?,?,?,?)",
                        values,
                    )
            except sqlite3.Error as exc:
                messagebox.showerror("Could not save attendance", str(exc), parent=dialog)
                return
            dialog.destroy()
            if self.current_page == "Attendance":
                self._refresh_attendance()
            else:
                self._show_page(self.current_page)
            self.status_var.set("Attendance record saved")

        actions = ttk.Frame(body)
        actions.grid(row=8, column=0, columnspan=2, sticky="e", pady=(15, 0))
        ttk.Button(actions, text="Cancel", style="Secondary.TButton", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Save record", style="Primary.TButton", command=save).pack(side="left")
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 260}+{self.winfo_rooty() + 150}")

    def _edit_selected_attendance(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "edit attendance records"):
            return
        selection = self.attendance_tree.selection()
        if not selection:
            messagebox.showinfo("Select a record", "Choose an attendance row first.", parent=self)
            return
        self._open_attendance_form(int(selection[0]))

    def _delete_selected_attendance(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "delete attendance records"):
            return
        selection = self.attendance_tree.selection()
        if not selection:
            messagebox.showinfo("Select a record", "Choose an attendance row first.", parent=self)
            return
        record = self._fetchone(
            "SELECT date FROM attendance WHERE attendance_id = ?", (int(selection[0]),)
        )
        if record is None:
            messagebox.showerror("Record not found", "Refresh the attendance list and try again.", parent=self)
            self._refresh_attendance()
            return
        if not messagebox.askyesno(
            "Delete attendance record",
            f"Delete the attendance record for {record['date']}? Payroll calculations for future runs will no longer include it.",
            parent=self,
        ):
            return
        try:
            self._execute("DELETE FROM attendance WHERE attendance_id = ?", (int(selection[0]),))
        except sqlite3.Error as exc:
            messagebox.showerror("Could not delete attendance", str(exc), parent=self)
            return
        self._refresh_attendance()

    def _build_leaves(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "manage leave and travel records"):
            return
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.rowconfigure(1, weight=1)
        page.columnconfigure(0, weight=1)
        toolbar = self._page_toolbar(
            page,
            "Leave & travel records",
            "Approve paid leave and travel orders to credit 8 weekday hours per day. Maternity leave is tracked separately and does not automatically add wages.",
        )
        ttk.Button(
            toolbar,
            text="+  Add leave / travel",
            style="Primary.TButton",
            command=self._open_leave_form,
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(10, 0))
        action_row = ttk.Frame(page)
        action_row.pack(fill="x", pady=(0, 10))
        ttk.Button(
            action_row,
            text="Delete selected",
            style="Danger.TButton",
            command=self._delete_selected_leave,
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            action_row,
            text="Edit selected",
            style="Secondary.TButton",
            command=self._edit_selected_leave,
        ).pack(side="right")
        self.leave_tree = self._make_tree(
            page,
            ("id", "employee", "type", "start", "end", "status", "notes"),
            {"id": "ID", "employee": "EMPLOYEE", "type": "TYPE", "start": "FROM", "end": "TO", "status": "STATUS", "notes": "NOTES"},
            {"id": 55, "employee": 180, "type": 145, "start": 110, "end": 110, "status": 100, "notes": 240},
        )
        self._refresh_leaves()

    def _refresh_leaves(self) -> None:
        if not hasattr(self, "leave_tree") or not self.leave_tree.winfo_exists():
            return
        for item in self.leave_tree.get_children():
            self.leave_tree.delete(item)
        rows = self._fetchall(
            "SELECT l.leave_id,e.first_name,e.last_name,l.leave_type,l.start_date,l.end_date,"
            "l.status,l.notes FROM leave_records l JOIN employees e ON e.employee_id=l.employee_id "
            "ORDER BY l.start_date DESC,e.last_name,e.first_name"
        )
        for row in rows:
            self.leave_tree.insert(
                "",
                "end",
                iid=str(row["leave_id"]),
                values=(
                    row["leave_id"],
                    f"{row['first_name']} {row['last_name']}",
                    row["leave_type"],
                    row["start_date"],
                    row["end_date"],
                    row["status"],
                    row["notes"] or "",
                ),
            )
        self.status_var.set(f"Showing {len(rows)} leave and travel record(s)")

    def _edit_selected_leave(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "edit leave and travel records"):
            return
        selection = self.leave_tree.selection()
        if not selection:
            messagebox.showinfo("Select a record", "Choose a leave or travel row first.", parent=self)
            return
        self._open_leave_form(int(selection[0]))

    def _delete_selected_leave(self) -> None:
        if not self._require_roles(self.EDIT_ROLES, "delete leave and travel records"):
            return
        selection = self.leave_tree.selection()
        if not selection:
            messagebox.showinfo("Select a record", "Choose a leave or travel row first.", parent=self)
            return
        leave_id = int(selection[0])
        record = self._fetchone(
            "SELECT leave_type,start_date,end_date FROM leave_records WHERE leave_id = ?",
            (leave_id,),
        )
        if record is None:
            messagebox.showerror("Record not found", "Refresh the leave list and try again.", parent=self)
            self._refresh_leaves()
            return
        if not messagebox.askyesno(
            "Delete leave / travel record",
            f"Delete this {record['leave_type'].lower()} record ({record['start_date']} to {record['end_date']})?",
            parent=self,
        ):
            return
        try:
            self._execute("DELETE FROM leave_records WHERE leave_id = ?", (leave_id,))
        except sqlite3.Error as exc:
            messagebox.showerror("Could not delete leave record", str(exc), parent=self)
            return
        self._refresh_leaves()

    def _open_leave_form(self, leave_id: int | None = None) -> None:
        if not self._require_roles(self.EDIT_ROLES, "create or edit leave and travel records"):
            return
        employees = self._fetchall(
            "SELECT employee_id,first_name,last_name FROM employees "
            "WHERE status='active' ORDER BY last_name,first_name"
        )
        if not employees:
            messagebox.showinfo(
                "No active employees",
                "Add an active employee before recording leave or travel.",
                parent=self,
            )
            return
        record = (
            self._fetchone("SELECT * FROM leave_records WHERE leave_id = ?", (leave_id,))
            if leave_id is not None
            else None
        )
        employee_options = {
            f"{row['last_name']}, {row['first_name']} (#{row['employee_id']})": int(row["employee_id"])
            for row in employees
        }
        selected_employee = next(
            (
                name
                for name, employee_option_id in employee_options.items()
                if record and employee_option_id == int(record["employee_id"])
            ),
            next(iter(employee_options)),
        )
        dialog = tk.Toplevel(self)
        dialog.title("Edit leave / travel" if record else "Add leave / travel")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Leave or travel record",
            style="Title.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            body,
            text="Approved paid leave and travel orders credit weekdays at 8 hours per day. Maternity leave is tracked only.",
            style="Muted.TLabel",
            wraplength=460,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))

        fields: list[tuple[str, ttk.Widget]] = []
        employee_var = tk.StringVar(value=selected_employee)
        employee_combo = ttk.Combobox(
            body,
            textvariable=employee_var,
            values=tuple(employee_options),
            state="readonly",
            width=36,
        )
        fields.append(("Employee", employee_combo))
        type_var = tk.StringVar(value=str(record["leave_type"]) if record else "Paid leave")
        fields.append(
            (
                "Type",
                ttk.Combobox(
                    body,
                    textvariable=type_var,
                    values=("Paid leave", "Maternity leave", "Travel order"),
                    state="readonly",
                    width=36,
                ),
            )
        )
        default_start = str(record["start_date"]) if record else date.today().isoformat()
        default_end = str(record["end_date"]) if record else date.today().isoformat()
        start_picker = DatePicker(body, default_start, width=18)
        end_picker = DatePicker(body, default_end, width=18)
        fields.extend((("Start date", start_picker), ("End date", end_picker)))
        status_var = tk.StringVar(value=str(record["status"]) if record else "Pending")
        fields.append(
            (
                "Approval status",
                ttk.Combobox(
                    body,
                    textvariable=status_var,
                    values=("Pending", "Approved", "Rejected"),
                    state="readonly",
                    width=36,
                ),
            )
        )
        notes_var = tk.StringVar(value=str(record["notes"] or "") if record else "")
        fields.append(("Notes", ttk.Entry(body, textvariable=notes_var, width=39)))
        for row_index, (label, widget) in enumerate(fields, start=2):
            ttk.Label(body, text=label, style="Muted.TLabel").grid(
                row=row_index, column=0, sticky="w", padx=(0, 12), pady=6
            )
            widget.grid(row=row_index, column=1, sticky="ew", pady=6)
        body.columnconfigure(1, weight=1)

        def save() -> None:
            employee_id_value = employee_options.get(employee_var.get())
            try:
                start_value = date.fromisoformat(start_picker.get())
                end_value = date.fromisoformat(end_picker.get())
                if end_value < start_value or employee_id_value is None:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Invalid leave dates",
                    "Choose an employee and valid dates. The end date cannot be before the start date.",
                    parent=dialog,
                )
                return
            overlap = self._fetchone(
                "SELECT leave_id FROM leave_records WHERE employee_id=? AND status!='Rejected' "
                "AND start_date<=? AND end_date>=? AND leave_id!=?",
                (
                    employee_id_value,
                    end_value.isoformat(),
                    start_value.isoformat(),
                    leave_id or -1,
                ),
            )
            if overlap:
                messagebox.showerror(
                    "Overlapping record",
                    "This employee already has a non-rejected leave or travel record during those dates.",
                    parent=dialog,
                )
                return
            values = (
                employee_id_value,
                type_var.get(),
                start_value.isoformat(),
                end_value.isoformat(),
                status_var.get(),
                notes_var.get().strip() or None,
            )
            try:
                if leave_id is None:
                    self._execute(
                        "INSERT INTO leave_records "
                        "(employee_id,leave_type,start_date,end_date,status,notes) VALUES (?,?,?,?,?,?)",
                        values,
                    )
                else:
                    self._execute(
                        "UPDATE leave_records SET employee_id=?,leave_type=?,start_date=?,end_date=?,"
                        "status=?,notes=? WHERE leave_id=?",
                        values + (leave_id,),
                    )
            except sqlite3.Error as exc:
                messagebox.showerror("Could not save leave record", str(exc), parent=dialog)
                return
            dialog.destroy()
            self._refresh_leaves()

        actions = ttk.Frame(body)
        actions.grid(row=8, column=0, columnspan=2, sticky="e", pady=(15, 0))
        ttk.Button(
            actions, text="Cancel", style="Secondary.TButton", command=dialog.destroy
        ).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Save record", style="Primary.TButton", command=save).pack(
            side="left"
        )
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 240}+{self.winfo_rooty() + 130}")

    def _build_payroll(self) -> None:
        if not self._require_roles(("admin",), "view payroll"):
            return
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        toolbar = self._page_toolbar(page, "Payroll processing", "Prepare monthly payroll, review past entries, and manage optional deductions.")
        ttk.Button(toolbar, text="Other deductions", style="Secondary.TButton", command=self._open_deductions_form).grid(row=0, column=1, rowspan=2, padx=(0, 8))

        process_panel = self._card(page, padding=18)
        process_panel.pack(fill="x", pady=(0, 16))
        process_card = process_panel.content
        ttk.Label(process_card, text="New payroll run", font=HEADING_FONT, background=WHITE, foreground=TEXT_COLOR).grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(
            process_card,
            text="Run one full calendar month at a time. Regular hours are paid at the hourly rate, overtime at 1.5×, and Philippine employee contributions and withholding tax are calculated automatically. Employer shares are not deducted.",
            style="CardMuted.TLabel",
            wraplength=860,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 14))
        ttk.Label(
            process_card,
            text="SSS's latest table located is for 2025. The estimate does not handle annual tax reconciliation or special-pay exemptions; confirm current agency rules before remitting.",
            style="CardMuted.TLabel",
            wraplength=860,
        ).grid(row=3, column=0, columnspan=5, sticky="w", pady=(10, 0))
        today = date.today()
        period_start_picker = DatePicker(process_card, today.replace(day=1).isoformat(), width=18)
        period_end_picker = DatePicker(
            process_card,
            today.replace(day=calendar.monthrange(today.year, today.month)[1]).isoformat(),
            width=18,
        )
        ttk.Label(process_card, text="Period start", style="Muted.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8))
        period_start_picker.grid(row=2, column=1, sticky="w", padx=(0, 18))
        ttk.Label(process_card, text="Period end", style="Muted.TLabel").grid(row=2, column=2, sticky="w", padx=(0, 8))
        period_end_picker.grid(row=2, column=3, sticky="w")
        ttk.Button(
            process_card,
            text="Review & process payroll  →",
            style="Primary.TButton",
            command=lambda: self._process_payroll(period_start_picker.get(), period_end_picker.get()),
        ).grid(row=2, column=4, sticky="e", padx=(20, 0))
        process_card.columnconfigure(4, weight=1)

        history_panel = self._card(page)
        history_panel.pack(fill="both", expand=True)
        history_card = history_panel.content
        history_heading = ttk.Frame(history_card, style="CardContent.TFrame")
        history_heading.pack(fill="x", pady=(0, 12))
        ttk.Label(
            history_heading,
            text="Payroll history",
            font=HEADING_FONT,
            background=WHITE,
            foreground=TEXT_COLOR,
        ).pack(side="left")
        ttk.Button(
            history_heading,
            text="Delete selected",
            style="Danger.TButton",
            command=self._delete_selected_payroll,
        ).pack(side="right")
        self.payroll_tree = self._make_tree(
            history_card,
            ("id", "employee", "period", "gross", "leave_hours", "late_minutes", "late_deduction", "deductions", "net", "generated"),
            {"id": "ID", "employee": "EMPLOYEE", "period": "PAY PERIOD", "gross": "GROSS PAY", "leave_hours": "PAID LEAVE HRS", "late_minutes": "LATE MIN", "late_deduction": "TARDINESS", "deductions": "STATUTORY + OTHER", "net": "NET PAY", "generated": "PROCESSED"},
            {"id": 50, "employee": 150, "period": 165, "gross": 105, "leave_hours": 105, "late_minutes": 85, "late_deduction": 105, "deductions": 115, "net": 105, "generated": 120},
        )
        self._refresh_payroll()

    def _refresh_payroll(self) -> None:
        if not hasattr(self, "payroll_tree") or not self.payroll_tree.winfo_exists():
            return
        for item in self.payroll_tree.get_children():
            self.payroll_tree.delete(item)
        rows = self._fetchall(
            "SELECT p.payroll_id, e.first_name, e.last_name, p.period_start, p.period_end, p.gross_pay, "
            "p.tardiness_minutes, p.tardiness_deduction, p.deductions, p.sss_deduction, "
            "p.philhealth_deduction, p.pagibig_deduction, p.tax_withheld, p.other_deductions,p.paid_leave_hours, "
            "p.net_pay, p.generated_at FROM payroll p "
            "JOIN employees e ON e.employee_id = p.employee_id "
            "ORDER BY p.period_end DESC, p.generated_at DESC, p.payroll_id DESC"
        )
        for row in rows:
            self.payroll_tree.insert("", "end", iid=str(row["payroll_id"]), values=(
                row["payroll_id"], f"{row['first_name']} {row['last_name']}",
                f"{row['period_start']} – {row['period_end']}", self._money(row["gross_pay"]),
                f"{float(row['paid_leave_hours'] or 0):.2f}",
                int(row["tardiness_minutes"]), self._money(row["tardiness_deduction"]),
                self._money(row["deductions"]),
                self._money(row["net_pay"]), str(row["generated_at"])[:16],
            ))
        self.status_var.set(f"{len(rows)} payroll record(s)")

    def _delete_selected_payroll(self) -> None:
        if not self._require_roles(("admin",), "delete payroll history"):
            return
        selection = self.payroll_tree.selection()
        if not selection:
            messagebox.showinfo("Select a payroll record", "Choose a payroll history row first.", parent=self)
            return
        payroll_id = int(selection[0])
        record = self._fetchone(
            "SELECT e.first_name,e.last_name,p.period_start,p.period_end FROM payroll p "
            "JOIN employees e ON e.employee_id=p.employee_id WHERE p.payroll_id=?",
            (payroll_id,),
        )
        if record is None:
            messagebox.showerror("Payroll record not found", "Refresh payroll history and try again.", parent=self)
            self._refresh_payroll()
            return
        if not messagebox.askyesno(
            "Delete payroll record",
            f"Delete payroll for {record['first_name']} {record['last_name']} "
            f"({record['period_start']} to {record['period_end']})? "
            "This removes it from payroll history and report totals. You can process the period again afterward.",
            parent=self,
        ):
            return
        try:
            self._execute("DELETE FROM payroll WHERE payroll_id = ?", (payroll_id,))
        except sqlite3.Error as exc:
            messagebox.showerror("Could not delete payroll record", str(exc), parent=self)
            return
        self._refresh_payroll()
        self.status_var.set("Payroll record deleted; report totals will reflect the change.")

    def _process_payroll(self, period_start: str, period_end: str) -> None:
        if not self._require_roles(("admin",), "process payroll"):
            return
        try:
            start = date.fromisoformat(period_start.strip())
            end = date.fromisoformat(period_end.strip())
            if end < start:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid payroll period", "Select valid start and end dates. The end date cannot be before the start date.", parent=self)
            return
        if not is_full_calendar_month(start, end):
            messagebox.showerror(
                "Full month required",
                "Statutory contributions are calculated monthly. Select the first and last day of one calendar month.",
                parent=self,
            )
            return
        employees = self._fetchall(
            "SELECT employee_id, first_name, last_name, hourly_rate "
            "FROM employees WHERE status = 'active' ORDER BY last_name, first_name"
        )
        if not employees:
            messagebox.showinfo("No active employees", "Add an active employee before processing payroll.", parent=self)
            return
        overlapping_period = self._fetchone(
            "SELECT period_start, period_end FROM payroll "
            "WHERE period_start <= ? AND period_end >= ? LIMIT 1",
            (end.isoformat(), start.isoformat()),
        )
        if overlapping_period:
            messagebox.showerror(
                "Payroll period overlaps",
                "An existing payroll period "
                f"({overlapping_period['period_start']} to {overlapping_period['period_end']}) overlaps these dates. "
                "No duplicate payroll was created.",
                parent=self,
            )
            return

        preview: list[tuple[int, float, float, int, float, float, float, float, float, float, float, float]] = []
        skipped: list[str] = []
        for employee in employees:
            name = f"{employee['first_name']} {employee['last_name']}"
            hourly_rate = float(employee["hourly_rate"] or 0)
            if not isfinite(hourly_rate) or hourly_rate <= 0:
                skipped.append(f"{name} (hourly rate not configured)")
                continue
            hours = self._fetchone(
                "SELECT "
                "COALESCE(SUM(CASE WHEN COALESCE(hours_worked, 0) > COALESCE(overtime_hours, 0) "
                "THEN COALESCE(hours_worked, 0) - COALESCE(overtime_hours, 0) ELSE 0 END), 0) AS regular_hours, "
                "COALESCE(SUM(MIN(COALESCE(overtime_hours, 0), COALESCE(hours_worked, 0))), 0) AS overtime_hours, "
                "COALESCE(SUM(late_minutes), 0) AS late_minutes "
                "FROM attendance WHERE employee_id = ? AND date BETWEEN ? AND ?",
                (employee["employee_id"], start.isoformat(), end.isoformat()),
            )
            regular_hours = float(hours["regular_hours"] or 0)
            overtime_hours = float(hours["overtime_hours"] or 0)
            attendance_rows = self._fetchall(
                "SELECT date FROM attendance WHERE employee_id=? AND date BETWEEN ? AND ?",
                (employee["employee_id"], start.isoformat(), end.isoformat()),
            )
            attendance_dates = {str(row["date"]) for row in attendance_rows}
            approved_leave_rows = self._fetchall(
                "SELECT start_date,end_date FROM leave_records WHERE employee_id=? "
                "AND leave_type IN ('Paid leave','Travel order') AND status='Approved' "
                "AND start_date<=? AND end_date>=?",
                (employee["employee_id"], end.isoformat(), start.isoformat()),
            )
            paid_leave_hours = calculate_paid_leave_hours(
                [
                    (str(row["start_date"]), str(row["end_date"]))
                    for row in approved_leave_rows
                ],
                attendance_dates,
                start,
                end,
            )
            regular_hours += paid_leave_hours
            try:
                gross = round(
                    calculate_hourly_gross(hourly_rate, regular_hours, overtime_hours), 2
                )
            except ValueError:
                skipped.append(f"{name} (invalid hourly rate or attendance hours)")
                continue
            if gross <= 0:
                skipped.append(f"{name} (hourly rate or attendance missing)")
                continue
            late_minutes = int(hours["late_minutes"] or 0)
            tardiness_deduction = round(hourly_rate * late_minutes / 60, 2)
            statutory = calculate_philippine_deductions(
                regular_hours * hourly_rate,
                gross,
            )
            other_deduction = self._fetchone(
                "SELECT COALESCE(other,0) AS total "
                "FROM deductions WHERE employee_id = ? ORDER BY deduction_id DESC LIMIT 1",
                (employee["employee_id"],),
            )
            other_amount = float(other_deduction["total"]) if other_deduction else 0.0
            sss, philhealth, pagibig, tax = statutory
            deductions = round(sss + philhealth + pagibig + tax + other_amount, 2)
            if not isfinite(deductions) or not isfinite(other_amount) or other_amount < 0:
                skipped.append(f"{name} (invalid deduction values)")
                continue
            if deductions + tardiness_deduction > gross:
                skipped.append(f"{name} (deductions exceed gross pay)")
                continue
            preview.append((
                int(employee["employee_id"]),
                gross,
                paid_leave_hours,
                late_minutes,
                tardiness_deduction,
                sss,
                philhealth,
                pagibig,
                tax,
                other_amount,
                deductions,
                gross - deductions - tardiness_deduction,
            ))

        if not preview:
            details = "\n".join(skipped[:8]) or "No eligible employees found."
            messagebox.showwarning("Nothing to process", f"No payroll records can be generated.\n\n{details}", parent=self)
            return
        total_gross = sum(item[1] for item in preview)
        total_paid_leave_hours = sum(item[2] for item in preview)
        total_tardiness = sum(item[4] for item in preview)
        total_sss = sum(item[5] for item in preview)
        total_philhealth = sum(item[6] for item in preview)
        total_pagibig = sum(item[7] for item in preview)
        total_tax = sum(item[8] for item in preview)
        total_other = sum(item[9] for item in preview)
        total_net = sum(item[11] for item in preview)
        skipped_detail = f"\n\nSkipped {len(skipped)} employee(s): " + "; ".join(skipped[:4]) if skipped else ""
        confirmation = (
            f"Period: {start.isoformat()} to {end.isoformat()}\n"
            f"Employees included: {len(preview)}\n"
            f"Gross total: {self._money(total_gross)}\n"
            f"Paid leave / travel hours: {total_paid_leave_hours:.2f}\n"
            f"Late minutes: {sum(item[3] for item in preview)}\n"
            f"Tardiness deduction: {self._money(total_tardiness)}\n"
            f"SSS: {self._money(total_sss)}  •  PhilHealth: {self._money(total_philhealth)}\n"
            f"Pag-IBIG: {self._money(total_pagibig)}  •  Withholding tax: {self._money(total_tax)}\n"
            f"Optional other deductions: {self._money(total_other)}\n"
            f"Net total: {self._money(total_net)}"
            f"{skipped_detail}\n\nProcess this run?"
        )
        if not messagebox.askyesno("Review payroll", confirmation, parent=self):
            return
        connection = self.db_manager.get_connection()
        try:
            connection.executemany(
                "INSERT INTO payroll (employee_id,period_start,period_end,gross_pay,deductions,"
                "sss_deduction,philhealth_deduction,pagibig_deduction,tax_withheld,other_deductions,"
                "paid_leave_hours,tardiness_minutes,tardiness_deduction,net_pay) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        employee_id,
                        start.isoformat(),
                        end.isoformat(),
                        gross,
                        deductions,
                        sss,
                        philhealth,
                        pagibig,
                        tax,
                        other_amount,
                        paid_leave_hours,
                        late_minutes,
                        tardiness_deduction,
                        net,
                    )
                    for (
                        employee_id, gross, paid_leave_hours, late_minutes, tardiness_deduction,
                        sss, philhealth, pagibig, tax, other_amount, deductions, net,
                    ) in preview
                ],
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            messagebox.showerror("Payroll was not saved", str(exc), parent=self)
            return
        finally:
            connection.close()
        self._refresh_payroll()
        self.status_var.set(f"Processed payroll for {len(preview)} employee(s); skipped {len(skipped)}")
        messagebox.showinfo("Payroll processed", f"Created {len(preview)} payroll record(s).\nNet payroll total: {self._money(total_net)}", parent=self)

    def _open_deductions_form(self) -> None:
        if not self._require_roles(("admin",), "manage deductions"):
            return
        employees = self._fetchall(
            "SELECT employee_id, first_name, last_name FROM employees WHERE status = 'active' ORDER BY last_name, first_name"
        )
        if not employees:
            messagebox.showinfo("No active employees", "Add an active employee before configuring deductions.", parent=self)
            return
        options = {f"{row['last_name']}, {row['first_name']}  (#{row['employee_id']})": int(row["employee_id"]) for row in employees}
        dialog = tk.Toplevel(self)
        dialog.title("Optional other deductions")
        dialog.configure(bg=BACKGROUND_COLOR)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Optional other deductions", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            body,
            text="SSS, PhilHealth, Pag-IBIG, and withholding tax are calculated automatically. Set an optional recurring amount here for loans or other deductions.",
            style="Muted.TLabel",
            wraplength=460,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))
        employee_var = tk.StringVar(value=next(iter(options)))
        combo = ttk.Combobox(body, textvariable=employee_var, values=tuple(options), state="readonly", width=35)
        ttk.Label(body, text="Employee", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        combo.grid(row=2, column=1, sticky="ew", pady=5)
        other_var = tk.StringVar(value="0.00")
        ttk.Label(body, text="Other amount per month", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(body, textvariable=other_var, width=38).grid(row=3, column=1, sticky="ew", pady=5)

        def load_current(*_args: object) -> None:
            employee_id = options.get(employee_var.get())
            if employee_id is None:
                return
            current = self._fetchone(
                "SELECT other FROM deductions WHERE employee_id = ? ORDER BY deduction_id DESC LIMIT 1",
                (employee_id,),
            )
            other_var.set(f"{float(current['other'] or 0):.2f}" if current else "0.00")

        combo.bind("<<ComboboxSelected>>", load_current)
        load_current()
        body.columnconfigure(1, weight=1)

        def save() -> None:
            try:
                other_amount = float(other_var.get())
                if not isfinite(other_amount) or other_amount < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid deduction", "Enter a non-negative amount for other deductions.", parent=dialog)
                return
            employee_id = options[employee_var.get()]
            try:
                connection = self.db_manager.get_connection()
                try:
                    connection.execute("DELETE FROM deductions WHERE employee_id = ?", (employee_id,))
                    connection.execute(
                        "INSERT INTO deductions (employee_id,sss,philhealth,pagibig,tax,other) VALUES (?,?,?,?,?,?)",
                        (employee_id, 0, 0, 0, 0, other_amount),
                    )
                    connection.commit()
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                messagebox.showerror("Could not save deductions", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.status_var.set("Deduction defaults saved")

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(15, 0))
        ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=dialog.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Save other deduction", style="Primary.TButton", command=save).pack(side="left")
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 280}+{self.winfo_rooty() + 160}")

    def _build_reports(self) -> None:
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        toolbar = self._page_toolbar(page, "Reports & exports", "Review payroll totals for a date range and export the underlying records.")
        ttk.Button(toolbar, text="Export payroll CSV", style="Primary.TButton", command=self._export_payroll_csv).grid(row=0, column=1, rowspan=2, sticky="e")

        filter_panel = self._card(page, padding=16)
        filter_panel.pack(fill="x", pady=(0, 16))
        filter_card = filter_panel.content
        today = date.today()
        start_picker = DatePicker(filter_card, today.replace(day=1).isoformat(), width=18)
        end_picker = DatePicker(filter_card, today.isoformat(), width=18)
        ttk.Label(filter_card, text="From", style="Muted.TLabel").pack(side="left", padx=(0, 7))
        start_picker.pack(side="left")
        ttk.Label(filter_card, text="To", style="Muted.TLabel").pack(side="left", padx=(18, 7))
        end_picker.pack(side="left")
        ttk.Button(filter_card, text="Run report", style="Secondary.TButton", command=lambda: self._refresh_report(start_picker.get(), end_picker.get())).pack(side="left", padx=10)

        body = ttk.Frame(page)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        self.report_metrics = ttk.Frame(body)
        self.report_metrics.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.report_table_panel = self._card(body)
        self.report_table_panel.grid(row=1, column=0, sticky="nsew")
        self.report_table_host = self.report_table_panel.content
        self._refresh_report(start_picker.get(), end_picker.get())

    def _refresh_report(self, start_value: str, end_value: str) -> None:
        try:
            start = date.fromisoformat(start_value.strip())
            end = date.fromisoformat(end_value.strip())
            if end < start:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid report period", "Select valid start and end dates. The end date cannot be before the start date.", parent=self)
            return
        summary = self._fetchone(
            "SELECT COUNT(*) AS records, COUNT(DISTINCT employee_id) AS employees, "
            "COALESCE(SUM(gross_pay),0) AS gross, "
            "COALESCE(SUM(deductions + tardiness_deduction),0) AS deductions, "
            "COALESCE(SUM(tardiness_deduction),0) AS tardiness, "
            "COALESCE(SUM(tardiness_minutes),0) AS late_minutes, "
            "COALESCE(SUM(net_pay),0) AS net FROM payroll WHERE period_start >= ? AND period_end <= ?",
            (start.isoformat(), end.isoformat()),
        )
        for child in self.report_metrics.winfo_children():
            child.destroy()
        for column in range(4):
            self.report_metrics.columnconfigure(column, weight=1, uniform="report")
        cards = (
            ("Payroll records", str(summary["records"]), f"{summary['employees']} employees"),
            ("Gross payroll", self._money(summary["gross"]), "Before deductions"),
            (
                "All deductions",
                self._money(summary["deductions"]),
                f"Includes {summary['late_minutes']} late minutes",
            ),
            ("Net payroll", self._money(summary["net"]), "Take-home total"),
        )
        for column, (title, value, detail) in enumerate(cards):
            self._metric_card(self.report_metrics, column, title, value, detail, SUCCESS_COLOR if column == 3 else ACCENT_BLUE)

        for child in self.report_table_host.winfo_children():
            child.destroy()
        ttk.Label(
            self.report_table_host,
            text=f"Payroll detail  •  {start.isoformat()} to {end.isoformat()}",
            font=HEADING_FONT,
            background=WHITE,
            foreground=TEXT_COLOR,
        ).pack(anchor="w", pady=(0, 12))
        tree = self._make_tree(
            self.report_table_host,
            ("employee", "period", "gross", "leave_hours", "sss", "philhealth", "pagibig", "tax", "other", "tardiness", "net"),
            {"employee": "EMPLOYEE", "period": "PERIOD", "gross": "GROSS PAY", "leave_hours": "PAID LEAVE HRS", "sss": "SSS", "philhealth": "PHILHEALTH", "pagibig": "PAG-IBIG", "tax": "TAX", "other": "OTHER", "tardiness": "TARDINESS", "net": "NET PAY"},
            {"employee": 155, "period": 150, "gross": 100, "leave_hours": 100, "sss": 85, "philhealth": 100, "pagibig": 95, "tax": 85, "other": 90, "tardiness": 100, "net": 100},
        )
        rows = self._fetchall(
            "SELECT e.first_name,e.last_name,p.period_start,p.period_end,p.gross_pay,"
            "p.sss_deduction,p.philhealth_deduction,p.pagibig_deduction,p.tax_withheld,"
            "p.other_deductions,p.paid_leave_hours,p.tardiness_minutes,p.tardiness_deduction,p.net_pay "
            "FROM payroll p JOIN employees e ON e.employee_id=p.employee_id "
            "WHERE p.period_start >= ? AND p.period_end <= ? ORDER BY p.period_end,e.last_name,e.first_name",
            (start.isoformat(), end.isoformat()),
        )
        for row in rows:
            tree.insert("", "end", values=(
                f"{row['first_name']} {row['last_name']}",
                f"{row['period_start']} – {row['period_end']}",
                self._money(row["gross_pay"]), f"{float(row['paid_leave_hours'] or 0):.2f}",
                self._money(row["sss_deduction"]),
                self._money(row["philhealth_deduction"]), self._money(row["pagibig_deduction"]),
                self._money(row["tax_withheld"]), self._money(row["other_deductions"]),
                self._money(row["tardiness_deduction"]),
                self._money(row["net_pay"]),
            ))
        if not rows:
            self._empty_state(self.report_table_host, "No payroll records found for this date range.")
        self.report_period = (start.isoformat(), end.isoformat())
        self.status_var.set(f"Report: {len(rows)} payroll record(s) from {start.isoformat()} to {end.isoformat()}")

    def _export_payroll_csv(self) -> None:
        if not self._role_allows("Reports"):
            messagebox.showerror(
                "Access denied",
                "Your account does not have permission to export payroll reports.",
                parent=self,
            )
            return
        period = getattr(self, "report_period", None)
        if period is None:
            messagebox.showinfo("Run a report first", "Set a date range and run the report before exporting.", parent=self)
            return
        rows = self._fetchall(
            "SELECT e.employee_id,e.first_name,e.middle_name,e.last_name,p.period_start,p.period_end,"
            "p.gross_pay,p.sss_deduction,p.philhealth_deduction,p.pagibig_deduction,p.tax_withheld,"
            "p.other_deductions,p.paid_leave_hours,p.tardiness_minutes,p.tardiness_deduction,"
            "p.deductions,p.net_pay,p.generated_at FROM payroll p "
            "JOIN employees e ON e.employee_id=p.employee_id "
            "WHERE p.period_start >= ? AND p.period_end <= ? ORDER BY p.period_end,e.last_name,e.first_name",
            period,
        )
        if not rows:
            messagebox.showinfo("Nothing to export", "There are no payroll records in this report range.", parent=self)
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export payroll report",
            defaultextension=".csv",
            initialfile=f"payroll-{period[0]}-to-{period[1]}.csv",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not filename:
            return
        output = Path(filename)
        try:
            with output.open("w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(("Employee ID", "First name", "Middle name", "Last name", "Period start", "Period end", "Gross pay", "SSS", "PhilHealth", "Pag-IBIG", "Withholding tax", "Other deductions", "Paid leave and travel hours", "Tardiness minutes", "Tardiness deduction", "Total statutory and other deductions", "Net pay", "Generated at"))
                for row in rows:
                    writer.writerow(tuple(row))
        except OSError as exc:
            messagebox.showerror("Export failed", f"Could not write the report:\n{exc}", parent=self)
            return
        self.status_var.set(f"Exported {len(rows)} payroll record(s) to {output.name}")
        messagebox.showinfo("Export complete", f"Saved {len(rows)} payroll record(s) to:\n{output}", parent=self)

    def _build_settings(self) -> None:
        if not self._require_roles(("admin",), "change organization settings"):
            return
        page = ttk.Frame(self.page_host)
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        self._page_toolbar(page, "Organization settings", "These preferences are saved locally and used throughout the workspace.")

        form_panel = self._card(page, padding=24)
        form_panel.pack(fill="x")
        form = form_panel.content
        ttk.Label(form, text="Branding & display", font=HEADING_FONT, background=WHITE, foreground=TEXT_COLOR).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(form, text="Organization name", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(18, 7), padx=(0, 20))
        organization_var = tk.StringVar(value=self.settings.get("organization_name", ""))
        ttk.Entry(form, textvariable=organization_var, width=48).grid(row=1, column=1, sticky="ew", pady=(18, 7))
        ttk.Label(form, text="Workspace tagline", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=7, padx=(0, 20))
        tagline_var = tk.StringVar(value=self.settings.get("organization_tagline", ""))
        ttk.Entry(form, textvariable=tagline_var, width=48).grid(row=2, column=1, sticky="ew", pady=7)
        ttk.Label(form, text="Currency symbol", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=7, padx=(0, 20))
        currency_var = tk.StringVar(value=self.settings.get("currency_symbol", "₱"))
        ttk.Combobox(form, textvariable=currency_var, values=("₱", "$", "€", "£", "¥"), state="readonly", width=45).grid(row=3, column=1, sticky="ew", pady=7)
        ttk.Label(
            form,
            text="Currency changes only the way amounts are displayed; it does not convert stored values.",
            style="CardMuted.TLabel",
        ).grid(row=4, column=1, sticky="w", pady=(4, 0))
        form.columnconfigure(1, weight=1)

        def save() -> None:
            values = {
                "organization_name": organization_var.get().strip(),
                "organization_tagline": tagline_var.get().strip(),
                "currency_symbol": currency_var.get().strip(),
            }
            if not values["organization_name"] or not values["organization_tagline"] or not values["currency_symbol"]:
                messagebox.showerror("Missing settings", "Enter an organization name, tagline, and currency symbol.", parent=self)
                return
            connection = self.db_manager.get_connection()
            try:
                connection.executemany(
                    "INSERT INTO app_settings (setting_key,setting_value) VALUES (?,?) "
                    "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
                    tuple(values.items()),
                )
                connection.commit()
            except sqlite3.Error as exc:
                connection.rollback()
                messagebox.showerror("Settings were not saved", str(exc), parent=self)
                return
            finally:
                connection.close()
            self.settings.update(values)
            self.brand_label.configure(text=values["organization_name"].upper())
            self.brand_subtitle.configure(text=values["organization_tagline"])
            self.status_var.set("Organization settings saved")
            messagebox.showinfo("Settings saved", "Your workspace preferences have been updated.", parent=self)

        buttons = ttk.Frame(form, style="CardContent.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(buttons, text="Save settings", style="Primary.TButton", command=save).pack(side="right")

        info_panel = self._card(page, padding=20)
        info_panel.pack(fill="x", pady=(16, 0))
        info = info_panel.content
        ttk.Label(info, text="Local data", font=HEADING_FONT, background=WHITE, foreground=TEXT_COLOR).pack(anchor="w")
        ttk.Label(info, text=f"Database file: {self.db_manager.db_path}", style="CardMuted.TLabel", wraplength=850).pack(anchor="w", pady=(8, 3))
        ttk.Label(info, text="Records remain in the local SQLite database on this computer.", style="CardMuted.TLabel").pack(anchor="w")


def main() -> None:
    """Launch the payroll application."""
    try:
        app = PayrollApp()
        app.mainloop()
    except (tk.TclError, sqlite3.Error, OSError) as exc:  # pragma: no cover - top-level UI guard
        messagebox.showerror("Application Error", str(exc))


if __name__ == "__main__":
    ensure_directories()
    main()
