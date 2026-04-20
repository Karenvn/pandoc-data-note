#!/usr/bin/env python3
# Post-process JATS XML file after Pandoc conversion


import sys, re, unicodedata


#Helper functions

def merge_author_year_xrefs(txt: str) -> str:
    """
    Merge constructions like:
        Howe <italic>et al</italic>. (<xref rid="ref-21" ref-type="bibr">2021</xref>)
    into:
        <xref rid="ref-21" ref-type="bibr">Howe <italic>et al</italic>. (2021)</xref>
    """
    pattern = re.compile(
        # Only merge year-only xrefs when the narrative form explicitly uses "et al".
        # This avoids corrupting names like "Knight-Jones & Mackie (-@...)".
        r'(?P<name>\b[A-Z][A-Za-z-]+\s*<italic>et al\.?<\/italic>)'       # Howe <italic>et al</italic>
        r'\s*(?P<dot>\.)?'                                              # optional dot
        r'\s*\(\s*'                                                     # opening parenthesis
        r'(?P<xref_open><xref\b[^>]*>)'                                 # opening <xref ...>
        r'\s*(?P<year>\d{4})\s*'                                        # year
        r'</xref>\s*\)',                                                # close
        flags=re.S
    )

    def repl(m: re.Match) -> str:
        name = m.group('name')
        dot  = m.group('dot') or '.'
        open_tag = m.group('xref_open')
        year = m.group('year')
        return f'{open_tag}{name}{dot} ({year})</xref>'

    return pattern.sub(repl, txt)


# Mapping of original ref-id to new ref-id
mapping = {}

# Read the entire XML from stdin
txt = sys.stdin.read()

# Normalize CRediT role values:
# - strip leading/trailing whitespace that can break downstream mapping
# - canonicalize known variants (e.g. Writing – original draft)
def normalize_credit_role_value(value: str) -> str:
    raw = re.sub(r'\s+', ' ', value.replace('&amp;', '&')).strip()
    key = raw.lower().replace('—', '–')
    key = re.sub(r'\s*-\s*', ' - ', key)
    key = re.sub(r'\s*–\s*', ' – ', key)
    key = re.sub(r'\s+', ' ', key).strip()

    mapping = {
        'conceptualization': 'Conceptualization',
        'data curation': 'Data Curation',
        'formal analysis': 'Formal Analysis',
        'funding acquisition': 'Funding Acquisition',
        'investigation': 'Investigation',
        'methodology': 'Methodology',
        'project administration': 'Project Administration',
        'resources': 'Resources',
        'software': 'Software',
        'supervision': 'Supervision',
        'validation': 'Validation',
        'visualization': 'Visualization',
        'writing - original draft': 'Writing – Original Draft Preparation',
        'writing – original draft': 'Writing – Original Draft Preparation',
        'writing - original draft preparation': 'Writing – Original Draft Preparation',
        'writing – original draft preparation': 'Writing – Original Draft Preparation',
        'writing - review & editing': 'Writing – Review & Editing',
        'writing – review & editing': 'Writing – Review & Editing',
        'writing - review and editing': 'Writing – Review & Editing',
        'writing – review and editing': 'Writing – Review & Editing',
    }

    return mapping.get(key, raw)


def normalize_credit_roles(xml_text: str) -> str:
    pattern = re.compile(
        r'<role\s+content-type="http://credit\.niso\.org/">(.*?)</role>',
        flags=re.S | re.I,
    )

    def repl(m: re.Match) -> str:
        val = normalize_credit_role_value(m.group(1))
        val = val.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<role content-type="http://credit.niso.org/">{val}</role>'

    return pattern.sub(repl, xml_text)


txt = normalize_credit_roles(txt)

#1)-----Patching the tables-----------

# --- convert <caption><p>…</p></caption> → <caption><title>…</title></caption>
txt = re.sub(
    r'(<caption>)\s*<p>(.*?)</p>\s*</caption>',
    r'\1<title>\2</title></caption>',
    txt,
    flags=re.S | re.I,
)

