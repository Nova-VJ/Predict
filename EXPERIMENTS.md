# Registro de experimentos

Cada experimento se anota ANTES de ver su resultado. Número de hipótesis probadas sobre
datos ya vistos: se cuenta para exigir más evidencia cuanto más se haya probado.

| # | Fecha registro | Datos | Hipótesis / regla | Criterio de éxito | Resultado |
|---|---|---|---|---|---|
| 1 | 2026-09-26 | 2018-2025 (visto) | V2 fundamentales mejora a Elo | log loss menor | Sí (ver README_V2) |
| 2 | 2026-09-26 | 2022-2025 (visto) | V2 + mercado a la apertura: CLV > 0 | CLV medio > 0 | +1,5 % (500 apuestas), ROI −4,9 %: pista, no prueba |
| 3 | 2026-09-26 13:50 Madrid | **2026, muestra ciega** OddsPapi: 9 ventanas de 2 días al azar (semilla 260926), 18 partidos por ventana elegidos por hash, sin mirar resultados | Modelo V2 congelado (fundamentales 2015-2025 + stack 2021-2025, sin reajustar). Decisión a T−3h: stack anclado en Pinnacle sin margen a T−3h, alineación = la del partido anterior. Apuesta 1 u si p × cuota − 1 > 2 % en la mejor de leovegas.es / bwin.es. Control: misma regla con p = Pinnacle T−3h sin margen | (a) CLV medio vs Pinnacle cierre sin margen > 0 con IC95 por remuestreo que excluya 0; (b) log loss del stack ≤ Pinnacle T−3h. ROI solo informativo | 161 partidos. (b) cumplido en la muestra (0,6839 vs 0,6857) pero IC [−0,0052; +0,0015] incluye 0: no concluyente. (a) no evaluable: solo 3 apuestas (margen de bwin.es 4,5 %, leovegas.es 12 %). Ver data/blind2026/blind2026_report.json |

Nota: la muestra de #3 (~160 partidos) es pequeña; un resultado positivo es preliminar, uno negativo con IC amplio no es concluyente. Se ampliará con el cupo de OddsPapi de los meses siguientes sin cambiar la regla.

Cambios de implementación en #3 hechos ANTES de ver resultados: historial de jugadores ampliado a 2024-2026 (con solo 2025-2026 las variables quedaban más comprimidas que en el entrenamiento); Elo recalculado con resultados de la API oficial (diferencia máx. 0,012 frente al Elo local). bet365.es y codere.es no tienen MLB en OddsPapi.

## Protocolo desde el 26/09/2026 14:40 (registrado antes de ejecutar el motor diario)

| Tramo | Años (partidos) | Años con cuotas | Uso |
|---|---|---|---|
| DEV | 2015–2023 | 2021–2023 | Probar ideas libremente |
| VALID | 2024 | 2024 | Solo ideas que mejoren DEV; se decide aquí qué entra |
| TEST | 2025 | ene–ago 2025 | Una sola evaluación final del modelo elegido |
| BLIND | 2026 | muestra OddsPapi | Confirmación ciega |

Motor: `backtest_engine.py`, reentrenamiento **diario** (cada día se entrena con todo lo anterior a ese día). Métrica principal frente al mercado: log loss vs consenso EE. UU. (apertura y cierre limpio); CLV vs cierre limpio. Una idea entra en VALID solo si mejora el log loss en DEV (2019–2023) sin empeorar ninguna temporada en más de 0,001.

