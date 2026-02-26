#!/usr/bin/env python3
"""
PokéPulse Backend API Proxy
- Proxies all requests to pokemonpricetracker.com/api/v2
- Keeps API key server-side (NEVER exposed to client)
- AGGRESSIVE caching (SQLite) to minimize API credit burn
- Manages watchlist + portfolio state
- Serves preloaded popular cards for dashboard
"""
import json, os, sys, sqlite3, hashlib, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────
DB_PATH = Path("pokepulse.db")
API_BASE = "https://www.pokemonpricetracker.com/api/v2"
# API key is loaded from environment variable POKEMON_API_KEY (set on your server)

# Cache TTLs (seconds) — AGGRESSIVE to save credits
TTL_SETS     = 86400     # 24 hours
TTL_CARDS    = 43200     # 12 hours for card lists
TTL_DETAIL   = 21600     # 6 hours for card detail w/ history
TTL_POPULAR  = 86400     # 24 hours for popular/trending

# Popular queries to seed the dashboard (fetched once, cached 24hr)
POPULAR_QUERIES = [
    {"search": "charizard", "limit": "8", "sortBy": "price", "sortOrder": "desc"},
    {"search": "pikachu", "limit": "6", "sortBy": "price", "sortOrder": "desc"},
    {"search": "mewtwo", "limit": "4", "sortBy": "price", "sortOrder": "desc"},
    {"search": "lugia", "limit": "4", "sortBy": "price", "sortOrder": "desc"},
    {"search": "umbreon", "limit": "4", "sortBy": "price", "sortOrder": "desc"},
    {"search": "rayquaza", "limit": "4", "sortBy": "price", "sortOrder": "desc"},
    {"search": "gengar", "limit": "4", "sortBy": "price", "sortOrder": "desc"},
    {"search": "blastoise", "limit": "4", "sortBy": "price", "sortOrder": "desc"},
    {"search": "mew", "limit": "3", "sortBy": "price", "sortOrder": "desc"},
    {"search": "eevee", "limit": "3", "sortBy": "price", "sortOrder": "desc"},
]

def get_api_key():
    return os.environ.get("POKEMON_API_KEY", "")

