"""Pruebas del agente contra las medidas de desempeño (Fase 3).

Uso:  python run_tests.py

Lee los umbrales de `thresholds.json` (fijados antes de ejecutar), corre cada
escenario con 5 semillas, guarda logs JSONL y CSV en `logs/` y `results/`, e
imprime la tabla de resultados.
"""
from __future__ import annotations

import csv
import difflib
import json
import random
import statistics as st
from pathlib import Path

from agent import InvoiceAgent
from erp import Notifier
from logger import RunLogger
from simulator import InvoiceSimulator

ROOT = Path(__file__).parent
CFG = json.loads((ROOT / "thresholds.json").read_text(encoding="utf-8"))
SEEDS = CFG["seeds"]
N_DOCS = CFG["docs_per_run"]
A = CFG["assumptions"]

# (id, nombre, tipo de caso, [(kind, ruido, n_items, peso)], docs por ejecución)
SCENARIOS = [
    ("S01", "Factura valida sin ruido", "normal", [("valid", 0.0, None, 1)], N_DOCS),
    ("S02", "Factura valida, ruido bajo (0.2%)", "normal", [("valid", 0.002, None, 1)], N_DOCS),
    ("S03", "Factura valida, ruido medio (1%)", "normal", [("valid", 0.01, None, 1)], N_DOCS),
    ("S04", "Factura valida, ruido alto (3%)", "limite", [("valid", 0.03, None, 1)], N_DOCS),
    ("S05", "Factura de 1 solo item", "limite", [("valid", 0.0, 1, 1)], N_DOCS),
    ("S06", "Factura de 12 items", "limite", [("valid", 0.0, 12, 1)], N_DOCS),
    ("S07", "Duplicado: mismo numero de factura", "excepcion", [("duplicate_number", 0.002, None, 1)], N_DOCS),
    ("S08", "Duplicado: otro numero, mismo contenido", "excepcion", [("duplicate_content", 0.002, None, 1)], N_DOCS),
    ("S09", "Monto distinto al de la orden de compra", "excepcion", [("amount_mismatch", 0.0, None, 1)], N_DOCS),
    ("S10", "Orden de compra inexistente", "excepcion", [("po_missing", 0.0, None, 1)], N_DOCS),
    ("S11", "Proveedor desconocido", "excepcion", [("unknown_supplier", 0.0, None, 1)], N_DOCS),
    ("S12", "FALLA: documento vacio (sensor sin dato)", "falla", [("empty", 0.0, None, 1)], N_DOCS),
    ("S13", "FALLA: documento ilegible", "falla", [("illegible", 0.0, None, 1)], N_DOCS),
    ("S14", "Flujo mixto realista", "mixto",
     [("valid", 0.002, None, 70), ("duplicate_number", 0.002, None, 6),
      ("duplicate_content", 0.002, None, 4), ("amount_mismatch", 0.002, None, 8),
      ("po_missing", 0.002, None, 6), ("valid", 0.03, None, 6)], CFG["mix_docs_per_run"]),
]
SC = {s[0]: s for s in SCENARIOS}

M1_SCEN = ["S01", "S02", "S03", "S05", "S06"]          # lectura en condiciones normales/limite
M3_SCEN = [s[0] for s in SCENARIOS]                     # todos los escenarios
M4_SCEN = M1_SCEN                                       # facturas validas y legibles
M5_SCEN = ["S07", "S08"]
M6_SCEN = ["S12", "S13"]
M2_SCEN = ["S14"]


def items_ok(percept, inv) -> bool:
    if len(percept.items) != len(inv.items):
        return False
    for (d, q, u, _), it in zip(percept.items, inv.items):
        if q != it.qty or u != it.unit:
            return False
        if difflib.SequenceMatcher(None, d.lower(), it.desc.lower()).ratio() < 0.85:
            return False
    return True


def field_hits(percept, inv) -> dict[str, bool]:
    return {
        "proveedor": percept.supplier == inv.supplier,
        "numero": percept.number == inv.number,
        "fecha": percept.date == inv.date,
        "monto": percept.total == inv.total,
        "items": items_ok(percept, inv),
    }


def run_all() -> list[dict]:
    rows: list[dict] = []
    for idx, (sid, name, tipo, mix, n) in enumerate(SCENARIOS):
        for seed in SEEDS:
            sim = InvoiceSimulator(seed=seed * 1000 + idx)
            logger = RunLogger(ROOT / "logs" / "tests" / f"{sid}_seed{seed}.jsonl",
                               run_id=f"{sid}-seed{seed}")
            agent = InvoiceAgent(sim.erp, Notifier(), logger)
            pick = random.Random(seed * 1000 + idx + 77)
            tm = random.Random(seed * 1000 + idx + 5000)
            weights = [m[3] for m in mix]
            for _ in range(n):
                kind, noise, n_items, _w = pick.choices(mix, weights=weights)[0]
                doc, truth = sim.generate(kind, noise, n_items)
                res = agent.step(doc)
                hits = field_hits(res.percept, truth.invoice) if truth.invoice else None
                registered = res.action == "REGISTRAR"
                wrong_reg = registered and (
                    truth.expected_action == "ALERTA" or (hits is not None and not all(hits.values())))
                rows.append({
                    "scenario": sid, "tipo": tipo, "seed": seed, "doc_id": doc.doc_id,
                    "kind": kind, "noise": noise,
                    "expected_action": truth.expected_action,
                    "expected_reason": truth.expected_reason or "",
                    "action": res.action, "reason": res.reason or "",
                    "fields_correct": sum(hits.values()) if hits else "",
                    "fields_total": len(hits) if hits else "",
                    "registered_wrong": int(wrong_reg),
                    "internal_error": int(res.error is not None),
                    "processing_s": round(res.processing_s, 6),
                    "manual_s": round(max(30.0, tm.gauss(A["manual_mean_s"], A["manual_sd_s"])), 2),
                    "review_s": round(max(15.0, tm.gauss(A["review_mean_s"], A["review_sd_s"])), 2),
                })
            logger.close()
    return rows


