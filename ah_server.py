"""Ultimate AH server scan: every Forever auction house, every hour, into a small database.

The PC script (ah_api.py) only scans while that PC is on. This one is meant for a machine that is
always there (the hourly GitHub job in .github/workflows/ah-scan.yml, or any server with Python):

    python ah_server.py probe --dir DIR     has Blizzard published new data? (a few small requests)
    python ah_server.py run   --dir DIR     scan every house, update the database, write the data files
    python ah_server.py info  --dir DIR     what the database holds

Everything lives in DIR:

    history.db                      SQLite: one row per auction house, item and day (30 days)
    history.db.gz                   the same, packed for publishing
    state-<region>-<house>.json.gz  the previous snapshot of a house: needed to see what was sold
    <region>-<house>.lua.gz         what the addon loads (the ApiData.lua format); ah_api.py downloads it
    index.json                      the list of houses with the time of their last scan

Credentials: the environment variables BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET (or blizzard_api.json).

Blizzard's API terms allow keeping API data for 30 days at most, so nothing older stays in the
database. Auction data: Blizzard Entertainment, through the Battle.net Game Data API.
"""
import argparse
import collections
import gzip
import json
import os
import shutil
import sqlite3
import sys
import time

import ah_api
from ah_api import ApiError, log

REGION = os.environ.get("AH_REGION", "eu")
RULESET = int(os.environ.get("AH_RULESET", "1"))     # every ruleset lists the same houses
FACTIONS = ("Alliance", "Horde")
KEEP_DAYS = 30                                        # Blizzard's limit for stored API data
SOURCE = "Blizzard Entertainment, Battle.net Game Data API"

SCHEMA = """
CREATE TABLE IF NOT EXISTS house (
  hk INTEGER PRIMARY KEY, region TEXT NOT NULL, id INTEGER NOT NULL, ruleset INTEGER, faction TEXT, name TEXT,
  t INTEGER, modified TEXT, auctions INTEGER, items INTEGER, UNIQUE (region, id));
-- one row per house, day and item (or item variant "id:b<bonus ids>"):
--   mkt_sum / n = the day's mean market price, min = the day's lowest buyout (copper per unit)
--   qty = units listed at the last scan of the day, sold / sold_n = units and auctions counted as sold
CREATE TABLE IF NOT EXISTS daily (
  house INTEGER NOT NULL, day INTEGER NOT NULL, key TEXT NOT NULL,
  mkt_sum INTEGER NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0, min INTEGER,
  qty INTEGER NOT NULL DEFAULT 0, sold INTEGER NOT NULL DEFAULT 0, sold_n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (house, day, key)) WITHOUT ROWID;
-- seconds of each day covered by two scans that could be compared (the base of the sale rates)
CREATE TABLE IF NOT EXISTS cover (house INTEGER NOT NULL, day INTEGER NOT NULL, seconds INTEGER NOT NULL,
  PRIMARY KEY (house, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS scan (house INTEGER NOT NULL, t INTEGER NOT NULL, auctions INTEGER, items INTEGER,
  sold_units INTEGER, PRIMARY KEY (house, t)) WITHOUT ROWID;
"""


def connect(folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "history.db")
    packed = path + ".gz"
    if not os.path.exists(path) and os.path.exists(packed):      # a fresh machine gets the published copy
        with gzip.open(packed, "rb") as src, open(path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def house_key(db, region, h):
    db.execute("INSERT OR IGNORE INTO house (region, id) VALUES (?, ?)", (region, h["id"]))
    return db.execute("SELECT hk FROM house WHERE region = ? AND id = ?", (region, h["id"])).fetchone()[0]


def read_gz(path, default=None):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, EOFError):
        return default


def write_gz(path, data):
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=5) as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


