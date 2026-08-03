#!/usr/bin/env python3
"""Inspect xs8jejsy.sqlite for outline build."""
import sqlite3, re, sys

db = sys.argv[1] if len(sys.argv) > 1 else 'corpus/wellcome/xs8jejsy.sqlite'
con = sqlite3.connect(db)

print('=== tables ===')
for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(' ', r[0])

print('\n=== document_metadata ===')
try:
    for r in con.execute('SELECT key, value FROM document_metadata'):
        v = (r[1] or '')[:200]
        print(f'  {r[0]}: {v}')
except Exception as e:
    print('  err:', e)

print('\n=== page_numbers summary ===')
print('  canvases:', con.execute('SELECT COUNT(*) FROM page_numbers').fetchone()[0])
try:
    print('  arabic span:', con.execute(
        "SELECT MIN(CAST(book_page_number AS INT)), MAX(CAST(book_page_number AS INT)) "
        "FROM page_numbers WHERE book_page_number GLOB '[0-9]*'").fetchone())
except Exception as e:
    print('  err arabic:', e)
try:
    print('  p.1 at leaf:', con.execute(
        "SELECT leaf_num FROM page_numbers WHERE book_page_number='1' LIMIT 1").fetchone())
    print('  all p.1 rows:')
    for r in con.execute("SELECT leaf_num, book_page_number FROM page_numbers WHERE book_page_number='1'"):
        print('   ', r)
except Exception as e:
    print('  err p1:', e)

print('\n=== first 30 page_number rows ===')
for r in con.execute('SELECT leaf_num, book_page_number FROM page_numbers ORDER BY leaf_num LIMIT 30'):
    print(' ', r)

print('\n=== ranges ===')
try:
    for r in con.execute('SELECT label, canvas_start, canvas_end FROM ranges ORDER BY range_index'):
        print(f'  [{r[1]}..{r[2]}]  {r[0]!r}')
except Exception as e:
    print(' err:', e)

print('\n=== TOC keyword scan front matter (page_id<25) ===')
pat = re.compile(r'\b(contents|inhalt|inhaltsverzeichnis|sommaire|tabula|register|verzeichnis)\b', re.IGNORECASE)
for r in con.execute('SELECT page_id, text FROM text_blocks WHERE page_id < 25 ORDER BY page_id, block_number'):
    if pat.search(r[1] or ''):
        print(f'  leaf {r[0]}: {(r[1] or "")[:140]!r}')

print('\n=== TOC keyword scan back matter ===')
maxleaf = con.execute('SELECT MAX(leaf_num) FROM page_numbers').fetchone()[0]
for r in con.execute('SELECT page_id, text FROM text_blocks WHERE page_id > ? ORDER BY page_id, block_number', (maxleaf-25,)):
    if pat.search(r[1] or ''):
        print(f'  leaf {r[0]}: {(r[1] or "")[:140]!r}')
