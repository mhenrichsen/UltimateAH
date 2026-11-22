-- AuctionLedger: answer "AH <item>" in guild chat with our price data
--
--   guildie: AH Silk Cloth           (also a shift-clicked item link or an item ID)
--   you:     [AL] [Silk Cloth]: market 1s 99c, lowest 1s 92c, top-100 avg 2s 1c, 14d avg 2s 1c, 22280 listed (scanned 12m ago)
--
-- Only messages starting with an uppercase "AH " are answered ("ah ok" is not a question). When
-- several guildies run the addon, each waits a random moment and stays quiet if someone else
-- already answered. Replies are throttled per asker and overall.
local _, AL = ...
local G = {}
AL.Guild = G

local REPLY_PREFIX = "[AL]"
local GLOBAL_GAP = 2          -- seconds between any two replies
local SAME_ASK_GAP = 20       -- the same asker asking the same thing again
local MAX_LEN = 255

local lastReply = 0
local recentAsks = {}         -- "asker|query" -> time
local answeredBySomeone = {}  -- lowercased item name -> time an [AL] reply was seen

local function isSecret(v) return issecretvalue and issecretvalue(v) or false end
local function now() return GetTime() end

function G:Enabled()
  local s = AL.db and AL.db.settings
  if not s then return false end
  if s.guildReply == nil then s.guildReply = true end
  return s.guildReply
end

---------------------------------------------------------------------------
-- finding the item
---------------------------------------------------------------------------
local function entryName(e)
  if not e.n and e.i then e.n = AL.ItemName(e.i) end
  return e.n
end

