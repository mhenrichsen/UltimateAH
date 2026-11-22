-- AuctionLedger: core (saved data, events, helpers, slash commands)
local ADDON, AL = ...
_G.AuctionLedger = AL

AL.version = "1.0.0"
AL.DB_VERSION = 1

---------------------------------------------------------------------------
-- events
---------------------------------------------------------------------------
local frame = CreateFrame("Frame")
AL.frame = frame
local handlers = {}

function AL:On(event, fn)
  if not handlers[event] then
    handlers[event] = {}
    if not event:find("^AL_") then
      pcall(frame.RegisterEvent, frame, event)
    end
  end
  table.insert(handlers[event], fn)
end

function AL:Fire(event, ...)
  local list = handlers[event]
  if not list then return end
  for _, fn in ipairs(list) do
    local ok, err = pcall(fn, ...)
    if not ok then AL:Error(event, err) end
  end
end

frame:SetScript("OnEvent", function(_, event, ...) AL:Fire(event, ...) end)

---------------------------------------------------------------------------
-- output
---------------------------------------------------------------------------
local PREFIX = "|cff33ccffAuctionLedger|r: "

function AL:Print(...)
  local parts = {}
  for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
  DEFAULT_CHAT_FRAME:AddMessage(PREFIX .. table.concat(parts, " "))
end

AL.errors = {}
function AL:Error(where, err)
  local msg = tostring(where) .. ": " .. tostring(err)
  table.insert(AL.errors, msg)
  if #AL.errors > 50 then table.remove(AL.errors, 1) end
  if AL.db and AL.db.settings and AL.db.settings.debug then
    AL:Print("|cffff4444error|r " .. msg)
  end
  if AL.DevLog then AL.DevLog("ERR " .. msg) end
end

