# MLB Time Machine — dataset V1 (26 septiembre 2026)

Base de investigación para el mercado **ganador del partido (moneyline)**. Contiene resultados reales de Retrosheet de 2014–2025 (2014 es calentamiento), una captura oficial de la temporada MLB 2026, estadísticas de forma previas al día del juego, cuotas históricas archivadas desde abril de 2021 hasta el 16 de agosto de 2025 y **primeros pronósticos retrospectivos de 2023–2025**. No contiene ganancias ni prueba de rentabilidad.

## Archivos entregados

- `output/mlb_time_machine.sqlite`: tablas `games`, `pregame_features`, `archive_matches`, `odds_quotes`, `public_signals`, `source_files` y `model_predictions`; vistas `model_inputs`, `timestamped_quotes` y `verified_bet_quotes`.
- `output/quality_report.json`: cobertura y comprobaciones de unión.
- `output/join_issues.csv`: encuentros de cuotas excluidos por emparejamiento ambiguo o discordante.
- `output/model_report.json`: Brier, log loss y calibración de cada modelo por año, más intervalos pareados por día.
- `output/market_diagnostic.json`: comparación **descriptiva** frente a cuotas archivadas de apertura, en los mismos encuentros disponibles.
- `output/parlay_capture_report.json`: primera captura prospectiva de cuotas, cobertura y exclusiones.
- `output/mlb_signal_report.json`: estado observado de plantillas y conflictos entre listas de lesionados y abridores probables.
- `output/mlb_context_report.json`: cobertura de historial de abridores, carga de relevistas y alineaciones captadas antes del juego.
- `FUENTES_GRATUITAS_20260926.md`: comprobación de la propuesta de fuentes gratuitas y experimento siguiente; `capturas/espn_alert_audit_*.json` conserva la auditoría puntual de cinco abridores anómalos.
- `capturas/statcast_pilot_game_744932.csv` y `output/statcast_pilot_744932.json`: piloto de Baseball Savant de 272 lanzamientos del 01/06/2024, con URL, hash y comprobación de claves únicas; todavía no se emplea en el pronóstico.
- `output/edge_diagnostic.json`: contraste exploratorio entre el EV calculado por Elo y el retorno bruto hipotético con una casa fija; no es ROI ejecutable.
- `output/market_anchor_experiment.json`: prueba por temporadas de dos modelos que parten del consenso de mercado y añaden Elo y forma previa.
- `output/market_scan_early_diagnostic.json`: cálculo local de diferencias entre casas frente a una referencia sin margen, solo para auditar la captura temprana.
- `capturas/parlay_live/`: respuesta JSON completa de cuotas MLB, metadatos de la hora de solicitud y recepción, y CSV diario original del 25/09/2026. Ningún archivo contiene la clave.
- `capturas/mlb_rosters_40man_2026_asof_*.json` y `capturas/mlb_conflicting_pitcher_transactions_20260926.json`: fotografías originales de plantillas y transacciones para auditar lesiones y contradicciones.
- `capturas/mlb_schedule_2026_asof_*.json`: observación realizada el 26/09/2026 de calendario y abridores probables publicados en la API de MLB. Tiene 2.402 resultados terminados y 28 encuentros futuros al captar el archivo; 19 de los futuros tienen ambos abridores probables identificados. Un abridor probable observado **ahora** en un partido anterior no se usa como variable histórica.
- `capturas/mlb_context_*.json`: respuestas originales de estadísticas de cada abridor probable y boxscores oficiales anteriores, más el estado de las alineaciones futuras. Cada petición registra URL y horas de solicitud y recepción; los errores quedan visibles.
- Scripts `fetch_sources.py`, `collect_mlb_public.py`, `collect_mlb_rosters.py`, `import_mlb_rosters.py`, `collect_mlb_game_context.py`, `import_mlb_game_context.py`, `capture_lineups_at_decision.py`, `collect_parlay_live.py`, `import_parlay_live.py`, `capture_decision_windows.py`, `fetch_free_odds_pilot.py`, `build_dataset.py`, `evaluate_models.py`, `market_diagnostic.py`, `edge_diagnostic.py`, `market_anchor_experiment.py`, `market_scan.py`, `import_snapshot.py`, `add_public_signal.py` y `tests.py` para repetir y ampliar el trabajo. Los originales de Retrosheet y el archivo de cuotas descargado no vienen en el paquete; `fetch_sources.py` los recupera.
- `audit_espn_alerts.py`: comprueba solo abridores con lesión contradictoria o descanso largo frente a la información secundaria de ESPN; conserva discrepancias sin reemplazar la observación de MLB.
- `pilot_statcast.py`: descarga un único partido anterior preseleccionado para comprobar el esquema de Statcast sin iniciar una descarga masiva.