# --- normalize wrapped caption titles produced by some table pipelines:
# <caption><p specific-use="wrapper"><title>...</title></p></caption>
# -> <caption><title>...</title></caption>
txt = re.sub(
    r'(<caption>)\s*<p\b[^>]*>\s*<title>(.*?)</title>\s*</p>\s*</caption>',
    r'\1<title>\2</title></caption>',
    txt,
    flags=re.S | re.I,
)

# Ensure <table-wrap id="Tn" position="anchor">
txt = re.sub(
    r'(<table-wrap\b(?=[^>]*\bid="T\d+")(?:(?!\bposition=).)*?)>',
    r'\1 position="anchor">',
    txt, flags=re.S | re.I)

# Add attrs to <table> (but not <table-wrap>)
txt = re.sub(
    r'(<table(?!-wrap)\b(?![^>]*\bcontent-type=)[^>]*?)>',
    r'\1 content-type="article-table">',
    txt, flags=re.I)

txt = re.sub(
    r'(<table(?!-wrap)\b(?![^>]*\bframe=)[^>]*?)>',
    r'\1 frame="below">',
    txt, flags=re.I)

# Avoid duplicate XML ID values between <table-wrap id="Tn"> and nested
# <table id="Tn">. Keep the ID on table-wrap only (xref target).
txt = re.sub(
    r'(<table(?!-wrap)\b[^>]*?)\s+id="T\d+"([^>]*>)',
    r'\1\2',
    txt,
    flags=re.I,
)

# Clean up any mistaken attrs on <table-wrap>
txt = re.sub(r'(<table-wrap\b[^>]*?)\s+content-type="[^"]*"', r'\1', txt, flags=re.I)
txt = re.sub(r'(<table-wrap\b[^>]*?)\s+frame="[^"]*"',         r'\1', txt, flags=re.I)

# Drop colgroup scaffolding. The journal has confirmed tables display better
# online without the width hints, and xrefs target the surrounding table-wrap.
txt = re.sub(
    r'\s*<colgroup>\s*(?:<col\b[^>]*/>\s*)+</colgroup>\s*',
    '\n',
    txt,
    flags=re.S | re.I,
)

# Remove a literal "Table " or "Figure " immediately before an <xref> that already contains it
txt = re.sub(
    r'(?<!\w)Table\s+(<xref\b[^>]*ref-type="table"[^>]*>\s*Table\b)',
    r'\1',
    txt
)
txt = re.sub(
    r'(?<!\w)Figure\s+(<xref\b[^>]*ref-type="fig"[^>]*>\s*Figure\b)',
    r'\1',
    txt
)

# 2)----Sort references alphabetically by first author surname----

def extract_first_author_surname(ref_block):
    """Extract first author's surname from a reference block for sorting."""
    # Try to find first surname in person-group
    match = re.search(r'<person-group[^>]*>.*?<surname>([^<]+)</surname>', ref_block, re.S)
    if match:
        surname = match.group(1)
    else:
        # Fallback: try string-name (for corporate authors)
        match = re.search(r'<string-name>([^<]+)</string-name>', ref_block, re.S)
        if match:
            surname = match.group(1)
        else:
            return 'zzz'  # Sort to end if no author found
    
    # Normalize Unicode for proper alphabetical sorting
    # This ensures š sorts with s, ž with z, etc.
    normalized = unicodedata.normalize('NFD', surname.lower())
    # Remove combining diacritical marks
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')

