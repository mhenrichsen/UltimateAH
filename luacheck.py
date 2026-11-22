"""Syntax-check every .lua file of the addon with lupa (compile only)."""
import glob
import os
import sys

import lupa

ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "UltimateAH")
lua = lupa.LuaRuntime()
check = lua.eval("function(src, name) local f, err = (loadstring or load)(src, name); return err end")
bad = 0
for path in sorted(glob.glob(os.path.join(ADDON, "*.lua"))):
    src = open(path, encoding="utf-8").read()
    err = check(src, "@" + os.path.basename(path))
    if err:
        bad += 1
        print("ERROR", err)
    else:
        print("ok   ", os.path.basename(path))
sys.exit(1 if bad else 0)
