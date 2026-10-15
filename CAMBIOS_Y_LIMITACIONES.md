# Cambios respecto al diseño, hallazgos de las pruebas y limitaciones

Material de base para la tabla de cambios del documento y para las secciones 9.6 (diferencias diseño vs. implementación), 9.7 (pruebas) y 9.8 (limitaciones).

## 1. Diferencias entre diseño e implementación

| Aspecto | Diseño | Implementación | Por qué |
|---|---|---|---|
| Sensor OCR | Motor OCR sobre PDF/imagen | Simulador que genera texto con errores tipo OCR | No hay facturas reales ni OCR desplegado; el simulador permite verdad de referencia y ruido controlado |
| ERP y correo | ERP corporativo por API/SQL, correo de la empresa | SQLite en memoria y notificador en memoria | No hay acceso a un ERP real |
| Aprendizaje (comp. 7) | Las correcciones humanas mejoran la exactitud del OCR | No implementado | Un agente reactivo basado en modelo no aprende por definición (incoherencia del diseño) y no hay OCR propio que reentrenar. Solo se aprende el formato de numeración del historial, que no es aprendizaje por retroalimentación |
| Dinamismo del ambiente | "Estático" | Debe leerse como **dinámico**: cada factura registrada modifica el historial con el que se evalúan las siguientes (lo que el propio diseño dice en episodicidad) | Corrección de una contradicción interna del diseño |
| Medida "300 facturas reales" | Muestra real | 300 facturas sintéticas (flujo mixto, 5 semillas × 60) | No hay facturas reales |
| Medidas de desempeño | 1 medida SMART (exactitud ≥ 90 % y −50 % de tiempo) | 6 medidas, M1–M6 | La medida original mezclaba dos objetivos y no cubría seguridad de las decisiones, duplicados ni robustez |
| Autonomía | "Integra de forma autónoma" | Igual, pero con regla R2b/R5 que escala ante baja confianza | Evitar registros con datos mal leídos |

## 2. Hallazgos de las pruebas (dos corridas)

La primera corrida (`evidence_v1/`) usó los umbrales ya fijados en `thresholds.json`. Resultado: **M5 no cumplió (93,3 % frente a 95 %)** y M3 cumplió con 99,78 %, con un registro erróneo en S04.

Causas encontradas y correcciones al agente (los umbrales no se tocaron):

1. **Truncamiento silencioso del número de factura.** Con la lectura `FV-315A` el agente extraía `FV-315` y registraba la factura con un número que no era el real. Corrección: los tokens (número, fecha, OC) deben consumirse completos; si queda un carácter ilegible, el campo se considera no leído. Además, el agente aprende del historial la cantidad de dígitos de la numeración (R2b) y escala los números con formato inusual.
2. **Duplicados que no se etiquetaban como tal.** La regla de duplicados corría después de exigir todos los campos, así que un duplicado con una línea perdida salía como `campos_faltantes`. Corrección: R1b detecta el duplicado solo con proveedor + número.

Resultado de la segunda corrida (`results/`): M1 97,8 %, M2 89,3 %, M3 100 %, M4 87,7 %, M5 95,0 %, M6 100 %. Todas cumplen, **pero M5 cumple exactamente en el umbral y con desviación de ±6,85 puntos entre semillas, así que no debe presentarse como holgada.**

Las correcciones se hicieron después de ver los resultados de la primera corrida; por eso se conserva `evidence_v1/` y se reportan ambas.

## 3. Limitaciones

- **Todo es sintético.** Las cifras miden el agente contra un simulador que yo mismo definí; no demuestran el desempeño con facturas reales ni con un OCR real. El ruido simulado (confusiones de caracteres, caracteres y líneas perdidas) es una aproximación.
- **M2 depende de supuestos** (180 s manual, 60 s de revisión por alerta) que no son mediciones. El resultado cambia si esos tiempos cambian.
- **M4 (automatización) es sensible al ruido:** 100 % sin ruido, 88 % con 0,2 %, 50 % con 1 % y 25 % con 3 %. Con ruido medio o alto el agente alerta mucho; es seguro, pero baja el beneficio.
- **M5:** los duplicados "con otro número y mismo contenido" no se reconocen si el ruido borró la fecha, el monto o la OC (6 de 60 casos en S08); igual se escalan a revisión humana, con motivo `campos_faltantes`.
- **Las tolerancias son estrictas por diseño:** el agente compara el monto contra la OC de forma exacta y no admite tolerancias; una diferencia de 1 peso se alerta.
- **Sin interfaz gráfica ni despliegue.** La evidencia de funcionamiento puede hacerse con `demo.py` + `run_tests.py` en video (opción B).

## 4. Trabajo futuro

Sustituir el simulador por un OCR real (Tesseract/PaddleOCR) y facturas reales o de un dataset público; mapear las correcciones del personal a una memoria de alias de proveedor para implementar el componente de aprendizaje; tolerancias configurables por proveedor; interfaz de revisión.
