"""Copy the addon from this repository into the game's AddOns folder.

    python deploy.py                 uses the standard install path (or "wow_dir" from blizzard_api.json)
    python deploy.py "D:\\Games\\World of Warcraft\\_forever_"

ApiData.lua in the game folder is left alone: that is the data file ah_api.py writes.
New files need a full game restart; changed files are picked up by /reload.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "UltimateAH")
WOW = r"C:\Program Files (x86)\World of Warcraft\_forever_"


def main():
    wow = WOW
    cfg = os.path.join(HERE, "blizzard_api.json")
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8") as f:
            wow = json.load(f).get("wow_dir") or wow
    if len(sys.argv) > 1:
        wow = sys.argv[1]
    dst = os.path.join(wow, "Interface", "AddOns", "UltimateAH")
    if not os.path.isdir(os.path.join(wow, "Interface", "AddOns")):
        sys.exit("no AddOns folder under " + wow)
    os.makedirs(dst, exist_ok=True)
    n = 0
    for name in sorted(os.listdir(SRC)):
        s, d = os.path.join(SRC, name), os.path.join(dst, name)
        if not os.path.isfile(s):
            continue
        if name == "ApiData.lua" and os.path.exists(d):
            continue                          # keep the scanned data
        if not os.path.exists(d) or open(s, "rb").read() != open(d, "rb").read():
            shutil.copyfile(s, d)
            n += 1
            print("copied", name)
    print("%d file(s) updated in %s" % (n, dst))


if __name__ == "__main__":
    main()
