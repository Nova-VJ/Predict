# Revisión de fuentes gratuitas — 26/09/2026

Objetivo: mejorar pronósticos **MLB moneyline** con información disponible antes de cada partido. Que un servicio responda sin clave no prueba que tenga un compromiso de disponibilidad o peticiones ilimitadas. Una biblioteca Python tampoco es una fuente independiente: hay que comprobar de dónde extrae los datos y guardar la hora de observación.

| Fuente | Qué aporta al proyecto | Condición actual | Decisión |
|---|---|---|---|
| MLB Stats API | Calendario, probables, plantillas, game logs, boxscores | Sin clave en las consultas probadas; no asumimos capacidad ilimitada garantizada | Fuente principal. Ya incorporada, con horas y caché. |
| ESPN endpoints de marcador/resumen | Segunda observación de probables y lesiones | Responden sin clave en la prueba; interfaz no documentada como contrato estable | Auditoría selectiva de contradicciones; no depende de ella el pronóstico. |
| Baseball Savant vía `pybaseball` | Statcast por lanzamiento; potencial de xwOBA, velocidad, calidad de contacto | Biblioteca que consulta Baseball Savant, no API nueva ni gratis ilimitado garantizado; la consulta grande se fragmenta en lotes | Siguiente piloto, almacenando datos diarios y usando solo fechas anteriores al juego. |
| `python-mlb-statsapi` | Objetos Python para MLB Stats API | Wrapper de la misma fuente ya conectada | No añade información; posponer migración. |
| API-Sports Baseball | Otra cobertura de juegos y cuotas por comprobar | 100 peticiones diarias gratis, registro y clave | No duplicar la fuente MLB/Parlay sin medir cobertura incremental de casas españolas. |
| The Odds API | Otra fuente de cuotas actuales | 500 créditos/mes gratis; histórico excluido de ese nivel | Puede complementar precios futuros, no resuelve el histórico T−3h. |
| Balldontlie MLB | Equipos, jugadores y juegos en nivel gratis | 5 peticiones/minuto; lesiones y estadísticas de jugadores requieren pago | Descartar para los factores que nos faltan. |
| SportsDataIO sandbox | Probar estructura del software | Nombres, resultados y estadísticas alterados en prueba gratuita | No usar para análisis o validación. |

## Prueba ESPN de hoy

`audit_espn_alerts.py` revisó solo los cinco abridores que la fuente principal marcó por lesión contradictoria o más de 14 días sin salida. Dos probables también constan como lesionados de 60 días en ESPN: Connelly Early (WSH) y Justin Verlander (DET). Los otros tres tienen descanso largo, sin lesión registrada en el resumen consultado; **ausencia en esa lista no demuestra que estén sanos**. Se conservaron URL, hora y dato de la revisión. Los identificadores ESPN y MLB no coinciden: se enlazaron juegos por fecha y equipos, y nombres con normalización de acentos.

El proceso no recomienda apuestas a partir de esos hallazgos. Mantener la exclusión de probables contradictorios hasta verificar un nuevo anuncio oficial; observar el resto sin convertir días de descanso en una penalización inventada.

## Siguiente experimento con rendimiento medible

El primer piloto ya descargó **272 lanzamientos distintos** del partido MLB `744932` del 01/06/2024, seleccionado por el menor `game_pk` de ese día. Están presentes los campos de lanzador, bateador, velocidad, giro, ángulo de salida y xwOBA estimado. `pilot_statcast.py`, el CSV y el informe con hash y URL permiten repetir esta comprobación. Es una prueba de estructura, no una mejora predictiva demostrada.

1. Ampliar el piloto de Statcast en bloques diarios de 2023–2025, con caché y cobertura registrada; verificar `game_pk`, fechas y tasa de faltantes. No iniciar una descarga masiva de varios años sin ese control.
2. Reconstruir, para cada partido, estadísticas de abridores y bateadores **solo hasta el día anterior**; entre los candidatos: velocidad reciente, tasa de ponches y bases por bolas, xwOBA permitido, calidad del contacto y producción reciente de la alineación. Las alineaciones futuras deben haber sido anunciadas antes de la hora de decisión.
3. Comparar variantes predefinidas con la probabilidad de mercado sin margen y medir Brier, log loss y calibración en una temporada posterior no usada para elegir variables. Conservar características solo si aportan señal estable; un marcador mejor no equivale por sí mismo a beneficio neto.
4. Evaluar retorno y CLV únicamente sobre cuotas T−3h guardadas con hora, casa y disponibilidad real para nuestra cuenta. Registrar predicción y regla antes del resultado.

**Fuentes de condiciones y datos:** [API-Sports Baseball](https://api-sports.io/sports/baseball), [The Odds API](https://the-odds-api.com/), [Balldontlie MLB](https://mlb.balldontlie.io/), [SportsDataIO prueba](https://sportsdata.io/developers), [pybaseball](https://github.com/jldbc/pybaseball), [documentación Statcast de Baseball Savant](https://baseballsavant.mlb.com/csv-docs), [wrapper Python de MLB](https://github.com/zero-sum-seattle/python-mlb-statsapi). La prueba ESPN empleó los endpoints de marcador y resumen provistos en la propuesta del usuario, observados directamente el 26/09/2026.