def build_items(db, hk, day, table):
    """the addon's item rows from today's prices plus the database's history and sale counts"""
    hist = collections.defaultdict(list)
    for key, dd, s, n, mn in db.execute(
            "SELECT key, day, mkt_sum, n, min FROM daily WHERE house = ? AND day > ? AND n > 0 ORDER BY key, day",
            (hk, day - ah_api.HISTORY_DAYS)):
        hist[key] += [dd, ah_api.sig3(int(round(s / n))), ah_api.sig3(mn)]
    since = day - ah_api.SOLD_DAYS
    cover = db.execute("SELECT COALESCE(SUM(seconds), 0) FROM cover WHERE house = ? AND day > ?", (hk, since)).fetchone()[0]
    rates = cover >= ah_api.MIN_COVER
    sold = {}
    if rates:
        sold = dict(db.execute("SELECT key, SUM(sold) FROM daily WHERE house = ? AND day > ? GROUP BY key HAVING SUM(sold) > 0",
                               (hk, since)))
    items = {}
    for key, p in table.items():
        items[key] = dict(p, h=hist.get(key, []), sold=(sold.get(key, 0) / cover * 86400) if rates else None)
    for key, units in sold.items():                     # sold out completely: the sale rate is still worth keeping
        if key not in items:
            items[key] = {"min": 0, "mkt": 0, "qty": 0, "num": 0, "top": 0, "other": 0, "h": [],
                          "sold": units / cover * 86400}
    # the addon reads sale rates only when soldHours >= 1, so this must agree with `rates`
    return items, (max(1.0, round(cover / 3600.0, 1)) if rates else 0.0)


def scan_house(api, db, folder, h, now=None, force=False):
    """-> index entry of the house, None when it is empty, or "same" when Blizzard has nothing newer"""
    region, hid = api.region, h["id"]
    name = "%s-%s" % (region, hid)
    state = os.path.join(folder, "state-%s.json.gz" % name)
    prev = read_gz(state)
    since = prev.get("modified") if prev and not force else None
    snap = ah_api.fetch_house(api, RULESET, hid, True, since=since)
    if snap is None or (prev and not force and prev.get("modified") and prev["modified"] == snap.get("modified")):
        return "same"
    aucs = snap["auctions"]
    if not aucs:
        return None
    if now:
        snap["t"] = now
    t, day = snap["t"], ah_api.day_of(snap["t"])
    hk = house_key(db, region, h)
    table = ah_api.price_table(aucs)

    n_sold = 0
    if prev and prev.get("auctions"):
        dt = t - prev["t"]
        if 0 < dt <= ah_api.MAX_GAP:
            sold = ah_api.sold_between(prev["auctions"], aucs, dt, prev.get("prices") or {})
            db.executemany(
                "INSERT INTO daily (house, day, key, sold, sold_n) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (house, day, key) DO UPDATE SET sold = sold + excluded.sold, sold_n = sold_n + excluded.sold_n",
                [(hk, day, key, units, cnt) for key, (units, cnt) in sold.items()])
            n_sold = sum(units for key, (units, cnt) in sold.items() if ":" not in key)
            db.execute("INSERT INTO cover (house, day, seconds) VALUES (?, ?, ?) "
                       "ON CONFLICT (house, day) DO UPDATE SET seconds = seconds + excluded.seconds", (hk, day, dt))
    db.executemany(
        "INSERT INTO daily (house, day, key, mkt_sum, n, min, qty) VALUES (?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT (house, day, key) DO UPDATE SET mkt_sum = mkt_sum + excluded.mkt_sum, n = n + 1, "
        "min = CASE WHEN min IS NULL OR excluded.min < min THEN excluded.min ELSE min END, qty = excluded.qty",
        [(hk, day, key, p["mkt"], p["min"], p["qty"]) for key, p in table.items()])
    for tbl in ("daily", "cover"):
        db.execute("DELETE FROM %s WHERE house = ? AND day <= ?" % tbl, (hk, day - KEEP_DAYS))
    db.execute("DELETE FROM scan WHERE house = ? AND t <= ?", (hk, t - KEEP_DAYS * 86400))
    db.execute("INSERT OR REPLACE INTO scan (house, t, auctions, items, sold_units) VALUES (?, ?, ?, ?, ?)",
               (hk, t, len(aucs), len(table), n_sold))
    faction = ah_api.faction_of(snap.get("name") or h.get("name"))
    db.execute("UPDATE house SET ruleset = ?, faction = ?, name = ?, t = ?, modified = ?, auctions = ?, items = ? WHERE hk = ?",
               (RULESET, faction, snap.get("name") or h.get("name"), t, snap.get("modified"), len(aucs), len(table), hk))

    items, sold_hours = build_items(db, hk, day, table)
    meta = collections.OrderedDict(v=1, t=t, region=region, house=hid, faction=faction,
                                   auctions=len(aucs), soldHours=sold_hours)
    lua = os.path.join(folder, name + ".lua")
    ah_api.write_lua(lua, meta, items)
    with open(lua, "rb") as src, gzip.open(lua + ".gz.tmp", "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    os.replace(lua + ".gz.tmp", lua + ".gz")
    os.remove(lua)
    write_gz(state, {"t": t, "modified": snap.get("modified"), "auctions": aucs,
                     "prices": {k: {"mkt": v["mkt"]} for k, v in table.items()}})
    db.commit()
    log("house %s %s: %d auctions, %d items, %d units sold since the last scan, sale rates from %.1f h" % (
        name, faction, len(aucs), len(table), n_sold, sold_hours))
    return {"region": region, "house": hid, "ruleset": RULESET, "faction": faction, "t": t,
            "modified": snap.get("modified"), "auctions": len(aucs), "items": len(table),
            "soldHours": sold_hours, "file": name + ".lua.gz"}


def read_index(folder):
    try:
        with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"houses": []}


