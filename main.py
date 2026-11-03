"""Read-only Modbus TCP register viewer for local testing.

This application intentionally restricts connections to IPv4 loopback addresses
(127.0.0.0/8). It is designed for a local Modbus simulator or service, not for
scanning remote industrial equipment.

Install the dependency with: python -m pip install pymodbus
Only Modbus Function Code 03 (Read Holding Registers) is issued.
"""

from __future__ import annotations

import ipaddress
import queue
import sqlite3
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from tkinter import messagebox, ttk
from typing import Any

from pymodbus.client import ModbusTcpClient


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_START_ADDRESS = 3000
DEFAULT_REGISTER_COUNT = 20
MAX_REGISTER_COUNT = 120
POLL_INTERVAL_MS = 800
SOCKET_TIMEOUT_SECONDS = 1.0
DATABASE_PATH = "modbus_scan_history.db"

BACKGROUND = "#171a21"
PANEL = "#222733"
FOREGROUND = "#e7eaf0"
MUTED = "#aab2c0"
ACCENT = "#58a6ff"
ERROR = "#ff7b72"
SUCCESS = "#3fb950"


class ModbusRegisterScanner:
    """Tkinter GUI and read-only local Modbus polling controller."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Modbus TCP Register Viewer — Local Only")
        self.root.geometry("760x590")
        self.root.minsize(650, 460)
        self.root.configure(bg=BACKGROUND)

        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="modbus-poller")
        self.result_queue: queue.Queue[Future[Any]] = queue.Queue()
        self.active = False
        self.poll_in_flight = False
        self.closed = False

        self._configure_theme()
        self._build_gui()
        self._initialize_database()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_results)

    def _configure_theme(self) -> None:
        """Apply a consistent dark theme to Tkinter and ttk widgets."""
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            ".", background=BACKGROUND, foreground=FOREGROUND,
            fieldbackground=PANEL, bordercolor="#394150", font=("Segoe UI", 10),
        )
        style.configure("TFrame", background=BACKGROUND)
        style.configure("TLabelframe", background=BACKGROUND, foreground=FOREGROUND)
        style.configure("TLabelframe.Label", background=BACKGROUND, foreground=ACCENT,
                        font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=BACKGROUND, foreground=FOREGROUND)
        style.configure("TEntry", padding=5)
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", background=PANEL, foreground=FOREGROUND,
                        fieldbackground=PANEL, rowheight=25)
        style.configure("Treeview.Heading", background="#303847", foreground=FOREGROUND,
                        font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#264f78")],
                  foreground=[("selected", "#ffffff")])

    def _build_gui(self) -> None:
        """Create connection controls, scan controls, and register table."""
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Industrial Modbus TCP Register Viewer",
                  font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 3))
        ttk.Label(outer, text="Read-only • Local loopback connections only • Function Code 03",
                  foreground=MUTED).pack(anchor="w", pady=(0, 12))

        connection = ttk.LabelFrame(outer, text="Connection", padding=10)
        connection.pack(fill="x", pady=(0, 10))
        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.unit_var = tk.StringVar(value=str(DEFAULT_UNIT_ID))
        self._add_labeled_entry(connection, "Server IP", self.host_var, 0, 0, 22)
        self._add_labeled_entry(connection, "Port", self.port_var, 0, 1, 8)
        self._add_labeled_entry(connection, "Slave ID / Unit", self.unit_var, 0, 2, 8)

        scanner = ttk.LabelFrame(outer, text="Scanner Configuration", padding=10)
        scanner.pack(fill="x", pady=(0, 10))
        self.start_var = tk.StringVar(value=str(DEFAULT_START_ADDRESS))
        self.count_var = tk.StringVar(value=str(DEFAULT_REGISTER_COUNT))
        self._add_labeled_entry(scanner, "Start Register Address", self.start_var, 0, 0, 16)
        self._add_labeled_entry(scanner, f"Registers to Read (max {MAX_REGISTER_COUNT})",
                                self.count_var, 0, 1, 16)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 10))
        self.start_button = ttk.Button(controls, text="Start Polling", command=self._start_polling)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="Stop", command=self._stop_polling,
                                      state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.status_var = tk.StringVar(value="Idle. Connect to a local Modbus simulator.")
        self.status_label = ttk.Label(controls, textvariable=self.status_var, foreground=MUTED)
        self.status_label.pack(side="left", padx=(14, 0))

        table_frame = ttk.LabelFrame(outer, text="Register Memory Map", padding=8)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=("address", "raw", "scaled"),
                                  show="headings", height=12)
        self.table.heading("address", text="Register Address")
        self.table.heading("raw", text="Raw Integer")
        self.table.heading("scaled", text="Scaled Float (raw / 10.0)")
        self.table.column("address", width=180, anchor="center")
        self.table.column("raw", width=160, anchor="center")
        self.table.column("scaled", width=260, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Label(outer, text=f"Successful scans are recorded in {DATABASE_PATH}",
                  foreground=MUTED).pack(anchor="w", pady=(8, 0))
        ttk.Label(outer, text="A product of Kutswa Inc.™", foreground=MUTED,
                  font=("Segoe UI", 9, "italic")).pack(anchor="center", pady=(4, 0))

    @staticmethod
    def _add_labeled_entry(parent: ttk.Frame, label: str, variable: tk.StringVar,
                           row: int, column: int, width: int) -> None:
        """Add a labeled text entry to a grid layout."""
        cell = ttk.Frame(parent)
        cell.grid(row=row, column=column, sticky="w", padx=(0, 18))
        ttk.Label(cell, text=label).pack(anchor="w", pady=(0, 4))
        ttk.Entry(cell, textvariable=variable, width=width).pack(anchor="w")

    def _initialize_database(self) -> None:
        """Create the local history table if it does not already exist."""
        try:
            with sqlite3.connect(DATABASE_PATH, timeout=5) as connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS register_samples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_utc TEXT NOT NULL,
                        host TEXT NOT NULL,
                        port INTEGER NOT NULL,
                        unit_id INTEGER NOT NULL,
                        register_address INTEGER NOT NULL,
                        raw_value INTEGER NOT NULL,
                        scaled_value REAL NOT NULL
                    )
                """)
                connection.execute("""
                    CREATE INDEX IF NOT EXISTS idx_register_samples_time_address
                    ON register_samples (timestamp_utc, register_address)
                """)
        except sqlite3.Error as exc:
            messagebox.showerror("Database Error", f"Could not initialize {DATABASE_PATH}:\n{exc}",
                                 parent=self.root)

    def _read_settings(self) -> dict[str, int | str]:
        """Validate settings and enforce the local-only connection boundary."""
        host = self.host_var.get().strip()
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("Enter a valid IPv4 address in the 127.0.0.0/8 range.") from exc
        if address.version != 4 or not address.is_loopback:
            raise ValueError("For safety, this application only connects to IPv4 loopback "
                             "addresses (127.0.0.0/8).")
        try:
            port = int(self.port_var.get())
            unit_id = int(self.unit_var.get())
            start = int(self.start_var.get())
            count = int(self.count_var.get())
        except ValueError as exc:
            raise ValueError("Port, unit ID, address, and count must be integers.") from exc
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        if not 0 <= unit_id <= 255:
            raise ValueError("Slave ID / Unit must be between 0 and 255.")
        if not 0 <= start <= 65535:
            raise ValueError("Start register address must be between 0 and 65535.")
        if not 1 <= count <= MAX_REGISTER_COUNT:
            raise ValueError(f"Register count must be between 1 and {MAX_REGISTER_COUNT}.")
        if start + count - 1 > 65535:
            raise ValueError("The requested register range exceeds address 65535.")
        return {"host": str(address), "port": port, "unit_id": unit_id,
                "start": start, "count": count}

    def _start_polling(self) -> None:
        """Validate settings and begin the Tkinter-scheduled polling loop."""
        try:
            self._read_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
            return
        self.active = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._set_status("Polling local endpoint…", MUTED)
        self.root.after(0, self._poll_tick)

    def _stop_polling(self) -> None:
        """Stop scheduling new scans; an in-progress request may finish."""
        self.active = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._set_status("Polling stopped.", MUTED)

    def _poll_tick(self) -> None:
        """Submit one background poll and schedule the next tick with after()."""
        if self.closed or not self.active:
            return
        if not self.poll_in_flight:
            try:
                settings = self._read_settings()
            except ValueError as exc:
                self._stop_polling()
                messagebox.showerror("Invalid Settings", str(exc), parent=self.root)
                return
            self.poll_in_flight = True
            future = self.executor.submit(self._poll_and_log, settings)
            future.add_done_callback(self.result_queue.put)
        self.root.after(POLL_INTERVAL_MS, self._poll_tick)

    @staticmethod
    def _read_holding_registers(client: ModbusTcpClient, start: int,
                                count: int, unit_id: int) -> Any:
        """Issue FC03 only, supporting unit-ID keywords across pymodbus versions."""
        try:
            return client.read_holding_registers(address=start, count=count, device_id=unit_id)
        except TypeError as first_error:
            # Older pymodbus releases called this parameter slave or unit.
            for keyword in ("slave", "unit"):
                try:
                    return client.read_holding_registers(address=start, count=count,
                                                         **{keyword: unit_id})
                except TypeError:
                    continue
            raise first_error

    @classmethod
    def _poll_and_log(cls, settings: dict[str, int | str]) -> tuple[list[tuple[int, int, float]], str]:
        """Perform one FC03 poll and persist its successful values in SQLite."""
        host, port = str(settings["host"]), int(settings["port"])
        unit_id, start, count = (int(settings[key]) for key in ("unit_id", "start", "count"))
        client = ModbusTcpClient(host=host, port=port, timeout=SOCKET_TIMEOUT_SECONDS)
        try:
            if not client.connect():
                raise ConnectionError(f"Could not connect to {host}:{port}.")
            response = cls._read_holding_registers(client, start, count, unit_id)
            if response is None:
                raise ConnectionError("The Modbus server returned no response.")
            if response.isError():
                raise RuntimeError(f"Modbus exception response: {response}")
            registers = list(response.registers)
            if len(registers) != count:
                raise RuntimeError(f"Expected {count} registers but received {len(registers)}.")

            timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            samples = [(start + offset, int(raw), int(raw) / 10.0)
                       for offset, raw in enumerate(registers)]
            with sqlite3.connect(DATABASE_PATH, timeout=5) as connection:
                connection.executemany("""
                    INSERT INTO register_samples (
                        timestamp_utc, host, port, unit_id,
                        register_address, raw_value, scaled_value
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, [(timestamp, host, port, unit_id, address, raw, scaled)
                      for address, raw, scaled in samples])
            return samples, f"Last successful scan: {timestamp}"
        finally:
            client.close()

    def _drain_results(self) -> None:
        """Consume completed worker results on Tkinter's main thread."""
        if self.closed:
            return
        while True:
            try:
                future = self.result_queue.get_nowait()
            except queue.Empty:
                break
            self.poll_in_flight = False
            try:
                samples, status = future.result()
            except Exception as exc:
                self._set_status(f"Connection / scan error: {exc}", ERROR)
                continue
            self._render_samples(samples)
            self._set_status(status, SUCCESS)
        self.root.after(100, self._drain_results)

    def _render_samples(self, samples: list[tuple[int, int, float]]) -> None:
        """Replace the table with the latest successful scan."""
        for item in self.table.get_children():
            self.table.delete(item)
        for address, raw, scaled in samples:
            self.table.insert("", "end", values=(address, raw, f"{scaled:.1f}"))

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(foreground=color)

    def _on_close(self) -> None:
        """Stop scheduling work and close the window."""
        self.closed = True
        self.active = False
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main() -> None:
    """Application entry point."""
    root = tk.Tk()
    ModbusRegisterScanner(root)
    root.mainloop()


if __name__ == "__main__":
    main()
