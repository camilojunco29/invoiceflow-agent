"""InvoiceFlow-Agent: agente reactivo basado en modelo (Russell & Norvig).

Ciclo explícito percepción -> decisión -> acción en `InvoiceAgent.step`:

  perceive()  Percepción: lee el texto OCR y extrae/normaliza los campos.
  decide()    Decisión: actualiza/consulta el ESTADO INTERNO (historial por
              proveedor) y aplica reglas condición-acción.
  act()       Acción: registra la compra y programa el pago en el ERP, o
              envía una alerta a revisión humana.

El estado interno (`self.known_numbers`, `self.known_content`) es lo que lo
hace "basado en modelo": la percepción actual no basta para detectar un
duplicado, hay que combinarla con las facturas ya vistas.

Qué hace el código y qué hacen las herramientas externas:
  * Todo el razonamiento (extracción por regex, normalización de confusiones
    OCR, validaciones y reglas) es código propio de este archivo.
  * No se usa ningún LLM. El "OCR" es el simulador (`simulator.py`).
  * El ERP y el correo son servicios externos simulados (`erp.py`).
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from erp import ERP, Notifier
from logger import RunLogger

# Normalización de confusiones típicas de OCR en campos numéricos
CONF = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8", "Z": "2"})
N = "[0-9OoIlSBZ]"
NP = "[0-9OoIlSBZ.]"
RE_ITEM = re.compile(rf"^\s*({N}{{1,3}})\s*[xX]\s*(.+?)\s*@\s*({NP}+)\s*=\s*({NP}+)\s*$")
# (?!\w): el token debe consumirse completo; si queda un carácter ilegible
# pegado (p. ej. "FV-315A") NO se acepta una lectura truncada ("FV-315").
RE_NUMBER = re.compile(rf"([A-Za-z]{{2}})\s*-\s*({N}{{3,8}})(?!\w)")
RE_DATE = re.compile(rf"({N}{{4}})\s*-\s*({N}{{2}})\s*-\s*({N}{{2}})(?!\w)")
RE_PO = re.compile(rf"[O0]C\s*-\s*({N}{{4,6}})(?!\w)")
LABELS = ["proveedor", "nit", "factura no", "fecha", "oc", "total"]
LABEL_FIX = str.maketrans("01582", "oisbz")
REQUIRED = ("supplier_raw", "number", "date", "po", "total")


def _digits(s: str) -> str:
    return s.translate(CONF)


def _money(s: str) -> int | None:
    s = _digits(s).replace(".", "")
    return int(s) if s.isdigit() else None


@dataclass
class Percept:
    supplier_raw: str | None = None
    nit: str | None = None
    supplier: str | None = None        # proveedor reconocido en el ERP
    number: str | None = None
    date: str | None = None
    po: str | None = None
    total: int | None = None
    items: list[tuple[str, int, int, int]] = field(default_factory=list)  # (desc, qty, unit, subtotal)
    item_lines_failed: int = 0
    n_lines: int = 0

    def summary(self) -> dict:
        return {"supplier": self.supplier, "supplier_raw": self.supplier_raw,
                "number": self.number, "date": self.date, "po": self.po,
                "total": self.total, "n_items": len(self.items),
                "item_lines_failed": self.item_lines_failed}


@dataclass
class Decision:
    action: str                 # "REGISTRAR" | "ALERTA"
    reason: str | None
    detail: str = ""
    checks: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    doc_id: str
    percept: Percept
    action: str
    reason: str | None
    processing_s: float
    error: str | None = None


class InvoiceAgent:
    def __init__(self, erp: ERP, notifier: Notifier, logger: RunLogger,
                 payment_terms_days: int = 30) -> None:
        self.erp, self.notifier, self.log = erp, notifier, logger
        self.payment_terms_days = payment_terms_days
        # ---- estado interno (modelo del entorno) ----
        self.suppliers = erp.suppliers()
        self.known_numbers: dict[str, set[str]] = defaultdict(set)
        self.known_content: set[tuple[str, str, int]] = set()
        for h in erp.history():
            self._remember(h["supplier"], h["number"], h["date"], h["total"])
        # formato de numeración aprendido del historial (cantidad de dígitos)
        self.number_digit_lens = {len(h["number"].split("-", 1)[-1]) for h in erp.history()}

    def _remember(self, supplier: str, number: str, date: str, total: int) -> None:
        self.known_numbers[supplier].add(number)
        self.known_content.add((supplier, date, total))

    # ==================================================================
    # CICLO PERCEPCIÓN -> DECISIÓN -> ACCIÓN
    # ==================================================================
    def step(self, doc) -> StepResult:
        t0 = time.perf_counter()
        error = None
        percept = Percept()
        try:
            percept = self.perceive(doc)                       # percepción
            decision = self.decide(doc, percept)               # decisión
        except Exception as exc:                               # fallo interno -> escalar
            error = repr(exc)
            decision = Decision("ALERTA", "error_interno", error)
            self.log.log("decision", doc.doc_id, action="ALERTA",
                         reason="error_interno", detail=error)
        self.act(doc, percept, decision)                       # acción
        return StepResult(doc.doc_id, percept, decision.action, decision.reason,
                          time.perf_counter() - t0, error)

    # ------------------------------------------------------------------
    # 1) PERCEPCIÓN
    # ------------------------------------------------------------------
    @staticmethod
    def _label(raw: str) -> str | None:
        s = raw.strip().lower().translate(LABEL_FIX)
        m = difflib.get_close_matches(s, LABELS, n=1, cutoff=0.7)
        return m[0] if m else None

    def perceive(self, doc) -> Percept:
        p = Percept()
        for line in doc.raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            p.n_lines += 1
            if "@" in line or RE_ITEM.match(line):
                m = RE_ITEM.match(line)
                unit = _money(m.group(3)) if m else None
                sub = _money(m.group(4)) if m else None
                if m and unit is not None and sub is not None:
                    p.items.append((m.group(2).strip(), int(_digits(m.group(1))), unit, sub))
                else:
                    p.item_lines_failed += 1
                continue
            if ":" not in line:
                continue
            label, value = line.split(":", 1)
            key = self._label(label)
            value = value.strip()
            if key == "proveedor":
                p.supplier_raw = value or None
            elif key == "nit":
                p.nit = _digits(value) or None
            elif key == "factura no":
                m = RE_NUMBER.search(value)
                if m:
                    p.number = f"{m.group(1).upper()}-{_digits(m.group(2))}"
            elif key == "fecha":
                m = RE_DATE.search(value)
                if m:
                    try:
                        d = dt.date.fromisoformat("-".join(_digits(g) for g in m.groups()))
                        if 2000 <= d.year <= 2100:
                            p.date = d.isoformat()
                    except ValueError:
                        pass
            elif key == "oc":
                m = RE_PO.search(value)
                if m:
                    p.po = f"OC-{_digits(m.group(1))}"
            elif key == "total":
                p.total = _money(value)
        p.supplier = self._match_supplier(p.supplier_raw, p.nit)
        self.log.log("percepcion", doc.doc_id, source=doc.source,
                     raw_chars=len(doc.raw_text), campos=p.summary())
        return p

    def _match_supplier(self, raw: str | None, nit: str | None) -> str | None:
        names = [n for n, _ in self.suppliers]
        if raw:
            m = difflib.get_close_matches(raw, names, n=1, cutoff=0.8)
            if m:
                return m[0]
        if nit:
            for name, known_nit in self.suppliers:
                if known_nit == nit:
                    return name
        return None

    # ------------------------------------------------------------------
    # 2) DECISIÓN (reglas condición-acción sobre percepción + estado interno)
    # ------------------------------------------------------------------
    def decide(self, doc, p: Percept) -> Decision:
        checks: list[str] = []

        def alert(reason: str, detail: str = "") -> Decision:
            d = Decision("ALERTA", reason, detail, checks)
            self.log.log("decision", doc.doc_id, action=d.action, reason=reason,
                         detail=detail, reglas_evaluadas=checks)
            return d

        # R1: documento ilegible / sin dato del sensor
        checks.append("R1_legible")
        if not doc.raw_text.strip() or (p.n_lines and not any(
                getattr(p, f) for f in REQUIRED) and not p.items):
            return alert("ilegible", "sin campos reconocibles")
        # R1b: un duplicado se reconoce solo con proveedor + número, aunque
        # falten otros campos (información parcial)
        checks.append("R1b_duplicado_temprano")
        if p.supplier and p.number and p.number in self.known_numbers[p.supplier]:
            return alert("duplicado", f"número {p.number} ya registrado")
        # R2: campos obligatorios presentes
        checks.append("R2_campos_obligatorios")
        missing = [f for f in REQUIRED if getattr(p, f) in (None, "")] + (
            ["items"] if not p.items else [])
        if missing:
            return alert("campos_faltantes", ",".join(missing))
        # R2b: el número debe tener el formato observado en el historial
        checks.append("R2b_formato_numero")
        if (self.number_digit_lens
                and len(p.number.split("-", 1)[-1]) not in self.number_digit_lens):
            return alert("baja_confianza", f"formato de número inusual: {p.number}")
        # R3: proveedor reconocido en el ERP
        checks.append("R3_proveedor_conocido")
        if p.supplier is None:
            return alert("proveedor_desconocido", p.supplier_raw or "")
        # R4: duplicados (usa el estado interno / historial por proveedor)
        checks.append("R4_duplicado")
        if p.number in self.known_numbers[p.supplier]:
            return alert("duplicado", f"número {p.number} ya registrado")
        if (p.supplier, p.date, p.total) in self.known_content:
            return alert("duplicado", "mismo proveedor, fecha y monto ya registrados")
        # R5: consistencia interna (baja confianza de la lectura)
        checks.append("R5_consistencia_interna")
        if p.item_lines_failed:
            return alert("baja_confianza", f"{p.item_lines_failed} línea(s) de ítem ilegibles")
        if any(q * u != s for _, q, u, s in p.items):
            return alert("baja_confianza", "ítem con cantidad x precio != subtotal")
        if sum(s for *_, s in p.items) != p.total:
            return alert("baja_confianza", "suma de ítems != total")
        # R6: existencia de la orden de compra
        checks.append("R6_orden_de_compra")
        po = self.erp.get_purchase_order(p.po)
        if po is None:
            return alert("oc_no_encontrada", p.po)
        # R7: la factura coincide con la orden de compra
        checks.append("R7_coincide_con_oc")
        inv_items = sorted((q, u) for _, q, u, _ in p.items)
        if (po["supplier"] != p.supplier or po["total"] != p.total
                or sorted(po["items"]) != inv_items):
            return alert("discrepancia_oc", f"total factura {p.total} vs OC {po['total']}")
        d = Decision("REGISTRAR", None, "todas las reglas superadas", checks)
        self.log.log("decision", doc.doc_id, action=d.action, reason=None,
                     detail=d.detail, reglas_evaluadas=checks)
        return d

    # ------------------------------------------------------------------
    # 3) ACCIÓN (actuadores: ERP y notificaciones)
    # ------------------------------------------------------------------
    def act(self, doc, p: Percept, d: Decision) -> None:
        if d.action == "REGISTRAR":
            inv_id = self.erp.register_invoice(p.supplier, p.number, p.date, p.total, p.po)
            due = (dt.date.fromisoformat(p.date)
                   + dt.timedelta(days=self.payment_terms_days)).isoformat()
            pay_id = self.erp.schedule_payment(inv_id, p.total, due)
            self._remember(p.supplier, p.number, p.date, p.total)   # actualiza el modelo
            self.log.log("accion", doc.doc_id, accion="registrar_compra_y_programar_pago",
                         invoice_id=inv_id, payment_id=pay_id, monto=p.total, vence=due)
        else:
            self.notifier.send_alert(doc.doc_id, d.reason or "", d.detail)
            self.log.log("accion", doc.doc_id, accion="alerta_revision_humana",
                         motivo=d.reason, detalle=d.detail)
