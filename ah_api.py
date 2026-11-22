"""UltimateAH auto scans through Blizzard's Game Data API.

An addon cannot talk to the internet, so this script does it from outside the game: it downloads
every auction of your auction house, works out the same prices the in-game scan does, estimates
how many units were sold since the previous run, and writes ApiData.lua into the addon folder.
The addon reads that file at login or /reload.

    python ah_api.py check      test the credentials and list rulesets + auction houses
    python ah_api.py detect     find which auction house is yours (compares with your in-game scan)
    python ah_api.py scan       one scan
    python ah_api.py auto       detect if needed, then scan (this is what the hourly scheduled task runs)
    python ah_api.py fetch      no API key needed: download the data file the project's server scan publishes
    python ah_api.py status     what the last scan stored

Without credentials, detect / auto / fetch use the files the server scan (ah_server.py, an hourly job in
the project's repository) publishes for every Forever auction house. With credentials the scan is your
own, and the server's files add what a PC that is not always on cannot have: a price point for every
day and a sold-per-day figure from every hour.

Credentials: blizzard_api.json next to this script (client_id / client_secret from
https://develop.battle.net/access/clients), or the environment variables
BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET.

The Forever endpoints are not documented by Blizzard; the paths come from community probing
(namespace dynamic-forever-<region>, auctions under /data/wow/ruleset/<id>/auctions/...).
"""
import argparse
import base64
import collections
import email.utils
import gzip
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "blizzard_api.json")
STATE = os.path.join(HERE, "api_state")
WOW = r"C:\Program Files (x86)\World of Warcraft\_forever_"
ADDON = os.path.join(WOW, "Interface", "AddOns", "UltimateAH")
OUT = os.path.join(ADDON, "ApiData.lua")

HISTORY_DAYS = 14          # daily prices handed to the addon
SOLD_DAYS = 7              # window of the units-sold-per-day estimate
MAX_GAP = 3 * 3600         # two scans further apart than this are not compared
MIN_COVER = 3000           # seconds of compared scans needed before sale rates are written: hourly
                           # snapshots are a few seconds short of 3600 s apart, so not a full hour
# the least time an auction in each bracket still has left; one that vanished sooner was
# bought or cancelled, it cannot have run out
# where the server scan publishes its files; "server": "" in blizzard_api.json turns it off
SERVER = "https://github.com/mhenrichsen/UltimateAH/releases/download/data"
MIN_LEFT = {"SHORT": 0, "MEDIUM": 1800, "LONG": 7200, "VERY_LONG": 43200}
TL_CODE = {"SHORT": 0, "MEDIUM": 1, "LONG": 2, "VERY_LONG": 3}
TL_MIN = [0, 1800, 7200, 43200]


def log(*a):
    line = " ".join(str(x) for x in a)
    if sys.stdout:
        print(time.strftime("%H:%M:%S"), line, flush=True)
    try:                                   # the scheduled task has no window: keep a short log
        os.makedirs(STATE, exist_ok=True)
        p = os.path.join(STATE, "scan.log")
        if os.path.exists(p) and os.path.getsize(p) > 200000:
            os.replace(p, p + ".old")
        with open(p, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def day_of(t):
    return int(t // 86400)


# ---------------------------------------------------------------------------
# config + state
# ---------------------------------------------------------------------------
def set_wow_dir(path):
    """the game folder to read saved data from and to write ApiData.lua into"""
    global WOW, ADDON, OUT
    if path:
        WOW = path
        ADDON = os.path.join(WOW, "Interface", "AddOns", "UltimateAH")
        OUT = os.path.join(ADDON, "ApiData.lua")


def load_config():
    cfg = {"client_id": "", "client_secret": "", "region": "eu", "ruleset": None, "house": None,
           "buyout_is_total": True, "wow_dir": WOW}
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    cfg["client_id"] = os.environ.get("BLIZZARD_CLIENT_ID") or cfg["client_id"]
    cfg["client_secret"] = os.environ.get("BLIZZARD_CLIENT_SECRET") or cfg["client_secret"]
    return cfg


def save_config(cfg):
    keep = dict(cfg)
    if os.environ.get("BLIZZARD_CLIENT_ID"):      # never copy env credentials into the file
        old = {}
        if os.path.exists(CONFIG):
            with open(CONFIG, encoding="utf-8") as f:
                old = json.load(f)
        keep["client_id"] = old.get("client_id", "")
        keep["client_secret"] = old.get("client_secret", "")
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(keep, f, indent=2)


def read_state(name, default):
    p = os.path.join(STATE, name)
    if not os.path.exists(p):
        return default
    try:
        if name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return json.load(f)
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, EOFError):
        return default


def write_state(name, data):
    os.makedirs(STATE, exist_ok=True)
    p = os.path.join(STATE, name)
    tmp = p + ".tmp"
    if name.endswith(".gz"):
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=5) as f:
            json.dump(data, f, separators=(",", ":"))
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Blizzard API
# ---------------------------------------------------------------------------
class ApiError(Exception):
    pass


