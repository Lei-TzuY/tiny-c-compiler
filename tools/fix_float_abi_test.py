from pathlib import Path

p = Path("tools/apply_float_abi.py")
text = p.read_text()
needle = "#include <stdio.h>\nint main()"
replacement = "int sprintf(char *str, char *fmt, ...);\nint main()"
count = text.count(needle)
if count != 2:
    raise SystemExit(f"expected 2 stdio ABI snippets, found {count}")
p.write_text(text.replace(needle, replacement))
print("rewrote sprintf ABI tests without stdio.h")