## Regla temporal

Las variables `pregame_features` se calculan exclusivamente con partidos en fechas **anteriores** a `cutoff_date_exclusive`. Los dos encuentros de una misma fecha no se ven entre sí, incluso si era un doble juego; este enfoque sacrifica información en el segundo partido para evitar filtraciones. `games` guarda resultados y **abridores reales ex post** para evaluación y conciliación; `model_inputs` omite deliberadamente los resultados y los abridores reales. No use `actual_*_starter_id`, puntos anotados, ni el resultado del mismo partido como entrada del modelo.

En 2024, por ejemplo:

```sql
SELECT game_id, game_date, home_team, away_team,
       home_win_pct_10, away_win_pct_10, home_rest_days, away_rest_days
FROM model_inputs
WHERE game_date BETWEEN '2024-06-01' AND '2024-06-07';
```

## Limitación decisiva de las cuotas

El archivo de cuotas proviene de una recopilación secundaria de SportsBookReview. `opening` significa apertura mostrada en ese archivo; `last_observed` es su última cotización archivada. **Ninguna fila incluye hora de observación verificable.** Por ello `observed_at_utc=NULL`, `availability=timestamp_unknown`, y la vista `verified_bet_quotes` está vacía. La última cotización no se presenta como cierre sharp/Pinnacle ni como CLV validado. El archivo tampoco incluye Pinnacle según las casas publicadas por el autor.

Se puede investigar calidad de datos, distribuciones y desarrollar un modelo de probabilidades con estas cuotas; **no** se puede atribuir un ROI ejecutable, un CLV riguroso ni un momento real de apuesta sin sustituir o completar el archivo con capturas verificables anteriores al inicio y su `observed_at_utc`. He fijado una hora de decisión de **3 horas antes** del comienzo para futuros estudios con capturas, admitiendo como máximo 30 minutos de antigüedad de captura y 1 hora desde la última actualización de la casa. La API histórica de The Odds API documenta capturas por instante, ofrece MLB desde junio de 2020 y requiere plan de pago para el histórico. El importador `import_snapshot.py` acepta su JSON ya descargado y rechaza cuotas tardías, obsoletas, de partidos ambiguos o incompletas. Entra como `timestamp_verified_pregame`, que todavía **no** verifica que la casa aceptara la apuesta para nosotros; `verified_bet_quotes` sigue vacío.

Las 25 entradas conflictivas del archivo de cuotas están aisladas en `join_issues.csv`. Los partidos sin oferta publicada no se inventan ni se rellenan.

## Fuentes gratuitas y captura prospectiva

La captura oficial de MLB del 26/09/2026 permite añadir los 2.402 partidos ya terminados a la base y conservar los abridores probables anunciados para los encuentros futuros **con hora de observación**. `collect_mlb_game_context.py` añade, sin créditos del proveedor de cuotas, los cinco últimos comienzos de cada probable, días de descanso, carga de lanzamientos de los relevistas durante los tres días previos y los IDs de la alineación cuando MLB la anuncie. `import_mlb_game_context.py` guarda esos rasgos en `observed_pitcher_form`, `observed_bullpen_workload`, `observed_lineups` y `latest_pregame_context`. La vista `decision_eligible_context` oculta el abridor cuando su condición pública actual contradice la previsión y señala descansos superiores a 14 días para revisión. No se imputa una alineación todavía vacía. Las estadísticas del mismo día de captura y los boxscores recibidos al comienzo o después del partido se excluyen. La ausencia de un abridor probable o de cobertura íntegra del bullpen queda como dato ausente, nunca como rendimiento cero.