def sort_references(xml_text):
    """Sort all references alphabetically by first author surname."""
    # Find the ref-list section
    ref_list_match = re.search(r'(<ref-list>.*?</ref-list>)', xml_text, re.S)
    if not ref_list_match:
        return xml_text
    
    ref_list_content = ref_list_match.group(1)
    
    # Extract all individual <ref> blocks
    ref_pattern = r'(<ref id="[^"]*">.*?</ref>)'
    refs = re.findall(ref_pattern, ref_list_content, re.S)
    
    if not refs:
        return xml_text
    
    # Sort references alphabetically by first author surname only
    def sort_key(ref_block):
        author = extract_first_author_surname(ref_block)
        return author
    
    sorted_refs = sorted(refs, key=sort_key)
    
    # Reconstruct ref-list with sorted references
    new_ref_list = '<ref-list>\n<title>References</title>\n'
    new_ref_list += '\n'.join(sorted_refs)
    new_ref_list += '\n</ref-list>'
    
    # Replace old ref-list with sorted one
    xml_text = xml_text.replace(ref_list_content, new_ref_list)
    
    return xml_text

txt = sort_references(txt)

# 3)----Renumber <ref id="..."> sequentially and record mapping-----------
counter = 0
def repl_ref(m):
    global counter
    old_id = m.group(1)
    counter += 1
    new_id = f"ref-{counter}"
    mapping[old_id] = new_id
    return f'<ref id="{new_id}">'  

txt = re.sub(r'<ref id="([^"]+)">', repl_ref, txt)

# 4) Remap inline citation rid attributes
for old, new in mapping.items():
    txt = txt.replace(f'rid="{old}"', f'rid="{new}"')

# 5) Convert element-citation → mixed-citation, preserve publication-type
# First, handle element-citations WITH publication-type attribute
txt = re.sub(
    r'<element-citation\s+publication-type="([^"]+)"[^>]*>',
    r'<mixed-citation publication-type="\1">',
    txt
)
# Then handle any element-citations WITHOUT publication-type (default to "other")
txt = re.sub(
    r'<element-citation\b(?![^>]*publication-type=)[^>]*>',
    '<mixed-citation publication-type="other">',
    txt
)
# Replace closing tags
txt = txt.replace('</element-citation>', '</mixed-citation>')

# Map JATS element-citation types to the journal's preferred types
txt = txt.replace('publication-type="article-journal"', 'publication-type="journal"')
txt = txt.replace('publication-type="chapter"', 'publication-type="book"')

# 5) Strip iso-8601-date from <year>
txt = re.sub(r'<year iso-8601-date="[^"]+">', '<year>', txt)

# 5b) Restore emphasis markers that were preserved through citeproc.
# This handles BibTeX \textit{...}/\emph{...} captured as markers by the
# prepare_bibtex_markup.lua pre-citeproc filter.
txt = txt.replace('__ITALIC_OPEN__', '<italic>')
txt = txt.replace('__ITALIC_CLOSE__', '</italic>')

# Also decode escaped HTML italic tags when present inside citation titles.
def restore_escaped_title_italics(match: re.Match) -> str:
    open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
    body = body.replace('&lt;i&gt;', '<italic>').replace('&lt;/i&gt;', '</italic>')
    body = body.replace('&lt;em&gt;', '<italic>').replace('&lt;/em&gt;', '</italic>')
    return f'{open_tag}{body}{close_tag}'

txt = re.sub(
    r'(<(?:article-title|chapter-title)>)(.*?)(</(?:article-title|chapter-title)>)',
    restore_escaped_title_italics,
    txt,
    flags=re.S | re.I,
)

