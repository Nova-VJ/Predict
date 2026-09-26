# MLB Time Machine — V2 (26/09/2026)

Cambios respecto a V1. El README original sigue siendo válido para todo lo anterior.

## 1. Nuevas variables: abridor, bullpen y alineación (históricas y gratuitas)

`build_player_features.py` lee los archivos jugador-partido de **retrosplits** (Chadwick Bureau,
derivados de Retrosheet; `make data` los descarga) y crea la tabla `player_features`:

| Variable | Qué mide | Cobertura |
|---|---|---|
| `*_sp_fip`, `*_sp_k`, `*_sp_bb` | Calidad del abridor (FIP por bateador enfrentado, K %, BB %), con decaimiento de 365 días y regresión a la media de liga | 25.192 partidos con ambos abridores |
| `*_sp_outs` | Profundidad esperada del abridor (detecta *openers*) | ídem |
| `*_bp_fip` | Calidad del bullpen (vida media 90 días) | todos |
| `*_bp_pitches_3d` | Lanzamientos de relevistas en los 3 días previos (fatiga) | todos |
| `*_lineup_woba` | wOBA previo de los 9 titulares ponderado por turno al bate | 25.192 partidos con ambas alineaciones |

Regla temporal: solo apariciones en **fechas anteriores** al partido. `tests_v2.py` recalcula el
historial de 40 abridores al azar y comprueba que los debutantes llegan con historial cero.

**Decisión metodológica nueva:** usamos el abridor real como aproximación del abridor anunciado.
MLB lo anuncia con días de antelación, los cambios de última hora son raros y las casas
estadounidenses anulan la apuesta si cambia el lanzador anunciado (*listed pitchers*). Las
alineaciones se publican 1–4 h antes del partido: valen para decidir cerca del cierre, **no**
siempre a T−3h.

## 2. Resultados walk-forward (`evaluate_v2.py` → `output/v2_report.json`)

Cada temporada se predice con modelos entrenados solo en temporadas anteriores. Sin ajustes
de hiperparámetros sobre el periodo de prueba. Log loss (menor es mejor):

| Temporada | Elo | **Fundamentales V2** | Mercado apertura | Mercado cierre (limpio) | Mercado + V2 (sobre apertura) |
|---|---:|---:|---:|---:|---:|
| 2022 | 0,6752 | 0,6704 | 0,6672 | 0,6669 | 0,6681 |
| 2023 | 0,6833 | 0,6783 | 0,6772 | 0,6767 | 0,6774 |
| 2024 | 0,6833 | 0,6762 | 0,6754 | 0,6742 | **0,6752** |
| 2025* | 0,6790 | 0,6775 | 0,6786 | 0,6774 | 0,6780 |

\*2025 hasta agosto. Todas las columnas se calculan sobre los mismos partidos con cuotas archivadas.

- El modelo de fundamentales **mejora a Elo en todas las temporadas 2018–2025**; la diferencia
  es estadísticamente clara (intervalo por días que excluye el cero) en 2022, 2023 y 2024.
- La brecha con el cierre del mercado baja de 0,002–0,009 (Elo) a 0,000–0,0035: el modelo queda
  **casi a la altura de las casas partiendo de cero** (en 2025 iguala el cierre y mejora la
  apertura), pero no las supera de forma estable.
- Mercado + V2 no mejora el cierre (diferencia dentro de ±0,0005).

## 3. Hallazgo sobre las cuotas de cierre archivadas

En 2021, **~8 % de los cierres de DraftKings y FanDuel son cuotas en directo** (precios < 1,15 o
> 6,0). Eso explica un Brier de cierre "demasiado bueno" (0,226) en 2021. `evaluate_v2.py`
construye un cierre limpio descartando cuotas que se alejan > 15 puntos de la apertura o
tienen precio extremo. Cualquier análisis futuro de CLV debe usar ese cierre limpio.

## 4. Diagnóstico de apuestas (hipotético, sin hora verificable)