En la primera observación se hicieron **117 peticiones gratuitas a MLB**, sin errores: 28 juegos, 44 historiales de abridores, 56 cargas de bullpen completas, 42 abridores probables sin conflicto de lista y cero alineaciones anunciadas. Dos abridores probables figuran simultáneamente como lesionados en la captura de plantilla; sus historiales no constituyen una confirmación de que vayan a jugar. La consulta posterior a la ventana T−3h podrá cambiar estos conteos; `output/mlb_context_report.json` muestra la última cobertura importada. Se reutilizan boxscores oficiales ya fechados en las actualizaciones para evitar repetir descargas.

Para actualizar fuentes gratuitas: `python collect_mlb_public.py --season 2026 --end-date AAAA-MM-DD`, luego `python collect_mlb_game_context.py raw/mlb_schedule_....json` y `python import_mlb_game_context.py raw/mlb_context_....json`. Los capturadores prospectivos en ejecución durante esta sesión intentan recopilar cuotas en T−3h y volver a consultar alineaciones próximas a la misma ventana. Dependen de que la máquina permanezca activa; el paquete no instala un servicio persistente ni promete disponibilidad continua.

`fetch_free_odds_pilot.py` deja preseleccionados por hash doce juegos (uno por mes de abril a septiembre de 2024 y 2025), sin escogerlos por resultado. **Una consulta de prueba devolvió HTTP 403:** la documentación actual limita los históricos del plan gratuito a **48 horas**, independientemente de los 1.000 créditos al mes. El script exige `--allow-deep-history` para impedir solicitudes retrospectivas infructuosas desde el plan gratuito. Los 2024–2025 no se han obtenido de esta API.

El 26/09/2026 entre las 08:38:06 y las 08:38:16 UTC sí se captó una cartelera **prospectiva**, mediante `collect_parlay_live.py --key-stdin`. `import_parlay_live.py` enlazó 13 partidos por equipos, inicio y `mlb_game_pk` con la observación del calendario oficial realizada once minutos antes. La tabla `observed_live_quotes` tiene **156 pares de cuotas moneyline**, de 14 casas, con actualización del mercado entre las 07:38:25 y 08:37:48 UTC; se rechazaron siete mercados incompletos. Los 26 ID de abridores probables del proveedor coincidieron con la captura oficial de esos 13 partidos. El precio está en formato decimal y la consulta se hizo por la mañana, **mucho antes de la decisión T−3h**: estas cuotas no se han introducido en `timestamped_quotes` ni usado para inferir ROI o CLV. Los encabezados de respuesta no comunicaron créditos gastados o restantes, por lo que no afirmamos un gasto verificado.

Una segunda consulta de `regions=eu` a las 09:02 UTC enlazó los mismos 13 juegos y añadió 46 pares de cuotas de PMU, Unibet, bet365 y Pinnacle. `observed_live_quotes` conserva el parámetro de región de ambas capturas, **202 pares en total**. La región europea tampoco prueba que la cotización exacta esté disponible en una cuenta española. El barrido local `market_scan.py --early-diagnostic` compara cada respuesta consigo misma: con actualización de mercado de como máximo 15 minutos, encontró cinco diferencias positivas frente a Pinnacle sin margen, hasta un 2,34 % indicativo. Son diferencias de pantalla matutinas, no pronósticos ni apuestas verificadas.

**Coste eficiente:** un GET `h2h` devuelve todos los partidos y casas de MLB de una región por 1 crédito documentado; nuestra programación consulta `us,eu` juntas por **2 créditos estimados por llamada**, unas **24 unidades** en los 12 horarios de los dos días. Se ejecutan los cálculos locales sin pagar por cada partido ni por el escáner `+EV` del proveedor. Los 1.000 créditos gratuitos al mes alcanzan para una programación moderada como esta, aunque hay que comprobar el gasto real en el panel: nuestras respuestas no trajeron encabezados de créditos. El histórico profundo continúa bloqueado por la ventana de 48 horas del plan gratis.

