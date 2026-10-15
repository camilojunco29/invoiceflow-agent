"""Registro (log) de ejecución en JSON Lines con marca de tiempo.

Cada línea es un evento de percepción, decisión o acción del agente. Este log
es la base de las pruebas de la Fase 3.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class RunLogger:
    def __init__(self, path: str | Path | None = None, run_id: str = "run") -> None:
        self.run_id = run_id
        self.records: list[dict] = []
        self._fh = None
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(p, "w", encoding="utf-8")

    def log(self, stage: str, doc_id: str, **data) -> None:
        rec = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "doc_id": doc_id,
            "stage": stage,
            **data,
        }
        self.records.append(rec)
        if self._fh:
            self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