-- returns entry, key, number of name matches
function G:Find(query)
  query = (query or ""):gsub("^%s+", ""):gsub("%s+$", "")
  if query == "" then return nil end
  local prices = AL.db.prices[AL:Scope()] or {}

  -- a link or an item ID
  if query:find("|Hitem:") or query:match("^%d+$") then
    local id = AL.ItemID(query)
    local e = id and AL.Scanner:ForItem(query:find("|H") and query or id)
    if e then return e, AL.KeyFromLink(query:find("|H") and query or nil, id) or tostring(id), 1 end
    return nil
  end

  local q = query:gsub("^%[", ""):gsub("%]$", ""):lower()
  local best, bestKey, matches = nil, nil, 0
  local exact, exactKey
  for key, e in pairs(prices) do
    local n = entryName(e)
    if n then
      local ln = n:lower()
      local plain = not key:find(":", 1, true)
      if ln == q then
        -- exact name: the all-variants price beats a single suffix variant
        if not exact or (plain and exactKey:find(":", 1, true)) then exact, exactKey = e, key end
      elseif ln:find(q, 1, true) then
        matches = matches + 1
        local better = not best
          or (plain and bestKey:find(":", 1, true))
          or (plain == not bestKey:find(":", 1, true) and #n < #(best.n or ""))
        if better then best, bestKey = e, key end
      end
    end
  end
  if exact then return exact, exactKey, 1 end
  return best, bestKey, matches
end

---------------------------------------------------------------------------
-- the reply line
---------------------------------------------------------------------------
local function money(c) return c and AL.Money(c, true) or "-" end

-- what buying `qty` of an item right now costs, from the last full scan (cheapest first, not
-- counting your own auctions); nil when the scan is not in memory
function G:BuyCost(key, qty)
  local last = AL.Scanner.last
  local entries = last and key and last.items[key]
  if not entries then return nil end
  local need, cost = qty, 0
  for _, x in ipairs(entries) do
    if not x[3] then
      local take = math.min(need, x[2] or 1)
      cost, need = cost + take * x[1], need - take
      if need <= 0 then return math.floor(cost + 0.5), true end
    end
  end
  return math.floor(cost + 0.5), false
end

-- "Silk Cloth x20", "Silk Cloth 20x", "20 Silk Cloth" -> "Silk Cloth", 20
function G.ParseQuery(q)
  q = (q or ""):gsub("^%s+", ""):gsub("%s+$", "")
  local item, n = q:match("^(.-)%s*[xX]%s*(%d+)$")
  if not item or item == "" then item, n = q:match("^(.-)%s+(%d+)%s*[xX]$") end
  if not item or item == "" then n, item = q:match("^(%d+)%s*[xX]?%s+(%D.*)$") end
  if item and item ~= "" and tonumber(n) and tonumber(n) > 0 then return item, math.min(tonumber(n), 100000) end
  return q, nil
end

G.HELP = REPLY_PREFIX .. " Ask 'AH <item>' for auction prices, 'AH <item> x20' for the cost of 20. " ..
  "A shift-clicked item link or an item ID works too."

function G:Reply(query, qty)
  if not qty then query, qty = G.ParseQuery(query) end
  local e, key, matches = self:Find(query)
  if not e then return nil end
  local name = entryName(e) or ("item " .. tostring(e.i))
  -- a real item link when the client has it (not for suffix variants: the plain link would mislead)
  local label = "[" .. name .. "]"
  if key and not key:find(":", 1, true) and e.i then
    local link = AL.ItemLink(e.i)
    if link then label = link end
  end
  local parts = { "market " .. money(e.mkt), "lowest " .. money(e.min) }
  if e.top and e.top ~= e.mkt then parts[#parts + 1] = "top-100 avg " .. money(e.top) end
  local avg = AL.Scanner.HistoryAvg(e, 14)
  if avg then parts[#parts + 1] = "14d avg " .. money(avg) end
  parts[#parts + 1] = (e.qty or 0) .. " listed"
  if qty and qty > 1 then
    local cost, enough = self:BuyCost(key, qty)
    if cost and enough then
      table.insert(parts, 1, string.format("x%d costs %s now", qty, money(cost)))
    elseif cost then
      table.insert(parts, 1, string.format("x%d: only %d listed", qty, e.qty or 0))
    elseif e.mkt then
      table.insert(parts, 1, string.format("x%d ~%s at market", qty, money(e.mkt * qty)))
    end
  end
  local msg = string.format("%s %s: %s (scanned %s)", REPLY_PREFIX, label, table.concat(parts, ", "), AL.UI.Ago(e.t))
  if matches and matches > 1 then msg = msg .. string.format(" - %d matches, be more specific", matches) end
  if #msg > MAX_LEN then
    -- drop the link formatting first, then cut
    msg = msg:gsub("|c%x%x%x%x%x%x%x%x|Hitem:[^|]+|h(%[.-%])|h|r", "%1")
    if #msg > MAX_LEN then msg = msg:sub(1, MAX_LEN) end
  end
  return msg, name
end

local function send(msg, channel, target)
  if C_ChatInfo and C_ChatInfo.SendChatMessage then
    C_ChatInfo.SendChatMessage(msg, channel, nil, target)
  else
    SendChatMessage(msg, channel, nil, target)
  end
end
G.Send = send

function G:WhisperEnabled()
  local s = AL.db and AL.db.settings
  if not s then return false end
  if s.whisperReply == nil then s.whisperReply = true end
  return s.whisperReply
end

---------------------------------------------------------------------------
-- watching guild chat and whispers
---------------------------------------------------------------------------
local function handle(text, sender, channel)
  if isSecret(text) or isSecret(sender) or type(text) ~= "string" then return end
  local whisper = channel == "WHISPER"
  if whisper and not G:WhisperEnabled() then return end
  if not whisper and not G:Enabled() then return end

  -- someone (maybe another copy of this addon) answered: remember which item
  if text:sub(1, #REPLY_PREFIX) == REPLY_PREFIX then
    if not whisper then
      local n = text:match("%[([^%]]+)%]", #REPLY_PREFIX + 1)
      if n then answeredBySomeone[n:lower()] = now() end
    end
    return
  end

  local query = text:match("^AH%s+(.+)$")
  if not query then return end

  local askKey = channel .. "|" .. tostring(sender) .. "|" .. query:lower()
  if recentAsks[askKey] and now() - recentAsks[askKey] < SAME_ASK_GAP then return end
  recentAsks[askKey] = now()

  local msg, name
  if query:lower():match("^%s*help%s*$") or query:match("^%s*%?%s*$") then
    msg, name = G.HELP, "help"
  else
    msg, name = G:Reply(query)
  end
  if not msg then
    -- in guild, stay quiet for plain words ("AH is busy"); a link, an ID or a whisper clearly asked
    if whisper or query:find("|Hitem:") or query:match("^%d+$") then
      msg, name = REPLY_PREFIX .. " no AH data for '" .. G.ParseQuery(query):sub(1, 60) .. "' yet", "?"
    else
      return
    end
  end

  if whisper then
    if now() - lastReply < 1 then return end
    lastReply = now()
    C_Timer.After(0.3, function() send(msg, "WHISPER", sender) end)
    return
  end

  -- wait a random moment so several addon users don't all answer
  local asked = now()
  C_Timer.After(0.4 + math.random() * 1.6, function()
    local seen = answeredBySomeone[(name or ""):lower()]
    if seen and seen >= asked then return end            -- someone beat us to it
    if now() - lastReply < GLOBAL_GAP then return end
    lastReply = now()
    send(msg, "GUILD")
  end)
end

AL:On("CHAT_MSG_WHISPER", function(text, sender) handle(text, sender, "WHISPER") end)
AL:On("CHAT_MSG_GUILD", function(text, sender) handle(text, sender, "GUILD") end)

-- forget old throttle entries now and then
C_Timer.NewTicker(300, function()
  local t = now()
  for k, v in pairs(recentAsks) do if t - v > 600 then recentAsks[k] = nil end end
  for k, v in pairs(answeredBySomeone) do if t - v > 600 then answeredBySomeone[k] = nil end end
end)

---------------------------------------------------------------------------
-- commands
---------------------------------------------------------------------------
AL:Command("guild", "turn the guild-chat price replies on or off ('AH <item>' in guild chat)", function()
  AL.db.settings.guildReply = not G:Enabled()
  AL:Print("guild chat replies", AL.db.settings.guildReply and "|cff59ff59on|r" or "|cffff7373off|r")
end)

AL:Command("whispers", "turn the whisper price replies on or off ('AH <item>' whispered to you)", function()
  AL.db.settings.whisperReply = not G:WhisperEnabled()
  AL:Print("whisper replies", AL.db.settings.whisperReply and "|cff59ff59on|r" or "|cffff7373off|r")
end)

AL:Command("ah", "preview the guild reply for an item, only you see it: /al ah <item> [x20]", function(arg)
  local msg = arg:lower():match("^%s*help%s*$") and G.HELP or G:Reply(arg)
  AL:Print(msg and ("guild reply would be: " .. msg) or ("no price data for '" .. tostring(arg) .. "'"))
end)
