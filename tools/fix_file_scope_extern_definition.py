from pathlib import Path

p = Path("parse.c")
text = p.read_text()
old = '''                if (consume(&tok, tok, "=")) {
                    Token *after_string = NULL;
'''
new = '''                if (consume(&tok, tok, "=")) {
                    // A file-scope declaration with an initializer is a
                    // definition even when it is spelled with `extern`.
                    var->is_extern = false;
                    Token *after_string = NULL;
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"parse.c: expected one file-scope initializer path, found {count}")
p.write_text(text.replace(old, new, 1))
print("file-scope extern definition fix applied")