class Api:
    def __init__(self, cfg, opener=None):
        self.region = cfg["region"].lower()
        self.host = "https://%s.api.blizzard.com" % self.region
        self.namespace = "dynamic-forever-%s" % self.region
        self.cfg = cfg
        self.token = None
        self.open = opener or self._open       # tests replace this
        self.requests = 0

    def _open(self, req):
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return r.status, body, dict(r.headers)

    def login(self):
        if not self.cfg["client_id"] or not self.cfg["client_secret"]:
            raise ApiError("no credentials: put client_id and client_secret in " + CONFIG)
        basic = base64.b64encode(("%s:%s" % (self.cfg["client_id"], self.cfg["client_secret"])).encode()).decode()
        req = urllib.request.Request("https://oauth.battle.net/token", data=b"grant_type=client_credentials",
                                     headers={"Authorization": "Basic " + basic})
        try:
            status, body, _ = self.open(req)
        except urllib.error.HTTPError as e:
            raise ApiError("login refused (HTTP %d): check client_id / client_secret" % e.code)
        self.token = json.loads(body)["access_token"]

    def get(self, path, since=None):
        """-> (status, json or None, headers). path is a path or a full URL on the API host."""
        if not self.token:
            self.login()
        if path.startswith("http"):
            if not path.startswith(self.host + "/"):          # never send the token anywhere else
                raise ApiError("refusing to follow a link to another host: " + path.split("?")[0])
            url = path
        else:
            url = self.host + path
        if "namespace=" not in url:
            url += ("&" if "?" in url else "?") + "namespace=" + self.namespace
        if "locale=" not in url:
            url += "&locale=en_US"
        headers = {"Authorization": "Bearer " + self.token, "Accept-Encoding": "gzip"}
        if since:
            headers["If-Modified-Since"] = since
        self.requests += 1
        try:
            status, body, h = self.open(urllib.request.Request(url, headers=headers))
        except urllib.error.HTTPError as e:
            return e.code, None, dict(e.headers or {})
        except urllib.error.URLError as e:
            raise ApiError("network error: %s" % e.reason)
        data = json.loads(body) if body else None
        return status, data, h


def text(v):
    """names come as a string (with locale=) or as a table of locales"""
    if isinstance(v, dict):
        return v.get("en_US") or v.get("en_GB") or next(iter(v.values()), "")
    return v or ""


def rulesets(api):
    status, data, _ = api.get("/data/wow/ruleset/index")
    if status != 200 or not data:
        raise ApiError("ruleset index answered HTTP %s (namespace %s)" % (status, api.namespace))
    out = []
    for r in data.get("rulesets") or data.get("ruleset") or []:
        out.append({"id": r.get("id"), "name": text(r.get("name"))})
    return out


def houses(api, ruleset):
    """auction houses of a ruleset: [{id, name, href}]"""
    for path in ("/data/wow/ruleset/%s/auctions/index" % ruleset, "/data/wow/ruleset/%s/auctions/" % ruleset):
        status, data, _ = api.get(path)
        if status == 200 and data and data.get("auctions"):
            return [{"id": h.get("id"), "name": text(h.get("name")), "href": (h.get("key") or {}).get("href")}
                    for h in data["auctions"]]
    raise ApiError("no auction house list for ruleset %s" % ruleset)