# 6) Add punctuation to references according to Standard_Ref_Styles.xml
def add_reference_punctuation(ref_block):
    """Add punctuation between elements in a reference."""
    
    # Colon after person-group (authors/editors)
    ref_block = re.sub(
        r'(</person-group>)\s*\n',
        r'\1:\n',
        ref_block
    )
    
    # Period after article-title (if not already there)
    ref_block = re.sub(
        r'(</article-title>)(?!\s*\.)',
        r'\1.',
        ref_block
    )
    # Ensure explicit separator to following citation elements.
    ref_block = re.sub(
        r'(</article-title>\.?)\s*(?=<source|<publisher-name|<publisher-loc|<year|<ext-link)',
        r'\1 ',
        ref_block,
    )
    
    # Period after chapter-title (if not already there)  
    ref_block = re.sub(
        r'(</chapter-title>)(?!\s*\.)',
        r'\1.',
        ref_block
    )
    ref_block = re.sub(
        r'(</chapter-title>\.?)\s*(?=<source|<publisher-name|<publisher-loc|<year|<ext-link)',
        r'\1 ',
        ref_block,
    )
    
    # Handle source element formatting based on publication type
    is_journal = 'publication-type="journal"' in ref_block
    is_book = 'publication-type="book"' in ref_block
    pub_ids_text = ''

    # For journal references, move identifiers after the page range so output
    # follows: year; volume(issue): fpage–lpage. <pub-id...>
    if is_journal:
        pub_ids = re.findall(r'\s*<pub-id[^>]*>[^<]*</pub-id>', ref_block)
        if pub_ids:
            # Journal requires identifier order: pmid, doi, pmcid.
            pub_id_order = {'pmid': 0, 'doi': 1, 'pmcid': 2}

            def pub_id_sort_key(pub_id_tag: str):
                m = re.search(r'pub-id-type="([^"]+)"', pub_id_tag, flags=re.I)
                pid_type = m.group(1).lower() if m else ''
                return (pub_id_order.get(pid_type, 99), pid_type)

            pub_ids = sorted(pub_ids, key=pub_id_sort_key)
            ref_block = re.sub(r'\s*<pub-id[^>]*>[^<]*</pub-id>', '', ref_block)
            pub_ids_text = ' '.join(p.strip() for p in pub_ids)
    
    if is_journal:
        # Journal: semicolon after source, then space before year
        ref_block = re.sub(
            r'(</source>)\s*\n?\s*(<year)',
            r'\1; \2',
            ref_block
        )
        # Semicolon + space after year before volume
        ref_block = re.sub(
            r'(</year>)\s*\n?\s*(<volume)',
            r'\1; \2',
            ref_block
        )
    elif is_book:
        # Book: separator after source before publisher/year
        ref_block = re.sub(
            r'(</source>)\s*(?=<publisher-name|<publisher-loc|<year)',
            r'\1. ',
            ref_block
        )
        # Book: period after year
        ref_block = re.sub(
            r'(</year>)\.?\s*\n?',
            r'\1. ',
            ref_block
        )
    else:
        # Non-journal/non-book refs can still contain source + publisher/year.
        ref_block = re.sub(
            r'(</source>)\s*(?=<publisher-name|<publisher-loc|<year)',
            r'\1. ',
            ref_block
        )

    # Publisher/location/year separators to avoid concatenation in display layers.
    ref_block = re.sub(
        r'(</publisher-name>)\s*(?=<publisher-loc)',
        r'\1, ',
        ref_block
    )
    ref_block = re.sub(
        r'(</publisher-name>)\s*(?=<year|<month|<volume|<issn|<ext-link)',
        r'\1 ',
        ref_block
    )
    ref_block = re.sub(
        r'(</publisher-loc>)\s*(?=<publisher-name)',
        r'\1: ',
        ref_block
    )
    ref_block = re.sub(
        r'(</publisher-loc>)\s*(?=<year|<month|<volume|<issn|<ext-link)',
        r'\1. ',
        ref_block
    )
    ref_block = re.sub(
        r'(</year>)(?!\.)\s*(?=<month)',
        r'\1 ',
        ref_block
    )
    ref_block = re.sub(
        r'(</month>)\s*(?=<volume|<issue|<fpage|<lpage|<issn|<ext-link)',
        r'\1; ',
        ref_block
    )
    ref_block = re.sub(
        r'(</issn>)\s*(?=<ext-link)',
        r'\1. ',
        ref_block
    )
    # If the year is terminal, ensure it ends with a full stop so identifiers
    # or links do not concatenate directly onto the year in display layers.
    ref_block = re.sub(
        r'(</year>)(?!\s*[.;])\s*(?=(<pub-id|<ext-link|</mixed-citation>))',
        r'\1. ',
        ref_block
    )
    
    # Issue in parentheses with colon before pages
    ref_block = re.sub(
        r'(<volume>[^<]+</volume>)\s*\n?\s*(<issue)',
        r'\1(\2',
        ref_block
    )
    ref_block = re.sub(
        r'(</issue>)\s*\n?\s*(<fpage|<lpage)',
        r'\1): \2',
        ref_block
    )
    # If there is an issue but no page tags, still close the parenthesis.
    ref_block = re.sub(r'(</issue>)(?!\))', r'\1)', ref_block)

    # Some records encode article numbers as fpage only, but Pandoc/citeproc can
    # still emit an empty <lpage>. Drop empty lpage tags so we do not generate a
    # fake page range like "125–".
    ref_block = re.sub(
        r'\s*–?\s*<lpage>\s*</lpage>',
        '',
        ref_block
    )
    
    # En-dash between page numbers (use – not -)
    ref_block = re.sub(
        r'(</fpage>)\s*\n?\s*(<lpage)',
        r'\1–\2',
        ref_block
    )
    # If no lpage is present, terminate fpage.
    ref_block = re.sub(
        r'(</fpage>)(?!\s*–\s*<lpage>)(?!\s*\.)',
        r'\1.',
        ref_block
    )
    
    # Period after lpage if not already there
    ref_block = re.sub(
        r'(</lpage>)(?!\s*\.)',
        r'\1.',
        ref_block
    )
    
    # Reinsert identifiers after page range (or closest fallback).
    if pub_ids_text:
        if re.search(r'</lpage>\.', ref_block):
            ref_block = re.sub(r'(</lpage>\.)', r'\1 ' + pub_ids_text, ref_block, count=1)
        elif re.search(r'</fpage>\.', ref_block):
            ref_block = re.sub(r'(</fpage>\.)', r'\1 ' + pub_ids_text, ref_block, count=1)
        elif re.search(r'</issue>\)', ref_block):
            ref_block = re.sub(r'(</issue>\))', r'\1. ' + pub_ids_text, ref_block, count=1)
        elif re.search(r'</volume>(?!\s*[(:])', ref_block):
            ref_block = re.sub(r'(</volume>)', r'\1. ' + pub_ids_text, ref_block, count=1)
        elif re.search(r'</year>\.', ref_block):
            ref_block = re.sub(r'(</year>\.)', r'\1 ' + pub_ids_text, ref_block, count=1)
        else:
            # Keep identifiers inside the reference block.
            ref_block = re.sub(
                r'(</mixed-citation>)',
                ' ' + pub_ids_text + r'\n      \1',
                ref_block,
                count=1
            )
    
    return ref_block