| # | Idea (DEV) | Resultado DEV | ¿Pasa a VALID? | Resultado VALID |
|---|---|---|---|---|
| 4 | Referencia: V2 con reentrenamiento diario | Stack − mercado: +0,0005 apertura / +0,0006 cierre (peor que el mercado). Apostar al cierre: ROI +8,7 % (843) | — (referencia) | 2024: stack ≈ mercado; cierre ROI −14 % (47): el +8,7 % de DEV era un espejismo de 2021–2022 |
| 5 | Movimiento apertura→cierre en el stack de cierre | Empeora (+0,00006 DEV) | No | — |
| 6 | Ventaja de mano (platoon) vs abridor rival | −0,00005 DEV (ruido); pasa el criterio formal | Sí | 2024: empeora +0,0003 → descartada |
| 7 | Stack no lineal (gradient boosting) sobre apertura + variables | Mucho peor (+0,007 a +0,015): sobreajuste | No | — |
| 8 | Comparar precios sin modelo: casa cuya apertura supera el consenso de las demás en > 2 % | 1.910 apuestas, CLV +4,6 % (73 % positivas, estable 3 años), ROI +1,5 % (IC −3,7 % a +6,7 %) | **No evaluable**: sin hora de apertura, las aperturas de otras casas pueden ser posteriores (mirar al futuro). 67 % de las apuestas son DraftKings, que suele abrir antes | Requiere cuotas con hora (OddsPapi 2026) |