def cmd_run(folder, opener=None, cfg=None, now=None, force=False):
    cfg = cfg or dict(ah_api.load_config(), region=REGION)
    api = ah_api.Api(cfg, opener)
    db = connect(folder)
    index = {(e["region"], e["house"]): e for e in read_index(folder).get("houses", [])}
    new = failed = 0
    for h in ah_api.houses(api, RULESET):
        if ah_api.faction_of(h["name"]) not in FACTIONS:
            continue
        try:
            entry = scan_house(api, db, folder, h, now=now, force=force)
        except ApiError as e:
            db.rollback()
            failed += 1
            log("house %s-%s failed: %s" % (api.region, h["id"], e))
            continue
        if isinstance(entry, dict):
            index[(entry["region"], entry["house"])] = entry
            new += 1
    db.execute("PRAGMA optimize")
    db.commit()
    db.close()
    houses = [index[k] for k in sorted(index)]
    tmp = os.path.join(folder, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "updated": max([e["t"] for e in houses] or [0]), "source": SOURCE, "houses": houses}, f, indent=1)
    os.replace(tmp, os.path.join(folder, "index.json"))
    if new:
        path = os.path.join(folder, "history.db")
        with open(path, "rb") as src, gzip.open(path + ".gz.tmp", "wb", compresslevel=5) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        os.replace(path + ".gz.tmp", path + ".gz")
    log("server scan done: %d house(s) with new data, %d failed, %d in the index" % (new, failed, len(houses)))
    return 1 if failed and not new else 0


def cmd_probe(folder, opener=None, cfg=None):
    """-> True when at least one house has data newer than index.json knows"""
    cfg = cfg or dict(ah_api.load_config(), region=REGION)
    known = read_index(folder).get("houses", [])
    changed = not known
    if known:
        api = ah_api.Api(cfg, opener)
        for e in known:
            if e.get("region") != api.region:
                continue
            status, _, _ = api.get("/data/wow/ruleset/%s/auctions/%s" % (e.get("ruleset") or RULESET, e["house"]),
                                   since=e.get("modified"))
            if status != 304:
                changed = True
                break
    log("new data: %s" % ("yes" if changed else "no"))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("changed=%s\n" % ("true" if changed else "false"))
    return changed


def cmd_info(folder):
    db = connect(folder)
    for hk, region, hid, faction, t, auctions, items in db.execute(
            "SELECT hk, region, id, faction, t, auctions, items FROM house ORDER BY region, id"):
        days, rows = db.execute("SELECT COUNT(DISTINCT day), COUNT(*) FROM daily WHERE house = ?", (hk,)).fetchone()
        cover = db.execute("SELECT COALESCE(SUM(seconds), 0) FROM cover WHERE house = ?", (hk,)).fetchone()[0]
        scans = db.execute("SELECT COUNT(*) FROM scan WHERE house = ?", (hk,)).fetchone()[0]
        print("%s-%s %-8s last scan %s, %s auctions, %s items; %d day(s), %d rows, %d scans, %.1f h compared" % (
            region, hid, faction, time.strftime("%Y-%m-%d %H:%M", time.localtime(t or 0)), auctions, items,
            days, rows, scans, cover / 3600.0))
    db.close()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="UltimateAH server scan: all Forever auction houses into a database")
    ap.add_argument("command", choices=["probe", "run", "info"])
    ap.add_argument("--dir", default=os.path.join(ah_api.HERE, "server_data"), help="folder for the database and the files")
    ap.add_argument("--force", action="store_true", help="run: scan even if Blizzard's data is unchanged")
    args = ap.parse_args(argv)
    ah_api.STATE = args.dir                       # the log goes next to the data
    try:
        if args.command == "probe":
            cmd_probe(args.dir)
            return 0
        if args.command == "info":
            return cmd_info(args.dir)
        return cmd_run(args.dir, force=args.force)
    except ApiError as e:
        log("failed:", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