La exportación CSV del 25/09/2026 devolvió 50.000 filas de mercados diversos, entre ellas 425 etiquetadas `moneyline`; 6.837 filas carecen de `commence_time`. Algunas filas `moneyline` usan columnas `over_price`/`under_price`, con semántica de lado no demostrada. Se conserva el original, sin importarlo como ofertas de apuestas. El proveedor documenta que el CSV es un archivo diario de cierres, no una reconstrucción de nuestra hora T−3h. El acceso libre a esa exportación tampoco equivale a cobertura completa de todos los juegos o casas.

Para nuevas capturas desde un entorno con almacenamiento persistente, ejecutar `python collect_parlay_live.py --key-stdin` antes del inicio y volver a capturar alrededor de T−3h; guardar el JSON y su `.meta.json`, actualizar el calendario oficial y usar `import_parlay_live.py JSON META CALENDARIO`. La clave se pide sin eco o se pasa como variable de entorno y nunca se empaqueta. La reconstrucción completa de la base borra `observed_live_quotes`, así que antes de reconstruir se debe conservar la captura original y reimportarla.

Para los partidos del 26 y 27/09/2026 se preparó `capture_decision_windows.py`: agrupa los 28 encuentros restantes en **12 consultas previstas** a T−3h según el calendario observado el 26/09 a las 08:27 UTC. Se inició en este entorno con la clave solo en memoria, pero **las capturas futuras dependen de que el proceso y el entorno sigan activos**. La primera consulta está prevista para el 26/09 a las 13:35 UTC (15:35 en Madrid). Dos minutos antes de cada toma refrescará el calendario oficial y las plantillas de los equipos implicados; si alguna de esas fuentes falla, registrará el error y seguirá intentando capturar las cuotas. Cada respuesta `us,eu` se guardará con su hora y se enlazará por partido. La vista `decision_window_quotes` escogerá la **respuesta completa** más cercana a T−3h para cada partido dentro de ±15 minutos, manteniendo las casas sincronizadas; está vacía hasta recibirlas. En una máquina persistente se puede lanzar `python capture_decision_windows.py capturas/mlb_schedule_2026_asof_20260926T082711Z.json --key-stdin`; `--dry-run` muestra horas sin consultar la API. El calendario puede cambiar por aplazamientos: si ya no coincide la hora, el emparejamiento se rechaza y hay que generar otro calendario y programación.

El histórico BASIC gratuito de Betfair contiene último precio negociado por minuto, pero Betfair afirma que las cuentas `Betfair.es` no acceden a su web histórica, reservada a cuentas `Betfair.com` elegibles. La cuenta debe corresponder a la residencia real admitida por Betfair. Si en el futuro se obtiene legítimamente un archivo Betfair BASIC, podemos añadir un lector; ese último precio negociado tampoco equivale a una oferta ejecutable de compra.

## Lesiones, abridores y moral

`public_signals` empieza vacío a propósito. Solo debe poblarse con **información publicada** cuyo `published_at_utc` y `collected_at_utc` sean anteriores a `decision_at_utc`, y una URL verificable. Puede registrar lesión confirmada, estado de lista de lesionados, alineación anunciada, cambio de abridor, límite de lanzamientos conocido, declaraciones públicas del entrenador, viaje u otras noticias relevantes. La fecha de efecto retroactivo de una lista de lesionados no equivale a la fecha en que la noticia se hizo pública. Las alineaciones y abridores registrados **después** del juego tampoco sirven para reconstruir lo que se sabía antes.

