-- Ultimate AH: UI kit - a flat dark theme with its own fonts, buttons, inputs, dropdowns,
-- switches, cards, tables and graphs (no Blizzard templates, so it looks the same everywhere)
local _, AL = ...
local W = {}
AL.W = W

W.ROW_H = 20
local ROW_H = W.ROW_H

---------------------------------------------------------------------------
-- palette and fonts
---------------------------------------------------------------------------
local C = {
  bg     = { 0.047, 0.051, 0.067, 0.985 },
  side   = { 0.031, 0.035, 0.047, 1 },
  panel  = { 0.071, 0.078, 0.098, 1 },
  panel2 = { 0.098, 0.106, 0.137, 1 },
  border = { 0.141, 0.153, 0.192, 1 },
  text   = { 0.90, 0.91, 0.94 },
  muted  = { 0.50, 0.53, 0.61 },
  accent = { 0.42, 0.47, 1.00 },
  green  = { 0.24, 0.86, 0.59 },
  red    = { 1.00, 0.38, 0.47 },
  gold   = { 1.00, 0.79, 0.30 },
  blue   = { 0.36, 0.67, 1.00 },
}
W.C = C
function W.Hex(c) return string.format("|cff%02x%02x%02x", math.floor(c[1] * 255 + 0.5), math.floor(c[2] * 255 + 0.5), math.floor(c[3] * 255 + 0.5)) end
W.GREEN, W.RED, W.MUTED, W.ACCENT, W.GOLD = W.Hex(C.green), W.Hex(C.red), W.Hex(C.muted), W.Hex(C.accent), W.Hex(C.gold)

local FONT = "Fonts\\ARIALN.TTF"
local function makeFont(name, size, color, flags)
  local f = CreateFont(name)
  f:SetFont(FONT, size, flags or "")
  if not f:GetFont() then                        -- font file missing: fall back to the game font
    f:SetFont((GameFontHighlight:GetFont()), size - 1, flags or "")
  end
  f:SetTextColor(color[1], color[2], color[3])
  f:SetShadowColor(0, 0, 0, 0.5)
  f:SetShadowOffset(1, -1)
  return f
end
W.F = {
  h1     = makeFont("UAHFontH1", 22, C.text),
  h2     = makeFont("UAHFontH2", 15, C.text),
  big    = makeFont("UAHFontBig", 19, C.text),
  body   = makeFont("UAHFontBody", 13, C.text),
  bright = makeFont("UAHFontBright", 13, { 1, 1, 1 }),
  small  = makeFont("UAHFontSmall", 12, C.text),
  muted  = makeFont("UAHFontMuted", 12, C.muted),
  label  = makeFont("UAHFontLabel", 10, C.muted),
  accent = makeFont("UAHFontAccent", 13, C.accent),
}
-- old Blizzard font names used around the addon -> theme fonts
local FONTMAP = {
  GameFontNormalLarge = "UAHFontH2", GameFontNormal = "UAHFontH2", GameFontHighlight = "UAHFontBody",
  GameFontHighlightSmall = "UAHFontSmall", GameFontDisableSmall = "UAHFontMuted", GameFontDisable = "UAHFontMuted",
  GameFontNormalSmall = "UAHFontLabel",
}

---------------------------------------------------------------------------
-- primitives
---------------------------------------------------------------------------
function W.Fill(f, c, layer, sub)
  local t = f:CreateTexture(nil, layer or "BACKGROUND", nil, sub or 0)
  t:SetAllPoints()
  t:SetColorTexture(c[1], c[2], c[3], c[4] or 1)
  return t
end

function W.Border(f, c)
  c = c or C.border
  f.borderTex = f.borderTex or {}
  local sides = { { "TOPLEFT", "TOPRIGHT", false }, { "BOTTOMLEFT", "BOTTOMRIGHT", false },
                  { "TOPLEFT", "BOTTOMLEFT", true }, { "TOPRIGHT", "BOTTOMRIGHT", true } }
  for i, s in ipairs(sides) do
    local t = f:CreateTexture(nil, "BORDER")
    t:SetPoint(s[1]); t:SetPoint(s[2])
    if s[3] then t:SetWidth(1) else t:SetHeight(1) end
    t:SetColorTexture(c[1], c[2], c[3], c[4] or 1)
    f.borderTex[i] = t
  end
end

function W.BorderColor(f, c)
  for _, t in ipairs(f.borderTex or {}) do t:SetColorTexture(c[1], c[2], c[3], c[4] or 1) end
end

function W.Panel(parent, c, noBorder)
  local f = CreateFrame("Frame", nil, parent)
  f.bg = W.Fill(f, c or C.panel)
  if not noBorder then W.Border(f) end
  return f
end