def ratio(num: float, den: float) -> float:
    return num / den if den else float("nan")


def per_run(rows, scen_ids, fn) -> list[float]:
    return [fn([r for r in rows if r["scenario"] in scen_ids and r["seed"] == s]) for s in SEEDS]


def m1(rs):
    rs = [r for r in rs if r["fields_total"] != ""]
    return ratio(sum(r["fields_correct"] for r in rs), sum(r["fields_total"] for r in rs))


def m2(rs):
    agent = sum(r["processing_s"] + (r["review_s"] if r["action"] == "ALERTA" else 0) for r in rs)
    return 1 - ratio(agent, sum(r["manual_s"] for r in rs))


def m3(rs):
    reg = [r for r in rs if r["action"] == "REGISTRAR"]
    return 1 - ratio(sum(r["registered_wrong"] for r in reg), len(reg))


def m4(rs):
    return ratio(sum(r["action"] == "REGISTRAR" for r in rs), len(rs))


def m5(rs):
    return ratio(sum(r["reason"] == "duplicado" for r in rs), len(rs))


def m6(rs):
    return ratio(sum(r["action"] == "ALERTA" and not r["internal_error"] for r in rs), len(rs))


MEASURES = [
    ("M1", m1, M1_SCEN, "campos correctos / campos evaluados (5 por factura: proveedor, numero, fecha, monto, items)"),
    ("M2", m2, M2_SCEN, "1 - (t_agente + t_revision_humana_de_alertas) / t_manual, sobre el flujo mixto"),
    ("M3", m3, M3_SCEN, "1 - registros erroneos / registros automaticos (erroneo: debia alertarse o con algun campo mal)"),
    ("M4", m4, M4_SCEN, "facturas validas registradas automaticamente / facturas validas"),
    ("M5", m5, M5_SCEN, "duplicados alertados con motivo 'duplicado' / duplicados"),
    ("M6", m6, M6_SCEN, "entradas invalidas escaladas sin error interno / entradas invalidas"),
]


def evaluate(rows: list[dict]) -> list[dict]:
    out = []
    for mid, fn, scen, formula in MEASURES:
        vals = per_run(rows, scen, fn)
        mean = st.mean(vals)
        sd = st.stdev(vals) if len(vals) > 1 else 0.0
        cfg = CFG["measures"][mid]
        ok = mean >= cfg["threshold"] - 1e-12
        n_docs = sum(1 for r in rows if r["scenario"] in scen)
        out.append({"id": mid, "name": cfg["name"], "formula": formula,
                    "threshold": cfg["threshold"], "scenarios": ",".join(scen),
                    "cases": n_docs, "mean": mean, "sd": sd, "ok": ok})
    return out


def scenario_table(rows) -> list[dict]:
    table = []
    for sid, name, tipo, *_ in SCENARIOS:
        rs = [r for r in rows if r["scenario"] == sid]
        with_fields = [r for r in rs if r["fields_total"] != ""]
        table.append({
            "scenario": sid, "name": name, "tipo": tipo, "docs": len(rs),
            "field_accuracy": round(ratio(sum(r["fields_correct"] for r in with_fields),
                                          sum(r["fields_total"] for r in with_fields)), 4)
            if with_fields else "",
            "auto_registered": round(ratio(sum(r["action"] == "REGISTRAR" for r in rs), len(rs)), 4),
            "expected_action_match": round(ratio(sum(r["action"] == r["expected_action"] for r in rs), len(rs)), 4),
            "wrong_registrations": sum(r["registered_wrong"] for r in rs),
            "mean_processing_ms": round(1000 * st.mean(r["processing_s"] for r in rs), 3),
        })
    return table


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    rows = run_all()
    res = evaluate(rows)
    scen = scenario_table(rows)
    write_csv(ROOT / "results" / "casos.csv", rows)
    write_csv(ROOT / "results" / "resumen_por_escenario.csv", scen)
    write_csv(ROOT / "results" / "resultados_medidas.csv", [
        {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in res])

    lines = ["| Medida | Formula | Umbral | Casos ejecutados | Resultado (media ± desv.) | Cumple | Evidencia |",
             "|---|---|---|---|---|---|---|"]
    for r in res:
        lines.append(
            f"| {r['id']} {r['name']} | {r['formula']} | >= {r['threshold']:.0%} | "
            f"{r['cases']} ({len(SEEDS)} semillas) | {r['mean']:.2%} ± {r['sd']:.2%} | "
            f"{'SI' if r['ok'] else 'NO'} | results/casos.csv; logs/tests/ ({r['scenarios']}) |")
    lines += ["", "| Escenario | Tipo | Docs | Exactitud campos | Registro auto | Accion esperada | Registros erroneos | ms/factura |",
              "|---|---|---|---|---|---|---|---|"]
    for s in scen:
        acc = f"{s['field_accuracy']:.1%}" if s["field_accuracy"] != "" else "-"
        lines.append(f"| {s['scenario']} {s['name']} | {s['tipo']} | {s['docs']} | {acc} | "
                     f"{s['auto_registered']:.1%} | {s['expected_action_match']:.1%} | "
                     f"{s['wrong_registrations']} | {s['mean_processing_ms']} |")
    md = "\n".join(lines)
    (ROOT / "results" / "resultados.md").write_text(md + "\n", encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
