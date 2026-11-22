-- Ultimate AH: auto scans from Blizzard's web API
--
-- An addon cannot reach the internet. ah_api.py (run every hour by a scheduled task, outside the
-- game) downloads the auction house from Blizzard's API and writes ApiData.lua into this folder;
-- this file merges it into the price data at login or /reload. Besides prices it brings the one
-- thing the game never tells you: an estimate of how many units of each item are sold per day.
local _, AL = ...
local A = {}
AL.Api = A

local BUDGET_MS = 10

local function today() return math.floor(time() / 86400) end

-- what the last import brought: { t, items, auctions, house, soldHours }
function A:Info()
  local sc = AL.db.scans[AL:Scope()]
  return sc and sc.api
end

-- units sold per day (estimate), nil when there is no recent API data for the item
function A.SoldPerDay(e)
  if not e or not e.sold or not e.soldT then return nil end
  if time() - e.soldT > 3 * 86400 then return nil end
  return e.sold
end

function A.SoldText(n)
  if not n then return "" end
  if n <= 0 then return "|cff5c6170\226\128\148|r" end
  if n >= 10 then return BreakUpLargeNumbers and BreakUpLargeNumbers(math.floor(n + 0.5)) or tostring(math.floor(n + 0.5)) end
  return string.format("%.1f", n)
end

-- an item arrives as one string, "min,market,qty,auctions,top100,lowestOther,soldPerDay,day,market,min,...":
-- the game's Lua allows about 262,000 different constants per file, and 26,000 items written as
-- tables of numbers would come close; as strings the file stays far below that whatever it holds
local function parse(s)
  local v, n = {}, 0
  for x in s:gmatch("[^,]+") do n = n + 1; v[n] = tonumber(x) or 0 end
  return v
end

local function merge(prices, key, v, d, keepFrom, rates)
  v = parse(v)
  local id = tonumber(key:match("^(%d+)"))
  local has = (v[1] or 0) > 0            -- on the auction house right now
  local e = prices[key]
  if not e then
    if not has and (v[7] or 0) <= 0 then return false end
    e = { i = id, h = {} }
    prices[key] = e
  end
  e.i = e.i or id
  e.h = e.h or {}
  local fresh = false
  if (e.t or 0) < d.t then               -- an in-game scan newer than the API data wins
    if has then
      e.min, e.mkt, e.qty, e.num, e.t = v[1], v[2], v[3], v[4], d.t
      e.top = (v[5] or 0) > 0 and v[5] or nil
      e.minOther = (v[6] or 0) > 0 and v[6] or nil
      e.fullT, e.src = d.t, "api"
      fresh = true
    else
      e.qty, e.num = 0, 0                 -- sold out
    end
  end
  if rates then e.sold, e.soldT = v[7] or 0, d.t end
  local pat = d.ins and d.ins[key]
  if pat then e.ins, e.insT = parse(pat), d.t else e.ins, e.insT = nil, nil end
  for j = 8, #v - 2, 3 do                 -- daily history: day, market, min
    if v[j] > keepFrom then e.h[v[j]] = { v[j + 1], v[j + 2] } end
  end
  return fresh
end