-- soft drop shadow around a frame
function W.Shadow(f)
  for i = 1, 6 do
    local t = f:CreateTexture(nil, "BACKGROUND", nil, -8)
    t:SetPoint("TOPLEFT", -i * 2, i * 2 - 2)
    t:SetPoint("BOTTOMRIGHT", i * 2, -i * 2 - 2)
    t:SetColorTexture(0, 0, 0, 0.09 - i * 0.012)
  end
end

-- a circle (texture + round mask)
function W.Circle(parent, size, c, layer)
  local t = parent:CreateTexture(nil, layer or "ARTWORK")
  t:SetSize(size, size)
  t:SetColorTexture(c[1], c[2], c[3], c[4] or 1)
  local m = parent:CreateMaskTexture()
  m:SetTexture("Interface\\CharacterFrame\\TempPortraitAlphaMask", "CLAMPTOBLACKADDITIVE", "CLAMPTOBLACKADDITIVE")
  m:SetAllPoints(t)
  t:AddMaskTexture(m)
  return t
end

function W.Label(parent, text, font)
  local fs = parent:CreateFontString(nil, "OVERLAY")
  fs:SetFontObject(FONTMAP[font] or font or "UAHFontSmall")
  fs:SetText(text or "")
  fs:SetJustifyH("LEFT")
  return fs
end

function W.Tip(frame, title, text)
  frame:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:AddLine(title)
    if text then GameTooltip:AddLine(text, 1, 1, 1, true) end
    GameTooltip:Show()
  end)
  frame:SetScript("OnLeave", function() GameTooltip:Hide() end)
end

---------------------------------------------------------------------------
-- buttons: style nil = quiet, "primary" = accent filled
---------------------------------------------------------------------------
function W.Button(parent, text, width, onClick, style)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(width or 100, 26)
  local primary = style == "primary"
  b.bg = W.Fill(b, primary and C.accent or C.panel)
  W.Border(b, primary and { C.accent[1] * 1.1, C.accent[2] * 1.1, 1 } or C.border)
  local hl = b:CreateTexture(nil, "HIGHLIGHT")
  hl:SetAllPoints()
  hl:SetColorTexture(1, 1, 1, primary and 0.12 or 0.05)
  local fs = b:CreateFontString(nil, "OVERLAY")
  fs:SetPoint("LEFT", 8, 0)
  fs:SetPoint("RIGHT", -8, 0)
  fs:SetWordWrap(false)
  b:SetFontString(fs)
  b:SetNormalFontObject(primary and "UAHFontBright" or "UAHFontBody")
  b:SetDisabledFontObject("UAHFontMuted")
  b:SetText(text)
  b:SetScript("OnClick", onClick)
  b:SetScript("OnMouseDown", function(s) if s:IsEnabled() then s.bg:SetAlpha(0.75) end end)
  b:SetScript("OnMouseUp", function(s) s.bg:SetAlpha(1) end)
  b:HookScript("OnDisable", function(s) s.bg:SetAlpha(0.45) end)
  b:HookScript("OnEnable", function(s) s.bg:SetAlpha(1) end)
  return b
end

-- an "x" close button
function W.Close(parent, onClick)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(28, 28)
  local hl = b:CreateTexture(nil, "HIGHLIGHT")
  hl:SetAllPoints()
  hl:SetColorTexture(C.red[1], C.red[2], C.red[3], 0.25)
  for i = 1, 2 do
    local l = b:CreateLine(nil, "OVERLAY")
    l:SetThickness(1.5)
    l:SetColorTexture(C.muted[1], C.muted[2], C.muted[3], 1)
    l:SetStartPoint("CENTER", b, -5, i == 1 and 5 or -5)
    l:SetEndPoint("CENTER", b, 5, i == 1 and -5 or 5)
  end
  b:SetScript("OnClick", onClick or function() parent:Hide() end)
  return b
end

---------------------------------------------------------------------------
-- text input
---------------------------------------------------------------------------
function W.Edit(parent, width, placeholder, onChange)
  local e = CreateFrame("EditBox", nil, parent)
  e:SetSize(width, 26)
  e:SetAutoFocus(false)
  e:SetFontObject("UAHFontBody")
  e:SetTextInsets(10, 10, 0, 0)
  W.Fill(e, C.panel)
  W.Border(e)
  local ph = e:CreateFontString(nil, "OVERLAY", "UAHFontMuted")
  ph:SetPoint("LEFT", 10, 0)
  ph:SetPoint("RIGHT", -10, 0)
  ph:SetJustifyH("LEFT")
  ph:SetWordWrap(false)
  ph:SetText(placeholder or "")
  e:SetScript("OnTextChanged", function(self)
    ph:SetShown(self:GetText() == "")
    if onChange then onChange(self:GetText()) end
  end)
  e:SetScript("OnEditFocusGained", function(self) W.BorderColor(self, C.accent) end)
  e:SetScript("OnEditFocusLost", function(self) W.BorderColor(self, C.border) end)
  e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
  e:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
  return e
