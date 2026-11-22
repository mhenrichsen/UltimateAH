"""Offline tests for the server scan (ah_server.py) and the PC script's use of its files:
a fake Blizzard API with several auction houses, two scans an hour apart, the database, the
published files, and ah_api.py reading them without an API key."""
import array
import datetime
import gzip
import io
import json
import math
import os
import random
import re
import sqlite3
import tempfile
import urllib.error

import lupa

import ah_api
import ah_server

fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (("  -- " + str(info)) if info else ""))
    if not cond:
        fails += 1


HOST = "https://eu.api.blizzard.com"
NAMES = {110: "Alliance Auction House", 112: "Alliance Auction House", 113: "Horde Auction House",
         116: "Blackwater Auction House"}


class Fake:
    """houses 110 (Alliance), 113 (Horde), 112 (empty), 116 (neutral); answers 304 to If-Modified-Since"""

    def __init__(self):
        self.regular = {110: [], 113: []}
        self.commodities = {110: [], 113: []}
        self.modified = {110: "Sun, 22 Nov 2026 12:23:00 GMT", 113: "Sun, 22 Nov 2026 12:23:05 GMT",
                         112: "Sun, 22 Nov 2026 12:22:00 GMT", 116: "Sun, 22 Nov 2026 12:22:00 GMT"}
        self.calls = []
        self.fail = set()

    def __call__(self, req):
        url = req.full_url
        self.calls.append(url)
        if url.startswith("https://oauth.battle.net/token"):
            return 200, json.dumps({"access_token": "TOKEN"}).encode(), {}
        path = url[len(HOST):].split("?")[0]
        if path in ("/data/wow/ruleset/1/auctions/index", "/data/wow/ruleset/1/auctions/"):
            body = {"auctions": [{"id": i, "name": n, "key": {"href": "%s/data/wow/ruleset/1/auctions/%d" % (HOST, i)}}
                                 for i, n in sorted(NAMES.items())]}
            return 200, json.dumps(body).encode(), {}
        m = re.fullmatch(r"/data/wow/ruleset/1/auctions/(\d+)(/commodities)?", path)
        if not m:
            raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
        hid = int(m.group(1))
        if hid in self.fail:
            raise urllib.error.HTTPError(url, 500, "server error", {}, io.BytesIO(b""))
        if req.get_header("If-modified-since") == self.modified[hid]:
            raise urllib.error.HTTPError(url, 304, "not modified", {"Last-Modified": self.modified[hid]}, io.BytesIO(b""))
        if m.group(2):
            body = {"auctions": self.commodities.get(hid, [])}
        elif hid in self.regular:
            body = {"id": hid, "name": NAMES[hid], "auctions": self.regular[hid],
                    "commodities": {"href": HOST + path + "/commodities?namespace=dynamic-forever-eu"}}
        else:
            body = {"id": hid, "name": NAMES[hid]}
        return 200, json.dumps(body).encode(), {"Last-Modified": self.modified[hid]}


def reg(aid, item, buyout, qty=1, tl="VERY_LONG", bonus=None):
    it = {"id": item}
    if bonus:
        it["bonus_lists"] = bonus
    return {"id": aid, "item": it, "buyout": buyout, "quantity": qty, "time_left": tl}


def com(aid, item, unit, qty, tl="VERY_LONG"):
    return {"id": aid, "item": {"id": item}, "unit_price": unit, "quantity": qty, "time_left": tl}


def published(folder, name):
    with gzip.open(os.path.join(folder, name), "rt", encoding="utf-8") as f:
        return ah_api.parse_data(f.read())


tmp = tempfile.mkdtemp(prefix="uahsrv_")
DIR = os.path.join(tmp, "server")
ah_api.STATE = os.path.join(tmp, "log")
cfg = {"client_id": "id", "client_secret": "secret", "region": "eu"}
fake = Fake()

# 1. first scan of every house
fake.regular[110] = [reg(1, 11991, 50000, bonus=[12745]), reg(2, 11991, 80000, bonus=[12745]),
                     reg(4, 2589, 2000, qty=20), reg(5, 2589, 2400, qty=20, tl="SHORT"), reg(8, 7005, 1000), reg(9, 7005, 1100)]
