"""ERP simulado (SQLite en memoria) y notificador.

Representa los "servicios externos" del diseño InvoiceFlow: el ERP al que el
agente consulta órdenes de compra e historial (sensor lógico) y en el que
registra compras y programa pagos (actuador), y el sistema de correo/alertas.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


class ERP:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(
            """
            CREATE TABLE suppliers(name TEXT PRIMARY KEY, nit TEXT);
            CREATE TABLE purchase_orders(
                po TEXT PRIMARY KEY, supplier TEXT, total INTEGER, items TEXT);
            CREATE TABLE invoices(
                id INTEGER PRIMARY KEY AUTOINCREMENT, supplier TEXT, number TEXT,
                date TEXT, total INTEGER, po TEXT, origin TEXT);
            CREATE TABLE payments(
                id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER,
                amount INTEGER, due_date TEXT);
            """
        )

    # ---- carga del entorno (la usa el simulador) -------------------------
    def add_supplier(self, name: str, nit: str) -> None:
        self.db.execute("INSERT INTO suppliers VALUES (?, ?)", (name, nit))

    def add_purchase_order(self, po: str, supplier: str, total: int,
                           items: list[tuple[int, int]]) -> None:
        """items: lista de (cantidad, precio_unitario)."""
        self.db.execute(
            "INSERT INTO purchase_orders VALUES (?, ?, ?, ?)",
            (po, supplier, total, json.dumps(items)),
        )

    # ---- consultas (sensores lógicos del agente) -------------------------
    def suppliers(self) -> list[tuple[str, str]]:
        return list(self.db.execute("SELECT name, nit FROM suppliers"))

    def get_purchase_order(self, po: str) -> dict | None:
        row = self.db.execute(
            "SELECT po, supplier, total, items FROM purchase_orders WHERE po=?", (po,)
        ).fetchone()
        if row is None:
            return None
        return {"po": row[0], "supplier": row[1], "total": row[2],
                "items": [tuple(i) for i in json.loads(row[3])]}

    def history(self) -> list[dict]:
        rows = self.db.execute("SELECT supplier, number, date, total FROM invoices")
        return [{"supplier": r[0], "number": r[1], "date": r[2], "total": r[3]}
                for r in rows]

    # ---- acciones (actuadores del agente) --------------------------------
    def register_invoice(self, supplier: str, number: str, date: str, total: int,
                         po: str, origin: str = "agente") -> int:
        cur = self.db.execute(
            "INSERT INTO invoices(supplier, number, date, total, po, origin) "
            "VALUES (?,?,?,?,?,?)",
            (supplier, number, date, total, po, origin),
        )
        return int(cur.lastrowid)

    def schedule_payment(self, invoice_id: int, amount: int, due_date: str) -> int:
        cur = self.db.execute(
            "INSERT INTO payments(invoice_id, amount, due_date) VALUES (?,?,?)",
            (invoice_id, amount, due_date),
        )
        return int(cur.lastrowid)

    def count(self, table: str, where: str = "1=1") -> int:
        return int(self.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0])


@dataclass
class Notifier:
    """Simula el sistema de correo/notificaciones hacia el personal de CxP."""
    alerts: list[dict] = field(default_factory=list)

    def send_alert(self, doc_id: str, reason: str, detail: str) -> None:
        self.alerts.append({"doc_id": doc_id, "reason": reason, "detail": detail})