# ── DB ────────────────────────────────────────────
def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS cache (
        cache_key TEXT PRIMARY KEY,
        data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ttl_seconds INTEGER DEFAULT 300
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS watchlist (
        card_id TEXT PRIMARY KEY,
        card_name TEXT,
        set_name TEXT,
        image_url TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id TEXT NOT NULL,
        card_name TEXT,
        set_name TEXT,
        image_url TEXT,
        variant TEXT DEFAULT 'Normal',
        condition TEXT DEFAULT 'Near Mint',
        quantity INTEGER DEFAULT 1,
        purchase_price REAL,
        purchase_date TEXT,
        notes TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    db.commit()
    return db

# ── Caching ─────────────────────────────────────────
def cache_get(db, key):
    row = db.execute("SELECT data, created_at, ttl_seconds FROM cache WHERE cache_key=?", (key,)).fetchone()
    if not row:
        return None
    age = (datetime.utcnow() - datetime.fromisoformat(row["created_at"])).total_seconds()
    if age > row["ttl_seconds"]:
        db.execute("DELETE FROM cache WHERE cache_key=?", (key,))
        db.commit()
        return None
    return json.loads(row["data"])

def cache_set(db, key, data, ttl=300):
    db.execute("INSERT OR REPLACE INTO cache (cache_key, data, created_at, ttl_seconds) VALUES (?,?,?,?)",
               (key, json.dumps(data), datetime.utcnow().isoformat(), ttl))
    db.commit()

# ── API Proxy ─────────────────────────────────────
def api_fetch(endpoint, params=None):
    key = get_api_key()
    if not key:
        return {"error": "API key not configured"}, 500

    url = f"{API_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("User-Agent", "PokePulse/2.0")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode())
            headers = dict(resp.headers)
            data["_rateLimit"] = {
                "limit": headers.get("X-RateLimit-Limit"),
                "remaining": headers.get("X-RateLimit-Remaining"),
                "reset": headers.get("X-RateLimit-Reset"),
            }
            return data, 200
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else "{}"
        try:
            err = json.loads(body)
        except:
            err = {"error": body}
        return err, e.code
    except Exception as e:
        return {"error": str(e)}, 500

# ── Route handlers ──────────────────────────────

def handle_popular(params):
    """Serve curated popular cards. Cached 24hr. 
    Fetches multiple search queries and merges, dedupes, sorts by price."""
    db = get_db()
    cache_key = "popular:v2"
    cached = cache_get(db, cache_key)
    if cached:
        cached["_cached"] = True
        return cached, 200

    # Fetch each popular query (costs ~10 API calls total, cached for 24hr)
    all_cards = []
    seen_ids = set()
    for q in POPULAR_QUERIES:
        data, status = api_fetch("cards", q)
        if status == 200 and "data" in data:
            for card in data["data"]:
                cid = card.get("tcgPlayerId") or card.get("id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_cards.append(card)

    # Sort by market price descending
    all_cards.sort(key=lambda c: c.get("prices", {}).get("market") or 0, reverse=True)

    result = {
        "data": all_cards,
        "metadata": {
            "total": len(all_cards),
            "count": len(all_cards),
            "source": "curated_popular",
        }
    }
    cache_set(db, cache_key, result, ttl=TTL_POPULAR)
    return result, 200

def handle_sets(params):
    cache_key = f"sets:{json.dumps(params, sort_keys=True)}"
    db = get_db()
    cached = cache_get(db, cache_key)
    if cached:
        cached["_cached"] = True
        return cached, 200
    data, status = api_fetch("sets", params)
    if status == 200:
        cache_set(db, cache_key, data, ttl=TTL_SETS)
    return data, status

def handle_cards(params):
    cache_key = f"cards:{json.dumps(params, sort_keys=True)}"
    db = get_db()
    include_history = params.get("includeHistory", "false") == "true"
    ttl = TTL_DETAIL if include_history else TTL_CARDS

    cached = cache_get(db, cache_key)
    if cached:
        cached["_cached"] = True
        return cached, 200

    data, status = api_fetch("cards", params)
    if status == 200:
        cache_set(db, cache_key, data, ttl=ttl)
    return data, status

def handle_card_detail(params):
    card_id = params.get("id") or params.get("tcgPlayerId")
    if not card_id:
        return {"error": "id required"}, 400
    api_params = {
        "tcgPlayerId": card_id,
        "includeHistory": "true",
        "days": params.get("days", "30"),
    }
    return handle_cards(api_params)

def handle_watchlist(method, params, body):
    db = get_db()
    if method == "GET":
        rows = db.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
        cards = [dict(r) for r in rows]
        return {"cards": cards, "count": len(cards)}, 200
    elif method == "POST":
        card_id = body.get("card_id", "")
        if not card_id:
            return {"error": "card_id required"}, 400
        existing = db.execute("SELECT 1 FROM watchlist WHERE card_id=?", (card_id,)).fetchone()
        if existing:
            db.execute("DELETE FROM watchlist WHERE card_id=?", (card_id,))
            db.commit()
            return {"status": "removed", "card_id": card_id}, 200
        else:
            db.execute("INSERT INTO watchlist (card_id, card_name, set_name, image_url) VALUES (?,?,?,?)",
                       (card_id, body.get("card_name", ""), body.get("set_name", ""),
                        body.get("image_url", "")))
            db.commit()
            return {"status": "added", "card_id": card_id}, 200
    elif method == "DELETE":
        card_id = params.get("card_id") or body.get("card_id", "")
        if card_id:
            db.execute("DELETE FROM watchlist WHERE card_id=?", (card_id,))
            db.commit()
        return {"status": "ok"}, 200

def handle_portfolio(method, params, body):
    db = get_db()
    if method == "GET":
        rows = db.execute("SELECT * FROM portfolio ORDER BY added_at DESC").fetchall()
        items = [dict(r) for r in rows]
        return {"items": items, "count": len(items)}, 200
    elif method == "POST":
        card_id = body.get("card_id", "")
        if not card_id:
            return {"error": "card_id required"}, 400
        db.execute("""INSERT INTO portfolio
            (card_id, card_name, set_name, image_url, variant, condition,
             quantity, purchase_price, purchase_date, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (card_id, body.get("card_name", ""), body.get("set_name", ""),
             body.get("image_url", ""), body.get("variant", "Normal"),
             body.get("condition", "Near Mint"), body.get("quantity", 1),
             body.get("purchase_price"), body.get("purchase_date"),
             body.get("notes", "")))
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"status": "added", "id": new_id, "card_id": card_id}, 201
    elif method == "PUT":
        item_id = body.get("id")
        if not item_id:
            return {"error": "id required"}, 400
        fields = []
        values = []
        for f in ["quantity", "purchase_price", "purchase_date", "notes", "variant", "condition"]:
            if f in body:
                fields.append(f"{f}=?")
                values.append(body[f])
        if fields:
            values.append(item_id)
            db.execute(f"UPDATE portfolio SET {', '.join(fields)} WHERE id=?", values)
            db.commit()
        return {"status": "updated", "id": item_id}, 200
    elif method == "DELETE":
        item_id = params.get("id") or body.get("id")
        if item_id:
            db.execute("DELETE FROM portfolio WHERE id=?", (item_id,))
            db.commit()
        return {"status": "deleted"}, 200

def handle_status():
    db = get_db()
    wl_count = db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    pf_count = db.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]
    cache_count = db.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    # Show cache stats
    cache_rows = db.execute("SELECT cache_key, created_at, ttl_seconds FROM cache ORDER BY created_at DESC LIMIT 20").fetchall()
    cache_detail = []
    for r in cache_rows:
        age = (datetime.utcnow() - datetime.fromisoformat(r["created_at"])).total_seconds()
        cache_detail.append({
            "key": r["cache_key"][:50],
            "age_mins": round(age / 60, 1),
            "ttl_hrs": round(r["ttl_seconds"] / 3600, 1),
            "fresh": age < r["ttl_seconds"],
        })
    return {
        "status": "ok",
        "has_api_key": bool(get_api_key()),
        "watchlist_count": wl_count,
        "portfolio_count": pf_count,
        "cache_entries": cache_count,
        "cache_detail": cache_detail,
        "timestamp": datetime.utcnow().isoformat(),
    }, 200

# ── Main CGI handler ────────────────────────────
def main():
    method = os.environ.get("REQUEST_METHOD", "GET")
    query_string = os.environ.get("QUERY_STRING", "")
    params = dict(urllib.parse.parse_qsl(query_string))
    action = params.pop("action", "")

    body = {}
    if method in ("POST", "PUT", "DELETE"):
        try:
            length = int(os.environ.get("CONTENT_LENGTH", 0))
            raw = sys.stdin.read(length) if length else "{}"
            body = json.loads(raw) if raw else {}
        except:
            body = {}

    if action == "popular":
        result, status = handle_popular(params)
    elif action == "sets":
        result, status = handle_sets(params)
    elif action == "cards":
        result, status = handle_cards(params)
    elif action == "card":
        result, status = handle_card_detail(params)
    elif action == "watchlist":
        result, status = handle_watchlist(method, params, body)
    elif action == "portfolio":
        result, status = handle_portfolio(method, params, body)
    elif action == "status":
        result, status = handle_status()
    else:
        result = {"error": "unknown action", "actions": [
            "popular", "sets", "cards", "card", "watchlist", "portfolio", "status"
        ]}
        status = 400

    print(f"Status: {status}")
    print("Content-Type: application/json")
    print()
    print(json.dumps(result))

if __name__ == "__main__":
    main()