Ya se captaron las plantillas oficiales **40Man** de los 30 equipos (26/09, alrededor de las 08:50 UTC): 1.364 jugadores únicos, 270 con estado de lista de lesionados. `observed_roster_status` enlaza las observaciones con los 28 juegos futuros; hay también una segunda captura de prueba de dos equipos realizada alrededor de las 08:58 UTC. `observed_probable_starters` conserva las versiones sucesivas de 44 anuncios de abridor para esos juegos. **Dos anuncios son contradictorios**: Connelly Early (WSH) y Justin Verlander (DET) aparecen a la vez como abridores probables y `Injured 60-Day`. La vista `nonconflicting_probable_starters` usa el último anuncio y el último estado observado por jugador, y excluye esos dos (42 registros) para que nadie los use como confirmados; las transacciones oficiales observadas para ambos se conservan como original. Se debe volver a verificar cerca del partido. Una fecha de transacción o un estado observado ahora no prueba cuándo se publicó originalmente ni la disponibilidad efectiva; la ausencia de un jugador del listado tampoco prueba que esté sano.

La “moral” no tiene un valor observado objetivo: conserve el texto de una declaración pública, su hora y una clasificación fijada **antes** de ver el resultado. Mantenga `impact_rating` vacío hasta definir un protocolo de puntuación estable y verificable. Reporte la cobertura: la ausencia de señal no significa que el jugador estuviera sano o el equipo animado. No solicite información médica o de vestuario confidencial.

CSV para `add_public_signal.py` (horas ISO 8601 UTC, estado `confirmed`, `credible_report` o `unconfirmed`):

```text
game_id,team,player_id,signal_type,source_url,published_at_utc,collected_at_utc,decision_at_utc,status,impact_note,impact_rating
```

El importador comprueba el equipo, la fecha, el orden temporal y, si existe, la hora archivada del inicio. La responsabilidad de contrastar que la URL efectivamente publicaba esa información a la hora declarada sigue siendo humana. Las señales de un medio sin archivo histórico verificable quedan fuera del backtest y se empiezan a capturar prospectivamente en 2026.

## Siguientes fases, en orden

1. Añadir capturas de cuotas con timestamp para evaluar un precio realmente disponible; no escoger retroactivamente la mejor casa si no estaba operativa en la fecha y jurisdicción estudiadas.
2. Reconstruir abridores **probables**, alineaciones y estado de lesiones con publicaciones fechadas; después calcular estadísticas de pitcher y bullpen solo con actuaciones previas. En ningún caso usar el abridor efectivo sin prueba de anuncio previo.
3. Ya se han evaluado referencia de victoria local histórica, Elo y regresión logística: 2015–2022 para el primer entrenamiento, 2023 para escoger parámetros de una rejilla corta, 2024 validación y 2025 comprobación final. Se reentrena la regresión con las temporadas anteriores a cada año predicho; Elo actualiza tras cada **día** y atenúa ratings en cada nueva temporada. Ningún modelo recibe cuotas, abridor efectivo, señales futuras ni resultados de la fecha predicha. Como todos los resultados están accesibles en la base, el examen es un **holdout por protocolo**, no un conjunto técnicamente sellado. En 2025 se usó la temporada entera para métricas deportivas; las cuotas disponibles llegan solo hasta agosto.
4. El consenso de apertura archivado (probabilidades desvigadas por casa y promedio) supera a nuestros modelos deportivos en la muestra comparable de 2024: Brier 0,241283 frente a 0,245124 de Elo. En 2025 parcial quedan cerca. Esta comparación es diagnóstica, ya que las horas de apertura no son verificables. **Todavía no hemos superado al mercado.** El próximo experimento debe incorporar abridores probables, bullpen e información pública con sus horas originales y verificar que mejora la prueba fuera de muestra.
5. Solo cuando las cotizaciones estén verificadas y disponibles para la jurisdicción/operador pertinente, evaluar apuestas a 1 unidad, ROI, CLV, drawdown y resultados por cuota/temporada. Registrar todas las predicciones antes de revelar sus resultados. No modificar parámetros usando el periodo final ya visto: esa muestra pasaría a ser exploratoria y haría falta una nueva prueba prospectiva.

## Primeros resultados deportivos