end

---------------------------------------------------------------------------
-- dropdown: W.Cycle(parent, label, width, { {value, text}, ... }, onChange)
-- left-click opens a menu, right-click steps back one option
---------------------------------------------------------------------------
local menu
local function closeMenu() if menu then menu:Hide() end end
W.CloseMenu = closeMenu

local function openMenu(owner)
  if not menu then
    menu = CreateFrame("Frame", nil, UIParent)
    menu:SetFrameStrata("FULLSCREEN_DIALOG")
    menu:SetClampedToScreen(true)
    menu:EnableMouse(true)
    W.Fill(menu, C.panel2)
    W.Border(menu)
    W.Shadow(menu)
    menu.items = {}
    local catcher = CreateFrame("Button", nil, UIParent)
    catcher:SetAllPoints(UIParent)
    catcher:SetFrameStrata("FULLSCREEN")
    catcher:RegisterForClicks("AnyUp")
    catcher:SetScript("OnClick", closeMenu)
    catcher:Hide()
    menu:SetScript("OnHide", function() catcher:Hide() end)
    menu.catcher = catcher
    menu:Hide()
  end
  if menu:IsShown() and menu.owner == owner then menu:Hide(); return end
  menu.owner = owner
  local opts = owner.opts
  for i, o in ipairs(opts) do
    local it = menu.items[i]
    if not it then
      it = CreateFrame("Button", nil, menu)
      it:SetHeight(24)
      local hl = it:CreateTexture(nil, "HIGHLIGHT")
      hl:SetAllPoints()
      hl:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 0.18)
      it.bar = it:CreateTexture(nil, "ARTWORK")
      it.bar:SetPoint("TOPLEFT"); it.bar:SetPoint("BOTTOMLEFT")
      it.bar:SetWidth(2)
      it.bar:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 1)
      it.fs = it:CreateFontString(nil, "OVERLAY", "UAHFontBody")
      it.fs:SetPoint("LEFT", 12, 0); it.fs:SetPoint("RIGHT", -10, 0)
      it.fs:SetJustifyH("LEFT")
      menu.items[i] = it
    end
    it:ClearAllPoints()
    it:SetPoint("TOPLEFT", 1, -4 - (i - 1) * 24)
    it:SetPoint("RIGHT", -1, 0)
    it.fs:SetText(o[2])
    local sel = i == owner.i
    it.bar:SetShown(sel)
    if sel then it.fs:SetTextColor(C.accent[1], C.accent[2], C.accent[3]) else it.fs:SetTextColor(C.text[1], C.text[2], C.text[3]) end
    it:SetScript("OnClick", function()
      menu:Hide()
      owner.i = i
      owner:Refresh()
      owner.onChange(owner:Value())
    end)
    it:Show()
  end
  for i = #opts + 1, #menu.items do menu.items[i]:Hide() end
  menu:SetSize(math.max(owner:GetWidth(), 150), #opts * 24 + 8)
  menu:ClearAllPoints()
  menu:SetPoint("TOPLEFT", owner, "BOTTOMLEFT", 0, -3)
  menu.catcher:Show()
  menu:Show()
end

function W.Cycle(parent, prefix, width, opts, onChange)
  local b = CreateFrame("Button", nil, parent)
  b:SetSize(width or 140, 26)
  b.bg = W.Fill(b, C.panel)
  W.Border(b)
  local hl = b:CreateTexture(nil, "HIGHLIGHT")
  hl:SetAllPoints()
  hl:SetColorTexture(1, 1, 1, 0.04)
  local fs = b:CreateFontString(nil, "OVERLAY", "UAHFontBody")
  fs:SetPoint("LEFT", 10, 0)
  fs:SetPoint("RIGHT", -24, 0)
  fs:SetJustifyH("LEFT")
  fs:SetWordWrap(false)
  for i = 1, 2 do                     -- chevron
    local l = b:CreateLine(nil, "OVERLAY")
    l:SetThickness(1.5)
    l:SetColorTexture(C.muted[1], C.muted[2], C.muted[3], 1)
    l:SetStartPoint("RIGHT", b, i == 1 and -16 or -8, 2)
    l:SetEndPoint("RIGHT", b, -12, -2)
  end
  b.opts, b.i, b.onChange = opts, 1, onChange
  function b:Refresh()
    local o = self.opts[self.i] or self.opts[1]
    fs:SetText(W.MUTED .. prefix .. "|r  " .. (o and o[2] or "-"))
  end
  function b:Value() local o = self.opts[self.i]; return o and o[1] end
  function b:SetOptions(o)
    local cur = self:Value()
    self.opts, self.i = o, 1
    for i, x in ipairs(o) do if x[1] == cur then self.i = i end end
    self:Refresh()
  end
  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  b:SetScript("OnClick", function(self, btn)
    if btn == "RightButton" then
      self.i = (self.i - 2) % #self.opts + 1
      self:Refresh()
      onChange(self:Value())
    else
      openMenu(self)
    end
  end)
  b:HookScript("OnHide", function(self) if menu and menu.owner == self then menu:Hide() end end)
  b:Refresh()
  return b
end

---------------------------------------------------------------------------
-- switch with a label and a description line
---------------------------------------------------------------------------
function W.Toggle(parent, label, desc, get, set, width)
  local c = CreateFrame("Button", nil, parent)
  c:SetSize(width or 420, desc and 40 or 28)
  local track = CreateFrame("Frame", nil, c)
  track:SetSize(34, 18)
  track:SetPoint("TOPLEFT", 0, -2)
  local capL = W.Circle(track, 18, C.border, "BACKGROUND")
  capL:SetPoint("LEFT")
  local capR = W.Circle(track, 18, C.border, "BACKGROUND")
  capR:SetPoint("RIGHT")
  local mid = track:CreateTexture(nil, "BACKGROUND")
  mid:SetPoint("TOPLEFT", 9, 0); mid:SetPoint("BOTTOMRIGHT", -9, 0)
  local knob = W.Circle(track, 14, { 1, 1, 1 }, "ARTWORK")
  local fs = c:CreateFontString(nil, "OVERLAY", "UAHFontBody")
  fs:SetPoint("TOPLEFT", 46, -3)
  fs:SetText(label)
  if desc then
    local d = c:CreateFontString(nil, "OVERLAY", "UAHFontMuted")
    d:SetPoint("TOPLEFT", 46, -20)
    d:SetPoint("RIGHT", 0, 0)
    d:SetJustifyH("LEFT")
    d:SetText(desc)
  end
  function c:Sync()
    local on = get() and true or false
    local col = on and C.accent or { 0.2, 0.22, 0.28 }
    for _, t in ipairs({ capL, capR, mid }) do t:SetColorTexture(col[1], col[2], col[3], 1) end
    knob:ClearAllPoints()
    knob:SetPoint(on and "RIGHT" or "LEFT", on and -2 or 2, 0)
    knob:SetVertexColor(1, 1, 1, on and 1 or 0.7)
  end
  function c:GetChecked() return get() end
  c:SetScript("OnClick", function(self)
    set(not get())
    self:Sync()
    if self.onChange then self.onChange() end
  end)
  c:Sync()
  return c
end

---------------------------------------------------------------------------
-- stat card: small label, big value, optional note
---------------------------------------------------------------------------
function W.Stat(parent, width, label)
  local f = W.Panel(parent, C.panel)
  f:SetSize(width, 60)
  f.bar = f:CreateTexture(nil, "ARTWORK")
  f.bar:SetPoint("TOPLEFT", 1, -1)
  f.bar:SetPoint("TOPRIGHT", -1, -1)
  f.bar:SetHeight(2)
  f.bar:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 0.0)
  f.label = f:CreateFontString(nil, "OVERLAY", "UAHFontLabel")
  f.label:SetPoint("TOPLEFT", 12, -10)
  f.label:SetText(label:upper())
  f.value = f:CreateFontString(nil, "OVERLAY", "UAHFontBig")
  f.value:SetPoint("BOTTOMLEFT", 12, 10)
  f.value:SetPoint("BOTTOMRIGHT", -10, 10)
  f.value:SetJustifyH("LEFT")
  f.value:SetWordWrap(false)
  f.note = f:CreateFontString(nil, "OVERLAY", "UAHFontMuted")
  f.note:SetPoint("TOPRIGHT", -10, -9)
  f.note:SetPoint("LEFT", f.label, "RIGHT", 8, 0)
  f.note:SetJustifyH("RIGHT")
  f.note:SetWordWrap(false)
  function f:Set(value, color, note, barColor)
    self.value:SetText(value or "")
    local c = color or C.text
    self.value:SetTextColor(c[1], c[2], c[3])
    self.note:SetText(note or "")
    local b = barColor or color
    if b then self.bar:SetColorTexture(b[1], b[2], b[3], 0.9) else self.bar:SetColorTexture(0, 0, 0, 0) end
  end
  return f
