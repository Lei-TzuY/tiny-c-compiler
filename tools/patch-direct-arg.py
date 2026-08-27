from pathlib import Path
p = Path('parse.c')
s = p.read_text()
old = '''                if (expected) {
                    if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                        arg->ty != expected->ty) {
'''
new = '''                if (expected) {
                    if (!assignment_compatible(expected->ty, arg))
                        error_at(tok->loc, "incompatible argument type");
                    if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                        arg->ty != expected->ty) {
'''
if s.count(old) != 1:
    raise SystemExit(f'direct-call argument anchor count={s.count(old)}')
p.write_text(s.replace(old, new))
