"""Offline tests for the server scan (ah_server.py) and the PC script's use of its files:
a fake Blizzard API with several auction houses, two scans an hour apart, the database, the
published files, and ah_api.py reading them without an API key."""
import gzip
import io
import json
import os
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
check("parity: server file equals the PC script's file", pc_items == items and pc_meta == meta,
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

print()
print("%d failure(s)" % fails)
raise SystemExit(1 if fails else 0)