end

-- a row of equal stat cards across `width`
function W.StatRow(parent, width, labels, gap)
  gap = gap or 10
  local n = #labels
  local w = math.floor((width - gap * (n - 1)) / n)
  local cards = {}
  for i, l in ipairs(labels) do
    local c = W.Stat(parent, w, l)
    if i == 1 then c:SetPoint("TOPLEFT") else c:SetPoint("LEFT", cards[i - 1], "RIGHT", gap, 0) end
    cards[i] = c
  end
  return cards
end

---------------------------------------------------------------------------
-- line graph: series = { { name=, color={r,g,b}, points={ {t, v}, ... } }, ... }
---------------------------------------------------------------------------
function W.Graph(parent, width, height, fmtY)
  local g = W.Panel(parent, C.panel)
  g:SetSize(width, height)
  local L, B, R, T = 78, 24, 14, 14
  local plot = CreateFrame("Frame", nil, g)
  plot:SetPoint("TOPLEFT", L, -T)
  plot:SetPoint("BOTTOMRIGHT", -R, B)
  g.plot = plot
  local pw, ph = width - L - R, height - T - B
  g.lines, g.grid, g.ylabels, g.xlabels, g.fills = {}, {}, {}, {}, {}
  local lineN, fillN = 0, 0
  local function fill()
    fillN = fillN + 1
    local f = g.fills[fillN]
    if not f then f = plot:CreateTexture(nil, "BACKGROUND", nil, 1); g.fills[fillN] = f end
    f:Show()
    return f
  end

  local function line(layer)
    lineN = lineN + 1
    local l = g.lines[lineN]
    if not l then l = plot:CreateLine(nil, layer or "ARTWORK"); g.lines[lineN] = l end
    l:Show()
    return l
  end

  for i = 1, 5 do
    local gl = plot:CreateLine(nil, "BACKGROUND")
    gl:SetColorTexture(1, 1, 1, 0.05)
    gl:SetThickness(1)
    g.grid[i] = gl
    local yl = g:CreateFontString(nil, "OVERLAY", "UAHFontLabel")
    yl:SetJustifyH("RIGHT")
    yl:SetWidth(L - 12)
    g.ylabels[i] = yl
    g.xlabels[i] = g:CreateFontString(nil, "OVERLAY", "UAHFontLabel")
  end
  g.empty = g:CreateFontString(nil, "OVERLAY", "UAHFontMuted")
  g.empty:SetPoint("CENTER", plot)
  g.dot = W.Circle(plot, 9, C.accent, "OVERLAY")
  g.dot:Hide()

  local marker = plot:CreateLine(nil, "OVERLAY")
  marker:SetColorTexture(1, 1, 1, 0.25)
  marker:SetThickness(1)
  marker:Hide()

  function g:SetData(series, x0, x1)
    self.series = series
    for i = 1, lineN do self.lines[i]:Hide() end
    for i = 1, fillN do self.fills[i]:Hide() end
    lineN, fillN = 0, 0
    self.dot:Hide()
    local ymin, ymax, n = math.huge, -math.huge, 0
    local tmin, tmax = math.huge, -math.huge
    for _, s in ipairs(series) do
      for _, p in ipairs(s.points) do
        n = n + 1
        if p[2] < ymin then ymin = p[2] end
        if p[2] > ymax then ymax = p[2] end
        if p[1] < tmin then tmin = p[1] end
        if p[1] > tmax then tmax = p[1] end
      end
    end
    x0 = x0 or tmin
    x1 = x1 or tmax
    if n < 2 or x1 <= x0 then
      self.empty:SetText(n == 0 and "No history yet - it records as you play." or "Not enough history yet - check back later.")
      for i = 1, 5 do self.grid[i]:Hide(); self.ylabels[i]:SetText(""); self.xlabels[i]:SetText("") end
      if n == 1 then x0, x1 = tmin - 3600, tmin + 3600 else return end
    else
      self.empty:SetText("")
    end
    if ymin == ymax then ymin, ymax = ymin * 0.9, ymax * 1.1 + 10000 end
    local pad = (ymax - ymin) * 0.08
    ymin = math.max(0, ymin - pad)
    ymax = ymax + pad
    self.x0, self.x1, self.y0, self.y1 = x0, x1, ymin, ymax
    local function X(t) return (t - x0) / (x1 - x0) * pw end
    local function Y(v) return (v - ymin) / (ymax - ymin) * ph end
    self.X, self.Y = X, Y
    for i = 1, 5 do
      local v = ymin + (ymax - ymin) * (i - 1) / 4
      local y = Y(v)
      self.grid[i]:SetStartPoint("BOTTOMLEFT", plot, 0, y)
      self.grid[i]:SetEndPoint("BOTTOMLEFT", plot, pw, y)
      self.grid[i]:Show()
      self.ylabels[i]:ClearAllPoints()
      self.ylabels[i]:SetPoint("RIGHT", plot, "BOTTOMLEFT", -10, y)
      self.ylabels[i]:SetText(fmtY and fmtY(v) or tostring(math.floor(v)))
      local t = x0 + (x1 - x0) * (i - 1) / 4
      self.xlabels[i]:ClearAllPoints()
      self.xlabels[i]:SetPoint("TOP", plot, "BOTTOMLEFT", X(t), -6)
      self.xlabels[i]:SetText(date((x1 - x0) > 3 * 86400 and "%d %b" or "%d %b %H:%M", t))
    end
    for si, s in ipairs(series) do
      local prev
      for _, p in ipairs(s.points) do
        if p[1] >= x0 then
          local x, y = X(p[1]), Y(p[2])
          if prev then
            -- area fill + a faint wide stroke under the main line
            if si == #series and x - prev[1] >= 0.5 then
              local fl = fill()
              fl:SetColorTexture(s.color[1], s.color[2], s.color[3], 0.05)
              fl:ClearAllPoints()
              fl:SetPoint("BOTTOMLEFT", plot, "BOTTOMLEFT", prev[1], 0)
              fl:SetSize(x - prev[1], math.max(1, (prev[2] + y) / 2))
            end
            if si == #series then
              local gl = line("BORDER")
              gl:SetColorTexture(s.color[1], s.color[2], s.color[3], 0.15)
              gl:SetThickness((s.thick or 2) + 5)
              gl:SetStartPoint("BOTTOMLEFT", plot, prev[1], prev[2])
              gl:SetEndPoint("BOTTOMLEFT", plot, x, y)
            end
            local l = line()
            l:SetColorTexture(s.color[1], s.color[2], s.color[3], s.alpha or 1)
            l:SetThickness(s.thick or 2)
            l:SetStartPoint("BOTTOMLEFT", plot, prev[1], prev[2])
            l:SetEndPoint("BOTTOMLEFT", plot, x, y)
          end
          prev = { x, y }
        end
      end
      if prev and si == #series then
        self.dot:SetVertexColor(s.color[1], s.color[2], s.color[3], 1)
        self.dot:ClearAllPoints()
        self.dot:SetPoint("CENTER", plot, "BOTTOMLEFT", prev[1], prev[2])
        self.dot:Show()
      end
    end
  end

  -- hover: value of every series at the mouse position
  plot:EnableMouse(true)
  plot:SetScript("OnLeave", function() marker:Hide(); GameTooltip:Hide() end)
  plot:SetScript("OnUpdate", function(self)
    if not self:IsMouseOver() or not g.series or not g.X then return end
    local mx = GetCursorPosition() / self:GetEffectiveScale() - self:GetLeft()
    local t = g.x0 + (g.x1 - g.x0) * (mx / pw)
    marker:SetStartPoint("BOTTOMLEFT", self, mx, 0)
    marker:SetEndPoint("BOTTOMLEFT", self, mx, ph)
    marker:Show()
    GameTooltip:SetOwner(self, "ANCHOR_CURSOR")
    local shownT
    for i = #g.series, 1, -1 do
      local s = g.series[i]
      local best
      for _, p in ipairs(s.points) do if p[1] <= t then best = p else break end end
      best = best or s.points[1]
      if best then
        if not shownT then GameTooltip:AddLine(date("%d %b %Y %H:%M", best[1])); shownT = true end
        GameTooltip:AddDoubleLine(s.name, fmtY and fmtY(best[2]) or best[2], s.color[1], s.color[2], s.color[3], 1, 1, 1)
      end
    end
    GameTooltip:Show()
  end)

  return g
