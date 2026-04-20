-- scripts/inject_frontmatter.lua
-- Injects structured metadata (authors, roles, affiliations, collaborators, keywords)
-- into the DOCX body so it renders in Word using your reference DOCX styles.
-- Compatible with Pandoc 2.x/3.x.

-- ========================
-- Output toggles (edit here)
-- ========================
local SHOW_SUPERSCRIPTS   = true   -- ¹ on author names
local SHOW_PER_AUTHOR_AFF = true   -- "Affiliation: …" line per author (for checking)
local SHOW_AFF_LEGEND     = false  -- global legend listing ¹ Org, City, …

-- Optional labels (set to "" to hide)
local AUTHOR_HEADING_TEXT = ""                 -- e.g. "Authors"
local COLLAB_HEADING_TEXT = "Collaborators"
local AFF_HEADING_TEXT    = "Affiliations"
local KEYWORDS_LABEL      = "Keywords: "

-- Paragraph styles (must exist in reference DOCX; else Word falls back to Normal)
local STYLE_HEADING    = "FM-Heading"
local STYLE_NAME       = "FM-Name"
local STYLE_ROLE       = "FM-Role"
local STYLE_AFFIL      = "FM-Affiliation"
-- Use author styles for collaborators as requested
local STYLE_COLLAB     = STYLE_NAME
local STYLE_CORRESP    = STYLE_ROLE
local STYLE_KEYWORDS   = "FM-Keywords"

local stringify = pandoc.utils.stringify

-- Helper: truthy 'yes'
local function is_yes(v)
  if v == nil then return false end
  if type(v) == "boolean" then return v end
  local s = tostring(stringify(v)):lower()
  return (s == "yes" or s == "true" or s == "y" or s == "1")
end

-- Debugging (opt-in): set FRONTMATTER_DEBUG=1 in the environment to log to stderr
local DEBUG = (os.getenv("FRONTMATTER_DEBUG") == "1")
local function dbg(...)
  if DEBUG then
    local parts = {}
    for i = 1, select('#', ...) do parts[i] = tostring(select(i, ...)) end
    io.stderr:write(table.concat(parts, " ") .. "\n")
  end
end

-- Convert a Meta* value (or plain Lua) to a Lua array of strings
local function to_array(x)
  if type(x) == "table" then
    if x.t == "MetaList" then
      local out = {}
      for i = 1, #x do out[i] = stringify(x[i]) end
      return out
    elseif x.t == "MetaInlines" or x.t == "MetaBlocks" or x.t == "MetaString" then
      return { stringify(x) }
    elseif x.t == nil then
      local out = {}
      for i = 1, #x do out[i] = stringify(x[i]) end
      return out
    end
  elseif type(x) == "string" then
    return { x }
  end
  return {}
end

