-- Combined pre-processing filter for Markdown -> JATS workflows.
-- 1) Promote table IDs from caption tokens like "{#tbl:table1}" to table attrs.
-- 2) Preserve BibTeX \textit{...}/\emph{...} through element_citations by
--    rewriting to neutral markers in temporary .bib files.

local stringify = pandoc.utils.stringify
local ptype = pandoc.utils.type

-- ---------------------------------------------------------------------------
-- Bibliography normalization
-- ---------------------------------------------------------------------------

local function replace_latex_italics(text)
  local out = text
  local changed = true
  while changed do
    changed = false
    local n1
    out, n1 = out:gsub("\\textit%s*(%b{})", function(braced)
      return "__ITALIC_OPEN__" .. braced:sub(2, -2) .. "__ITALIC_CLOSE__"
    end)
    if n1 > 0 then
      changed = true
    end

    local n2
    out, n2 = out:gsub("\\emph%s*(%b{})", function(braced)
      return "__ITALIC_OPEN__" .. braced:sub(2, -2) .. "__ITALIC_CLOSE__"
    end)
    if n2 > 0 then
      changed = true
    end
  end
  return out
end

local function meta_to_paths(meta_val)
  if not meta_val then
    return {}
  end

  local t = ptype(meta_val)
  if t == "List" or t == "MetaList" then
    local out = {}
    for _, item in ipairs(meta_val) do
      out[#out + 1] = stringify(item)
    end
    return out
  end

  local s = stringify(meta_val)
  local out = {}
  for part in s:gmatch("[^,]+") do
    local trimmed = part:gsub("^%s+", ""):gsub("%s+$", "")
    if trimmed ~= "" then
      out[#out + 1] = trimmed
    end
  end
  return out
end

local function write_temp_bib(src_path)
  local fh = io.open(src_path, "r")
  if not fh then
    return nil
  end
  local content = fh:read("*a")
  fh:close()

  local rewritten = replace_latex_italics(content)
  local tmp = os.tmpname() .. ".bib"
  local wf = io.open(tmp, "w")
  if not wf then
    return nil
  end
  wf:write(rewritten)
  wf:close()
  return tmp
end

function Meta(meta)
  if not meta.bibliography then
    return nil
  end

  local bib_paths = meta_to_paths(meta.bibliography)
  if #bib_paths == 0 then
    return nil
  end

  local out = {}
  for _, p in ipairs(bib_paths) do
    if p:match("%.bib$") then
      local tmp = write_temp_bib(p)
      out[#out + 1] = pandoc.Inlines({ pandoc.Str(tmp or p) })
    else
      out[#out + 1] = pandoc.Inlines({ pandoc.Str(p) })
    end
  end

  meta.bibliography = out
  return meta
end

-- ---------------------------------------------------------------------------
-- Table ID normalization
-- ---------------------------------------------------------------------------

local function strip_id_tokens(inlines)
  local out = {}
  local found_id = nil

  for _, inline in ipairs(inlines) do
    if inline.t == "Str" then
      local text = inline.text
      local id = text:match("{#(tbl:[^}]+)}")
      if id and not found_id then
        found_id = id
      end
      local cleaned = text:gsub("{#tbl:[^}]+}", "")
      if cleaned ~= "" then
        inline.text = cleaned
        out[#out + 1] = inline
      end
    else
      out[#out + 1] = inline
    end
  end

  if #out > 0 and out[1].t == "Space" then
    table.remove(out, 1)
  end
  if #out > 0 and out[#out].t == "Space" then
    table.remove(out, #out)
  end

  return out, found_id
end

function Table(tbl)
  local found_id = nil

  if tbl.caption and tbl.caption.long then
    for i, block in ipairs(tbl.caption.long) do
      if block.t == "Para" or block.t == "Plain" then
        local cleaned, id_here = strip_id_tokens(block.content)
        if id_here and not found_id then
          found_id = id_here
        end
        block.content = cleaned
        tbl.caption.long[i] = block
      end
    end
  end

  if tbl.caption and tbl.caption.short then
    local cleaned_short, id_here = strip_id_tokens(tbl.caption.short)
    if id_here and not found_id then
      found_id = id_here
    end
    tbl.caption.short = cleaned_short
  end

  if found_id and (tbl.attr.identifier == nil or tbl.attr.identifier == "") then
    tbl.attr.identifier = found_id
  end

  return tbl
end
