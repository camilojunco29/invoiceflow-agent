"""Demo del agente: ejecuta un escenario típico y uno de falla esperada.

Uso:
    python demo.py                  # típico + duplicado + falla (documento vacío)
    python demo.py --seed 7 --ruido 0.01

Muestra, para cada factura, el ciclo percepción -> decisión -> acción tal como
queda en el log (`logs/demo.jsonl`).
"""
from __future__ import annotations

import argparse
import json

from agent import InvoiceAgent
from erp import Notifier
from logger import RunLogger
from simulator import InvoiceSimulator


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ruido", type=float, default=0.002, help="nivel de ruido OCR (0 a 0.05)")
    args = ap.parse_args()

    sim = InvoiceSimulator(seed=args.seed)
    log = RunLogger("logs/demo.jsonl", run_id=f"demo-seed{args.seed}")
    notifier = Notifier()
    agent = InvoiceAgent(sim.erp, notifier, log)

    casos = [
        ("TIPICO: factura valida", "valid"),
        ("EXCEPCION: factura duplicada", "duplicate_number"),
        ("EXCEPCION: monto distinto a la orden de compra", "amount_mismatch"),
        ("FALLA ESPERADA: documento vacio (sensor sin dato)", "empty"),
    ]
    for titulo, kind in casos:
        doc, truth = sim.generate(kind, args.ruido)
        print("=" * 72)
        print(titulo)
        print("--- texto OCR recibido ---")
        print(doc.raw_text or "(vacio)")
        n0 = len(log.records)
        res = agent.step(doc)
        print("--- ciclo del agente ---")
        for rec in log.records[n0:]:
            extra = {k: v for k, v in rec.items() if k not in ("ts", "run_id", "doc_id", "stage")}
            print(f"[{rec['ts'][11:]}] {rec['stage']:<10} {json.dumps(extra, ensure_ascii=False)}")
        print(f"=> esperado: {truth.expected_action}  |  obtenido: {res.action}"
              f"{' (' + res.reason + ')' if res.reason else ''}")
    print("=" * 72)
    registradas = sim.erp.count("invoices", "origin = 'agente'")
    print(f"ERP: {registradas} compras registradas por el agente, "
          f"{sim.erp.count('payments')} pagos programados, "
          f"{len(notifier.alerts)} alertas a revision humana.")
    log.close()


if __name__ == "__main__":
    main()