| Temporada | Partidos | Referencia local Brier | Elo Brier | Regresión Brier | Consenso archivado, muestra parcial Brier |
|---|---:|---:|---:|---:|---:|
| 2024 | 2.429 | 0,249682 | **0,245136** | 0,246508 | 0,241283 (2.382 partidos) |
| 2025 | 2.430 | 0,248274 | **0,244451** | 0,245674 | 0,242877 (1.688 partidos hasta agosto) |

**No compare directamente columnas calculadas sobre distinta muestra.** `market_diagnostic.json` vuelve a calcular los tres modelos sobre exactamente los encuentros con cuotas. Un Brier menor es mejor. Estos números no implican apuesta rentable; incluso el modelo Elo queda por detrás del consenso archivado de 2024. La prueba del 2025 ya ha sido consultada, por lo que cualquier cambio inspirado por ella necesita otro periodo futuro sin mirar.

### ¿Qué dice la prueba de retorno?

`edge_diagnostic.py` aplica una regla fija y transparente sobre **una sola casa archivada, FanDuel**: una apuesta plana a la cara con mayor `p_elo × cuota_decimal − 1`, solo cuando esa cantidad es positiva. No busca a posteriori la mejor cuota. El archivo no tiene la hora de apertura ni prueba de que la oferta fuera aceptable desde España; por ello las cifras son **retornos brutos hipotéticos**, no ROI ejecutable:

| Muestra | Selecciones | EV medio previsto por Elo | Retorno bruto hipotético | Intervalo 95 % por remuestreo de días |
|---|---:|---:|---:|---:|
| 2024 | 1.741 | +8,88 % | **−3,64 %** | −8,05 % a +1,09 % |
| 2025 hasta agosto | 1.266 | +9,84 % | +2,44 % | −3,38 % a +8,27 % |
| Conjunto | 3.007 | +9,28 % | **−1,08 %** | −4,73 % a +2,49 % |

El gran desfase entre el EV previsto y el retorno observado indica que **las probabilidades Elo no están calibradas para seleccionar esas apuestas frente a la casa**. Los intervalos solo miden variación entre días, no corrigen la falta de hora de precio ni de acceso al operador. Subir el umbral de EV después de mirar estos resultados sería una regla adaptada al mismo periodo; hace falta fijar las reglas y esperar datos prospectivos nuevos. La decisión actual de producción es **ninguna apuesta recomendada**.

La vía de mejora es predecir el resultado condicionado al **precio de mercado disponible**, incorporar abridor probable y estado público observado antes de T−3h, evaluar calibración por temporadas, y medir si las señales añaden capacidad predictiva fuera de muestra. Además de Brier/log loss, se seguirá la diferencia entre precio capturado y cierre de la misma casa cuando ambos sean verificables. Solo se calculará retorno de apuestas de una casa y jurisdicción realmente accesibles, registradas antes del resultado, con precio y aceptación documentados. La fórmula `p × cuota_decimal − 1` calcula un EV **condicional a que p sea correcta**; por sí sola nunca demuestra que lo sea.

### Métodos abiertos que hemos probado

