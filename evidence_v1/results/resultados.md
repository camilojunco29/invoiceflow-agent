| Medida | Formula | Umbral | Casos ejecutados | Resultado (media ± desv.) | Cumple | Evidencia |
|---|---|---|---|---|---|---|
| M1 Exactitud de extraccion por campo | campos correctos / campos evaluados (5 por factura: proveedor, numero, fecha, monto, items) | >= 90% | 300 (5 semillas) | 97.80% ± 0.96% | SI | results/casos.csv; logs/tests/ (S01,S02,S03,S05,S06) |
| M2 Reduccion del tiempo de procesamiento | 1 - (t_agente + t_revision_humana_de_alertas) / t_manual, sobre el flujo mixto | >= 50% | 300 (5 semillas) | 89.32% ± 1.35% | SI | results/casos.csv; logs/tests/ (S14) |
| M3 Precision del registro automatico | 1 - registros erroneos / registros automaticos (erroneo: debia alertarse o con algun campo mal) | >= 98% | 1080 (5 semillas) | 99.78% ± 0.49% | SI | results/casos.csv; logs/tests/ (S01,S02,S03,S04,S05,S06,S07,S08,S09,S10,S11,S12,S13,S14) |
| M4 Tasa de automatizacion en facturas validas | facturas validas registradas automaticamente / facturas validas | >= 80% | 300 (5 semillas) | 87.67% ± 5.48% | SI | results/casos.csv; logs/tests/ (S01,S02,S03,S05,S06) |
| M5 Deteccion de duplicados | duplicados alertados con motivo 'duplicado' / duplicados | >= 95% | 120 (5 semillas) | 93.33% ± 6.32% | NO | results/casos.csv; logs/tests/ (S07,S08) |
| M6 Robustez ante entradas invalidas | entradas invalidas escaladas sin error interno / entradas invalidas | >= 100% | 120 (5 semillas) | 100.00% ± 0.00% | SI | results/casos.csv; logs/tests/ (S12,S13) |

| Escenario | Tipo | Docs | Exactitud campos | Registro auto | Accion esperada | Registros erroneos | ms/factura |
|---|---|---|---|---|---|---|---|
| S01 Factura valida sin ruido | normal | 60 | 100.0% | 100.0% | 100.0% | 0 | 0.366 |
| S02 Factura valida, ruido bajo (0.2%) | normal | 60 | 98.3% | 88.3% | 88.3% | 0 | 0.362 |
| S03 Factura valida, ruido medio (1%) | normal | 60 | 90.7% | 50.0% | 50.0% | 0 | 0.33 |
| S04 Factura valida, ruido alto (3%) | limite | 60 | 82.7% | 25.0% | 25.0% | 1 | 0.302 |
| S05 Factura de 1 solo item | limite | 60 | 100.0% | 100.0% | 100.0% | 0 | 0.33 |
| S06 Factura de 12 items | limite | 60 | 100.0% | 100.0% | 100.0% | 0 | 0.389 |
| S07 Duplicado: mismo numero de factura | excepcion | 60 | 99.0% | 0.0% | 100.0% | 0 | 0.301 |
| S08 Duplicado: otro numero, mismo contenido | excepcion | 60 | 96.7% | 0.0% | 100.0% | 0 | 0.309 |
| S09 Monto distinto al de la orden de compra | excepcion | 60 | 100.0% | 0.0% | 100.0% | 0 | 0.317 |
| S10 Orden de compra inexistente | excepcion | 60 | 100.0% | 0.0% | 100.0% | 0 | 0.304 |
| S11 Proveedor desconocido | excepcion | 60 | 80.0% | 0.0% | 100.0% | 0 | 0.279 |
| S12 FALLA: documento vacio (sensor sin dato) | falla | 60 | - | 0.0% | 100.0% | 0 | 0.037 |
| S13 FALLA: documento ilegible | falla | 60 | - | 0.0% | 100.0% | 0 | 0.042 |
| S14 Flujo mixto realista | mixto | 300 | 97.5% | 68.0% | 89.7% | 0 | 0.324 |
