# PokéPulse 🃏

A real-time Pokémon card price tracker built with React 18 and Python.

## Features

- **Dashboard** — Trending cards with real-time prices
- **Card Detail** — Price history charts, stats, volatility analysis
- **Compare** — Side-by-side card comparison with overlaid price charts
- **Set Browser** — Browse all Pokémon TCG sets and explore cards within each set
- **Portfolio** — Track your collection with purchase price, condition, quantity
- **Watchlist** — Save cards you're keeping an eye on
- **How It Works** — Explainer page

## Tech Stack

- **Frontend**: React 18 (CDN), Chart.js 4.4, Space Grotesk + JetBrains Mono
- **Backend**: Python 3 CGI proxy (349 LOC, zero pip dependencies)
- **Database**: SQLite — caching, watchlist, portfolio
- **API**: pokemonpricetracker.com v2 (Bearer auth)
- **Caching**: Aggressive SQLite caching (Popular 24hr, Cards 12hr, Detail 6hr, Sets 24hr)

## File Structure

```
├── index.html          # Entry point (32 lines)
├── app.jsx             # React source — 2,188 lines
├── app.js              # Babel-compiled output — 2,854 lines
├── style.css           # Dark premium stylesheet — 2,121 lines
├── cgi-bin/
│   └── api.py          # Backend proxy — 349 lines
└── key.txt             # API key (not in repo)
```

## Setup

1. Get an API key from [pokemonpricetracker.com](https://www.pokemonpricetracker.com/api)
2. Create `key.txt` in the project root with your API key
3. Serve with any static + CGI-capable server

## Stats

| Metric | Value |
|---|---|
| Total LOC | ~7,500 |
| React Components | 20 |
| Pages | 7 |
| SQLite Tables | 3 |
| External Dependencies | 0 (pip) / 3 (CDN) |
| Build Tools | None |