def faction_of(name):
    n = (name or "").lower()
    return "Alliance" if "alliance" in n else "Horde" if "horde" in n else "Neutral"


def item_key(item):
    """the addon's price key: the item id, plus its sorted bonus ids for random-suffix gear"""
    iid = item.get("id")
    b = item.get("bonus_lists")
    if b:
        return "%d:b%s" % (iid, "-".join(str(x) for x in sorted(b)))
    return str(iid)


def fetch_house(api, ruleset, house, total=True, since=None):
    """-> { "t", "modified", "auctions": {id: [key, qty, unit, tl, commodity]} }.
    With since (the Last-Modified of the data you already have): None when nothing newer exists."""
    base = "/data/wow/ruleset/%s/auctions/%s" % (ruleset, house)
    status, data, h = api.get(base, since=since)
    if status == 304:
        return None
    if status != 200 or data is None:
        raise ApiError("auction house %s answered HTTP %s" % (house, status))
    out = {}
    for a in data.get("auctions") or []:
        item = a.get("item") or {}
        qty = a.get("quantity") or 1
        buyout = a.get("buyout")
        if not item.get("id") or not buyout or qty <= 0:
            continue                                   # bid-only auctions carry no price
        unit = buyout / qty if total else buyout
        out[str(a["id"])] = [item_key(item), qty, unit, TL_CODE.get(a.get("time_left"), 3), 0]
    link = (data.get("commodities") or {}).get("href") or (base + "/commodities")
    status2, cdata, _ = api.get(link)
    if status2 == 200 and cdata:
        for a in cdata.get("auctions") or []:
            item = a.get("item") or {}
            qty = a.get("quantity") or 0
            unit = a.get("unit_price")
            if not item.get("id") or not unit or qty <= 0:
                continue
            out[str(a["id"])] = [str(item["id"]), qty, unit, TL_CODE.get(a.get("time_left"), 3), 1]
    modified = h.get("Last-Modified") or h.get("last-modified")
    t = int(time.time())
    if modified:                       # the age of the data, not of the download
        try:
            t = min(t, int(email.utils.parsedate_to_datetime(modified).timestamp()))
        except (TypeError, ValueError):
            pass
    return {"t": t, "modified": modified, "name": text(data.get("name")), "auctions": out}


# ---------------------------------------------------------------------------
# prices: the same maths as Scanner.lua (S.Stats / S.Top)
# ---------------------------------------------------------------------------
def top_avg(entries, n=100):
    k = min(n, len(entries))
    if k == 0:
        return None
    part = entries[:k]
    q = sum(e[1] for e in part)
    mean = sum(e[0] * e[1] for e in part) / q
    sd = math.sqrt(sum(e[1] * (e[0] - mean) ** 2 for e in part) / q)
    if sd > 0:
        kept = [e for e in part if abs(e[0] - mean) <= 1.5 * sd]
        q2 = sum(e[1] for e in kept)
        if q2 > 0:
            mean = sum(e[0] * e[1] for e in kept) / q2
    return int(math.floor(mean + 0.5))


def stats(entries):
    """entries: [[unit, qty], ...] -> (min, market, total qty, auctions, top-100 average)"""
    if not entries:
        return None
    entries.sort(key=lambda e: (e[0], e[1]))
    total = sum(e[1] for e in entries)
    picked, cum, prev = [], 0, None
    for e in entries:
        share = cum / total
        if not picked or share < 0.15 or (share < 0.30 and prev and e[0] <= prev * 1.2):
            picked.append(e)
            cum += e[1]
            prev = e[0]
        else:
            break
    n = sum(e[1] for e in picked)
    mean = sum(e[0] * e[1] for e in picked) / n
    sd = math.sqrt(sum(e[1] * (e[0] - mean) ** 2 for e in picked) / n)
    if sd > 0:
        kept = [e for e in picked if abs(e[0] - mean) <= 1.5 * sd]
        n2 = sum(e[1] for e in kept)
        if n2 > 0:
            mean = sum(e[0] * e[1] for e in kept) / n2
    return entries[0][0], int(math.floor(mean + 0.5)), total, len(entries), top_avg(entries)