---------------------------------------------------------------------------
-- price patterns
--
-- The server scan keeps 30 days of history and works out, per item: the trend of the last week,
-- where today's price sits in the month, the weekday and the hour of the day the item is usually
-- cheapest and dearest, when it sells, and (once it has proven better than "the price stays the
-- same") a forecast for a week ahead. They arrive as ApiData's "ins" table; e.ins holds the numbers
-- in the order of FIELDS. Weekdays and hours are UTC on the wire.
---------------------------------------------------------------------------
local FIELDS = { "days", "pos", "trend", "wdLo", "wdLoPct", "wdHi", "wdHiPct", "hrLo", "hrHi", "hrPct", "hrSell", "in7" }
local DAY_NAME = { [0] = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday" }
local DAY_SHORT = { [0] = "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun" }
local STEADY = 10                          -- under 1% a day reads as "steady"

local function fresh(e)
  return e and e.ins and e.insT and time() - e.insT <= 3 * 86400
end

-- the patterns of one price entry as a table with the FIELDS names; nil without recent server data.
-- trend is nil when the last week has too few prices
function A.Insight(e)
  if not fresh(e) then return nil end
  local p = {}
  for i, name in ipairs(FIELDS) do p[name] = e.ins[i] or 0 end
  if p.trend == 9999 then p.trend = nil end
  return p
end

-- the trend alone (tenths of a percent per day), without building a table: the Prices page asks for every item
function A.Trend(e)
  if not fresh(e) then return nil end
  local tr = e.ins[3]
  if not tr or tr == 9999 then return nil end
  return tr
end

function A.TrendText(tr)
  if not tr then return "" end
  local W = AL.W
  if math.abs(tr) < STEADY then return (W and W.MUTED or "") .. "steady|r" end
  return (tr > 0 and ((W and W.GREEN or "") .. "+") or (W and W.RED or "")) .. string.format("%.1f%%", tr / 10) .. "|r"
end

local function span(p)
  return p.days >= 25 and "the month" or ("the last " .. p.days .. " days")
end

-- an hour of the day on the wire (UTC) as the player's clock shows it
local function clock(h)
  local off = (tonumber(date("%H")) - tonumber(date("!%H"))) % 24
  return string.format("%02d:00", (h + off) % 24)
end

local function utcWeekday()
  return (math.floor(time() / 86400) + 3) % 7             -- 0 = Monday
end

-- lines for a tooltip or a row's hint: { { label, text }, ... }
function A.InsightLines(e)
  local p = A.Insight(e)
  if not p then return nil end
  local out = {}
  local where = (p.pos >= 85 and ("high for " .. span(p))) or (p.pos <= 15 and ("low for " .. span(p))) or nil
  if p.trend or where then
    local t = p.trend and A.TrendText(p.trend) or ""
    if p.trend and math.abs(p.trend) >= STEADY then t = t .. " a day" end
    out[#out + 1] = { "Trend", t .. ((t ~= "" and where) and ", " or "") .. (where or "") }
  end
  local wd = {}
  if p.wdLo >= 0 then wd[#wd + 1] = string.format("cheapest %s (%d%%)", DAY_SHORT[p.wdLo], p.wdLoPct) end
  if p.wdHi >= 0 then wd[#wd + 1] = string.format("dearest %s (+%d%%)", DAY_SHORT[p.wdHi], p.wdHiPct) end
  if #wd > 0 then out[#out + 1] = { "Usually", table.concat(wd, ", ") } end
  local hr = {}
  if p.hrLo >= 0 then hr[#hr + 1] = string.format("cheapest ~%s, dearest ~%s", clock(p.hrLo), clock(p.hrHi)) end
  if p.hrSell >= 0 then hr[#hr + 1] = "sells most ~" .. clock(p.hrSell) end
  if #hr > 0 then out[#out + 1] = { "By hour", table.concat(hr, ", ") } end
  if p.in7 > 0 then out[#out + 1] = { "In 7 days", "~" .. AL.Money(p.in7) } end
  return out
end

-- one short hint for someone about to sell this item -> text, "green" (a good moment) or "gold"
-- (waiting may pay) or "muted"; nil when the history has nothing to say
function A.SellAdvice(e)
  local p = A.Insight(e)
  if not p then return nil end
  if p.wdHi >= 0 and p.wdHiPct >= 5 then
    local ahead = (p.wdHi - utcWeekday()) % 7
    if ahead == 0 then return "usually dearest today (" .. DAY_NAME[p.wdHi] .. ")", "green" end
    if ahead <= 3 then return string.format("usually %d%% higher on %s", p.wdHiPct, DAY_NAME[p.wdHi]), "gold" end
  end
  local up, down = p.trend and p.trend >= STEADY, p.trend and p.trend <= -STEADY
  if p.pos >= 85 then return "high for " .. span(p) .. (up and ", still rising" or ""), "green" end
  if p.pos <= 15 then return "low for " .. span(p) .. (down and ", still falling" or ""), "gold" end
  if up then return string.format("rising %.1f%% a day", p.trend / 10), "gold" end
  if down then return string.format("falling %.1f%% a day", -p.trend / 10), "green" end
  if p.hrHi >= 0 then return "usually dearest around " .. clock(p.hrHi), "muted" end
  return nil
end

-- merge ApiData.lua into the prices; spread over frames (10k+ items)
function A:Import(d, done)
  d = d or UltimateAH_ApiData
  if type(d) ~= "table" or type(d.items) ~= "table" or not d.t then return false, "no API data" end
  local me = AL:Me()
  if d.faction and d.faction ~= me.faction then return false, "the API data is for " .. tostring(d.faction) end
  local scope = AL:Scope()
  AL.db.scans[scope] = AL.db.scans[scope] or {}
  local sc = AL.db.scans[scope]
  if sc.api and sc.api.t == d.t then return false, "already loaded" end
  if self.busy then return false, "busy" end
  self.busy = true
  local prices = AL.Scanner:Prices(scope)
  local keys = {}
  for k in pairs(d.items) do keys[#keys + 1] = k end
  local keepFrom = today() - (AL.db.settings.historyDays or 30)
  local rates = (d.soldHours or 0) >= 1
  local i, fresh = 0, 0
  local function finish()
    self.busy = false
    sc.api = { t = d.t, items = #keys, auctions = d.auctions, house = d.house, soldHours = d.soldHours, insDays = d.insDays }
    if d.t > (sc.t or 0) then
      sc.t, sc.kind, sc.items, sc.auctions = d.t, "API", fresh, d.auctions
    end
    if d == UltimateAH_ApiData then UltimateAH_ApiData = nil end      -- free the memory
    -- watchlist: only news counts
    if time() - d.t < 2 * 3600 and AL.Watch then
      for key, w in pairs(AL.Watch:List()) do
        local e = AL.Scanner:Get(key)
        if e and e.src == "api" and e.t == d.t and e.min and e.min <= w.max then
          AL.Watch:Alert(w, nil, e.min, "API scan")
        end
      end
    end
    AL:Print(string.format("API scan from %s loaded: %d items%s", AL.UI and AL.UI.Ago and AL.UI.Ago(d.t) or "earlier", fresh,
      rates and string.format(", sale rates from %.0f h of data", d.soldHours) or ""))
    AL:Fire("AL_SCAN_DONE", "api")
    if done then done(fresh) end
  end
  local function step()
    local t0 = debugprofilestop()
    while i < #keys and debugprofilestop() - t0 < BUDGET_MS do
      local stop = math.min(i + 100, #keys)
      while i < stop do
        i = i + 1
        local ok, r = pcall(merge, prices, keys[i], d.items[keys[i]], d, keepFrom, rates)
        if ok and r then fresh = fresh + 1 end
      end
    end
    if i < #keys then
      C_Timer.After(0, function()
        local ok, err = pcall(step)
        if not ok then self.busy = false; AL:Error("api import", err) end
      end)
    else
      finish()
    end
  end
  step()
  return true
end

AL:On("AL_LOGIN", function()
  C_Timer.After(3, function()
    local ok, err = pcall(A.Import, A)
    if not ok then A.busy = false; AL:Error("api import", err) end
  end)
end)

AL:Command("api", "status of the auto scans from Blizzard's API", function()
  local info = A:Info()
  if not info then
    AL:Print("no API scan loaded yet. Run ah_api.py outside the game (see the README), then /reload.")
    return
  end
  AL:Print(string.format("API scan %s: auction house %s, %s auctions, %d items. %s New scans are picked up at login or /reload.",
    AL.UI and AL.UI.Ago and AL.UI.Ago(info.t) or "?", tostring(info.house), tostring(info.auctions or "?"), info.items or 0,
    (info.soldHours or 0) >= 1 and string.format("Sale rates from %.0f h of data.", info.soldHours) or "No sale rates yet (needs two scans)."))
  if info.insDays then
    AL:Print(string.format("Price patterns: the server has %d day(s) of history. Trend and range need 7 days, weekdays about 4 weeks.", info.insDays))
  end
end)
