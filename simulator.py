"""Simulador del entorno de InvoiceFlow.

Genera facturas sintéticas con su verdad de referencia (ground truth) y las
convierte en la salida de un motor OCR ruidoso. El ambiente es estocástico:
el ruido depende de una semilla y de un nivel de ruido configurable.

Percepciones generadas (sección 5 del diseño):
  * Archivos de facturación  -> `Document` (identificador + texto OCR)
  * Texto y coordenadas      -> `Document.raw_text` (líneas con ruido OCR)
  * Estado de compras/ERP    -> `ERP` poblado con proveedores, OC e historial
"""
from __future__ import annotations

import copy
import datetime as dt
import random
import string
from dataclasses import dataclass

from erp import ERP

SUPPLIERS = [
    ("Distribuidora Andina SAS", "900123456-1"),
    ("Suministros del Caribe Ltda", "800234567-2"),
    ("Tecnoredes Colombia SAS", "901345678-3"),
    ("Papeleria Central SA", "860456789-4"),
    ("Ferreteria El Constructor", "890567890-5"),
    ("Insumos Medicos Bolivar", "900678901-6"),
    ("Logistica y Transporte Norte", "830789012-7"),
    ("Comercializadora Cartagena SAS", "901890123-8"),
]
UNKNOWN_SUPPLIERS = [
    ("Importaciones Zeta Group", "999111222-0"),
    ("Servicios Omega Express", "999333444-1"),
]
CATALOG = [
    ("Cable UTP categoria 6", 12500), ("Mouse optico USB", 18900),
    ("Teclado mecanico", 85000), ("Resma papel carta", 14200),
    ("Tinta impresora negra", 64000), ("Disco duro externo 1TB", 245000),
    ("Router inalambrico", 132000), ("Silla ergonomica", 398000),
    ("Monitor 24 pulgadas", 520000), ("Memoria USB 64GB", 27500),
    ("Cinta de empaque", 4800), ("Guantes de nitrilo caja", 31000),
]