Regla fija: apostar 1 unidad en bet365 cuando `p × cuota − 1 > 2 %`.

| Estrategia 2022–2025 | Apuestas | ROI | CLV medio vs cierre limpio |
|---|---:|---:|---:|
| Fundamentales a la apertura | 3.320 | −1,7 % | −0,7 % |
| Fundamentales al cierre | 3.414 | −1,9 % | — |
| Mercado + V2 a la apertura | 500 | −4,9 % | **+1,5 %** |
| Solo consenso vs bet365 (control, 2023–25) | 54 | −0,9 % | +3,2 % |
| Mercado + V2 a la apertura (2023–25) | 88 | −10,3 % | **+5,5 %** (69 % positivas) |

Lectura: el modelo solo **no** tiene ventaja (CLV negativo). Combinado con el mercado, las pocas
apuestas que selecciona a la apertura **se mueven a su favor** hasta el cierre más que el
control. Es la mejor pista hasta ahora, pero con 88 apuestas y horas de apertura desconocidas no
es una prueba. Es exactamente lo que la fase prospectiva debe confirmar o descartar.

## 5. Captura automática (sin depender de un chat abierto)

- `pipeline/collect_snapshot.py`: calendario oficial + abridores probables + alineaciones cada
  ejecución; cuotas solo en las ventanas T−3h y cierre (≈ 24 créditos/día).
- `.github/workflows/capture.yml`: lo ejecuta cada 20 min en GitHub Actions y guarda todo en
  `data/captures/` con hora UTC de petición y recepción.
- `pipeline/fetch_oddspapi_history.py`: rellena la temporada 2026 con historial de cuotas con hora
  (Pinnacle + bet365) desde el plan gratuito de OddsPapi, reanudable y con tope de peticiones.

Configuración: ver `.env.example`. Las claves van en *GitHub Secrets*, nunca en el código ni en un chat.

## 6. Comandos

```bash
pip install -r requirements.txt
make data        # descargas gratuitas
make build       # base V1
make features    # variables V2
make test
make evaluate
```

## 8. Comparación de mercados (EE. UU. como referencia principal)

`pipeline/market_compare.py` convierte cada captura de cuotas en un tablero comparativo. **Referencia principal: consenso de EE. UU.** = mediana sin margen de DraftKings, FanDuel, BetMGM, Caesars, BetRivers y bet365 (US), las mismas 6 casas con las que se entrenó la capa de mercado del modelo. Pinnacle y el consenso global se muestran como referencias secundarias.

- Registro de casas: `config/bookmakers.json` (país, tipo: regulada EE. UU., offshore, exchange, mercado de predicción, sharp global, Europa, España…, y si tiene licencia en España). Añadir una casa = añadir una línea.
- Por partido y casa: margen, probabilidad sin margen, desviación frente a EE. UU. (puntos), valor de cada lado frente a la línea justa de EE. UU., antigüedad de la cuota, validez (se descartan cuotas de un solo lado o márgenes absurdos, p. ej. Kalshi).
- Mejores precios por lado: global, solo casas reguladas de EE. UU. y solo casas con licencia en España.
- Salidas: tablas `market_quotes` y `market_board` en SQLite y `data/app/market_board_<captura>.json` (esquema estable, `SCHEMA` en el script) para el front.
- Fuentes: ParlayAPI (`us,eu`: 11 casas de EE. UU., exchanges Novig/ProphetX, Pinnacle, Unibet, PMU) y OddsPapi para el resto del mundo (`pipeline/oddspapi_to_capture.py`: casas .es, Asia, Betfair).
- Tests: `tests_market.py`.

Primera captura (26/09, 5 partidos): el consenso de EE. UU. y Pinnacle difieren 0,0–0,7 puntos; los exchanges de EE. UU. tienen margen < 1 % y dan el mejor precio en 7 de 10 lados; PMU (Francia) cobra ~10 %.