def sig3(x):
    """history prices keep three significant digits: plenty for averages and graphs, and it
    keeps the number of different values in the game's saved data small (Lua 5.1 constant limit)"""
    if x < 1000:
        return x
    m = 10 ** (len(str(int(x))) - 3)
    return int(round(x / m)) * m


def plain(key):
    return key.split(":", 1)[0]


def price_table(auctions, mine=()):
    """{key: {min, mkt, qty, num, top, other}}: variants are also counted under the plain item"""
    lists = collections.defaultdict(list)
    for aid, a in auctions.items():
        e = [a[2], a[1], aid in mine]
        lists[a[0]].append(e)
        p = plain(a[0])
        if p != a[0]:
            lists[p].append(e)
    out = {}
    for key, entries in lists.items():
        mn, mkt, qty, num, top = stats(entries)
        other = next((e[0] for e in entries if not e[2]), None)
        out[key] = {"min": int(math.floor(mn + 0.5)), "mkt": mkt, "qty": qty, "num": num, "top": top,
                    "other": int(math.floor(other + 0.5)) if other is not None else None}
    return out


# ---------------------------------------------------------------------------
# units sold between two scans
# ---------------------------------------------------------------------------
def sold_between(prev, cur, dt, prev_prices):
    """-> {key: [units, auctions]}.

    An auction that is gone counts as sold when
      - it still had more time left than passed between the scans (so it did not run out), and
      - it was not priced above cheaper auctions of the same item that are still up: buyers take
        the cheapest first (the commodity market enforces it), so an auction that vanished while a
        cheaper one stayed was cancelled, not bought.
    A commodity listing whose quantity dropped was partly bought.
    """
    sold = collections.defaultdict(lambda: [0, 0])
    if dt <= 0 or dt > MAX_GAP:
        return sold
    frontier = {}                       # key -> cheapest auction of the previous scan still up
    for aid, a in prev.items():
        if aid in cur:
            k = a[0]
            if k not in frontier or a[2] < frontier[k]:
                frontier[k] = a[2]

    def add(key, units):
        sold[key][0] += units
        sold[key][1] += 1
        p = plain(key)
        if p != key:
            sold[p][0] += units
            sold[p][1] += 1

    for aid, a in prev.items():
        key, qty, unit, tl, commodity = a
        now = cur.get(aid)
        if now is not None:
            if now[1] < qty:
                add(key, qty - now[1])
            continue
        if dt >= TL_MIN[tl]:
            continue                    # may simply have expired
        f = frontier.get(key)
        if f is not None:
            if unit > f * (1.0 if commodity else 1.1):
                continue                # a cheaper one is still up: cancelled
        else:
            ref = prev_prices.get(key)
            if ref and unit > 1.5 * ref["mkt"]:
                continue                # everything of this item is gone, and this one was overpriced
        add(key, qty)
    return sold


# ---------------------------------------------------------------------------
# your own data from the game (optional): auction ids of your listings, in-game prices
# ---------------------------------------------------------------------------
def saved_variables():
    """the newest UltimateAHDB of any account, as a lupa table (None without lupa or data)"""
    try:
        import lupa
    except ImportError:
        return None
    acc = os.path.join(WOW, "WTF", "Account")
    best = None
    if os.path.isdir(acc):
        for d in os.listdir(acc):
            p = os.path.join(acc, d, "SavedVariables", "UltimateAH.lua")
            if os.path.exists(p) and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
                best = p
    if not best:
        return None
    try:
        L = lupa.LuaRuntime()
        with open(best, encoding="utf-8") as f:
            L.execute(f.read())
        return L.globals().UltimateAHDB
    except Exception:
        return None


def my_auction_ids(db):
    ids = set()
    if db is None or not db.listings:
        return ids
    for _, snap in db.listings.items():
        if snap.list:
            for _, a in snap.list.items():
                if a.aid:
                    ids.add(str(int(a.aid)))
    return ids


