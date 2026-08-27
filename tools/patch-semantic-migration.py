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
p.write_text(s.replace(old, new))

# Extend regression coverage for array decay through assignments and both
# direct/indirect fixed-parameter calls.
t = Path('test/semantic_assignments.sh')
ts = t.read_text()
anchor = "assert_run 1 'int main(){int x=1; int *p=&x; _Bool b=p; return b;}'\n"
extra = anchor + "assert_run 6 'int main(){int a[2];int *p=a;p[1]=6;return a[1];}'\n" + \
        "assert_run 4 'int first(int *p){return p[0];} int main(){int a[1];a[0]=4;return first(a);}'\n" + \
        "assert_run 6 'int first(int *p){return p[0];} int main(){int a[1];a[0]=6;int (*fp)(int*)=first;return fp(a);}'\n"
if ts.count(anchor) != 1:
    raise SystemExit('test anchor missing')
t.write_text(ts.replace(anchor, extra))
