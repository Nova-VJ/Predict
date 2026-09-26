# Runbook de captura en vivo (sesión de Claude + navegador integrado)

Cada aviso programado indica una ventana: `T3H` (decisión) o `CLOSE` (cierre, para CLV).

1. Navegador integrado → pestaña ya abierta (fetch CORS a parlay-api.com, regiones `us,eu`) → fragmento (1) de `browser_capture.js`
   con la clave que dio el usuario en el chat. Guardar el CSV en
   `data/live/<fecha>/odds_parlay_<UTC>.csv` (2 créditos por toma).
2. Navegador → statsapi.mlb.com → recalcular variables (mismo fragmento que produjo
   `features_20260926T110121Z.csv`; en CLOSE usar alineaciones publicadas si ya están).
   Guardar `features_<UTC>.csv`.
3. Refrescar el calendario oficial si hace falta para Elo (resultados del día anterior).
4. `python pipeline/predict_live.py --features ... --odds ... --schedule ... --label T3H|CLOSE`
   → añade filas a `data/live/predictions.csv` (nunca se reescriben).
5. Solo las filas `T3H` con `paper_bet=True` son decisiones. `CLOSE` sirve para medir CLV:
   precio tomado / precio justo al cierre (Pinnacle sin margen, o consenso) − 1.
6. Guardar también la captura en formato común (`event_id,commence_utc,home,away,book,last_update,home_price,away_price`)
   y ejecutar `python pipeline/market_compare.py <csv>` → tablero comparativo con EE. UU. como referencia.
7. Al día siguiente: resultados oficiales → `data/live/results.csv` y resumen de CLV/ROI.

Si el ordenador del usuario está apagado o la app cerrada, la ventana se pierde: se anota
en `data/live/missed.csv` y no se reconstruye a posteriori.