# Confusiones típicas de OCR (carácter real -> carácter leído)
CONFUSIONS = {"0": "O", "O": "0", "1": "l", "l": "1", "I": "1",
              "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "Z": "2"}

KINDS = ["valid", "duplicate_number", "duplicate_content", "amount_mismatch",
         "po_missing", "unknown_supplier", "empty", "illegible"]


@dataclass
class Item:
    desc: str
    qty: int
    unit: int

    @property
    def subtotal(self) -> int:
        return self.qty * self.unit


@dataclass
class Invoice:
    supplier: str
    nit: str
    number: str
    date: str
    po: str
    items: list[Item]

    @property
    def total(self) -> int:
        return sum(i.subtotal for i in self.items)


@dataclass
class Truth:
    kind: str
    invoice: Invoice | None
    expected_action: str          # "REGISTRAR" | "ALERTA"
    expected_reason: str | None


@dataclass
class Document:
    doc_id: str
    raw_text: str
    source: str = "simulador-ocr"


def money(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def render(inv: Invoice) -> str:
    lines = [
        "FACTURA DE VENTA",
        f"Proveedor: {inv.supplier}",
        f"NIT: {inv.nit}",
        f"Factura No: {inv.number}",
        f"Fecha: {inv.date}",
        f"OC: {inv.po}",
    ]
    for it in inv.items:
        lines.append(f"{it.qty} x {it.desc} @ {money(it.unit)} = {money(it.subtotal)}")
    lines.append(f"TOTAL: {money(inv.total)}")
    return "\n".join(lines)


def ocr_noise(text: str, rate: float, rng: random.Random) -> str:
    """Simula errores de OCR: confusiones de caracteres, pérdidas y líneas perdidas."""
    if rate <= 0:
        return text
    out_lines = []
    for line in text.split("\n"):
        if rng.random() < min(0.5, rate * 3):      # línea perdida por completo
            continue
        chars = []
        for c in line:
            if c in CONFUSIONS and rng.random() < rate:
                chars.append(CONFUSIONS[c])
            elif rng.random() < rate * 0.3:
                if rng.random() < 0.5:
                    continue                          # carácter perdido
                chars.append(rng.choice(string.ascii_letters + string.digits))
            else:
                chars.append(c)
        out_lines.append("".join(chars))
    return "\n".join(out_lines)


class InvoiceSimulator:
    def __init__(self, seed: int, n_history: int = 15) -> None:
        self.rng = random.Random(seed)
        self.base_date = dt.date(2026, 10, 1)
        self._used_numbers: set[str] = set()
        self._po_counter = 1000
        self._doc_counter = 0
        self.erp = ERP()
        for name, nit in SUPPLIERS:
            self.erp.add_supplier(name, nit)
        self.history: list[Invoice] = []
        for _ in range(n_history):
            inv = self._make_invoice()
            self._add_po(inv)
            self.erp.register_invoice(inv.supplier, inv.number, inv.date,
                                      inv.total, inv.po, origin="historico")
            self.history.append(inv)

    # ---- construcción de facturas ---------------------------------------
    def _new_number(self) -> str:
        while True:
            n = f"FV-{self.rng.randint(1000, 9999)}"
            if n not in self._used_numbers:
                self._used_numbers.add(n)
                return n

    def _make_invoice(self, n_items: int | None = None,
                      supplier: tuple[str, str] | None = None) -> Invoice:
        name, nit = supplier or self.rng.choice(SUPPLIERS)
        k = n_items if n_items is not None else self.rng.randint(1, 6)
        products = self.rng.sample(CATALOG, k)
        items = [Item(d, self.rng.randint(1, 20), p) for d, p in products]
        self._po_counter += 1
        date = self.base_date - dt.timedelta(days=self.rng.randint(0, 60))
        return Invoice(name, nit, self._new_number(), date.isoformat(),
                       f"OC-{self._po_counter:05d}", items)

    def _add_po(self, inv: Invoice) -> None:
        self.erp.add_purchase_order(inv.po, inv.supplier, inv.total,
                                    [(i.qty, i.unit) for i in inv.items])

    # ---- generación de documentos ---------------------------------------
    def generate(self, kind: str, noise: float = 0.0,
                 n_items: int | None = None) -> tuple[Document, Truth]:
        self._doc_counter += 1
        doc_id = f"DOC-{self._doc_counter:04d}"
        inv: Invoice | None = None
        action, reason = "ALERTA", None

        if kind == "valid":
            inv = self._make_invoice(n_items)
            self._add_po(inv)
            action = "REGISTRAR"
        elif kind == "duplicate_number":
            inv = copy.deepcopy(self.rng.choice(self.history))
            reason = "duplicado"
        elif kind == "duplicate_content":
            inv = copy.deepcopy(self.rng.choice(self.history))
            inv.number = self._new_number()
            reason = "duplicado"
        elif kind == "amount_mismatch":
            inv = self._make_invoice(n_items)
            self._add_po(inv)                       # la OC conserva los valores originales
            inv.items[0].qty += self.rng.randint(1, 3)   # la factura cobra de más
            reason = "discrepancia_oc"
        elif kind == "po_missing":
            inv = self._make_invoice(n_items)       # no se crea la OC
            reason = "oc_no_encontrada"
        elif kind == "unknown_supplier":
            inv = self._make_invoice(n_items, supplier=self.rng.choice(UNKNOWN_SUPPLIERS))
            reason = "proveedor_desconocido"
        elif kind == "empty":
            return Document(doc_id, ""), Truth(kind, None, "ALERTA", "ilegible")
        elif kind == "illegible":
            junk = "\n".join(
                "".join(self.rng.choice(string.ascii_letters + string.digits + "#%&?~")
                        for _ in range(self.rng.randint(8, 30)))
                for _ in range(self.rng.randint(4, 9)))
            return Document(doc_id, junk), Truth(kind, None, "ALERTA", "ilegible")
        else:
            raise ValueError(f"tipo de documento desconocido: {kind}")

        text = ocr_noise(render(inv), noise, self.rng)
        return Document(doc_id, text), Truth(kind, inv, action, reason)
