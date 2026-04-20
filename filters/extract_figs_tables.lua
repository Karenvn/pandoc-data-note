-- place_figs_tables_after_refs.lua
-- Goal:
--   1) Remove figures and tables from the main flow.
--   2) Ensure a 'refs' anchor exists:
--        - If a References/Bibliography/Literature cited/Works cited heading exists,
--          inject ::: {#refs} ::: *immediately after that heading*.
--        - Otherwise, add a 'refs' placeholder near the end of the body.
--   3) Make References, Figures and Tables each start on a new page.
--   4) Append "Figures" then "Tables" after everything else.
--
-- Result with --citeproc:
--   body … → page break → heading "References" → <Div id="refs"> (filled by citeproc)
--           → page break → Figures
--           → page break → Tables

local stringify = pandoc.utils.stringify
local function lower(s) return string.lower(s or "") end

-- --- helpers ---------------------------------------------------------------

local function has_class(el, klass)
  if not el then return false end
  if el.classes then
    for _, c in ipairs(el.classes) do
      if c == klass then return true end
    end
  end
  if el.attributes and el.attributes["class"] then
    for c in el.attributes["class"]:gmatch("%S+") do
      if c == klass then return true end
    end
  end
  return false
end

local function is_refs_heading(b)
  if b.t ~= "Header" then return false end
  local txt = lower(stringify(b.content)):gsub("%s+", " ")
  return txt:match("^references")
      or txt:match("^bibliography")
      or txt:match("^literature cited")
      or txt:match("^works cited")
end

local function is_refs_div(b)
  return b.t == "Div"
     and (b.identifier == "refs"
          or has_class(b, "references")
          or has_class(b, "bibliography"))
end

local function is_figure_block(b)
  if b.t == "Figure" then return true end
  if b.t == "Para" or b.t == "Plain" then
    for _, inl in ipairs(b.content or {}) do
      if inl.t == "Image" then return true end
    end
  end
  if b.t == "Div" then
    if has_class(b, "figure") or has_class(b, "Figure") then return true end
    for _, bb in ipairs(b.content or {}) do
      if (bb.t == "Para" or bb.t == "Plain") and bb.content then
        for _, inl in ipairs(bb.content) do
          if inl.t == "Image" then return true end
        end
      end
    end
  end
  return false
end

local function is_table_block(b)
  if b.t == "Table" then return true end
  if b.t == "CodeBlock" and (has_class(b, "table") or has_class(b, "jats-table")) then
    return true
  end
  if b.t == "Div" then
    if has_class(b, "table") or has_class(b, "jats-table") then return true end
    for _, inner in ipairs(b.content or {}) do
      if inner.t == "Table" then return true end
    end
  end
  return false
end

local function is_table_note_block(b)
  if not b then return false end
  if b.t ~= "Para" and b.t ~= "Plain" then return false end
  local txt = lower(stringify(b.content)):gsub("^%s+", "")
  return txt:match("^notes?:")
end

local function refs_placeholder()
  -- ::: {#refs}
  -- :::
  return pandoc.Div({}, pandoc.Attr("refs", {"references"}))
end

local function pagebreak_block()
  if FORMAT and FORMAT:match("docx") then
    return pandoc.RawBlock("openxml", "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>")
  elseif FORMAT and FORMAT:match("latex") then
    return pandoc.RawBlock("latex", "\\newpage")
  elseif FORMAT and FORMAT:match("html") then
    return pandoc.RawBlock("html", "<div style=\"page-break-before: always;\"></div>")
  else
    -- harmless fallback in other formats
    return pandoc.HorizontalRule()
  end
end

-- Optional: allow custom section titles via YAML, but be safe if keys are missing
local function meta_title(meta, key, default)
  local v = meta[key]
  if not v then
    return default
  end
  local s = stringify(v)
  if not s or s == "" then
    return default
  end
  return s
end

-- --- main ------------------------------------------------------------------

function Pandoc(doc)
  local others, figs, tabs = {}, {}, {}
  local have_refs_div = false
  local refs_heading_pos = nil
  local refs_div_pos = nil

  -- Partition blocks and strip out figures/tables
  local i = 1
  while i <= #doc.blocks do
    local b = doc.blocks[i]
    if is_figure_block(b) then
      table.insert(figs, b)
    elseif is_table_block(b) then
      local nxt = doc.blocks[i + 1]
      -- Keep a trailing "Notes:" paragraph attached to its table.
      if is_table_note_block(nxt) then
        table.insert(tabs, pandoc.Div({ b, nxt }, pandoc.Attr("", {"table-with-notes"})))
        i = i + 1
      else
        table.insert(tabs, b)
      end
    else
      local idx = #others + 1
      table.insert(others, b)
      if is_refs_div(b) then
        have_refs_div = true
        refs_div_pos = idx
      elseif is_refs_heading(b) then
        refs_heading_pos = idx
      end
    end
    i = i + 1
  end

  -- Section titles (default to plain English)
  local figs_title = meta_title(doc.meta, "figures-section-title", "Figures")
  local tabs_title = meta_title(doc.meta, "tables-section-title", "Tables")
  local refs_title = meta_title(doc.meta, "reference-section-title", "References")

  -- Ensure References starts on a new page and has a #refs anchor right after it
  if refs_heading_pos then
    -- Insert page break *before* the existing heading
    table.insert(others, refs_heading_pos, pagebreak_block())
    refs_heading_pos = refs_heading_pos + 1
    -- Ensure a #refs div immediately after the heading
    if not have_refs_div then
      table.insert(others, refs_heading_pos + 1, refs_placeholder())
      have_refs_div = true
    end
  else
    -- No heading: insert page break, then heading, then #refs
    table.insert(others, pagebreak_block())
    table.insert(others, pandoc.Header(2, { pandoc.Str(refs_title) }))
    table.insert(others, refs_placeholder())
    have_refs_div = true
  end

  -- If there was a refs div but no heading, add a heading and page break before it
  if have_refs_div and not refs_heading_pos and refs_div_pos then
    table.insert(others, refs_div_pos, pagebreak_block())
    table.insert(others, refs_div_pos + 1, pandoc.Header(2, { pandoc.Str(refs_title) }))
  end

  -- Assemble output: body (with refs) → Figures (new page) → Tables (new page)
  local out = {}
  for _, b in ipairs(others) do
    table.insert(out, b)
  end

  if #figs > 0 then
    table.insert(out, pagebreak_block())
    table.insert(out, pandoc.Header(2, { pandoc.Str(figs_title) }))
    for _, f in ipairs(figs) do
      table.insert(out, f)
    end
  end

  if #tabs > 0 then
    table.insert(out, pagebreak_block())
    table.insert(out, pandoc.Header(2, { pandoc.Str(tabs_title) }))
    for _, t in ipairs(tabs) do
      table.insert(out, t)
    end
  end

  return pandoc.Pandoc(out, doc.meta)
end
