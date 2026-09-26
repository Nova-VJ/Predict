// Snippets run in the Claude desktop browser pane (see README_V2 §7).
// (1) ODDS — run on a https://parlay-api.com page. Replace KEY. Returns CSV text.
//   const t0=new Date().toISOString();
//   const r=await fetch('https://parlay-api.com/v1/sports/baseball_mlb/odds?regions=us,eu&markets=h2h&oddsFormat=decimal',{headers:{'X-API-Key':KEY}});
//   const d=await r.json(); const rows=['home,away,start_utc,book,last_update,home_price,away_price'];
//   for(const e of d) for(const b of e.bookmakers){const m=b.markets.find(m=>m.key==='h2h'); if(!m) continue;
//     const o={}; m.outcomes.forEach(x=>o[x.name]=x.price); rows.push([e.home_team,e.away_team,e.commence_time,b.key,b.last_update,o[e.home_team]??'',o[e.away_team]??''].join(','));}
//   `# request_utc=${t0} status=${r.status} remaining=${r.headers.get('x-requests-remaining')}\n`+rows.join('\n')
// (2) FEATURES — run on a https://statsapi.mlb.com page; see the feature snippet stored with
//     data/live/<date>/features_*.csv (same formulas as build_player_features.py, MLBAM ids,
//     2025+2026 game logs, decay 365/90 days, posted lineup or last game's lineup).
