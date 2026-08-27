from pathlib import Path

path = Path("tools/apply_nested_brace_designators.py")
src = path.read_text()
old = '''brace = src.index("{", start)\ndepth = 0\nend = None\nfor i in range(brace, len(src)):\n    c = src[i]\n    if c == "{":\n        depth += 1\n    elif c == "}":\n        depth -= 1\n        if depth == 0:\n            end = i + 1\n            break\nif end is None:\n    raise RuntimeError("could not find parse_automatic_aggregate_subobject end")\n'''
new = '''end = src.index("static void parse_automatic_designated_initializer(", start)\n'''
if old not in src:
    raise RuntimeError("migration boundary block not found")
src = src.replace(old, new, 1)
path.write_text(src)

exec(compile(src, str(path), "exec"))