---------------------------------------------------------------------------
-- money / item helpers
---------------------------------------------------------------------------
function AL.Money(copper, plain, numColor)
  if not copper then return "-" end
  local neg = copper < 0
  copper = math.floor(math.abs(copper) + 0.5)
  local g, s, c = math.floor(copper / 10000), math.floor(copper / 100) % 100, copper % 100
  local out
  if plain == "short" then
    local big = BreakUpLargeNumbers or tostring
    if g >= 10000 then out = big(g) .. "g"
    elseif g > 0 then out = s > 0 and string.format("%sg %ds", big(g), s) or (big(g) .. "g")
    elseif s > 0 then out = c > 0 and string.format("%ds %dc", s, c) or (s .. "s")
    else out = c .. "c" end
  elseif plain then
    local p = {}
    if g > 0 then p[#p + 1] = g .. "g" end
    if s > 0 then p[#p + 1] = s .. "s" end
    if c > 0 or #p == 0 then p[#p + 1] = c .. "c" end
    out = table.concat(p, " ")
  else
    -- compact: 12,345g / 44g 05s / 45s 07c / 7c, unit letters tinted; numbers keep the text colour
    if copper == 0 then return "|cff5c6170\226\128\148|r" end
    local back = numColor or "|r"
    local G, S, C = "|cffe8b94ag" .. back, "|cffaab2c0s" .. back, "|cffcf8f63c" .. back
    local big = BreakUpLargeNumbers or tostring
    if g >= 10000 then out = big(g) .. G
    elseif g > 0 then out = string.format("%s%s %02d%s", big(g), G, s, S)
    elseif s > 0 then out = string.format("%d%s %02d%s", s, S, c, C)
    else out = c .. C end
    if numColor then out = numColor .. out .. "|r" end
  end
  return neg and ("-" .. out) or out
end

-- itemID from a link, item string or number
function AL.ItemID(x)
  if type(x) == "number" then return x end
  if type(x) ~= "string" then return nil end
  return tonumber(x:match("item:(%-?%d+)")) or tonumber(x)
end

-- price key: "itemID", or "itemID:b<bonusIDs>" for variants such as random-suffix gear.
-- On Forever "of the Sorcerer" is a bonus ID in the link (item:11991::::::::1:1491::1:1:12745:...),
-- the classic suffix field is empty. Lookups fall back to the plain itemID (all variants).
function AL.KeyFromLink(link, itemID)
  itemID = itemID or AL.ItemID(link)
  if not itemID then return nil end
  if type(link) == "string" then
    local s = link:match("item:([%-%d:]+)")
    if s then
      local f = { strsplit(":", s) }
      local nb = tonumber(f[13] or "")
      if nb and nb > 0 and nb <= 24 then            -- (a real link carries a handful of bonus ids)
        local b = {}
        for i = 14, 13 + nb do b[#b + 1] = tonumber(f[i]) or 0 end
        table.sort(b)
        return itemID .. ":b" .. table.concat(b, "-")
      end
      local suffix = tonumber(f[7] or "")
      if suffix and suffix ~= 0 then return itemID .. ":s" .. suffix end
    end
  end
  return tostring(itemID)
end

function AL.ItemName(itemID, link)
  if link and type(link) == "string" then
    local n = link:match("|h%[(.-)%]|h")
    if n then return n end
  end
  if not itemID then return nil end
  local n = C_Item.GetItemNameByID and C_Item.GetItemNameByID(itemID)
  if not n and C_Item.GetItemInfo then n = C_Item.GetItemInfo(itemID) end
  return n
end

function AL.ItemIcon(itemID)
  if not itemID then return 134400 end
  return (C_Item.GetItemIconByID and C_Item.GetItemIconByID(itemID)) or 134400
end

function AL.ItemQuality(itemID, link)
  local q
  if link and C_Item.GetItemQualityByID then q = C_Item.GetItemQualityByID(link) end
  if not q and itemID and C_Item.GetItemQualityByID then q = C_Item.GetItemQualityByID(itemID) end
  return q
end

function AL.ItemLink(itemID)
  if not itemID then return nil end
  local _, link = C_Item.GetItemInfo(itemID)
  return link
end

-- turn a GlobalStrings format ("A buyer has been found for your auction of %s.") into a Lua pattern
function AL.FormatToPattern(fmt)
  if not fmt then return nil end
  local p = fmt:gsub("([%(%)%.%%%+%-%*%?%[%]%^%$])", "%%%1")
  p = p:gsub("%%%%%d?%$?s", "(.+)"):gsub("%%%%%d?%$?d", "(%%d+)")
  return "^" .. p .. "$"
end

---------------------------------------------------------------------------
-- identity
---------------------------------------------------------------------------
-- Forever characters have a first and a last name: UnitName returns both ("Tess", "Bank")
-- and GetRealmName() is empty, so the full name is the character key.
function AL:Me()
  if not self.me or self.me.name == "" then
    local first, last = UnitName("player")
    local name = first or "?"
    if last and last ~= "" then name = name .. " " .. last end
    local realm = GetRealmName()
    if not realm or realm == "" then realm = "Forever" end
    self.me = { name = name, realm = realm, faction = UnitFactionGroup("player") or "Neutral",
                class = select(2, UnitClass("player")) }
  end
  return self.me
end

-- the auction house a character sees (prices are kept per realm + faction)
function AL:Scope()
  local me = self:Me()
  return me.realm .. " " .. me.faction
end

function AL:Debug(...)
  if self.db and self.db.settings.debug then self:Print("|cff888888[debug]|r", ...) end
  if self.DevLog then
    local parts = {}
    for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
    self.DevLog("dbg " .. table.concat(parts, " "))
  end
end

---------------------------------------------------------------------------
-- saved data
---------------------------------------------------------------------------
local DEFAULTS = {
  settings = { debug = false, tooltip = true, autoScan = false, historyDays = 30, keepTx = 20000 },
  chars = {},      -- ["Name-Realm"] = { name, realm, faction, class, lastSeen, money }
  tx = {},         -- transactions, oldest first
  prices = {},     -- [scope] = { [key] = { n=name, i=itemID, min, mkt, qty, num, t, h = {[day]={mkt,min}} } }
  scans = {},      -- [scope] = { t, kind, auctions, items }
  invoices = {},   -- signatures of mail invoices already recorded
}

local function fill(dst, src)
  for k, v in pairs(src) do
    if dst[k] == nil then
      dst[k] = type(v) == "table" and CopyTable(v) or v
    elseif type(v) == "table" and type(dst[k]) == "table" and next(v) then
      fill(dst[k], v)
    end
  end
end

function AL:InitDB()
  AuctionLedgerDB = AuctionLedgerDB or {}
  fill(AuctionLedgerDB, DEFAULTS)
  AuctionLedgerDB.dbVersion = AL.DB_VERSION
  self.db = AuctionLedgerDB
  self.db.dev = nil                -- development output is never kept
  -- early dev builds keyed characters as "First-" (realm is empty on Forever)
  for k in pairs(self.db.chars) do if k:sub(-1) == "-" then self.db.chars[k] = nil end end
  -- early dev builds stored browse-suffix keys ("123:14303") that never match an item link
  if not self.db.keysV2 then
    for _, scope in pairs(self.db.prices) do
      for k in pairs(scope) do if k:match("^%d+:%d+$") then scope[k] = nil end end
    end
    self.db.keysV2 = true
  end
end

-- my characters' names, normalised ("Tess Bank", "Tess-Bank" -> "tessbank"), for spotting my own auctions
local function normName(s)
  if type(s) ~= "string" or s == "" then return nil end
  return (s:lower():gsub("[%s%-']", ""))
end
AL.NormName = normName

function AL:MyNameSet()
  local set = {}
  for k, c in pairs(self.db and self.db.chars or {}) do
    local n = normName(c.name or k)
    if n then set[n] = true end
  end
  local me = normName(self:Me().name)
  if me then set[me] = true end
  return set
end

function AL.IsMineName(set, ownerFull, owner)
  local a, b = normName(ownerFull), normName(owner)
  return (a and set[a]) or (b and set[b]) or false
end

function AL:CharKey()
  return self:Me().name
end

function AL:TouchChar()
  local me = self:Me()
  local c = self.db.chars[self:CharKey()] or {}
  c.name, c.realm, c.faction, c.class = me.name, me.realm, me.faction, me.class
  c.lastSeen = time()
  c.money = GetMoney()
  self.db.chars[self:CharKey()] = c
end

-- add a transaction; returns the record
function AL:AddTx(rec)
  local me = self:Me()
  rec.t = rec.t or time()
  rec.char = rec.char or me.name
  rec.realm = rec.realm or me.realm
  rec.faction = rec.faction or me.faction
  if rec.item and not rec.name then rec.name = AL.ItemName(rec.item, rec.link) end
  table.insert(self.db.tx, rec)
  local keep = self.db.settings.keepTx or 20000
  while #self.db.tx > keep do table.remove(self.db.tx, 1) end
  self:Fire("AL_TX_ADDED", rec)
  return rec
end

---------------------------------------------------------------------------
-- startup
---------------------------------------------------------------------------
AL:On("ADDON_LOADED", function(name)
  if name ~= ADDON then return end
  AL:InitDB()
  AL:Fire("AL_DB_READY")
end)

AL:On("PLAYER_LOGIN", function()
  AL:TouchChar()
  AL:Fire("AL_LOGIN")
end)

AL:On("PLAYER_MONEY", function() if AL.db then AL:TouchChar() end end)
AL:On("PLAYER_LOGOUT", function() if AL.db then AL:TouchChar() end end)

---------------------------------------------------------------------------
-- slash commands
---------------------------------------------------------------------------
AL.commands = {}

function AL:Command(name, help, fn)
  self.commands[name] = { help = help, fn = fn }
end

SLASH_AUCTIONLEDGER1 = "/al"
SLASH_AUCTIONLEDGER2 = "/ledger"
SLASH_AUCTIONLEDGER3 = "/auctionledger"
SlashCmdList.AUCTIONLEDGER = function(msg)
  msg = msg or ""
  local cmd, rest = msg:match("^%s*(%S*)%s*(.-)%s*$")
  cmd = (cmd or ""):lower()
  local c = AL.commands[cmd]
  if c then
    local ok, err = pcall(c.fn, rest)
    if not ok then AL:Print("|cffff4444" .. tostring(err) .. "|r") end
  elseif cmd == "" and AL.commands.show then
    AL.commands.show.fn("")
  else
    AL:Print("commands:")
    local names = {}
    for k in pairs(AL.commands) do names[#names + 1] = k end
    table.sort(names)
    for _, k in ipairs(names) do
      if AL.commands[k].help then AL:Print("  /al " .. k .. " - " .. AL.commands[k].help) end
    end
  end
end

AL:Command("debug", "toggle debug messages", function()
  AL.db.settings.debug = not AL.db.settings.debug
  AL:Print("debug", AL.db.settings.debug and "on" or "off")
end)

AL:Command("errors", "list recent internal errors", function()
  if #AL.errors == 0 then AL:Print("no errors") end
  for _, e in ipairs(AL.errors) do AL:Print(e) end
end)