fake.commodities[110] = [com(100, 4306, 150, 200), com(101, 4306, 160, 500)]
fake.regular[113] = [reg(50, 2589, 3000, qty=20), reg(51, 7005, 900)]
fake.commodities[113] = [com(150, 4306, 140, 300)]
T0 = 1795300000 - 3598
check("probe: an empty folder means there is work", ah_server.cmd_probe(DIR, opener=fake, cfg=cfg) is True)
rc = ah_server.cmd_run(DIR, opener=fake, cfg=cfg, now=T0)
idx = ah_server.read_index(DIR)
check("run: both factions scanned, empty and neutral houses left out",
      rc == 0 and [(e["house"], e["faction"]) for e in idx["houses"]] == [(110, "Alliance"), (113, "Horde")], idx["houses"])
check("run: files published", all(os.path.exists(os.path.join(DIR, f)) for f in
                                  ("eu-110.lua.gz", "eu-113.lua.gz", "history.db.gz", "state-eu-110.json.gz", "index.json")))
check("run: index names Blizzard as the source", "Blizzard" in idx.get("source", ""))
meta, items = published(DIR, "eu-110.lua.gz")
check("file: header", meta.get("house") == 110 and meta.get("faction") == "Alliance" and meta.get("t") == T0
      and meta.get("auctions") == 8 and meta.get("soldHours") == 0, meta)
check("file: prices", items["2589"][:4] == [100, 100, 40, 2] and items["4306"][0] == 150 and items["11991:b12745"][0] == 50000,
      (items["2589"], items["4306"]))