# Apply punctuation to each reference
def process_all_references(xml_text):
    """Add punctuation to all references."""
    def process_ref(match):
        return add_reference_punctuation(match.group(0))
    
    return re.sub(
        r'<ref id="[^"]*">.*?</ref>',
        process_ref,
        xml_text,
        flags=re.S
    )

txt = process_all_references(txt)

# 7) Wrap <source> contents in <italic>
txt = re.sub(
    r'<source>([^<]+)</source>',
    r'<source><italic>\1</italic></source>',
    txt
)

# 8) Convert PMID and PMCID placeholders to <pub-id>
txt = re.sub(
    r'PMID: (\d+)',
    r'<pub-id pub-id-type="pmid">\1</pub-id>',
    txt
)
txt = re.sub(
    r'PMCID: (\w+)',
    r'<pub-id pub-id-type="pmcid">\1</pub-id>',
    txt
)

# 8b) Extract DOIs from <uri> elements and convert to <pub-id>
# Match both doi.org and dx.doi.org URLs
txt = re.sub(
    r'<uri\s+xlink:href="https?://(?:dx\.)?doi\.org/(10\.[^"]+)">[^<]*</uri>',
    r'<pub-id pub-id-type="doi">\1</pub-id>',
    txt
)
# Also handle <uri> without xlink:href (in case they exist)
txt = re.sub(
    r'<uri>https?://(?:dx\.)?doi\.org/(10\.[^<]+)</uri>',
    r'<pub-id pub-id-type="doi">\1</pub-id>',
    txt
)

