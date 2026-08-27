from pathlib import Path

p = Path('tools/apply_aggregate_brace_elision.py')
s = p.read_text()
old = "s = replace_once(s, old, new, 'automatic designated array braces')"
new = "\nif s.count(old) != 2:\n    raise SystemExit(f'automatic designated array braces: expected two pre-rewrite anchors, found {s.count(old)}')\ns = s.replace(old, new, 1)"
if s.count(old) != 1:
    raise SystemExit(f'expected one migration call anchor, found {s.count(old)}')
p.write_text(s.replace(old, new, 1))
