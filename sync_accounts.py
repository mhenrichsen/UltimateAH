"""Merge UltimateAH data across every WoW account folder, so each account sees all characters.

WoW keeps addon data per account (WTF/Account/<id>/SavedVariables/UltimateAH.lua). Run this while
the game is closed or at the character-select screen; the game overwrites the file when you log out.

    python sync_accounts.py            # merge and write back (keeps a .sync-backup copy)
    python sync_accounts.py --dry-run  # only report
"""
import glob
import os
import shutil
import sys

import lupa

WTF = r"C:\Program Files (x86)\World of Warcraft\_forever_\WTF\Account"
NAME = "UltimateAH.lua"


def load(path):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(open(path, encoding="utf-8").read())
    return to_py(lua.globals().UltimateAHDB)


def to_py(v):
    if lupa.lua_type(v) == "table":
        keys = list(v.keys())
        if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
            return [to_py(v[k]) for k in sorted(keys)]
        return {k: to_py(v[k]) for k in keys}
    return v


def lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


def ser(v, ind=0):
    pad = "\t" * (ind + 1)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(int(v)) if isinstance(v, float) and v.is_integer() and abs(v) < 2**53 else repr(v)
    if isinstance(v, str):
        return lua_str(v)
    if v is None:
        return "nil"
    if isinstance(v, list):
        if not v:
            return "{}"
        return "{\n" + "".join(f"{pad}{ser(x, ind + 1)}, -- [{i}]\n" for i, x in enumerate(v, 1)) + "\t" * ind + "}"
    if isinstance(v, dict):
        if not v:
            return "{}"
        out = []
        for k, x in v.items():
            key = f"[{lua_str(k)}]" if isinstance(k, str) else f"[{ser(k)}]"
            out.append(f"{pad}{key} = {ser(x, ind + 1)},\n")
        return "{\n" + "".join(out) + "\t" * ind + "}"
    raise TypeError(type(v))


def tx_key(r):
    return (r.get("t"), r.get("char"), r.get("type"), r.get("name") or r.get("item"), r.get("qty"), r.get("total"))


def merge(dbs):
    m = {"tx": [], "chars": {}, "prices": {}, "scans": {}, "invoices": {}, "listings": {}, "inv": {}, "value": {}}
    seen = set()
    for db in dbs:
        for r in db.get("tx", []) or []:
            k = tx_key(r)
            if k not in seen:
                seen.add(k)
                m["tx"].append(r)
        for ck, c in (db.get("chars") or {}).items():
            if ck not in m["chars"] or (c.get("lastSeen") or 0) > (m["chars"][ck].get("lastSeen") or 0):
                m["chars"][ck] = c
        for scope, items in (db.get("prices") or {}).items():
            dst = m["prices"].setdefault(scope, {})
            for key, e in items.items():
                old = dst.get(key)
                if not old or (e.get("t") or 0) > (old.get("t") or 0):
                    hist = dict((old or {}).get("h") or {})
                    hist.update(e.get("h") or {})
                    e = dict(e)
                    e["h"] = hist
                    dst[key] = e
                else:
                    hist = dict(e.get("h") or {})
                    hist.update(old.get("h") or {})
                    old["h"] = hist
        for scope, s in (db.get("scans") or {}).items():
            if scope not in m["scans"] or (s.get("t") or 0) > (m["scans"][scope].get("t") or 0):
                m["scans"][scope] = s
        for sig, times in (db.get("invoices") or {}).items():
            m["invoices"].setdefault(sig, [])
            for t in times or []:
                if t not in m["invoices"][sig]:
                    m["invoices"][sig].append(t)
        for name in ("listings", "inv"):
            for ck, v in (db.get(name) or {}).items():
                old = m[name].get(ck)
                tv = v.get("t") or v.get("bagsT") or 0
                to = (old or {}).get("t") or (old or {}).get("bagsT") or 0
                if not old or tv >= to:
                    m[name][ck] = v
        for ck, pts in (db.get("value") or {}).items():
            have = {p[0] for p in m["value"].get(ck, [])}
            m["value"].setdefault(ck, []).extend(p for p in pts or [] if p[0] not in have)
    m["tx"].sort(key=lambda r: r.get("t") or 0)
    for pts in m["value"].values():
        pts.sort(key=lambda p: p[0])
    return m


def main():
    dry = "--dry-run" in sys.argv
    files = sorted(glob.glob(os.path.join(WTF, "*", "SavedVariables", NAME)))
    if len(files) < 2:
        print("found", len(files), "account file(s) - nothing to merge (log in once on each account first)")
        for f in files:
            print("  ", f)
        return
    dbs = [load(f) for f in files]
    merged = merge(dbs)
    for f, db in zip(files, dbs):
        print(f"{f}: {len(db.get('tx') or [])} tx, chars {sorted((db.get('chars') or {}).keys())}")
    print(f"merged: {len(merged['tx'])} tx, chars {sorted(merged['chars'].keys())}")
    if dry:
        return
    for f, db in zip(files, dbs):
        out = dict(db)
        out.update(merged)               # keep each account's own settings / dev data
        shutil.copy2(f, f + ".sync-backup")
        with open(f, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\nUltimateAHDB = " + ser(out) + "\n")
        print("wrote", f)


if __name__ == "__main__":
    main()
