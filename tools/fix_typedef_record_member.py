from pathlib import Path

p = Path("parse.c")
text = p.read_text()
old = '''        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||\n            attrs.is_inline || attrs.is_noreturn)\n            error_at(tok->loc, "storage/function specifier is not allowed on a record member");\n'''
new = '''        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||\n            attrs.is_typedef || attrs.is_inline || attrs.is_noreturn)\n            error_at(tok->loc, "storage/function specifier is not allowed on a record member");\n'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one record-member constraint site, found {count}")
p.write_text(text.replace(old, new, 1))
print("typedef record-member constraint fixed")
