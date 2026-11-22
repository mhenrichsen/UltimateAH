-- Ultimate AH: auction house price scanning
--
-- Full scan   C_AuctionHouse.ReplicateItems(): every auction on the AH at once (server allows one per 15 min).
-- Quick scan  a blank browse query paged to the end: the lowest buyout and quantity of every item.
-- Passive     whatever you search for in the AH (or another addon scans) also refreshes that item's price.
local _, AL = ...
local S = {}
AL.Scanner = S

local AH = C_AuctionHouse
local REPLICATE_COOLDOWN = 15 * 60
local BUDGET_MS = 12

S.state = "idle"     -- idle | waiting | reading | browsing
S.progress = 0

local function today() return math.floor(time() / 86400) end

function S:Status(msg)
  self.msg = msg
  AL:Fire("AL_SCAN_STATUS", msg)
end

---------------------------------------------------------------------------
-- price statistics
---------------------------------------------------------------------------
-- entries: array of { unit, qty } ; returns min, market, totalQty, numAuctions
function S.Stats(entries)
  if #entries == 0 then return nil end
  -- equal prices: smaller lots first, so the result does not depend on the order they arrived in
  table.sort(entries, function(a, b) if a[1] ~= b[1] then return a[1] < b[1] end return a[2] < b[2] end)
  local total = 0
  for _, e in ipairs(entries) do total = total + e[2] end
  -- market value: the cheapest 15% of units, extended up to 30% while prices stay within 20%
  -- of the previous one, then outliers beyond 1.5 standard deviations are dropped
  local picked, cum, prev = {}, 0, nil
  for _, e in ipairs(entries) do
    local share = cum / total
    if #picked == 0 or share < 0.15 or (share < 0.30 and prev and e[1] <= prev * 1.2) then
      picked[#picked + 1] = e
      cum = cum + e[2]
      prev = e[1]
    else
      break
    end
  end
  local sum, n = 0, 0
  for _, e in ipairs(picked) do sum = sum + e[1] * e[2]; n = n + e[2] end
  local mean = sum / n
  local var = 0
  for _, e in ipairs(picked) do var = var + e[2] * (e[1] - mean) ^ 2 end
  local sd = math.sqrt(var / n)
  if sd > 0 then
    local s2, n2 = 0, 0
    for _, e in ipairs(picked) do
      if math.abs(e[1] - mean) <= 1.5 * sd then s2 = s2 + e[1] * e[2]; n2 = n2 + e[2] end
    end
    if n2 > 0 then mean = s2 / n2 end
  end
  return entries[1][1], math.floor(mean + 0.5), total, #entries, S.Top(entries, 100)
end

-- average unit price of the cheapest `n` auctions (entries already sorted), outliers beyond
-- 1.5 standard deviations dropped
function S.Top(entries, n)
  local k = math.min(n or 100, #entries)
  if k == 0 then return nil end
  local sum, q = 0, 0
  for i = 1, k do sum = sum + entries[i][1] * entries[i][2]; q = q + entries[i][2] end
  local mean = sum / q
  local var = 0
  for i = 1, k do var = var + entries[i][2] * (entries[i][1] - mean) ^ 2 end
  local sd = math.sqrt(var / q)
  if sd > 0 then
    local s2, q2 = 0, 0
    for i = 1, k do
      if math.abs(entries[i][1] - mean) <= 1.5 * sd then s2 = s2 + entries[i][1] * entries[i][2]; q2 = q2 + entries[i][2] end
    end
    if q2 > 0 then mean = s2 / q2 end
  end
  return math.floor(mean + 0.5)
end

---------------------------------------------------------------------------
-- price storage
---------------------------------------------------------------------------
function S:Prices(scope)
  scope = scope or AL:Scope()
  AL.db.prices[scope] = AL.db.prices[scope] or {}
  return AL.db.prices[scope]
end

-- history prices keep three significant digits: plenty for averages and graphs, and it keeps the
-- number of different values in the saved data small (the game's Lua allows ~262,000 per file)
local function sig3(v)
  v = math.floor(v + 0.5)
  if v < 1000 then return v end
  local m = 10 ^ (#tostring(v) - 3)
  return math.floor(v / m + 0.5) * m
end
S.Sig3 = sig3

function S:Store(key, itemID, name, min, mkt, qty, num, t, top)
  local p = self:Prices()
  local e = p[key] or {}
  e.i = itemID
  e.n = name or e.n
  e.min, e.mkt, e.qty, e.num, e.t = min, mkt or e.mkt or min, qty, num, t or time()
  if top then e.top = top end
  e.h = e.h or {}
  local d = today()
  local h = e.h[d]
  if h then
    h[1] = sig3((h[1] + e.mkt) / 2)                  -- several scans on one day: running blend
    h[2] = math.min(h[2], sig3(min))
  else
    e.h[d] = { sig3(e.mkt), sig3(min) }
  end
  p[key] = e
  return e
end

function S:PruneHistory()
  local keep = today() - (AL.db.settings.historyDays or 30)
  for _, scope in pairs(AL.db.prices) do
    for _, e in pairs(scope) do
      if e.h then for d in pairs(e.h) do if d < keep then e.h[d] = nil end end end
    end
  end
end

-- mean of the daily market values (default 14 days)
function S.HistoryAvg(e, days)
  if not e or not e.h then return nil end
  local from = today() - (days or 14)
  local s, n = 0, 0
  for d, h in pairs(e.h) do if d > from then s = s + h[1]; n = n + 1 end end
  return n > 0 and math.floor(s / n + 0.5) or nil
end

function S:Get(key, scope)
  local p = AL.db.prices[scope or AL:Scope()]
  return p and p[tostring(key)]
end

-- price entry for an item link or id (falls back from suffix key to the plain item)
function S:ForItem(linkOrID)
  local id = AL.ItemID(linkOrID)
  if not id then return nil end
  local key = AL.KeyFromLink(type(linkOrID) == "string" and linkOrID or nil, id)
  return self:Get(key) or self:Get(id)
end

---------------------------------------------------------------------------
-- full scan (replicate)
---------------------------------------------------------------------------
function S:LastReplicate()
  local s = AL.db.scans[AL:Scope()]
  return s and s.replicate or 0
end

function S:ReplicateReadyIn()
  return math.max(0, REPLICATE_COOLDOWN - (time() - self:LastReplicate()))
end

function S:Full()
  if not AL.ahOpen then AL:Print("open the auction house first"); return end
  if self.state ~= "idle" then AL:Print("a scan is already running"); return end
  local wait = self:ReplicateReadyIn()
  if wait > 0 then
    AL:Print(string.format("full scan allowed again in %d:%02d (server limit: one per 15 minutes) - use Quick Scan meanwhile",
      math.floor(wait / 60), wait % 60))
    return
  end
  self.state = "waiting"
  self.requested = true
  AL.db.scans[AL:Scope()] = AL.db.scans[AL:Scope()] or {}
  AL.db.scans[AL:Scope()].replicate = time()
  self:Status("Full scan: waiting for the server...")
  AH.ReplicateItems()
  -- give up if the server never answers
  local token = {}
  self.token = token
  C_Timer.After(90, function()
    if self.token == token and self.state == "waiting" then
      self.state = "idle"
      self:Status("Full scan: no answer from the server")
    end
  end)
end

function S:ReadReplicate()
  if self.state == "reading" then return end
  local n = AH.GetNumReplicateItems() or 0
  if n == 0 then
    self.state = "idle"
    self:Status("Full scan: the server returned no auctions")
    return
  end
  self.state = "reading"
  local agg, names, ids = {}, {}, {}
  local i = 0
  local started = debugprofilestop()
  local perf = { steps = 0, busy = 0, n = n, bad = 0, mine = 0 }
  self.perf = perf
  local mineNames = AL:MyNameSet()
  local function readOne(idx)
    local name, _, count, _, _, _, _, _, _, buyout, _, _, _, owner, ownerFull, _, itemID, hasAll = AH.GetReplicateItemInfo(idx)
    if itemID and count and count > 0 and buyout and buyout > 0 then
      local plain = tostring(itemID)
      local mine = AL.IsMineName(mineNames, ownerFull, owner)
      if mine then perf.mine = perf.mine + 1 end
      local e = { buyout / count, count, mine or nil }
      local list = agg[plain]
      if not list then list = {}; agg[plain] = list; ids[plain] = itemID end
      list[#list + 1] = e
      -- variants (random-suffix gear) also get a price of their own
      local link = hasAll and AH.GetReplicateItemLink(idx)
      local key = link and AL.KeyFromLink(link, itemID)
      if key and key ~= plain then
        local vl = agg[key]
        if not vl then vl = {}; agg[key] = vl; ids[key] = itemID end
        vl[#vl + 1] = e
        local vname = link:match("|h%[(.-)%]|h")
        if vname then names[key] = vname end
      elseif name and name ~= "" then
        names[plain] = name
      end
    end
  end
  -- read for at most BUDGET ms per frame so the game keeps running smoothly; one bad
  -- auction must not stop the whole scan, so each read is protected
  local function step()
    local t0 = debugprofilestop()
    perf.steps = perf.steps + 1
    while i < n and debugprofilestop() - t0 < BUDGET_MS do
      local stop = math.min(i + 200, n)
      while i < stop do
        local ok, err = pcall(readOne, i)
        if not ok then
          perf.bad = perf.bad + 1
          if perf.bad <= 3 then AL:Error("replicate #" .. i, err) end
        end
        i = i + 1
      end
    end
    perf.busy = perf.busy + (debugprofilestop() - t0)
    self.progress = i / n
    self:Status(string.format("Full scan: reading %d / %d auctions", i, n))
    if i < n then
      C_Timer.After(0, function()
        local ok, err = pcall(step)
        if not ok then
          AL:Error("full scan", err)
          self.state = "idle"
          self:Status("Full scan failed: " .. tostring(err))
        end
      end)
    else
      self:FinishAgg(agg, names, ids, n, "full", started)
    end
  end
  step()
end

AL:Command("reread", nil, function() S:ReadReplicate() end)

function S:FinishAgg(agg, names, ids, auctions, kind, started)
  local t = time()
  local items = 0
  local keys = {}
  for key in pairs(agg) do keys[#keys + 1] = key end
  local k = 0
  -- every auction of the scan, per item, kept for this session (the deal finder walks it)
  self.last = { t = t, items = {} }
  local keep = self.last.items
  self:Status("Full scan: calculating prices...")
  -- price math is chunked as well (300k+ auctions)
  local function step()
    local t0 = debugprofilestop()
    while k < #keys and debugprofilestop() - t0 < BUDGET_MS do
      k = k + 1
      local key = keys[k]
      local min, mkt, qty, num, top = S.Stats(agg[key])
      if min then
        local name = names[key] or AL.ItemName(ids[key])
        local e = self:Store(key, ids[key], name, math.floor(min + 0.5), mkt, qty, num, t, top)
        e.fullT = t
        -- lowest price from other sellers (for undercut checks)
        e.minOther = nil
        for _, x in ipairs(agg[key]) do
          if not x[3] then e.minOther = math.floor(x[1] + 0.5); break end
        end
        items = items + 1
        keep[key] = agg[key]                                           -- sorted by S.Stats
      end
      agg[key] = nil
    end
    if self.perf then self.perf.busy = self.perf.busy + (debugprofilestop() - t0); self.perf.steps = self.perf.steps + 1 end
    if k < #keys then
      C_Timer.After(0, function()
        local ok, err = pcall(step)
        if not ok then AL:Error("full scan prices", err); self.state = "idle"; self:Status("Full scan failed: " .. tostring(err)) end
      end)
      return
    end
    local sc = AL.db.scans[AL:Scope()] or {}
    sc.t, sc.kind, sc.auctions, sc.items = t, kind, auctions, items
    sc.fullT = t
    AL.db.scans[AL:Scope()] = sc
    self.state = "idle"
    self.progress = 1
    local secs = started and (debugprofilestop() - started) / 1000 or 0
    self:Status(string.format("Full scan done: %d auctions, %d items (%.0fs)", auctions, items, secs))
    if self.perf then self.perf.secs = secs end
    AL:Print(self.msg)
    AL:Fire("AL_SCAN_DONE", kind)
  end
  step()
end

AL:On("REPLICATE_ITEM_LIST_UPDATE", function()
  -- also fires for replicate scans started by other addons (e.g. Auctionator): use those too
  -- one reader at a time: the event can fire twice, and another addon may re-request right after
  if S.state == "reading" or S.state == "browsing" or S.state == "deep" or S.readQueued then return end
  if not S.requested then
    AL.db.scans[AL:Scope()] = AL.db.scans[AL:Scope()] or {}
    AL.db.scans[AL:Scope()].replicate = time()
  end
  S.requested = false
  S.readQueued = true
  C_Timer.After(0.2, function() S.readQueued = false; S:ReadReplicate() end)
end)

hooksecurefunc(AH, "ReplicateItems", function()
  if S.state == "idle" then
    AL.db.scans[AL:Scope()] = AL.db.scans[AL:Scope()] or {}
    AL.db.scans[AL:Scope()].replicate = time()
  end
end)

---------------------------------------------------------------------------
-- quick scan (browse everything, lowest price per item)
---------------------------------------------------------------------------
function S:Quick()
  if not AL.ahOpen then AL:Print("open the auction house first"); return end
  if self.state ~= "idle" then AL:Print("a scan is already running"); return end
  self.state = "browsing"
  self.browse = { agg = {}, names = {}, ids = {}, seen = 0, started = debugprofilestop(), last = GetTime() }
  self:Status("Quick scan: searching...")
  local query = { searchString = "", sorts = { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } },
                  filters = {}, itemClassFilters = {} }
  local ok, err = pcall(AH.SendBrowseQuery, query)
  if not ok then
    self.state = "idle"
    self:Status("Quick scan failed: " .. tostring(err))
    return
  end
  self:WatchBrowse()
end

function S:WatchBrowse()
  local b = self.browse
  if not b then return end
  C_Timer.After(5, function()
    if self.browse == b and self.state == "browsing" and GetTime() - b.last > 15 then
      self:FinishBrowse()          -- server went quiet: keep what we have
    elseif self.browse == b and self.state == "browsing" then
      self:WatchBrowse()
    end
  end)
end

function S:AbsorbBrowse(results)
  local b = self.browse
  for _, r in ipairs(results or {}) do
    local k = r.itemKey
    if k and k.itemID and r.minPrice and r.minPrice > 0 then
      -- browse rows carry a suffix number that does not match item links: price per item
      -- (lowest over its variants, quantities summed)
      local key = tostring(k.itemID)
      if b then
        local cur = b.agg[key]
        if not cur then
          b.seen = b.seen + 1
          b.agg[key] = { r.minPrice, r.totalQuantity or 1 }
        else
          cur[1] = math.min(cur[1], r.minPrice)
          cur[2] = cur[2] + (r.totalQuantity or 1)
        end
        b.ids[key] = k.itemID
      else
        -- passive (the player browsing): refresh the lowest price, keep the market value.
        -- Several rows (variants) can share an item: within one batch keep the lowest.
        local e = self:Get(key)
        local now = time()
        local min = r.minPrice
        if e and e.browseT == now and e.min and e.min < min then min = e.min end
        local mkt = e and e.mkt and e.t and now - e.t < 86400 and e.mkt or min
        local stored = self:Store(key, k.itemID, e and e.n or AL.ItemName(k.itemID), min, math.max(mkt, min), r.totalQuantity, e and e.num, now)
        stored.browseT = now
      end
    end
  end
end

function S:NextBrowsePage()
  if self.state ~= "browsing" then return end
  self.browse.last = GetTime()
  if AH.HasFullBrowseResults() then
    self:FinishBrowse()
    return
  end
  self:Status(string.format("Quick scan: %d items so far...", self.browse.seen))
  if AH.IsThrottledMessageSystemReady() then
    AH.RequestMoreBrowseResults()
  else
    self.browse.waitThrottle = true
  end
end

function S:FinishBrowse()
  local b = self.browse
  self.browse = nil
  if not b then return end
  local agg = {}
  for key, v in pairs(b.agg) do agg[key] = { { v[1], v[2] } } end
  -- a browse only knows the lowest price: keep a recent full-scan market value if there is one
  local t = time()
  local items = 0
  for key, list in pairs(agg) do
    local min, qty = list[1][1], list[1][2]
    local e = self:Get(key)
    local mkt = (e and e.mkt and e.fullT and t - e.fullT < 2 * 86400) and math.max(e.mkt, min) or min
    local stored = self:Store(key, b.ids[key], e and e.n or AL.ItemName(b.ids[key]), min, mkt, qty, e and e.num, t)
    stored.fullT = e and e.fullT
    items = items + 1
  end
  local sc = AL.db.scans[AL:Scope()] or {}
  sc.t, sc.kind, sc.auctions, sc.items = t, "quick", items, items
  AL.db.scans[AL:Scope()] = sc
  self.state = "idle"
  local secs = (debugprofilestop() - b.started) / 1000
  self:Status(string.format("Quick scan done: %d items (%.1fs)", items, secs))
  AL:Print(self.msg)
  AL:Fire("AL_SCAN_DONE", "quick")
end

AL:On("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED", function()
  local res = AH.GetBrowseResults()
  S:AbsorbBrowse(res)
  if S.state == "browsing" then S:NextBrowsePage() end
end)
AL:On("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", function(added)
  S:AbsorbBrowse(added)
  if S.state == "browsing" then S:NextBrowsePage() end
end)
AL:On("AUCTION_HOUSE_THROTTLED_SYSTEM_READY", function()
  if S.state == "browsing" and S.browse and S.browse.waitThrottle then
    S.browse.waitThrottle = false
    AH.RequestMoreBrowseResults()
  end
end)
AL:On("AUCTION_HOUSE_BROWSE_FAILURE", function()
  if S.state == "browsing" then S:FinishBrowse() end
end)

---------------------------------------------------------------------------
-- passive: exact prices from item / commodity searches
---------------------------------------------------------------------------
AL:On("COMMODITY_SEARCH_RESULTS_UPDATED", function(itemID)
  if not itemID then return end
  local n = AH.GetNumCommoditySearchResults(itemID) or 0
  if n == 0 then return end
  local list = {}
  for i = 1, n do
    local r = AH.GetCommoditySearchResultInfo(itemID, i)
    if r and r.unitPrice and r.unitPrice > 0 then
      local mine = r.containsOwnerItem and (r.numOwnerItems or 0) >= (r.quantity or 1)
      list[#list + 1] = { r.unitPrice, r.quantity or 1, mine or nil }
    end
  end
  local min, mkt, qty, num, top = S.Stats(list)
  if not min then return end
  if not AH.HasFullCommoditySearchResults(itemID) then
    qty = AH.GetCommoditySearchResultsQuantity(itemID) or qty
  end
  local e = S:Store(tostring(itemID), itemID, AL.ItemName(itemID), min, mkt, qty, num, time(), top)
  e.fullT = time()
  e.minOther = nil
  for _, x in ipairs(list) do if not x[3] then e.minOther = x[1]; break end end
  AL:Fire("AL_PRICE", tostring(itemID), list)
end)

AL:On("ITEM_SEARCH_RESULTS_UPDATED", function(itemKey)
  if not itemKey or not itemKey.itemID then return end
  local n = AH.GetNumItemSearchResults(itemKey) or 0
  local groups = {}
  for i = 1, n do
    local r = AH.GetItemSearchResultInfo(itemKey, i)
    if r and r.buyoutAmount and r.buyoutAmount > 0 then
      local q = r.quantity or 1
      local key = AL.KeyFromLink(r.itemLink, itemKey.itemID)
      groups[key] = groups[key] or {}
      table.insert(groups[key], { r.buyoutAmount / q, q, r.containsOwnerItem or nil })
    end
  end
  for key, list in pairs(groups) do
    local min, mkt, qty, num, top = S.Stats(list)
    if min then
      local e = S:Store(key, itemKey.itemID, AL.ItemName(itemKey.itemID), math.floor(min + 0.5), mkt, qty, num, time(), top)
      e.fullT = time()
      e.minOther = nil
      for _, x in ipairs(list) do if not x[3] then e.minOther = math.floor(x[1] + 0.5); break end end
      AL:Fire("AL_PRICE", key, list)
    end
  end
end)

---------------------------------------------------------------------------
-- deep scan: search each of *your* items (ledger, listings, bags) one by one and price it
-- from its cheapest 100 auctions (the passive handlers above do the maths per result)
---------------------------------------------------------------------------
function S:DeepItems()
  local want, list = {}, {}
  local function add(id)
    if id and not want[id] then want[id] = true; list[#list + 1] = id end
  end
  local since = time() - 90 * 86400
  for _, r in ipairs(AL.db.tx) do
    if (r.t or 0) > since then add(r.item or AL:IdForName(r.name)) end
  end
  for _, snap in pairs(AL.db.listings or {}) do
    for _, a in ipairs(snap.list or {}) do add(a.id) end
  end
  -- bag items that are on the AH (known from a scan) and not soulbound
  local prices = AL.db.prices[AL:Scope()] or {}
  for bag = 0, (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) do
    for slot = 1, C_Container.GetContainerNumSlots(bag) or 0 do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and info.itemID and not info.isBound and prices[tostring(info.itemID)] then add(info.itemID) end
    end
  end
  return list
end

function S:Deep()
  if not AL.ahOpen then AL:Print("open the auction house first"); return end
  if self.state ~= "idle" then AL:Print("a scan is already running"); return end
  local items = self:DeepItems()
  if #items == 0 then AL:Print("deep scan: no items yet (it scans the items in your ledger, listings and bags)"); return end
  self.state = "deep"
  self.deep = { items = items, i = 0, done = 0, started = debugprofilestop() }
  self:Status(string.format("Deep scan: 0 / %d items", #items))
  self:DeepNext()
end

function S:DeepNext()
  local d = self.deep
  if not d or self.state ~= "deep" then return end
  if d.i >= #d.items then
    self.state = "idle"
    self.deep = nil
    local secs = (debugprofilestop() - d.started) / 1000
    self:Status(string.format("Deep scan done: %d of %d items priced (%.0fs)", d.done, #d.items, secs))
    AL:Print(self.msg)
    AL:Fire("AL_SCAN_DONE", "deep")
    return
  end
  if not AH.IsThrottledMessageSystemReady() then
    d.waitSince = d.waitSince or GetTime()
    if GetTime() - d.waitSince > 30 then
      self.state = "idle"
      self.deep = nil
      self:Status(string.format("Deep scan stopped: the auction house is not answering searches (%d / %d done). Try again later.", d.done, #d.items))
      AL:Print(self.msg)
      return
    end
    d.waitThrottle = true
    C_Timer.After(1, function() if self.deep == d and d.waitThrottle then d.waitThrottle = false; self:DeepNext() end end)
    return
  end
  d.waitSince = nil
  d.i = d.i + 1
  local id = d.items[d.i]
  d.current = id
  local token = {}
  d.token = token
  local key = AH.MakeItemKey(id)
  local ok = pcall(AH.SendSearchQuery, key, { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } }, true)
  self:Status(string.format("Deep scan: %d / %d items", d.i, #d.items))
  -- move on when the result arrives, or after 4 s without one (item not listed)
  C_Timer.After(ok and 4 or 0, function()
    if self.deep == d and d.token == token then self:DeepNext() end
  end)
end

local function deepGotResult(itemID)
  local d = S.deep
  if not d or S.state ~= "deep" or d.current ~= itemID then return end
  d.done = d.done + 1
  d.current = nil            -- several result events per item: count it once
  d.token = nil
  C_Timer.After(0.15, function() if S.deep == d then S:DeepNext() end end)
end

AL:On("AL_PRICE", function(key) deepGotResult(tonumber((tostring(key):match("^(%d+)")))) end)

AL:On("AUCTION_HOUSE_THROTTLED_SYSTEM_READY", function()
  local d = S.deep
  if d and d.waitThrottle then d.waitThrottle = false; S:DeepNext() end
end)

---------------------------------------------------------------------------
-- AH open/close + auto scan
---------------------------------------------------------------------------
AL:On("AUCTION_HOUSE_SHOW", function()
  AL.ahOpen = true
  if AL.db.settings.autoScan and S:ReplicateReadyIn() == 0 then
    C_Timer.After(2, function() if AL.ahOpen and S.state == "idle" then S:Full() end end)
  end
end)

AL:On("AUCTION_HOUSE_CLOSED", function()
  AL.ahOpen = false
  if S.state == "waiting" then
    S.state = "idle"
    S:Status("Full scan: cancelled (auction house closed)")
  elseif S.state == "browsing" then
    S:FinishBrowse()
  elseif S.state == "deep" then
    S.state = "idle"
    S.deep = nil
    S:Status("Deep scan: stopped (auction house closed)")
  end
end)

AL:On("AL_DB_READY", function() S:PruneHistory() end)

AL:Command("scan", "full auction house scan ('/uah scan quick', '/uah scan deep')", function(arg)
  if arg == "quick" then S:Quick() elseif arg == "deep" then S:Deep() else S:Full() end
end)
AL:Command("autoscan", "toggle a full scan each time you open the AH (when allowed)", function()
  AL.db.settings.autoScan = not AL.db.settings.autoScan
  AL:Print("auto scan", AL.db.settings.autoScan and "on" or "off")
end)