FiveThirtyEight publicó que su pronóstico completo combinaba fortaleza del equipo, proyecciones iniciales y un ajuste por el abridor; su archivo distingue el Elo simple de esa versión. La documentación de scikit-learn enfatiza que una probabilidad útil debe estar calibrada, y que la calibración se ajusta en datos separados de los usados para entrenar. Nuestro siguiente bloque de investigación es reconstruir rendimiento **anterior** de los abridores probables y carga del bullpen, unido a capturas oficiales anteriores a la decisión. Una lesión se representará como estado público observado con fuente y hora, no como un supuesto valor universal de “moral”. Fuentes: [archivo y definiciones de FiveThirtyEight](https://github.com/fivethirtyeight/data/tree/master/mlb-elo), [calibración probabilística](https://scikit-learn.org/stable/modules/calibration.html), [modelo bayesiano de fortaleza con cuotas de mercado](https://arxiv.org/abs/1701.05976).

FanGraphs combina varias proyecciones de talento con **tiempo de juego previsto** actualizado, una idea especialmente útil cuando un titular está lesionado o cambia la alineación. El método público se puede reproducir con estimaciones propias de sustitución y disponibilidad; no se debe asumir que una lista de lesionados equivale a perder el valor total del jugador. Statcast publica estadísticas esperadas basadas en calidad del contacto, que pueden ayudar a separar habilidad y resultados ruidosos si se reconstruyen exclusivamente con lanzamientos previos a cada decisión. Fuentes: [FanGraphs Depth Charts](https://blogs.fangraphs.com/introducing-fangraphs-depth-charts-and-standings/), [Statcast expected statistics](https://baseballsavant.mlb.com/leaderboard/expected_statistics).

Orden de incorporación: (1) validar la disponibilidad de abridores y captar su historial **anterior** a T−3h; (2) estimar carga reciente de relevistas a partir de boxscores ya finalizados; (3) ajustar calidad de alineación por titulares realmente anunciados y sustitutos, con hora de publicación; (4) probar si esas diferencias mejoran Brier, log loss y calibración **frente al precio de mercado**, en temporadas nuevas. No asignar un ajuste de puntos fijo a cualquier lesión: el puesto, reemplazo y minutos/entradas previstos importan. No usar la alineación final o las estadísticas de fin de temporada para juegos anteriores.

Ya ejecutamos `market_anchor_experiment.py` sobre el archivo de cuotas de apertura, todavía sin hora. Usa el consenso sin margen como referencia y añade primero Elo; la segunda variante suma diferencias de victorias, carreras y descanso **calculadas antes del día**. Se entrena inicialmente con 2021–2022, se escoge regularización con 2023 y se reajusta cada año solo con temporadas anteriores. Brier en los mismos partidos (menor es mejor):

| Temporada | Juegos con consenso | Mercado archivado | Mercado + Elo | Mercado + Elo + forma |
|---|---:|---:|---:|---:|
| 2024 | 2.382 | **0,241283** | 0,241487 | 0,241788 |
| 2025 hasta agosto | 1.688 | 0,242877 | 0,242487 | **0,242403** |

La mejora de 2025 no se sostuvo en 2024 y el periodo final ya fue consultado. Estos modelos quedan **experimentales**; no se trasladan como estrategia rentable. La prueba definitiva requiere cuotas verificadas a T−3h, información pública capturada entonces y resultados posteriores al congelamiento del método. El importador crea `market_hybrid_predictions` para inspeccionar cada probabilidad y compararla con el consenso de los mismos juegos.

## Reproducción

Python 3.10+ sin paquetes de terceros:

```bash
python fetch_sources.py
python collect_mlb_public.py --season 2026 --end-date 2026-09-27
python tests.py
python build_dataset.py
python evaluate_models.py
python market_diagnostic.py
python edge_diagnostic.py
python market_anchor_experiment.py
```

Para importar un JSON histórico autorizado y guardado previamente: `python import_snapshot.py captura.json`. La reconstrucción borra y recrea `output/mlb_time_machine.sqlite`, incluidos registros añadidos a `public_signals`, `odds_quotes` y `model_predictions`: exporte los datos propios antes de reconstruir. `source_files` contiene tamaño, enlace y SHA-256 de cada descarga para auditar versiones.

**Fuentes:** Retrosheet (© 1996–2026 Retrosheet), [game logs](https://www.retrosheet.org/gamelogs/); [archivo de cuotas MLB y su descripción](https://github.com/ArnavSaraogi/mlb-odds-scraper/releases/tag/dataset); [MLB Stats API](https://statsapi.mlb.com/api/v1/schedule?sportId=1); [ParlayAPI histórico](https://parlay-api.com/historical-odds-api); [acceso histórico Betfair](https://support.developer.betfair.com/hc/en-us/articles/360008664937-Which-jurisdictions-is-Betfair-Exchange-Historical-Data-available-to). La fuente de cuotas es independiente y sus datos deben cotejarse con el operador si se pretende inferir ejecución real.