def ingame_prices(db, faction, max_age=3 * 86400):
    """{key: min} from the in-game scans of the last days"""
    out = {}
    if db is None or not db.prices:
        return out
    now = time.time()
    for scope, p in db.prices.items():
        if not str(scope).endswith(faction):
            continue
        for key, e in p.items():
            if e.min and e.t and now - e.t < max_age:
                out[str(key)] = e.min
    return out


# ---------------------------------------------------------------------------
# output for the addon
# ---------------------------------------------------------------------------
def lua_num(x):
    if x is None:
        return "0"
    if isinstance(x, float):
        return ("%.2f" % x).rstrip("0").rstrip(".")
    return str(x)


def write_lua(path, meta, items):
    lines = ["-- written by ah_api.py (UltimateAH auto scan); do not edit",
             "-- auction data: Blizzard Entertainment, through the Battle.net Game Data API",
             "UltimateAH_ApiData = {"]
    for k, v in meta.items():
        lines.append("  %s = %s," % (k, json.dumps(v) if isinstance(v, str) else lua_num(v)))
    # one string per item: the game's Lua 5.1 allows 262,143 different constants in a file, and
    # tables of numbers for 26,000 items with two weeks of history would run into that
    lines.append("  -- [key] = \"min,market,qty,auctions,top100,lowestOther,soldPerDay,day,market,min,day,market,min,...\"")
    lines.append("  items = {")
    for key in sorted(items):
        it = items[key]
        vals = [it["min"], it["mkt"], it["qty"], it["num"], it["top"], it["other"], it["sold"]] + it["h"]
        lines.append('    ["%s"]="%s",' % (key, ",".join(lua_num(x) for x in vals)))
    lines.append("  },")
    lines.append("}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# the server scan's published files (no API key needed)
# ---------------------------------------------------------------------------
def fetch_url(url, timeout=120):
    """-> bytes, or None when the file is not there (tests replace this)"""
    req = urllib.request.Request(url, headers={"User-Agent": "UltimateAH"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError):
        return None


def server_base(cfg):
    base = cfg.get("server")
    return (SERVER if base is None else base).rstrip("/")


def server_index(cfg):
    """what the server scan has: {"houses": [{region, house, faction, t, auctions, items, soldHours, file}]}"""
    base = server_base(cfg)
    body = fetch_url(base + "/index.json") if base else None
    try:
        return json.loads(body.decode("utf-8")) if body else None
    except ValueError:
        return None


def server_file(cfg, region, house):
    """the data file of one house as text (the ApiData.lua format), or None"""
    base = server_base(cfg)
    body = fetch_url("%s/%s-%s.lua.gz" % (base, region, house)) if base else None
    if not body:
        return None
    try:
        return gzip.decompress(body).decode("utf-8")
    except (OSError, EOFError, ValueError):
        return None


def parse_data(data):
    """a data file -> (meta, {key: [min, market, qty, auctions, top100, lowestOther, soldPerDay, day, market, min, ...]})"""
    meta, items = {}, {}
    for line in data.split("\n"):
        line = line.strip()
        if line.startswith('["'):
            key, _, rest = line[2:].partition('"]="')
            items[key] = [float(x) if "." in x else int(x) for x in rest.rstrip('",').split(",") if x]
        elif " = " in line and not items:
            k, _, v = line.rstrip(",").partition(" = ")
            if k.isidentifier() and v and v != "{":
                try:
                    meta[k] = json.loads(v)
                except ValueError:
                    pass
    return meta, items


def cmd_fetch(cfg, out=None):
    """download the server scan's file of your auction house into the addon folder"""
    out = out or OUT
    region, house = cfg["region"].lower(), cfg.get("house")
    if not house:
        raise ApiError("no auction house chosen yet: run  python ah_api.py detect")
    txt = server_file(cfg, region, house)
    if not txt:
        raise ApiError("the server has no data file for auction house %s-%s" % (region, house))
    meta, items = parse_data(txt)
    if meta.get("house") != house or not items:
        raise ApiError("the server's file for auction house %s-%s is not readable" % (region, house))
    last = read_state("last.json", None)
    if last and last.get("t", 0) >= meta.get("t", 0) and os.path.exists(out):
        log("no newer data on the server (its last scan: %s)" % time.strftime("%H:%M", time.localtime(meta.get("t", 0))))
        return 0
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    os.replace(tmp, out)
    write_state("last.json", {"t": meta.get("t", 0), "house": house, "auctions": meta.get("auctions", 0),
                              "items": len(items), "sold_units": 0, "cover_hours": meta.get("soldHours", 0),
                              "source": "server"})
    log("server data loaded: house %s, %d auctions, %d items, sale rates from %.1f h of data" % (
        house, meta.get("auctions", 0), len(items), meta.get("soldHours", 0)))
    return 0


def game_faction(db, faction=None):
    if faction:
        return faction
    counts = collections.Counter()
    for scope, p in (db.prices.items() if db.prices else []):
        counts[str(scope).split(" ")[-1]] += len(list(p.keys()))
    return counts.most_common(1)[0][0] if counts else "Alliance"


def cmd_detect_server(cfg, faction=None):
    """find your auction house without an API key: compare the server's files with your in-game scan"""
    db = saved_variables()
    if db is None:
        raise ApiError("cannot read UltimateAH's saved data (log out or /reload once after a full scan)")
    faction = game_faction(db, faction)
    game = ingame_prices(db, faction)
    if len(game) < 50:
        raise ApiError("too little in-game data to compare with: do a Full Scan in the game, /reload, and retry")
    idx = server_index(cfg)
    if not idx or not idx.get("houses"):
        raise ApiError("the server's list of auction houses is not reachable")
    region, best = cfg["region"].lower(), None
    for h in idx["houses"]:
        if h.get("region") != region or h.get("faction") != faction:
            continue
        txt = server_file(cfg, region, h["house"])
        if not txt:
            continue
        _, items = parse_data(txt)
        both = [k for k in game if k in items and items[k][0] > 0]
        hit = sum(1 for k in both if abs(items[k][0] - game[k]) <= 0.05 * game[k] + 1)
        score = hit / max(len(both), 1) if len(both) >= 50 else 0
        log("  house %s: %d/%d prices match" % (h["house"], hit, len(both)))
        if best is None or score > best[0]:
            best = (score, h["house"], h.get("ruleset"), hit, len(both))
    if not best or best[0] <= 0.2:
        raise ApiError("no auction house on the server matches your in-game prices well enough")
    cfg["house"], cfg["ruleset"], cfg["faction"], cfg["buyout_is_total"] = best[1], best[2] or 1, faction, True
    save_config(cfg)
    log("your auction house: %s, %d of %d prices match - saved" % (best[1], best[3], best[4]))
    return 0


def server_overlay(cfg, region, house, t, items):
    """give a local scan the server's history and sale rates: the server scans every hour, this PC
    only while it is on. -> the server's soldHours, or None when its file is missing or stale"""
    txt = server_file(cfg, region, house)
    if not txt:
        return None
    meta, srv = parse_data(txt)
    if meta.get("house") != house or abs(t - meta.get("t", 0)) > MAX_GAP:
        return None
    rates = (meta.get("soldHours") or 0) >= 1
    for key, it in items.items():
        v = srv.get(key)
        if v and len(v) > 7:
            it["h"] = v[7:]
        if rates:
            it["sold"] = v[6] if v and len(v) > 6 else 0
    if rates:
        for key, v in srv.items():
            if key not in items and len(v) > 6 and v[6] > 0:
                items[key] = {"min": 0, "mkt": 0, "qty": 0, "num": 0, "top": 0, "other": 0, "h": [], "sold": v[6]}
    return meta.get("soldHours") or 0


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_check(api, cfg):
    rs = rulesets(api)
    log("credentials work. namespace %s" % api.namespace)
    for r in rs:
        try:
            hs = houses(api, r["id"])
        except ApiError as e:
            log("  ruleset %s %-14s %s" % (r["id"], r["name"], e))
            continue
        log("  ruleset %s %-14s houses: %s" % (r["id"], r["name"],
            ", ".join("%s %s" % (h["id"], faction_of(h["name"])[0]) for h in hs)))
    return 0


def cmd_detect(api, cfg, faction=None):
    db = saved_variables()
    if db is None:
        raise ApiError("cannot read UltimateAH's saved data (log out or /reload once after a full scan)")
    faction = game_faction(db, faction)
    mine = my_auction_ids(db)
    game = ingame_prices(db, faction)
    if len(game) < 50 and not mine:
        raise ApiError("too little in-game data to compare with: do a Full Scan in the game, /reload, and retry")
    rs = rulesets(api)
    seen, best = {}, None
    for r in rs:
        try:
            hs = houses(api, r["id"])
        except ApiError:
            continue
        for h in hs:
            if faction_of(h["name"]) != faction or h["id"] in seen:
                continue                          # every ruleset lists the same houses
            seen[h["id"]] = True
            for total in (True, False):
                try:
                    snap = fetch_house(api, r["id"], h["id"], total)
                except ApiError as e:
                    log("  house %s: %s" % (h["id"], e))
                    break
                aucs = snap["auctions"]
                if not aucs:
                    log("  house %s: empty" % h["id"])
                    break
                table = price_table(aucs)
                both = [k for k in game if k in table]
                hit = sum(1 for k in both if abs(table[k]["min"] - game[k]) <= 0.05 * game[k] + 1)
                own = len(mine & set(aucs))
                score = own * 1000 + (hit / max(len(both), 1) if len(both) >= 50 else 0)
                log("  house %s %s (%s): %d auctions, %d/%d prices match, %d of my auctions" % (
                    h["id"], "stack buyout" if total else "unit buyout", r["id"], len(aucs), hit, len(both), own))
                if best is None or score > best[0]:
                    best = (score, r["id"], h["id"], total, hit, len(both), own)
    if not best or best[0] <= 0.2:
        raise ApiError("no auction house matches your in-game prices well enough")
    cfg["ruleset"], cfg["house"], cfg["buyout_is_total"], cfg["faction"] = best[1], best[2], best[3], faction
    save_config(cfg)
    log("your auction house: %s (ruleset %s), %d of %d prices match, %d own auctions found - saved" % (
        best[2], best[1], best[4], best[5], best[6]))
    return 0


def cmd_scan(api, cfg, out=None, now=None, force=False):
    out = out or OUT
    if not cfg.get("house") or not cfg.get("ruleset"):
        raise ApiError("no auction house chosen yet: run  python ah_api.py detect")
    house = cfg["house"]
    snap = fetch_house(api, cfg["ruleset"], house, cfg.get("buyout_is_total", True))
    if now:
        snap["t"] = now
    aucs = snap["auctions"]
    if not aucs:
        raise ApiError("auction house %s returned no auctions" % house)
    name = "house_%s_%s" % (api.region, house)
    prev = read_state(name + ".json.gz", None)
    acc = read_state(name + "_acc.json", {"hist": {}, "sold": {}, "cover": {}})
    t, d = snap["t"], day_of(snap["t"])

    if not force and prev and prev.get("modified") and prev["modified"] == snap.get("modified"):
        log("no new data since the last scan (%s)" % snap["modified"])
        return 0

    db = saved_variables()
    table = price_table(aucs, my_auction_ids(db))

    # units sold since the previous scan
    n_sold = 0
    if prev and prev.get("auctions"):
        dt = t - prev["t"]
        if 0 < dt <= MAX_GAP:
            for key, (units, cnt) in sold_between(prev["auctions"], aucs, dt, prev.get("prices") or {}).items():
                s = acc["sold"].setdefault(key, {}).setdefault(str(d), [0, 0])
                s[0] += units
                s[1] += cnt
                if ":" not in key:
                    n_sold += units
            acc["cover"][str(d)] = acc["cover"].get(str(d), 0) + dt

    # daily price history: mean of the day's market values, lowest minimum
    for key, p in table.items():
        h = acc["hist"].setdefault(key, {}).setdefault(str(d), [0, 0, p["min"]])
        h[0] += p["mkt"]
        h[1] += 1
        h[2] = min(h[2], p["min"])

    # forget old days
    for key in list(acc["hist"]):
        hk = acc["hist"][key]
        for dd in [x for x in hk if int(x) <= d - HISTORY_DAYS]:
            del hk[dd]
        if not hk:
            del acc["hist"][key]
    for key in list(acc["sold"]):
        sk = acc["sold"][key]
        for dd in [x for x in sk if int(x) <= d - SOLD_DAYS]:
            del sk[dd]
        if not sk:
            del acc["sold"][key]
    for dd in [x for x in acc["cover"] if int(x) <= d - SOLD_DAYS]:
        del acc["cover"][dd]
    cover = sum(acc["cover"].values())
    rates = cover >= MIN_COVER

    items = {}
    for key, p in table.items():
        hist = []
        for dd in sorted(acc["hist"].get(key, {}), key=int):
            s, n, mn = acc["hist"][key][dd]
            hist += [int(dd), sig3(int(round(s / n))), sig3(mn)]
        units = sum(v[0] for v in acc["sold"].get(key, {}).values())
        items[key] = dict(p, h=hist, sold=(units / cover * 86400) if rates else None)
    # items that sold out completely still have a sale rate worth keeping
    if rates:
        for key, days in acc["sold"].items():
            if key not in items:
                items[key] = {"min": 0, "mkt": 0, "qty": 0, "num": 0, "top": 0, "other": 0, "h": [],
                              "sold": sum(v[0] for v in days.values()) / cover * 86400}

    # the addon reads sale rates only when soldHours >= 1, so this must agree with `rates`
    sold_hours = max(1.0, round(cover / 3600.0, 1)) if rates else 0.0
    srv_hours = server_overlay(cfg, api.region, house, t, items)
    if srv_hours is not None:
        log("history and sale rates taken from the server scan (%.0f h of data)" % srv_hours)
        if srv_hours >= 1:
            sold_hours = srv_hours
    meta = collections.OrderedDict(v=1, t=t, region=api.region, house=house,
                                   faction=cfg.get("faction") or faction_of(snap.get("name")),
                                   auctions=len(aucs), soldHours=sold_hours)
    write_lua(out, meta, items)
    write_state(name + ".json.gz", {"t": t, "modified": snap.get("modified"), "auctions": aucs,
                                    "prices": {k: {"mkt": v["mkt"]} for k, v in table.items()}})
    write_state(name + "_acc.json", acc)
    write_state("last.json", {"t": t, "house": house, "auctions": len(aucs), "items": len(table),
                              "sold_units": n_sold, "cover_hours": sold_hours})
    log("scan done: %d auctions, %d items, %d units sold since the last scan, sale rates from %.1f h of data" % (
        len(aucs), len(table), n_sold, sold_hours))
    return 0


def cmd_status():
    last = read_state("last.json", None)
    if not last:
        log("no scan yet")
        return 1
    log("last scan %d min ago: house %s, %d auctions, %d items, sale rates from %.1f h of data" % (
        (time.time() - last["t"]) / 60, last["house"], last["auctions"], last["items"], last["cover_hours"]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="UltimateAH auto scans through Blizzard's API")
    ap.add_argument("command", choices=["check", "detect", "scan", "auto", "fetch", "status"])
    ap.add_argument("--faction", help="Alliance or Horde (detect: default is the one you scanned in-game)")
    ap.add_argument("--force", action="store_true", help="scan: write the data file even if Blizzard's data is unchanged")
    args = ap.parse_args(argv)
    if args.command == "status":
        return cmd_status()
    cfg = load_config()
    set_wow_dir(cfg.get("wow_dir"))
    try:
        keyless = not (cfg["client_id"] and cfg["client_secret"])
        if args.command == "fetch" or (keyless and args.command in ("detect", "auto")):
            if args.command == "detect" or not cfg.get("house"):       # no API key: use the server's files
                cmd_detect_server(cfg, args.faction)
                if args.command == "detect":
                    return 0
            return cmd_fetch(cfg)
        api = Api(cfg)
        if args.command == "check":
            return cmd_check(api, cfg)
        if args.command == "detect":
            return cmd_detect(api, cfg, args.faction)
        if args.command == "auto" and not (cfg.get("house") and cfg.get("ruleset")):
            cmd_detect(api, cfg, args.faction)          # the scheduled task finds the house by itself
        return cmd_scan(api, cfg, force=args.force)
    except ApiError as e:
        log("failed:", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