# 9) Remove alt="..." attributes from <xref> tags
txt = re.sub(r'<xref([^>]*)\s+alt="[^"]+"', r'<xref\1', txt)



# 9) Fix the funding statement <p> issue

txt = re.sub(
    r'<funding-statement>\s*<p>(.*?)</p>\s*</funding-statement>',
    r'<funding-statement>\1</funding-statement>',
    txt,
    flags=re.S | re.I,
)


# -----------------------------------------------------------------
# 10) add missing id="Tn" to every <table-wrap> by reading the caption
# -----------------------------------------------------------------
txt = re.sub(
    r'(<table-wrap)([^>]*>)\s*<caption>\s*<title>\s*Table\s+(\d+):',
    r'\1 id="T\3"\2<caption><title>Table \3:',
    txt,
    flags=re.S | re.I,
)

# Add position="anchor" once ids are present on table-wrap.
txt = re.sub(
    r'(<table-wrap\b(?=[^>]*\bid="T\d+")(?:(?!\bposition=).)*?)>',
    r'\1 position="anchor">',
    txt,
    flags=re.S | re.I,
)


# ============================================================================
# 12) Convert <uri> to <ext-link> in references
# ============================================================================

# Convert <uri> elements to <ext-link> within reference sections
# First add xlink:href to any URIs that don't have it
txt = re.sub(
    r'<uri>(https?://[^<]+)</uri>',
    r'<uri xlink:href="\1">\1</uri>',
    txt
)

# Then convert <uri> to <ext-link> within <ref> blocks (references only)
# Match uri elements that appear within mixed-citation blocks
def convert_ref_uris(match):
    """Convert URIs within a single reference to ext-links"""
    ref_content = match.group(0)
    # Replace uri with ext-link only in this reference
    ref_content = re.sub(
        r'<uri\s+xlink:href="([^"]+)">(?:[^<]+)</uri>',
        r'<ext-link ext-link-type="uri" xlink:href="\1">Reference Source</ext-link>',
        ref_content
    )
    return ref_content

# Apply conversion to each reference block
txt = re.sub(
    r'<ref id="[^"]*">.*?</ref>',
    convert_ref_uris,
    txt,
    flags=re.S
)



# Insert <label>Table n. </label> if missing (just after <table-wrap ... id="Tn">)
txt = re.sub(
    r'(<table-wrap\b[^>]*\bid="T(\d+)"[^>]*>\s*)(?!<label>)',
    r'\1<label>Table \2. </label>',
    txt,
    flags=re.S | re.I,
)

# Remove any leading "Table n: " inside <caption><title>…</title>
txt = re.sub(
    r'(<table-wrap\b[^>]*\bid="T(\d+)"[^>]*>.*?<caption>\s*<title>)\s*Table\s+\2:\s*',
    r'\1',
    txt,
    flags=re.S | re.I,
)

# Remove leading "Figure n: " inside <caption><title>…</title>
txt = re.sub(
    r'(<fig\b[^>]*\bid="f(\d+)"[^>]*>.*?<caption>\s*<title>)\s*Figure\s+\2:\s*',
    r'\1',
    txt,
    flags=re.S | re.I,
)

# Move trailing table notes into <table-wrap-foot> when written as a paragraph
# immediately after </table-wrap>.
txt = re.sub(
    r'(<table-wrap\b[^>]*>.*?)(</table-wrap>)\s*'
    r'(<p>\s*(?:<bold>\s*)?Notes?:\s*(?:</bold>\s*)?.*?</p>)',
    r'\1<table-wrap-foot>\3</table-wrap-foot>\2',
    txt,
    flags=re.S | re.I,
)

# Handle year-only citations to get the full xref
txt = merge_author_year_xrefs(txt)



# ============================================================================
# Final output
# ============================================================================
sys.stdout.write(txt)