check("file: no sale rate from one scan, today's history point", items["4306"][6] == 0 and items["4306"][7:] == [T0 // 86400, items["4306"][1], 150])
meta_h, items_h = published(DIR, "eu-113.lua.gz")
check("file: the Horde house has its own prices", meta_h.get("faction") == "Horde" and items_h["4306"][0] == 140 and items_h["2589"][0] == 150)
check("probe: nothing new right after a scan", ah_server.cmd_probe(DIR, opener=fake, cfg=cfg) is False)
n = len(fake.calls)
ah_server.cmd_run(DIR, opener=fake, cfg=cfg, now=T0 + 600)
db = sqlite3.connect(os.path.join(DIR, "history.db"))
check("run: unchanged data is not counted twice",
      db.execute("SELECT n FROM daily WHERE key = '4306' AND house = 1").fetchone()[0] == 1 and len(fake.calls) - n <= 6,
      len(fake.calls) - n)
db.close()

# 2. an hour later only the Alliance house has new data
fake.modified[110] = "Sun, 22 Nov 2026 13:23:00 GMT"
fake.regular[110] = [reg(2, 11991, 80000, bonus=[12745]),     # 1 gone, cheapest               -> sold
                     reg(9, 7005, 1100, tl="SHORT"),          # 8 gone, 9 dearer and still up  -> sold
                     reg(20, 2589, 2200, qty=20)]             # 4 gone -> 20 sold; 5 was SHORT -> expired
fake.commodities[110] = [com(100, 4306, 150, 80), com(101, 4306, 160, 500)]      # 120 of 200 bought
T1 = T0 + 3598                                                # Blizzard's hours are a little short
DAY = 86400 / 3598.0
check("probe: new data is seen", ah_server.cmd_probe(DIR, opener=fake, cfg=cfg) is True)
ah_server.cmd_run(DIR, opener=fake, cfg=cfg, now=T1)
meta, items = published(DIR, "eu-110.lua.gz")


def near(a, b):
    return abs(a - b) <= 0.01 * b


check("sold: rates after two scans a short hour apart", meta.get("soldHours") == 1 and near(items["4306"][6], 120 * DAY)
      and near(items["2589"][6], 20 * DAY) and near(items["11991:b12745"][6], DAY) and near(items["11991"][6], DAY)
      and near(items["7005"][6], DAY), (meta.get("soldHours"), items["4306"][6], items["2589"][6]))
meta_h2, _ = published(DIR, "eu-113.lua.gz")
check("run: the unchanged house keeps its file", meta_h2.get("t") == T0)
db = sqlite3.connect(os.path.join(DIR, "history.db"))
row = db.execute("SELECT mkt_sum, n, min, qty, sold, sold_n FROM daily d JOIN house h ON h.hk = d.house "
                 "WHERE h.id = 110 AND d.key = '4306'").fetchone()
check("database: the day's row adds up", row[1] == 2 and row[2] == 150 and row[3] == 580 and row[4] == 120 and row[5] == 1, row)
check("database: one row per house and scan", db.execute("SELECT COUNT(*) FROM scan").fetchone()[0] == 3)
check("database: compared time recorded", db.execute("SELECT seconds FROM cover").fetchall() == [(3598,)])
db.close()

# 3. the same two scans through the PC script give the same file
ah_api.STATE = os.path.join(tmp, "pc_state")
ah_api.saved_variables = lambda: None
OUT = os.path.join(tmp, "ApiData.lua")
pc_cfg = dict(cfg, ruleset=1, house=110, buyout_is_total=True, faction="Alliance", server="")
fake2 = Fake()
fake2.regular[110] = [reg(1, 11991, 50000, bonus=[12745]), reg(2, 11991, 80000, bonus=[12745]),
                      reg(4, 2589, 2000, qty=20), reg(5, 2589, 2400, qty=20, tl="SHORT"), reg(8, 7005, 1000), reg(9, 7005, 1100)]
fake2.commodities[110] = [com(100, 4306, 150, 200), com(101, 4306, 160, 500)]
api2 = ah_api.Api(pc_cfg, opener=fake2)
ah_api.cmd_scan(api2, pc_cfg, out=OUT, now=T0)
fake2.modified[110], fake2.regular[110], fake2.commodities[110] = fake.modified[110], fake.regular[110], fake.commodities[110]
ah_api.cmd_scan(api2, pc_cfg, out=OUT, now=T1)
pc_meta, pc_items = ah_api.parse_data(open(OUT, encoding="utf-8").read())
check("parity: server file equals the PC script's file", pc_items == items and pc_meta == {k: v for k, v in meta.items() if k != "insDays"},
      [k for k in set(pc_items) | set(items) if pc_items.get(k) != items.get(k)][:3])

# 4. a failing house does not stop the others; old days leave the database
fake.fail = {113}
fake.modified[110] = "Tue, 22 Dec 2026 13:23:00 GMT"
T31 = T1 + 31 * 86400
rc = ah_server.cmd_run(DIR, opener=fake, cfg=cfg, now=T31)
db = sqlite3.connect(os.path.join(DIR, "history.db"))
days = [r[0] for r in db.execute("SELECT DISTINCT day FROM daily d JOIN house h ON h.hk = d.house WHERE h.id = 110")]
check("run: one house failing does not stop the rest", rc == 0 and days == [T31 // 86400], (rc, days))
check("database: nothing older than 30 days is kept (Blizzard's limit)",
      db.execute("SELECT COUNT(*) FROM scan s JOIN house h ON h.hk = s.house WHERE h.id = 110").fetchone()[0] == 1
      and db.execute("SELECT COUNT(*) FROM cover c JOIN house h ON h.hk = c.house WHERE h.id = 110").fetchone()[0] == 0)
db.close()
fake.fail = set()

# 5. the PC script without an API key: the server's files
fake.modified[110] = "Sun, 22 Nov 2026 13:23:00 GMT"
DIR2 = os.path.join(tmp, "server2")
for now in (T0, T1):
    if now == T0:
        f3 = Fake()
        f3.regular, f3.commodities = dict(fake2.regular), dict(fake2.commodities)
        f3.regular[110] = [reg(1, 11991, 50000, bonus=[12745]), reg(2, 11991, 80000, bonus=[12745]), reg(4, 2589, 2000, qty=20),
                           reg(5, 2589, 2400, qty=20, tl="SHORT"), reg(8, 7005, 1000), reg(9, 7005, 1100)]
        f3.commodities[110] = [com(100, 4306, 150, 200), com(101, 4306, 160, 500)]
        f3.regular[113], f3.commodities[113] = fake.regular[113], fake.commodities[113]
    else:
        f3.modified[110], f3.regular[110], f3.commodities[110] = "Sun, 22 Nov 2026 13:23:00 GMT", fake.regular[110], fake.commodities[110]
    ah_server.cmd_run(DIR2, opener=f3, cfg=cfg, now=now)
asked = []


def from_folder(url, timeout=120):
    asked.append(url)
    p = os.path.join(DIR2, url.rsplit("/", 1)[1])
    return open(p, "rb").read() if os.path.exists(p) else None


ah_api.fetch_url = from_folder
ah_api.STATE = os.path.join(tmp, "keyless_state")
ah_api.save_config = lambda c: None
key_cfg = {"client_id": "", "client_secret": "", "region": "eu", "house": None, "server": "https://files.example/data"}


class NoDb:
    prices = None


ah_api.saved_variables = lambda: NoDb()
ah_api.ingame_prices = lambda db, faction, max_age=0: {str(1000 + i): 500 + i for i in range(60)}
try:
    ah_api.cmd_detect_server(dict(key_cfg), "Horde")
    check("keyless detect: refuses when nothing matches", False)
except ah_api.ApiError:
    check("keyless detect: refuses when nothing matches", True)
# sixty in-game prices that match the Horde house: give that house sixty items
f4 = Fake()
f4.regular[113] = [reg(1000 + i, 1000 + i, 500 + i) for i in range(60)]
f4.regular[110] = [reg(3000 + i, 1000 + i, 900 + i) for i in range(60)]
DIR3 = os.path.join(tmp, "server3")
ah_server.cmd_run(DIR3, opener=f4, cfg=cfg, now=T1)
DIR2 = DIR3
c = dict(key_cfg)
ah_api.cmd_detect_server(c, "Horde")
check("keyless detect: finds the house from the server's files", c["house"] == 113 and c["faction"] == "Horde", c)
check("keyless: only the configured server is asked", all(u.startswith("https://files.example/data/") for u in asked))
OUT2 = os.path.join(tmp, "ApiData2.lua")
rc = ah_api.cmd_fetch(c, out=OUT2)
m2, i2 = ah_api.parse_data(open(OUT2, encoding="utf-8").read())
check("keyless fetch: the data file is written", rc == 0 and m2.get("house") == 113 and len(i2) == 60, (rc, m2))
lua = lupa.LuaRuntime(unpack_returned_tuples=True)
lua.execute(open(OUT2, encoding="utf-8").read())
d = lua.globals().UltimateAH_ApiData
check("keyless fetch: the file is valid Lua for the addon", d is not None and d.house == 113 and d.faction == "Horde" and d["items"]["1000"] is not None)
size = os.path.getsize(OUT2)
del asked[:]
ah_api.cmd_fetch(c, out=OUT2)
check("keyless fetch: nothing rewritten when the server has nothing newer", os.path.getsize(OUT2) == size)
check("keyless fetch: the small list answers it, no data file is downloaded",
      [u.rsplit("/", 1)[1] for u in asked] == ["index.json"], asked)
try:
    ah_api.cmd_fetch(dict(c, house=999), out=OUT2)
    check("keyless fetch: an unknown house is an error", False)
except ah_api.ApiError:
    check("keyless fetch: an unknown house is an error", True)

# 6. a PC with an API key that was off: its own scan plus the server's history and sale rates
DIR2 = os.path.join(tmp, "server2")
ah_api.STATE = os.path.join(tmp, "pc_state2")
ah_api.saved_variables = lambda: None
fake5 = Fake()
fake5.modified[110], fake5.regular[110], fake5.commodities[110] = "Sun, 22 Nov 2026 13:23:00 GMT", fake.regular[110], fake.commodities[110]
pc2 = dict(cfg, ruleset=1, house=110, buyout_is_total=True, faction="Alliance", server="https://files.example/data")
OUT3 = os.path.join(tmp, "ApiData3.lua")
ah_api.cmd_scan(ah_api.Api(pc2, opener=fake5), pc2, out=OUT3, now=T1)
m3, i3 = ah_api.parse_data(open(OUT3, encoding="utf-8").read())
check("overlay: a first local scan gets the server's sale rates", m3.get("soldHours") == 1 and near(i3["4306"][6], 120 * DAY), (m3, i3["4306"]))
check("overlay: prices stay the local scan's", i3["4306"][:4] == items["4306"][:4] and i3["2589"][0] == 110)
ah_api.STATE = os.path.join(tmp, "pc_state3")
ah_api.cmd_scan(ah_api.Api(pc2, opener=fake5), pc2, out=OUT3, now=T1 + 5 * 3600)
m4, i4 = ah_api.parse_data(open(OUT3, encoding="utf-8").read())
check("overlay: a stale server file is ignored", m4.get("soldHours") == 0 and i4["4306"][6] == 0, m4)

# 7. the service's HTTP side: only the public files, streamed, with 304 and without the private ones
httpd = ah_server.cmd_serve(DIR3, 0, rounds=0)
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


def http(path, method="GET", headers=None):
    req = urllib.request.Request(BASE + path, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


st, hd, body = http("/eu-113.lua.gz")
on_disk = open(os.path.join(DIR3, "eu-113.lua.gz"), "rb").read()
check("http: a data file arrives whole", st == 200 and body == on_disk and hd.get("Content-Length") == str(len(on_disk)), (st, len(body)))
check("http: it names Blizzard as the source", "Blizzard" in (hd.get("X-Data-Source") or ""), dict(hd))
st2, hd2, body2 = http("/eu-113.lua.gz", headers={"If-Modified-Since": hd.get("Last-Modified")})
check("http: unchanged since the last download is a 304 without a body", st2 == 304 and body2 == b"", (st2, len(body2)))
st3, _, _ = http("/eu-113.lua.gz", headers={"If-Modified-Since": "Thu, 01 Jan 2015 00:00:00 GMT"})
st4, _, _ = http("/eu-113.lua.gz", headers={"If-Modified-Since": "not a date"})
check("http: an older or unreadable date gets the file", st3 == 200 and st4 == 200, (st3, st4))
st, hd, body = http("/eu-113.lua.gz", method="HEAD")
check("http: HEAD gives the size and no body", st == 200 and body == b"" and hd.get("Content-Length") == str(len(on_disk)), (st, len(body)))
st, _, body = http("/")
check("http: / is the list of houses", st == 200 and json.loads(body.decode()).get("houses"), st)
st, _, body = http("/healthz")
check("http: healthz answers", st == 200 and json.loads(body.decode()).get("ok") is True, (st, body))
private = ["/state-eu-113.json.gz", "/history.db", "/scan.log", "/../ah_api.py", "/eu-113.lua.gz/../history.db", "/%2e%2e/x"]
check("http: private files and paths outside the folder are not handed out",
      all(http(p)[0] == 404 for p in private), [(p, http(p)[0]) for p in private])
check("http: the database download is there", http("/history.db.gz", method="HEAD")[0] == 200)
httpd.shutdown()

# 8. price patterns: the pure functions on made-up series
D0 = 20801                                               # a Monday (UTC day number)
check("patterns: day numbers map to weekdays", all(ah_server.weekday(x) == (datetime.date(1970, 1, 1) + datetime.timedelta(days=x)).weekday() for x in range(D0, D0 + 14)) and ah_server.weekday(D0) == 0)
rnd = random.Random(7)
days = list(range(D0, D0 + 30))
flat = [math.log(10000) + rnd.gauss(0, 0.01) for _ in days]
rising = [math.log(10000) + 0.02 * max(0, d - (D0 + 21)) + rnd.gauss(0, 0.002) for d in days]
tr = ah_server.trend(days, rising, D0 + 29)
check("trend: a price rising 2% a day is found", tr is not None and abs(tr - 0.02) < 0.004, tr)
check("trend: too few recent days gives no answer", ah_server.trend(days[:4], flat[:4], D0 + 3) is None)
check("trend: old prices do not count", ah_server.trend(days[:10], rising[:10], D0 + 29) is None)
wk = [math.log(20000) + {5: math.log(1.12), 1: math.log(0.90)}.get(ah_server.weekday(d), 0) + rnd.gauss(0, 0.005) for d in days]
we = ah_server.weekday_effect(days, wk)
check("weekday: dear Saturdays and cheap Tuesdays are found", we[0] == 1 and -12 <= we[1] <= -8 and we[2] == 5 and 10 <= we[3] <= 14, we)
check("weekday: three weeks are not enough to say", ah_server.weekday_effect(days[:21], wk[:21]) == [-1, 0, -1, 0],
      ah_server.weekday_effect(days[:21], wk[:21]))


def hour_row(price_at, units_at, n_days, noise, r):
    """the hours-table row an item gets from n_days of hourly scans"""
    a = array.array("f", [0.0] * 96)
    for d in range(n_days):
        a = array.array("f", [x * ah_server.PROFILE_DECAY for x in a])
        for h in range(24):
            x = math.log(price_at(h)) + r.gauss(0, noise)
            a[h] += x
            a[24 + h] += 1
            a[72 + h] += x * x
            a[48 + h] += units_at(h)
    return a.tobytes()


wave = hour_row(lambda h: 1 + 0.1 * math.cos(2 * math.pi * (h - 20) / 24), lambda h: 60 if h in (19, 20, 21) else 2, 14, 0.01, rnd)
he = ah_server.hour_effect(wave)
check("hours: cheapest and dearest hour of a daily wave are found", he[0] in (7, 8, 9) and he[1] in (19, 20, 21) and 15 <= he[2] <= 23, he)
check("hours: the hour most units sell is found", he[3] in (19, 20, 21), he)
check("hours: four days are not enough to say", ah_server.hour_effect(hour_row(lambda h: 1 + 0.1 * math.cos(h), lambda h: 0, 4, 0.01, rnd))[:3] == [-1, -1, 0])
check("hours: no row, no answer", ah_server.hour_effect(None) == [-1, -1, 0, -1])

# pure noise must rarely look like a pattern
false_tr = false_wd = false_hr = 0
N = 300
for seed in range(N):
    r = random.Random(1000 + seed)
    noise = [math.log(10000) + r.gauss(0, 0.05) for _ in days]
    false_tr += bool(ah_server.trend(days, noise, D0 + 29))
    w = ah_server.weekday_effect(days, noise)
    false_wd += (w[0] >= 0) or (w[2] >= 0)
    false_hr += ah_server.hour_effect(hour_row(lambda h: 1.0, lambda h: 5, 30, 0.05, r))[0] >= 0
check("noise: a trend is seen in under 8% of random series", false_tr <= 0.08 * N, "%d of %d" % (false_tr, N))
check("noise: a weekday is seen in under 5% of random series", false_wd <= 0.05 * N, "%d of %d" % (false_wd, N))
check("noise: an hour of the day is seen in under 5% of random series", false_hr <= 0.05 * N, "%d of %d" % (false_hr, N))

# the forecast: fitted on what happened, switched on only when it beats "the price stays the same"
ah_server.FIT_MIN = 100
samples = []
for seed in range(40):                                   # prices that drift back to their usual level
    r = random.Random(2000 + seed)
    x, series = 0.0, []
    for _ in days:
        x = 0.6 * x + r.gauss(0, 0.1)
        series.append(math.log(10000) + x)
    samples += ah_server.fit_samples(days, series)
a, b, n, err, naive, ok = ah_server.fit(samples)
check("forecast: prices that drift back are forecast better than 'unchanged'", ok == 1 and b > 0.3 and err < naive, (a, b, n, err, naive))
samples = []
for seed in range(40):                                   # a random walk cannot be forecast
    r = random.Random(3000 + seed)
    x, series = 0.0, []
    for _ in days:
        x += r.gauss(0, 0.05)
        series.append(math.log(10000) + x)
    samples += ah_server.fit_samples(days, series)
a, b, n, err, naive, ok = ah_server.fit(samples)
check("forecast: stays off for prices that cannot be forecast", ok == 0, (a, b, n, err, naive))
check("forecast: stays off with too few checks", ah_server.fit(samples[:50])[5] == 0)

# 9. a simulated month of hourly scans, through the real scan code
DIR4 = os.path.join(tmp, "server4")
ah_server.FIT_SAMPLE = 1
sim = Fake()
api4 = ah_api.Api(cfg, opener=sim)
db4 = ah_server.connect(DIR4)
rnd = random.Random(11)
ar = {item: 0.0 for item in range(5000, 5030)}
day_noise = {}
entry = None
for i in range(30 * 24):
    d, h = divmod(i, 24)
    if h == 0:
        for item in ar:
            ar[item] = 0.6 * ar[item] + rnd.gauss(0, 0.1)
        if d >= 28:
            ar[5000] = 0.5                               # far above its usual price at the end
        day_noise = {7005: rnd.gauss(0, 0.004)}
    aucs = []

    def put(item, price):
        for k in range(6):                               # six auctions each: enough to follow the item by the hour
            aucs.append(com(item * 100 + k, item, int(round(price)), 10))

    put(4306, 15000 * (1 + 0.1 * math.cos(2 * math.pi * (h - 20) / 24)))
    aucs.append(com(900000 + i, 4306, int(round(15000 * (1 + 0.1 * math.cos(2 * math.pi * (h - 20) / 24)))),
                    60 if h in (18, 19, 20) else 2))     # bought within the hour: most in the evening
    put(7005, 20000 * {5: 1.12, 1: 0.90}.get(ah_server.weekday(D0 + d), 1.0) * math.exp(day_noise[7005]))
    put(2589, 30000 * math.exp(0.02 * max(0, d - 21)))
    put(3000, 10000 * math.exp(rnd.gauss(0, 0.05)))
    for item, x in ar.items():
        put(item, 10000 * math.exp(x))
    sim.regular[110], sim.commodities[110] = [], aucs
    sim.modified[110] = "scan %d" % i
    entry = ah_server.scan_house(api4, db4, DIR4, {"id": 110, "name": NAMES[110]}, now=D0 * 86400 + 23 * 60 + i * 3600)
db4.close()
with gzip.open(os.path.join(DIR4, "eu-110.lua.gz"), "rt", encoding="utf-8") as f:
    month = f.read()
m4, i4, p4 = ah_api.parse_file(month)
F = {name: j for j, name in enumerate(ah_api.INS_FIELDS)}
check("month: the header says how many days stand behind the patterns", m4.get("insDays") == 30 and entry["days"] == 30, m4)
check("month: every followed item has patterns", all(str(k) in p4 for k in [4306, 7005, 2589, 3000, 5000]) and len(p4["4306"]) == len(F), sorted(p4)[:8])
x = p4["4306"]
check("month: the daily wave is found (cheapest near 08:00, dearest near 20:00 UTC)",
      x[F["hrLo"]] in (7, 8, 9) and x[F["hrHi"]] in (19, 20, 21) and 15 <= x[F["hrPct"]] <= 23, x)
check("month: the evening is when it sells", x[F["hrSell"]] in (19, 20, 21), x)
check("month: an item with a daily wave has no trend and no weekday", x[F["trend"]] == 0 and x[F["wdLo"]] == -1 and x[F["wdHi"]] == -1, x)
x = p4["7005"]
check("month: dear Saturdays and cheap Tuesdays are found", x[F["wdLo"]] == 1 and -12 <= x[F["wdLoPct"]] <= -8
      and x[F["wdHi"]] == 5 and 10 <= x[F["wdHiPct"]] <= 14, x)
x = p4["2589"]
check("month: a price rising 2% a day shows as +2.0%/day at the top of its range", 17 <= x[F["trend"]] <= 23 and x[F["pos"]] >= 95, x)
x = p4["3000"]
check("month: a noisy item shows no pattern", x[F["trend"]] == 0 and x[F["wdLo"]] == -1 and x[F["wdHi"]] == -1 and x[F["hrLo"]] == -1, x)
x = p4["5000"]
check("month: the forecast is on and expects a spiked price to come down", entry["forecast"]["on"] and 0 < x[F["in7"]] < i4["5000"][1],
      (entry["forecast"], x, i4["5000"][:2]))
check("month: the sale rate and history are still there", i4["4306"][6] > 0 and len(i4["4306"]) == 7 + 3 * ah_api.HISTORY_DAYS, i4["4306"][:8])
lua = lupa.LuaRuntime(unpack_returned_tuples=True)
lua.execute(month)
d = lua.globals().UltimateAH_ApiData
check("month: the file is valid Lua with both tables", d["items"]["4306"] is not None and d["ins"]["4306"] is not None and d.insDays == 30)
old_items = {}
for line in month.split("\n"):                           # how script versions before the patterns read the file
    line = line.strip()
    if line.startswith('["'):
        key, _, rest = line[2:].partition('"]="')
        old_items[key] = rest
check("month: older script versions still read the items and nothing else", len(old_items) == len(i4), (len(old_items), len(i4)))
con = sqlite3.connect(os.path.join(DIR4, "history.db"))
check("month: nothing older than 30 days is kept", con.execute("SELECT MIN(day) FROM daily").fetchone()[0] == D0
      and con.execute("SELECT MIN(day) FROM hours").fetchone()[0] > D0 + 29 - ah_server.KEEP_DAYS)
con.close()

# the PC script with an API key passes the server's patterns on
DIR2 = DIR4
pc4 = dict(cfg, ruleset=1, house=110, buyout_is_total=True, faction="Alliance", server="https://files.example/data")
OUT4 = os.path.join(tmp, "ApiData4.lua")
ah_api.STATE = os.path.join(tmp, "pc4_state")
ah_api.cmd_scan(ah_api.Api(pc4, opener=sim), pc4, out=OUT4, now=D0 * 86400 + 23 * 60 + 719 * 3600 + 300)
m5, i5, p5 = ah_api.parse_file(open(OUT4, encoding="utf-8").read())
check("overlay: the PC script's file carries the server's patterns", p5.get("4306") == p4["4306"] and m5.get("insDays") == 30, (m5, p5.get("4306")))

print()
print("%d failure(s)" % fails)
raise SystemExit(1 if fails else 0)