Conclusión provisional (26/09): con los datos históricos gratuitos, las variables deportivas adicionales no mejoran al mercado de EE. UU.; el mercado ya las incorpora. La señal más fuerte es de **precio y momento** (#8), justo lo que exige cuotas con hora para validarlo.
| 9 | (registrado 26/09 14:55, antes de descargar) **Comparar precios con hora real, 2026.** Partidos de la muestra ciega #3 (mismo orden), casas DraftKings, FanDuel y Circa Sports vía OddsPapi. En cada actualización de precio de una casa antes del inicio: precio justo = mediana sin margen de las OTRAS dos casas, usando solo cuotas activas publicadas en los 60 min anteriores a ese instante. Se apuesta 1 u la primera vez que precio × p_justa − 1 > 2 % (una por partido). CLV frente a Pinnacle al cierre sin margen (fuente independiente, ya descargada en #3); ROI informativo. Criterio: CLV medio > 0 con IC95 que excluya 0. Se ejecuta con el cupo que quede este mes y se completa en octubre sin cambiar la regla | 162 partidos, 97 con las 3 casas (Circa falta en 64). **DraftKings abre primero en el 87 % → confirma que #8 estaba contaminado: con hora real, 0 apuestas a DraftKings.** 15 apuestas (12 Circa, 3 FanDuel), CLV +1,7 % (IC +0,2 % a +3,2 %), 67 % positivas, ROI −15 % (ruido con 15). Cumple el criterio formal, pero con 15 apuestas es **preliminar** | Ampliar muestra | |

Aclaración de #9 antes de ejecutar (14:58): OddsPapi guarda solo los cambios de precio, así que una cuota estable no se vuelve a publicar. "Cuota de las otras casas" = la última cuota activa publicada en o antes del instante t (vigente en t); se exige que ambas existan. Ventana de decisión: las 24 h anteriores al inicio.

Observación (no es experimento) 26/09: Betfair Exchange global (OddsPapi `betfair-ex`, exige 1 petición por lado) en NYM-AZ 09/04: T−3h 1,60 / 2,62 (margen 0,7 % antes de comisión; con 5 % de comisión sobre ganancias ≈ 3,1 %), liquidez disponible 8 € y 73 € a T−3h, 109 € y 248 € al cierre. Ojo: el exchange de Betfair.es está segregado (solo liquidez española); estos precios globales no son los accesibles desde España. `betfair.es` en OddsPapi es la casa de apuestas, no el exchange.

## Mercado objetivo: EE. UU. (decisión del usuario, 26/09 15:16)

| # | Idea | Criterio | Resultado |
|---|---|---|---|
| 10 | (registrado 15:20, antes de calcular) **Modelo V2 congelado en el mercado de EE. UU., 2026.** Partidos de #3/#9 con DraftKings y FanDuel. A T−3h: ancla = media sin margen de DraftKings y FanDuel (y Circa si existe) vigentes en ese instante; p = stack(ancla, p_fund con alineación anterior) con los coeficientes congelados; se apuesta 1 u al mejor precio entre DraftKings, FanDuel y Circa si p × precio − 1 > 2 %. Control: misma regla con p = ancla (solo comparar precios a T−3h). CLV frente a Pinnacle al cierre sin margen. Muestra ampliable con nuevas ventanas aleatorias (semilla 261001) sin cambiar la regla | CLV medio > 0, IC95 excluye 0 | **No cumple.** 318 partidos (160 + 158 nuevos, 171 peticiones). Log loss: modelo 0,6954, Pinnacle cierre 0,6928, EE. UU. a T−3h 0,6932, stack 0,6930. 11 apuestas, CLV −0,3 % (IC −2,8 % a +1,5 %). El "empate con Pinnacle" de la primera muestra era suerte: en la segunda el modelo va peor que el mercado. Control: 0 apuestas (las casas grandes de EE. UU. nunca se separan > 2 % del consenso a T−3h) |
| 11 | (registrado 15:58, antes de calcular) **Casa blanda que llega tarde a Pinnacle.** Muestra nueva de #10 (160 partidos con series de Pinnacle, DraftKings, FanDuel). En cada cambio de precio en las 24 h previas: si precio de DraftKings o FanDuel × p Pinnacle sin margen vigente − 1 > 2 %, se apuesta 1 u (primera vez por partido). CLV frente a Pinnacle al cierre | CLV medio > 0, IC95 excluye 0 | **Cumple (preliminar).** 159 partidos → 26 apuestas (16 %; 18 DraftKings, 8 FanDuel), CLV +1,9 % (IC +0,75 % a +3,1 %), 73 % positivas, ROI +43 % (ruido). Mediana 5 h antes del inicio. **La ventana dura poco: mediana 2 min, p75 4 min** |
| 12 | (registrado 16:05, antes de calcular) **Latencia en #11.** Misma señal, pero el precio se toma el que esté vigente X minutos después de detectarla (X = 1, 2, 5, 10); si ya no da > 0 % se cuenta como apuesta perdida por llegar tarde (no se apuesta) | Qué CLV sobrevive con cada retraso | 0 min: 26 apuestas, CLV +1,9 %. 1 min: 21 (5 perdidas), +1,3 %. 2 min: 17, +1,4 %. 5 min: 13, +1,4 %. 10 min: 12, +1,2 %. **Con 5 min de retraso se pierde la mitad de las oportunidades, pero las que quedan mantienen CLV > 1 %** |
| 13 | (registrado 26/09 16:00, antes de calcular) **Método para quitar el margen.** Cierres limpios del archivo SBR, 6 casas de EE. UU. Métodos: proporcional (actual), aditivo, power, Shin, odds-ratio. Métrica: log loss medio por casa y del consenso. Elección en DEV (2021–2023); confirmación en VALID (2024) | El método elegido en DEV también es el mejor o empata en 2024 | **Proporcional gana** en DEV (consenso 0,67176 vs 0,67187–0,67196) y en 2024 (0,67420 vs 0,67421–0,67426). Power/Shin solo empatan en favoritos claros de 2024. Se mantiene el proporcional |
| 14 | (registrado 16:05) **Simulador bateador a bateador v0.** Tasas por aparición al plate (K, BB+HBP, 1B, 2B, 3B, HR, out en juego) de cada bateador titular, del abridor y del bullpen, con decaimiento y regresión a la liga, solo con datos anteriores; enfrentamiento por log5; 1.000 simulaciones por partido; el abridor lanza hasta sus outs esperados. Se evalúa p(ganar) del simulador y combinado con V2 en DEV 2019–2023 | log loss del simulador ≤ V2, o la combinación mejora a V2 en DEV sin empeorar ninguna temporada > 0,001 | **No cumple en ganador del partido.** DEV: V2 0,67184, simulador calibrado 0,67505, combinación 0,67201. El v0 no incluye Elo/fuerza de equipo, defensa, estadio ni ventaja de local, y su base running es simple (carreras simuladas algo bajas). Se conserva como base para primeras 5 entradas, totales y ponches, donde se evaluará con cuotas de esos mercados |
