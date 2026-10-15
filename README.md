# InvoiceFlow-Agent

Agente inteligente de procesamiento automático de facturas (Universidad Tecnológica de Bolívar — Inteligencia Artificial, Tarea 3).
Tipo de agente (Russell & Norvig): **agente reactivo basado en modelo**.

El agente recibe el texto que entregaría un OCR sobre una factura, extrae y normaliza los campos, los contrasta con las órdenes de compra del ERP y con su historial por proveedor, y decide: **registrar la compra y programar el pago**, o **alertar a revisión humana**.

## Ejecución (desde cero)

Requiere solo Python 3.10+ (probado con 3.13). No hay dependencias externas.

```bash
python demo.py                 # escenario típico + excepciones + falla esperada, con el ciclo del agente impreso
python demo.py --seed 7 --ruido 0.01
python run_tests.py            # corre las 14 escenarios x 5 semillas y genera la tabla de resultados
```

Salidas de `run_tests.py`:

- `results/resultados.md`: tabla de resultados por medida y por escenario.
- `results/resultados_medidas.csv`, `results/resumen_por_escenario.csv`.
- `results/casos.csv`: una fila por factura procesada (evidencia trazable).
- `logs/tests/<escenario>_seed<k>.jsonl`: log con marca de tiempo de cada percepción, decisión y acción.

## Estructura

| Archivo | Rol |
|---|---|
| `agent.py` | Agente. `InvoiceAgent.step()` implementa el ciclo **percepción** (`perceive`) → **decisión** (`decide`) → **acción** (`act`). |
| `simulator.py` | Entorno simulado: genera facturas con verdad de referencia y ruido OCR (estocástico, por semilla). |
| `erp.py` | ERP simulado en SQLite (proveedores, órdenes de compra, historial, pagos) y notificador de alertas. |
| `logger.py` | Log JSONL con marca de tiempo. |
| `run_tests.py` | Pruebas contra las medidas de desempeño. |
| `thresholds.json` | Umbrales y supuestos **fijados antes de ejecutar las pruebas**. |
| `evidence_v1/` | Resultados de la primera corrida (antes de las correcciones descritas en `CAMBIOS_Y_LIMITACIONES.md`). |

## Qué hace el código y qué hacen las herramientas externas

- **Todo el razonamiento es código propio** (`agent.py`): extracción por expresiones regulares, normalización de confusiones OCR (O↔0, l↔1, S↔5…), reglas R1–R7 y estado interno.
- **No se usa ningún LLM** ni modelo de ML. No hay prompt de sistema.
- El **OCR es simulado** (`simulator.py` produce texto con errores de lectura). El **ERP y el correo son simulados** (`erp.py`).

## Estado interno (lo que lo hace "basado en modelo")

`known_numbers` (números de factura por proveedor), `known_content` (proveedor + fecha + monto) y `number_digit_lens` (formato de numeración) se cargan del historial del ERP y se actualizan después de cada registro. La percepción actual no basta para detectar un duplicado; hace falta combinarla con este estado.

## Reglas de decisión (en orden)

R1 legible · R1b duplicado temprano (proveedor + número) · R2 campos obligatorios · R2b formato del número · R3 proveedor conocido · R4 duplicado (por contenido) · R5 consistencia interna (cantidad × precio, suma = total) · R6 orden de compra existe · R7 coincide con la OC. Si alguna falla → alerta a revisión humana con el motivo; si todas pasan → registrar y programar pago a 30 días.

## Los siete componentes IBM → código

| Componente | Dónde | Estado |
|---|---|---|
| Percepción y manejo de entradas | `InvoiceAgent.perceive`, `simulator.ocr_noise` | Implementado (OCR simulado) |
| Planificación y descomposición | `InvoiceAgent.step` + orden de reglas en `decide` | Implementado (secuencia fija) |
| Memoria | `known_numbers`, `known_content`, historial del ERP, `logger.py` | Implementado |
| Razonamiento y decisión | `InvoiceAgent.decide` (R1–R7) | Implementado |
| Tool calling y acción | `erp.py`, `Notifier`, `InvoiceAgent.act` | Implementado (herramientas simuladas) |
| Comunicación | `Notifier.send_alert`, log JSONL | Implementado (sin interfaz gráfica) |
| Aprendizaje y adaptación | — | **No implementado** (ver `CAMBIOS_Y_LIMITACIONES.md`) |

## Supuestos del modelo de tiempo (medida M2)

Fijados en `thresholds.json` antes de correr las pruebas: procesamiento manual ≈ 180 s por factura (σ = 30), revisión humana de una alerta ≈ 60 s (σ = 15). Son **supuestos simulados**, no mediciones reales; deben sustituirse por tiempos reales del área de cuentas por pagar.