-- Build lookup: affiliation id -> "Org, Dept, City, State, Country"
local function build_aff_lookup(meta)
  local lut = {}
  -- Accept multiple possible keys used across pipelines (JATS, pandoc-scholar, etc.)
  local sources = {
    meta.affiliation, meta.affiliations,
    meta.institution, meta.institutions,
    meta.organization, meta.organizations,
    meta.organisation, meta.organisations
  }
  local seen_source = false
  local function add_aff_entry(id, a)
    id = tostring(tonumber(id) or id)
    if id == "" then return end
    local parts = {
      stringify(a.organization or a.organisation or a.institution or ""),
      stringify(a.department or ""),
      stringify(a.city or ""),
      stringify(a.state or a.region or ""),
      stringify(a.country or "")
    }
    local kept = {}
    for _, p in ipairs(parts) do if p ~= "" then table.insert(kept, p) end end
    local txt = table.concat(kept, ", ")
    if txt ~= "" then lut[id] = txt end
  end
  for _, aff in ipairs(sources) do
    if aff then
      seen_source = true
      if type(aff) == "table" and aff.t == "MetaList" then
        for i = 1, #aff do
          local a = aff[i]
          if type(a) == "table" and a.t == "MetaMap" then
            local id = stringify(a.id or a.key or a.index or "")
            add_aff_entry(id, a)
          end
        end
      elseif type(aff) == "table" and aff.t == "MetaMap" then
        -- Handle YAML maps keyed by the id (e.g. affiliation: { "1": { organization: ... } })
        for k, a in pairs(aff) do
          if k ~= "t" and type(a) == "table" then
            local id = stringify(a.id or a.key or a.index or k)
            add_aff_entry(id, a)
          end
        end
      elseif type(aff) == "table" then
        -- Plain Lua array of tables
        for i = 1, #aff do
          local a = aff[i]
          if type(a) == "table" then
            local id = stringify(a.id or a.key or a.index or i)
            add_aff_entry(id, a)
          end
        end
      else
        -- Single string: assign sequential id
        local idx = tostring(#lut + 1)
        lut[idx] = stringify(aff)
      end
    end
  end
  if DEBUG then
    local ks = {}
    for k,_ in pairs(lut) do table.insert(ks, k) end
    table.sort(ks, function(a,b)
      local na, nb = tonumber(a), tonumber(b)
      if na and nb then return na < nb else return tostring(a) < tostring(b) end
    end)
    dbg("[inject] build_aff_lookup: source_present=", seen_source, "; ids=", table.concat(ks, ","))
  end
  return lut
end

-- Wrap a paragraph in a Div that assigns a DOCX custom paragraph style
local function para_with_style(inlines, style)
  local p = pandoc.Para(inlines)
  if style and style ~= "" then
    return pandoc.Div(p, pandoc.Attr("", {}, { ["custom-style"] = style }))
  end
  return p
end

-- Superscript digits for 0..9
local superscripts = { ["0"]="⁰", ["1"]="¹", ["2"]="²", ["3"]="³", ["4"]="⁴",
                       ["5"]="⁵", ["6"]="⁶", ["7"]="⁷", ["8"]="⁸", ["9"]="⁹" }
local function sup_str(s)
  local out = {}
  for c in tostring(s):gmatch(".") do table.insert(out, superscripts[c] or c) end
  return table.concat(out)
end

-- Create front-matter blocks from meta
local function make_frontmatter(meta)
  local blocks = {}

  -- Affiliation lookup
  local aff_lut = build_aff_lookup(meta)

  -- Capture authors before removing default DOCX author output
  local authors_src = meta.author    -- MetaList / array / MetaMap
  meta.author = nil                  -- stop DOCX writer emitting its own author line

  -- Normalise authors to array of items
  local authors = {}
  if authors_src then
    if type(authors_src) == "table" and authors_src.t == "MetaList" then
      for i = 1, #authors_src do authors[i] = authors_src[i] end
    elseif type(authors_src) == "table" then
      for i = 1, #authors_src do authors[i] = authors_src[i] end
    else
      authors = { authors_src }
    end
  end

  if AUTHOR_HEADING_TEXT ~= "" then
    table.insert(blocks, para_with_style({ pandoc.Str(AUTHOR_HEADING_TEXT) }, STYLE_HEADING))
  end

  for _, am in ipairs(authors) do
    local given  = stringify(am["given-names"] or "")
    local family = stringify(am.surname or "")
    local email  = stringify(am.email or "")
    local afids  = to_array(am.affiliation)  -- e.g. {"1","2"}

    dbg("[inject] author:", given .. " " .. family, "affids=", table.concat(afids, ","))

    -- Name line: Given Family + optional superscripts + optional <mailto:>
    local line = {}
    if given ~= "" then table.insert(line, pandoc.Str(given .. " ")) end
    if family ~= "" then table.insert(line, pandoc.Str(family)) end
    if SHOW_SUPERSCRIPTS and #afids > 0 then
      -- Only superscript numeric IDs; ignore free text
      local numeric = {}
      for _, id in ipairs(afids) do
        local s = tostring(id)
        if s:match("^%d+$") then table.insert(numeric, s) end
      end
      if #numeric > 0 then
        local sup = {}
        for _, s in ipairs(numeric) do table.insert(sup, sup_str(s)) end
        table.insert(line, pandoc.Str(table.concat(sup, "")))
      end
    end
    if email ~= "" then
      table.insert(line, pandoc.Space())
      table.insert(line, pandoc.Str("<"))
      table.insert(line, pandoc.Link(email, "mailto:" .. email))
      table.insert(line, pandoc.Str(">"))
    end
    table.insert(blocks, para_with_style(line, STYLE_NAME))

    -- Roles line
    local roles = to_array(am.role)
    if #roles > 0 then
      table.insert(blocks, para_with_style({ pandoc.Str("Roles: " .. table.concat(roles, "; ")) }, STYLE_ROLE))
    end

    -- Explicit affiliation line(s) per author (for checking)
    if SHOW_PER_AUTHOR_AFF and #afids > 0 then
      local affs = {}
      for _, id in ipairs(afids) do
        local key = stringify(id); key = tostring(tonumber(key) or key)
        if aff_lut[key] and aff_lut[key] ~= "" then
          table.insert(affs, aff_lut[key])
        else
          -- Free text vs numeric id
          if key:match("^%d+$") then
            table.insert(affs, "[" .. key .. "]")
          else
            table.insert(affs, key)
          end
        end
      end
      dbg("[inject] resolved affiliations:", table.concat(affs, " ; "))
      table.insert(blocks, para_with_style({ pandoc.Str("Affiliation: " .. table.concat(affs, " ; ")) }, STYLE_AFFIL))
    end
  end

  -- Collaborators
  do
    local collab_src = meta.collab
    local clist = {}
    if collab_src then
      if type(collab_src) == "table" and collab_src.t == "MetaList" then
        for i = 1, #collab_src do clist[i] = collab_src[i] end
      elseif type(collab_src) == "table" then
        for i = 1, #collab_src do clist[i] = collab_src[i] end
      else
        clist = { collab_src }
      end
    end

    if #clist > 0 then
      if COLLAB_HEADING_TEXT ~= "" then
        table.insert(blocks, para_with_style({ pandoc.Str(COLLAB_HEADING_TEXT) }, STYLE_HEADING))
      end

      local dagger = "†"
      for _, c in ipairs(clist) do
        if type(c) == "table" and c.t == "MetaMap" then
          local nm = stringify(c.name or "")
          if nm ~= "" then
            if is_yes(c.corresp) then nm = nm .. dagger end
            table.insert(blocks, para_with_style({ pandoc.Str(nm) }, STYLE_COLLAB))
          end
        else
          local nm = stringify(c)
          if nm ~= "" then
            table.insert(blocks, para_with_style({ pandoc.Str(nm) }, STYLE_COLLAB))
          end
        end
      end

      -- Single correspondence line (first collab with corresp: yes and email)
      for _, c in ipairs(clist) do
        if type(c) == "table" and c.t == "MetaMap" and is_yes(c.corresp) and c.email then
          local em = stringify(c.email)
          local line = {
            pandoc.Str("† Correspondence: "),
            pandoc.Str("<"),
            pandoc.Link(em, "mailto:" .. em),
            pandoc.Str(">")
          }
          table.insert(blocks, para_with_style(line, STYLE_CORRESP))
          break
        end
      end
    end
  end

  -- Affiliations legend (optional)
  if SHOW_AFF_LEGEND and next(aff_lut) ~= nil then
    if AFF_HEADING_TEXT ~= "" then
      table.insert(blocks, para_with_style({ pandoc.Str(AFF_HEADING_TEXT) }, STYLE_HEADING))
    end
    local ids = {}
    for id,_ in pairs(aff_lut) do table.insert(ids, id) end
    table.sort(ids, function(a,b)
      local na, nb = tonumber(a), tonumber(b)
      if na and nb then return na < nb else return tostring(a) < tostring(b) end
    end)
    for _, id in ipairs(ids) do
      local txt = sup_str(id) .. " " .. aff_lut[id]
      table.insert(blocks, para_with_style({ pandoc.Str(txt) }, STYLE_AFFIL))
    end
  end

  -- Keywords
  if meta.keywords then
    local kws = to_array(meta.keywords)
    if #kws > 0 then
      table.insert(blocks, para_with_style({ pandoc.Str(KEYWORDS_LABEL .. table.concat(kws, "; ")) }, STYLE_KEYWORDS))
    end
  end

  return blocks
end

function Pandoc(doc)
  local pre = make_frontmatter(doc.meta)
  if #pre == 0 then return doc end
  local all = {}
  for _, b in ipairs(pre) do table.insert(all, b) end
  for _, b in ipairs(doc.blocks) do table.insert(all, b) end
  return pandoc.Pandoc(all, doc.meta)
end
