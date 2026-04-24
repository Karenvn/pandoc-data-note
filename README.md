# data_note_pandoc

Pandoc filters, templates, and wrapper scripts for converting genome note
Markdown files to docx, pdf and JATS-XML files.

## Dependencies

- [Pandoc](https://pandoc.org/) 3.x
- [pandoc-crossref](https://github.com/lierdakil/pandoc-crossref)
- [panflute](https://github.com/sergiocorreia/panflute) (`pip install panflute`)
- XeLaTeX (for PDF output)

## Usage

All scripts take the input `.md` file as the first argument and derive the
output filename automatically. An explicit output path can be given as a
second argument.

```bash
# PDF via XeLaTeX
bin/gn-pdf ilActPoly1.md

# DOCX for review (figures and tables inline)
bin/gn-docx-review ilActPoly1.md

# DOCX for submission (figures and tables at end)
bin/gn-docx-sub ilActPoly1.md

# JATS XML for Wellcome Open Research
bin/gn-jats ilActPoly1.md
```

## Filter order

Filter order matters and must not be changed.

**JATS pipeline:**
1. `normalize_pandoc_inputs.lua` — rewrites BibTeX italic markers; promotes table IDs
2. `pandoc-crossref` — resolves `@fig:` / `@tbl:` cross-references
3. `fix-figtbl-xref.py` — converts figure/table elements to raw JATS blocks
4. `--citeproc` — processes citations using BibTeX input and CSL
5. JATS writer using Pandoc and an XML template
6. `postprocess-jats.py` — sorts references, adds punctuation, restores italics

**DOCX submission pipeline:**
1. `inject_frontmatter.lua` — injects styled author/affiliation/grant block
2. `pandoc-crossref`
3. `extract_figs_tables.lua` — moves figures and tables after references
4. `--citeproc`

**DOCX review pipeline:** same as submission but without `extract_figs_tables.lua`.

**PDF pipeline:** `pandoc-crossref` → `--citeproc` → XeLaTeX.

## Repository layout

```
bin/          wrapper scripts (gn-pdf, gn-docx-review, gn-docx-sub, gn-jats)
filters/      Lua and Python Pandoc filters
templates/    LaTeX template, JATS-XML template, DOCX reference doc, CSL, fonts
```