end

---------------------------------------------------------------------------
-- table: columns = { { title=, width=, justify=, icon=bool }, ... }
-- rows   = { { cells = {...}, sort = {...}, link=, itemID=, colors={...}, tip={...} }, ... }
---------------------------------------------------------------------------
function W.Table(parent, columns, numRows)
  local t = CreateFrame("Frame", nil, parent)
  t.columns, t.numRows, t.offset, t.data = columns, numRows, 0, {}
  t.sortCol, t.sortAsc = nil, false
  local width = 0
  for _, c in ipairs(columns) do width = width + c.width end
  t:SetSize(width + 16, (numRows + 1) * ROW_H + 6)

  -- header
  local x = 0
  t.headers = {}
  for i, c in ipairs(columns) do
    local h = CreateFrame("Button", nil, t)
    h:SetSize(c.width, ROW_H)
    h:SetPoint("TOPLEFT", x, 0)
    local fs = h:CreateFontString(nil, "OVERLAY", "UAHFontLabel")
    local gap = (c.justify ~= "RIGHT" and i > 1 and columns[i - 1].justify == "RIGHT") and 16 or (c.justify == "RIGHT" and 0 or 6)
    fs:SetPoint("TOPLEFT", gap, 0)
    fs:SetPoint("BOTTOMRIGHT", c.justify == "RIGHT" and -6 or 0, 0)
    fs:SetJustifyH(c.justify or "LEFT")
    fs:SetText(c.title:upper())
    h.fs = fs
    h:SetScript("OnClick", function()
      if t.sortCol == i then t.sortAsc = not t.sortAsc else t.sortCol, t.sortAsc = i, c.justify ~= "RIGHT" end
      t:Sort()
      t:Refresh()
    end)
    local hl = h:CreateTexture(nil, "HIGHLIGHT")
    hl:SetAllPoints()
    hl:SetColorTexture(1, 1, 1, 0.03)
    h.chev = {}
    for k = 1, 2 do
      local l = h:CreateLine(nil, "OVERLAY")
      l:SetThickness(1.5)
      l:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 1)
      l:Hide()
      h.chev[k] = l
    end
    h.right = c.justify == "RIGHT"
    h.gap = gap
    t.headers[i] = h
    x = x + c.width
  end
  local line = t:CreateTexture(nil, "ARTWORK")
  line:SetColorTexture(C.border[1], C.border[2], C.border[3], 1)
  line:SetPoint("TOPLEFT", 0, -ROW_H - 1)
  line:SetSize(width, 1)

  -- rows
  t.rows = {}
  for r = 1, numRows do
    local row = CreateFrame("Button", nil, t)
    row:SetSize(width, ROW_H)
    row:SetPoint("TOPLEFT", 0, -(r * ROW_H) - 4)
    local bg = row:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(1, 1, 1, (r % 2 == 0) and 0.018 or 0)
    local hl = row:CreateTexture(nil, "HIGHLIGHT")
    hl:SetAllPoints()
    hl:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 0.10)
    local bar = row:CreateTexture(nil, "HIGHLIGHT")
    bar:SetPoint("TOPLEFT"); bar:SetPoint("BOTTOMLEFT")
    bar:SetWidth(2)
    bar:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 1)
    -- the selected row (tables with t.isSelected = function(data) ... end)
    local sel = row:CreateTexture(nil, "BORDER")
    sel:SetAllPoints()
    sel:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 0.16)
    sel:Hide()
    local selBar = row:CreateTexture(nil, "ARTWORK")
    selBar:SetPoint("TOPLEFT"); selBar:SetPoint("BOTTOMLEFT")
    selBar:SetWidth(2)
    selBar:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 1)
    selBar:Hide()
    row.sel, row.selBar = sel, selBar
    row.cells = {}
    local cx = 0
    for i, c in ipairs(columns) do
      local fs = row:CreateFontString(nil, "OVERLAY", "UAHFontBody")
      fs:SetJustifyH(c.justify or "LEFT")
      fs:SetWordWrap(false)
      if c.icon then
        local ic = row:CreateTexture(nil, "ARTWORK")
        ic:SetSize(ROW_H - 4, ROW_H - 4)
        ic:SetPoint("LEFT", cx + 6, 0)
        ic:SetTexCoord(0.08, 0.92, 0.08, 0.92)
        row.icon = ic
        fs:SetPoint("LEFT", cx + ROW_H + 8, 0)
        fs:SetWidth(c.width - ROW_H - 12)
      else
        local gap = (c.justify ~= "RIGHT" and i > 1 and columns[i - 1].justify == "RIGHT") and 16 or 6
        fs:SetPoint("LEFT", cx + gap, 0)
        fs:SetWidth(c.width - gap - 6)
      end
      if c.pill then
        row.pills = row.pills or {}
        local p = row:CreateTexture(nil, "ARTWORK")
        p:SetHeight(ROW_H - 6)
        p:SetPoint("LEFT", fs, "LEFT", -6, 0)
        row.pills[i] = p
      end
      row.cells[i] = fs
      cx = cx + c.width
    end
    row:RegisterForClicks("LeftButtonUp", "RightButtonUp")
    row:SetScript("OnEnter", function(self)
      local d = self.data
      if not d then return end
      if d.link or d.itemID then
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        if d.link and d.link:find("|H") then GameTooltip:SetHyperlink(d.link)
        elseif d.itemID then GameTooltip:SetItemByID(d.itemID) end
        if d.tip then for _, l in ipairs(d.tip) do GameTooltip:AddLine(l, 1, 1, 1, true) end end
        GameTooltip:Show()
      elseif d.tip then
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        for i, l in ipairs(d.tip) do GameTooltip:AddLine(l, 1, 1, 1, i > 1) end
        GameTooltip:Show()
      end
    end)
    row:SetScript("OnLeave", function() GameTooltip:Hide() end)
    row:SetScript("OnClick", function(self, btn)
      local d = self.data
      if not d then return end
      if IsModifiedClick("CHATLINK") and d.link then
        ChatEdit_InsertLink(d.link)
      elseif t.onClick then
        t.onClick(d, btn)
      end
    end)
    t.rows[r] = row
  end

  -- thin scroll bar
  local sb = CreateFrame("Slider", nil, t)
  sb:SetOrientation("VERTICAL")
  sb:SetPoint("TOPLEFT", width + 8, -ROW_H - 4)
  sb:SetSize(4, numRows * ROW_H)
  W.Fill(sb, { 1, 1, 1, 0.04 })
  local thumb = sb:CreateTexture(nil, "OVERLAY")
  thumb:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 0.7)
  thumb:SetSize(4, 36)
  sb:SetThumbTexture(thumb)
  sb:SetMinMaxValues(0, 0)
  sb:SetValueStep(1)
  sb:SetObeyStepOnDrag(true)
  sb:SetScript("OnValueChanged", function(_, v)
    v = math.floor(v + 0.5)
    if v ~= t.offset then t.offset = v; t:Refresh() end
  end)
  t.scrollbar = sb

  t:EnableMouseWheel(true)
  t:SetScript("OnMouseWheel", function(_, delta)
    local step = IsShiftKeyDown() and t.numRows or 3
    local maxOff = math.max(0, #t.data - t.numRows)
    t.offset = math.max(0, math.min(maxOff, t.offset - delta * step))
    t.scrollbar:SetValue(t.offset)
    t:Refresh()
  end)

  t.empty = t:CreateFontString(nil, "OVERLAY", "UAHFontMuted")
  t.empty:SetPoint("TOP", 0, -ROW_H * 3)
  t.empty:SetWidth(width - 40)

  function t:SetData(rows, keepOffset)
    self.data = rows or {}
    if self.sortCol then self:Sort() end
    if not keepOffset then self.offset = 0 end
    self:Refresh()
  end

  function t:Sort()
    local i, asc = self.sortCol, self.sortAsc
    if not i then return end
    table.sort(self.data, function(a, b)
      local x, y = a.sort and a.sort[i], b.sort and b.sort[i]
      if x == nil then x = a.cells[i] end
      if y == nil then y = b.cells[i] end
      if type(x) ~= type(y) then x, y = tostring(x), tostring(y) end
      if x == y then return false end
      if asc then return x < y else return x > y end
    end)
    for j, h in ipairs(self.headers) do
      local c = self.columns[j]
      h.fs:SetText(c.title:upper())
      local on = j == i
      if on then h.fs:SetTextColor(C.accent[1], C.accent[2], C.accent[3]) else h.fs:SetTextColor(C.muted[1], C.muted[2], C.muted[3]) end
      local tw = h.fs:GetStringWidth() or 0
      local cx = h.right and (c.width - 6 - tw - 8) or (h.gap + tw + 8)
      local dy = asc and -1.5 or 1.5           -- chevron points down when sorted high-to-low
      h.chev[1]:SetStartPoint("LEFT", h, cx - 3, dy)
      h.chev[1]:SetEndPoint("LEFT", h, cx, -dy)
      h.chev[2]:SetStartPoint("LEFT", h, cx, -dy)
      h.chev[2]:SetEndPoint("LEFT", h, cx + 3, dy)
      h.chev[1]:SetShown(on)
      h.chev[2]:SetShown(on)
    end
  end

  function t:Refresh()
    local maxOff = math.max(0, #self.data - self.numRows)
    if self.offset > maxOff then self.offset = maxOff end
    self.scrollbar:SetMinMaxValues(0, maxOff)
    self.scrollbar:SetValue(self.offset)
    self.scrollbar:SetShown(maxOff > 0)
    for r, row in ipairs(self.rows) do
      local d = self.data[r + self.offset]
      row.data = d
      if d then
        for i, fs in ipairs(row.cells) do
          fs:SetText(d.cells[i] ~= nil and tostring(d.cells[i]) or "")
          local col = d.colors and d.colors[i]
          if col then fs:SetTextColor(col[1], col[2], col[3]) else fs:SetTextColor(C.text[1], C.text[2], C.text[3]) end
          local p = row.pills and row.pills[i]
          if p then
            local txt = d.cells[i] ~= nil and tostring(d.cells[i]) or ""
            if txt ~= "" then
              local pc = col or C.muted
              p:SetColorTexture(pc[1], pc[2], pc[3], 0.13)
              p:SetWidth(math.min(fs:GetStringWidth() + 12, self.columns[i].width - 4))
              p:Show()
            else
              p:Hide()
            end
          end
        end
        if row.icon then
          row.icon:SetTexture(d.icon)
          row.icon:SetShown(d.icon ~= nil)
        end
        local on = self.isSelected and self.isSelected(d) or false
        row.sel:SetShown(on)
        row.selBar:SetShown(on)
        row:Show()
      else
        row:Hide()
      end
    end
    self.empty:SetText(#self.data == 0 and (self.emptyText or "Nothing to show.") or "")
  end

  return t
end
