-- AuctionLedger: total value tracking (gold + what your items are worth), per character over time
--
-- Inventory is remembered per character (bags always, bank when you open it, mail when you open
-- the mailbox, auctions from the AH). Items are valued at the scanned market price; soulbound
-- items are worth 0. A snapshot is stored at most every 15 minutes and thinned out as it ages.
local _, AL = ...
local V = {}
AL.Value = V

local MERGE = 15 * 60

local function now() return time() end

function V:Inv()
  AL.db.inv = AL.db.inv or {}
  local k = AL:CharKey()
  AL.db.inv[k] = AL.db.inv[k] or {}
  return AL.db.inv[k]
end

-- read a list of containers into { [priceKey] = { id, count, link } }
local function readContainers(bags)
  local out = {}
  for _, bag in ipairs(bags) do
    local ok, n = pcall(C_Container.GetContainerNumSlots, bag)
    for slot = 1, (ok and n or 0) do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and info.itemID and not info.isBound then
        local key = AL.KeyFromLink(info.hyperlink, info.itemID)
        local e = out[key]
        if e then e[2] = e[2] + (info.stackCount or 1)
        else out[key] = { info.itemID, info.stackCount or 1, info.hyperlink } end
      end
    end
  end
  return out
end

function V:ReadBags()
  local bags = {}
  for b = 0, (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) do bags[#bags + 1] = b end
  self:Inv().bags = readContainers(bags)
  self:Inv().bagsT = now()
end

function V:ReadBank()
  local bags = { (Enum.BagIndex and Enum.BagIndex.Bank) or -1 }
  local first = (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) + 1
  for b = first, first + (NUM_BANKBAGSLOTS or 7) - 1 do bags[#bags + 1] = b end
  if Enum.BagIndex and Enum.BagIndex.Reagentbank then bags[#bags + 1] = Enum.BagIndex.Reagentbank end
  self:Inv().bank = readContainers(bags)
  self:Inv().bankT = now()
end

function V:ReadMail()
  local out, money = {}, 0
  for i = 1, GetInboxNumItems() or 0 do
    local _, _, _, _, m, cod = GetInboxHeaderInfo(i)
    if (cod or 0) == 0 then money = money + (m or 0) end
    for a = 1, ATTACHMENTS_MAX_RECEIVE or 16 do
      local name, itemID, _, count = GetInboxItem(i, a)
      if itemID then
        local link = GetInboxItemLink(i, a)
        local key = AL.KeyFromLink(link, itemID)
        local e = out[key]
        if e then e[2] = e[2] + (count or 1) else out[key] = { itemID, count or 1, link } end
      end
    end
  end
  self:Inv().mail = out
  self:Inv().mailMoney = money
  self:Inv().mailT = now()
end

-- unit value of an item for the value graph
function V.UnitValue(itemID, link)
  local e = AL.Scanner:ForItem(link or itemID)
  if not e then return 0 end
  return e.mkt or e.min or 0
end

local function worth(list)
  local v = 0
  for _, e in pairs(list or {}) do v = v + V.UnitValue(e[1], e[3]) * e[2] end
  return math.floor(v + 0.5)
end

-- current value breakdown of a character (from what was last seen of them)
function V:Breakdown(charKey)
  local inv = AL.db.inv and AL.db.inv[charKey] or {}
  local c = AL.db.chars[charKey] or {}
  local ah = 0
  local snap = AL.db.listings and AL.db.listings[charKey]
  for _, a in ipairs(snap and snap.list or {}) do
    local q = math.max(a.qty or 1, 1)
    local listed = a.buyout and a.buyout > 0 and a.buyout / q or nil   -- buyout is for the whole stack
    if a.sold then
      ah = ah + (a.buyout or 0) * 0.95               -- money on its way (less the 5% AH cut)
    else
      local unit = V.UnitValue(a.id, a.link)
      if unit == 0 then unit = listed or 0 end
      ah = ah + math.min(unit, listed or unit) * q
    end
  end
  local b = { gold = c.money or 0, bags = worth(inv.bags), bank = worth(inv.bank),
              mail = worth(inv.mail) + (inv.mailMoney or 0), ah = math.floor(ah + 0.5) }
  b.items = b.bags + b.bank + b.mail + b.ah
  b.total = b.gold + b.items
  return b
end

---------------------------------------------------------------------------
-- snapshots
---------------------------------------------------------------------------
function V:Series(charKey)
  AL.db.value = AL.db.value or {}
  AL.db.value[charKey] = AL.db.value[charKey] or {}
  return AL.db.value[charKey]
end

function V:Snapshot()
  if not AL.db then return end
  AL:TouchChar()
  local key = AL:CharKey()
  local b = self:Breakdown(key)
  local s = self:Series(key)
  local p = { now(), b.gold, b.items }
  local last = s[#s]
  if last and p[1] - last[1] < MERGE and #s > 1 then
    s[#s] = p
  else
    s[#s + 1] = p
  end
  AL:Fire("AL_VALUE")
end

-- older points are thinned: 2 weeks at full detail, then one per 6 hours, after 90 days one per day
function V:Compact()
  local t = now()
  for _, s in pairs(AL.db.value or {}) do
    local out, lastBucket = {}, nil
    for i, p in ipairs(s) do
      local age = t - p[1]
      local bucket
      if age > 90 * 86400 then bucket = "d" .. math.floor(p[1] / 86400)
      elseif age > 14 * 86400 then bucket = "h" .. math.floor(p[1] / 21600) end
      if bucket and bucket == lastBucket then
        out[#out] = p                           -- keep the latest point of the bucket
      else
        out[#out + 1] = p
      end
      lastBucket = bucket
    end
    for i = #s, 1, -1 do s[i] = nil end
    for i, p in ipairs(out) do s[i] = p end
  end
end

-- account series: at every snapshot time, the sum of each character's latest known value
function V:AccountSeries(from)
  local times, seen = {}, {}
  for _, s in pairs(AL.db.value or {}) do
    for _, p in ipairs(s) do
      if not seen[p[1]] then seen[p[1]] = true; times[#times + 1] = p[1] end
    end
  end
  table.sort(times)
  local idx, cur = {}, {}
  local out = {}
  for _, t in ipairs(times) do
    local g, it = 0, 0
    for ck, s in pairs(AL.db.value) do
      local i = idx[ck] or 0
      while s[i + 1] and s[i + 1][1] <= t do i = i + 1 end
      idx[ck] = i
      if i > 0 then g = g + s[i][2]; it = it + s[i][3] end
    end
    if t >= (from or 0) then out[#out + 1] = { t, g, it } end
  end
  return out
end

---------------------------------------------------------------------------
-- triggers
---------------------------------------------------------------------------
local timers = {}
local function debounce(name, secs, fn)
  if timers[name] then return end
  timers[name] = true
  C_Timer.After(secs, function() timers[name] = nil; pcall(fn) end)
end

local function snap() V:Snapshot() end

AL:On("AL_LOGIN", function()
  V:Compact()
  C_Timer.After(5, function() V:ReadBags(); snap() end)
end)
AL:On("PLAYER_MONEY", function() debounce("money", 5, snap) end)
AL:On("BAG_UPDATE_DELAYED", function()
  debounce("bags", 20, function()
    V:ReadBags()
    if V.bankOpen then V:ReadBank() end
    snap()
  end)
end)
AL:On("BANKFRAME_OPENED", function() V.bankOpen = true; C_Timer.After(1, function() V:ReadBank(); snap() end) end)
AL:On("PLAYERBANKSLOTS_CHANGED", function() if V.bankOpen then debounce("bank", 2, function() V:ReadBank() end) end end)
AL:On("BANKFRAME_CLOSED", function() V.bankOpen = false; snap() end)
AL:On("MAIL_INBOX_UPDATE", function() debounce("mail", 1, function() V:ReadMail() end) end)
AL:On("MAIL_CLOSED", function() pcall(V.ReadMail, V); snap() end)
AL:On("AL_LISTINGS", function() debounce("listings", 3, snap) end)
AL:On("AL_SCAN_DONE", function() debounce("scan", 2, function() V:ReadBags(); snap() end) end)
AL:On("PLAYER_LOGOUT", function() pcall(V.ReadBags, V); pcall(snap) end)

AL:Command("value", "print the gold + item value of this character and the account", function()
  local b = V:Breakdown(AL:CharKey())
  AL:Print(string.format("%s: %s (gold %s, bags %s, bank %s, mail %s, auctions %s)", AL:CharKey(), AL.Money(b.total),
    AL.Money(b.gold), AL.Money(b.bags), AL.Money(b.bank), AL.Money(b.mail), AL.Money(b.ah)))
  local tot = 0
  for ck in pairs(AL.db.chars) do tot = tot + V:Breakdown(ck).total end
  AL:Print("account total: " .. AL.Money(tot))
end)
