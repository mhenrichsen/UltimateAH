"""Small helper for UI passes: exact search/replace edits on addon files (fails loudly)."""
import os
import sys

ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AuctionLedger")
_cache = {}


def rep(fname, old, new, count=1):
    p = os.path.join(ADDON, fname)
    s = _cache.get(p) or open(p, encoding="utf-8").read()
    n = s.count(old)
    if n < 1 or (count == 1 and n != 1):
        sys.exit("%s: expected 1 match, found %d for:\n%s" % (fname, n, old[:200]))
    s = s.replace(old, new) if count != 1 else s.replace(old, new, 1)
    _cache[p] = s


def save():
    for p, s in _cache.items():
        open(p, "w", encoding="utf-8", newline="").write(s)
    print("saved", len(_cache), "file(s)")
