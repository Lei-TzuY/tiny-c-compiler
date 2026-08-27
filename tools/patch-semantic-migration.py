from pathlib import Path

p = Path('parse.c')
s = p.read_text()

# Array expressions decay to pointers before assignment compatibility checks.
old = '''    add_type(rhs);
    Type *src = rhs->ty;

    if (!dst || !src || dst->kind == TY_ARRAY || dst->kind == TY_FUNC)
'''
new = '''    add_type(rhs);
    Type *src = rhs->ty;

    if (src && src->kind == TY_ARRAY)
        src = pointer_to(src->base);

    if (!dst || !src || dst->kind == TY_ARRAY || dst->kind == TY_FUNC)
'''
if s.count(old) != 1:
    raise SystemExit(f'array-decay anchor count={s.count(old)}')
s = s.replace(old, new)

# The generic migration updates the standalone indirect-call path. Patch the
# identifier function-pointer path and the direct-call path separately.
patterns = [
('''                    if (expected) {
                        if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                            arg->ty != expected->ty) {
''', '''                    if (expected) {
                        if (!assignment_compatible(expected->ty, arg))
                            error_at(tok->loc, "incompatible argument type");
                        if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                            arg->ty != expected->ty) {
'''),
('''                if (expected) {
                    if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                        arg->ty != expected->ty) {
''', '''                if (expected) {
                    if (!assignment_compatible(expected->ty, arg))
                        error_at(tok->loc, "incompatible argument type");
                    if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                        arg->ty != expected->ty) {
'''),
]
for old, new in patterns:
    if s.count(old) != 1:
        raise SystemExit(f'call-argument anchor count={s.count(old)}')
    s = s.replace(old, new)

p.write_text(s)

# Extend regression coverage for array/function decay through assignments and
# both direct/indirect fixed-parameter calls.
t = Path('test/semantic_assignments.sh')
ts = t.read_text()
anchor = "assert_run 1 'int main(){int x=1; int *p=&x; _Bool b=p; return b;}'\n"
extra = anchor + "assert_run 6 'int main(){int a[2];int *p=a;p[1]=6;return a[1];}'\n" + \
        "assert_run 4 'int first(int *p){return p[0];} int main(){int a[1];a[0]=4;return first(a);}'\n" + \
        "assert_run 6 'int first(int *p){return p[0];} int main(){int a[1];a[0]=6;int (*fp)(int*)=first;return fp(a);}'\n"
if ts.count(anchor) != 1:
    raise SystemExit('test anchor missing')
ts = ts.replace(anchor, extra)
t.write_text(ts)
