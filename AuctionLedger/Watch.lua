-- AuctionLedger: watchlist / sniper
--
-- Each watched item has a max price per unit. Whenever we see auctions (full scan, quick scan, or
-- any AH search you do) listed at or below it, you get a chat line, an on-screen warning and a
-- sound. Your own auctions never trigger it.
local _, AL = ...
local Wt = {}
AL.Watch = Wt

local REPEAT = 600      -- don't repeat an alert for the same item within 10 minutes unless cheaper

function Wt:List()
  AL.db.watch = AL.db.watch or {}
  return AL.db.watch
end

-- "40g", "1g 50s", "35s20c", "2.5" (gold) -> copper
function AL.ParseMoney(s)
  if type(s) ~= "string" then return nil end
  s = s:lower():gsub("%s+", "")
  if s == "" then return nil end
  local n = tonumber(s)
  if n then return math.floor(n * 10000 + 0.5) end
  local total, found = 0, false
  for num, unit in s:gmatch("(%d+%.?%d*)([gsc])") do
    found = true
    local v = tonumber(num)
    total = total + (unit == "g" and v * 10000 or unit == "s" and v * 100 or v)
  end
  return found and math.floor(total + 0.5) or nil
end

-- item from a link, an ID or a (partial) name known to the price data -> id, name
function Wt:Resolve(text)
  text = (text or ""):gsub("^%s+", ""):gsub("%s+$", "")
  if text == "" then return nil end
  if text:find("|Hitem:") or text:match("^%d+$") then
    local id = AL.ItemID(text)
    return id, AL.ItemName(id, text:find("|H") and text or nil) or ("item " .. id)
  end
  local e = AL.Guild and AL.Guild:Find(text)
  if e and e.i then return e.i, e.n or AL.ItemName(e.i) end
  if C_Item.GetItemInfoInstant then
    local id = C_Item.GetItemInfoInstant(text)
    if type(id) == "number" then return id, AL.ItemName(id) or text end
  end
  return nil
end

function Wt:Add(id, name, max)
  self:List()[tostring(id)] = { id = id, name = name, max = max, added = time() }
  AL:Fire("AL_WATCH")
end

function Wt:Remove(id)
  self:List()[tostring(id)] = nil
  AL:Fire("AL_WATCH")
end

function Wt:For(key)
  local list = self:List()
  return list[tostring(key)] or list[tostring(key):match("^(%d+)") or ""]
end

function Wt:Alert(w, qty, cheapest, source)
  local t = time()
  if w.lastAlert and t - w.lastAlert < REPEAT and cheapest >= (w.lastPrice or 0) then return end
  w.lastAlert, w.lastPrice = t, cheapest
  w.hit = { t = t, qty = qty, price = cheapest, source = source }
  local msg = string.format("|cff59ff59Watchlist:|r %s - %s at or under your %s (cheapest %s)%s",
    w.name or ("item " .. w.id), qty and (qty .. " listed") or "listed", AL.Money(w.max, true), AL.Money(cheapest, true),
    source and (" - " .. source) or "")
  AL:Print(msg)
  if AL.db.settings.watchAlert ~= false then
    pcall(RaidNotice_AddMessage, RaidWarningFrame, "AuctionLedger: " .. (w.name or "watched item") .. " at " ..
      AL.Money(cheapest, true), ChatTypeInfo and ChatTypeInfo.RAID_WARNING or { r = 1, g = 1, b = 0 })
    pcall(PlaySound, (SOUNDKIT and SOUNDKIT.RAID_WARNING) or 8959, "Master")
  end
  AL:Fire("AL_WATCH")
end

-- entries: { unit, qty, mine } (any order)
function Wt:Check(key, entries, source)
  local w = self:For(key)
  if not w or not w.max or not entries then return end
  local qty, cheapest = 0, nil
  for _, x in ipairs(entries) do
    if not x[3] and x[1] <= w.max then
      qty = qty + (x[2] or 1)
      if not cheapest or x[1] < cheapest then cheapest = x[1] end
    end
  end
  if qty > 0 then self:Alert(w, qty, math.floor(cheapest + 0.5), source) end
end

-- after a scan, or when results arrive while you search the AH
AL:On("AL_SCAN_DONE", function(kind)
  local list = Wt:List()
  if not next(list) then return end
  if kind == "full" and AL.Scanner.last then
    for key, w in pairs(list) do Wt:Check(key, AL.Scanner.last.items[key], "full scan") end
  else
    for key, w in pairs(list) do
      local e = AL.Scanner:Get(key)
      if e and e.min and e.t and time() - e.t < 120 and e.min <= w.max then
        Wt:Alert(w, nil, e.min, kind .. " scan")
      end
    end
  end
end)

AL:On("AL_PRICE", function(key, entries) Wt:Check(key, entries, "AH search") end)

---------------------------------------------------------------------------
-- commands
---------------------------------------------------------------------------
AL:Command("watch", "watch an item: /al watch <item> <max price, e.g. 40g or 1g50s>", function(arg)
  if arg == "" then AL.UI:Toggle("Watch"); return end
  -- the price is the last word (or two: "1g 50s")
  local item, price = arg:match("^(.-)%s+([%d%.]+[gsc]?%s*[%d%.]*[gsc]?)$")
  local max = price and AL.ParseMoney(price)
  if not item or not max then AL:Print("usage: /al watch <item name or link> <max price per item, e.g. 40g>"); return end
  local id, name = Wt:Resolve(item)
  if not id then AL:Print("unknown item:", item, "(use a shift-clicked link or scan the AH first)"); return end
  Wt:Add(id, name, max)
  AL:Print(string.format("watching %s at %s or less", name, AL.Money(max, true)))
end)

AL:Command("unwatch", "stop watching an item: /al unwatch <item>", function(arg)
  local id, name = Wt:Resolve(arg)
  if id and Wt:List()[tostring(id)] then Wt:Remove(id); AL:Print("stopped watching", name)
  else AL:Print("not on the watchlist:", arg) end
end)
