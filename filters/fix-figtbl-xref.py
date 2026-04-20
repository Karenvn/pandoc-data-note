#!/usr/bin/env python3

"""Panflute filter for WOR JATS

* Renames fig: / tbl: identifiers to fN / TN
* Converts Cite & @ref links into <xref>
* Emits raw JATS <fig> and <table-wrap> blocks that match the journal template

Works ***before*** the JATS writer, so it operates on Pandoc Figure and Table
objects.
"""

import re
from panflute import *  # Figure, Table, Cite, etc.

# ------------------------------------------------------------------
# helpers -----------------------------------------------------------

def find_first_image(node):
    """Depth‑first search for the first Image below *node*."""
    if isinstance(node, Image):
        return node
    if hasattr(node, 'content'):
        for child in node.content:
            found = find_first_image(child)
            if found is not None:
                return found
    return None


# --- caption/render helpers (preserve italics & bold in titles) ---

def _render_inlines_to_jats(inlines):
    out = []
    for x in (inlines or []):
        if isinstance(x, Emph):
            out.append('<italic>' + _render_inlines_to_jats(x.content) + '</italic>')
        elif isinstance(x, Strong):
            out.append('<bold>' + _render_inlines_to_jats(x.content) + '</bold>')
        elif isinstance(x, (Space, SoftBreak, LineBreak)):
            out.append(' ')
        elif isinstance(x, Code):
            out.append('<monospace>' + x.text + '</monospace>')
        elif isinstance(x, Str):
            out.append(x.text)
        elif hasattr(x, 'content'):
            out.append(_render_inlines_to_jats(x.content))
        else:
            out.append(stringify(x))
    return ''.join(out).strip()


def caption_to_jats_text(caption):
    """Return caption text with inline JATS tags across Panflute versions."""
    # Newer Panflute: Caption object with optional .long/.short
    if type(caption).__name__ == 'Caption':
        if hasattr(caption, 'long') and caption.long:
            blk = caption.long[0] if len(caption.long) > 0 else None
            if isinstance(blk, (Para, Plain)):
                return _render_inlines_to_jats(blk.content)
            if blk is not None:
                return stringify(blk).strip()
        if hasattr(caption, 'short') and caption.short:
            return _render_inlines_to_jats(caption.short)
        if hasattr(caption, 'content') and caption.content:
            return _render_inlines_to_jats(caption.content)
        return ''
    # Older forms
    if isinstance(caption, (list, ListContainer)):
        return _render_inlines_to_jats(caption)
    if isinstance(caption, (Para, Plain)):
        return _render_inlines_to_jats(caption.content)
    return stringify(caption).strip()


# ------------------------------------------------------------------
# prepare pass – rename ids so later code & writer see short forms ----
# ------------------------------------------------------------------

fig_rx = re.compile(r'fig[\-:].*?(\d+)')
tbl_rx = re.compile(r'tbl[\-:].*?(\d+)')


def prepare(doc):
    def rename(elem, _):
        if hasattr(elem, 'identifier') and elem.identifier:
            m = fig_rx.match(elem.identifier)
            if m:
                elem.identifier = f"f{m.group(1)}"
                return
            m = tbl_rx.match(elem.identifier)
            if m:
                elem.identifier = f"T{m.group(1)}"
    doc.walk(rename)

# ------------------------------------------------------------------
# main action pass --------------------------------------------------
# ------------------------------------------------------------------

tbl_counter = 0  # global so Table branch can number sequentially

def action(elem, doc):
    # 1) Cite-based figure/table references ---------------------------------
    if isinstance(elem, Cite):
        out = []
        for citation in elem.citations:
            m = re.match(r'^(fig|tbl)[\-:](.*)', citation.id)
            if not m:
                continue
            kind, rest = m.groups()
            num = re.search(r'\d+', rest)
            if not num:
                continue
            idx = num.group()
            ref_type = 'fig' if kind == 'fig' else 'table'
            rid = f"{'f' if kind=='fig' else 'T'}{idx}"
            text = f"{'Figure' if kind=='fig' else 'Table'} {idx}"
            out.append(RawInline(f'<xref ref-type="{ref_type}" rid="{rid}">{text}</xref>',
                                  format='jats'))
        if out:
            return out

    # 2) @ref links ----------------------------------------------------------
    if isinstance(elem, Link) and elem.url.startswith('#'):
        target = elem.url[1:]
        if target.startswith('fig') or target.startswith('tbl'):
            fake = Citation(prefix='', id=target, suffix='')
            return action(Cite(citations=[fake]), doc)

    # 3) Figure objects -------------------------------------------------------
    if isinstance(elem, Figure):
        m = re.match(r'([fT])(\d+)', elem.identifier or '')
        if not m:
            return
        prefix, idx = m.groups()
        rid   = f"{prefix}{idx}"
        text  = f"{'Figure' if prefix=='f' else 'Table'} {idx}"

        parts = [f'<fig position="float" fig-type="figure" id="{rid}">',
                 f'<label>{text}. </label>']

        # caption -> title ---------------------------------------------------
        if elem.caption:
            cap_text = caption_to_jats_text(elem.caption)
            if cap_text:
                parts.append(f'<caption><title>{cap_text}</title></caption>')




        # graphic ------------------------------------------------------------
        img = find_first_image(elem)
        if img is not None:
            href = img.url
            if href.lower().endswith('.png'):
                href = href[:-4] + '.gif'
            graphic_id = f"figure{idx}"
            parts.append(f'<graphic id="{graphic_id}" xlink:href="{href}" />')

        parts.append('</fig>')
        return RawBlock('\n'.join(parts), format='jats')

    # 4) Table objects – keep full table, just fix caption ----------------
    if isinstance(elem, Table):
        # Identifier already shortened in prepare()
        m = re.match(r'T(\d+)', elem.identifier or '')
        if not m:
            return
        idx = m.group(1)

        # ------- caption: replace the single Para with a RawBlock ----------
        if elem.caption:
            cap_text = caption_to_jats_text(elem.caption)
            elem.caption.content = [RawBlock(             # ← replaces <p> … </p>
                f'<title>{cap_text}</title>', # ← becomes <title> … </title>
                format='jats'                              #     seen verbatim by the writer
            )]

        return None        # keep the original Table element



    return None

if __name__ == '__main__':
    run_filter(action, prepare=prepare)
