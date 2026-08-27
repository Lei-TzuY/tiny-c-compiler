from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = '''static bool is_scalar_expr(Node *node) {
    add_type(node);
    Type *ty = decay_value_type(node->ty);
    return ty && (is_numeric(ty) || ty->kind == TY_PTR);
}
'''
insert = anchor + '''
static bool cast_compatible(Type *dst, Node *expr) {
    add_type(expr);

    // A cast to void explicitly discards the value and accepts any complete
    // expression type, including aggregates and void-valued expressions.
    if (dst && dst->kind == TY_VOID)
        return true;

    Type *src = decay_value_type(expr->ty);
    if (!dst || !src)
        return false;

    // Non-void cast targets must be scalar.  Arrays/functions have already
    // decayed above when they appear as values.
    bool dst_arith = is_numeric(dst);
    bool src_arith = is_numeric(src);
    bool dst_ptr = dst->kind == TY_PTR;
    bool src_ptr = src->kind == TY_PTR;

    if (dst_arith && src_arith)
        return true;
    if (dst_ptr && src_ptr)
        return true;
    if (dst_ptr && is_integer(src))
        return true;
    if (is_integer(dst) && src_ptr)
        return true;
    return false;
}
'''
if s.count(anchor) != 1:
    raise SystemExit(f'is_scalar_expr anchor count={s.count(anchor)}')
s = s.replace(anchor, insert, 1)

old = '''    if (equal(tok, "(") && is_typename(tok->next)) {
        tok = tok->next;
        Type *ty = type_name(&tok, tok);
        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC)
            error_at(tok->loc, "cast specifies non-scalar type");
        tok = skip(tok, ")");
        Node *node = new_unary(ND_CAST, unary(rest, tok));
        node->ty = ty;
        return node;
    }
'''
new = '''    if (equal(tok, "(") && is_typename(tok->next)) {
        Token *cast_tok = tok;
        tok = tok->next;
        Type *ty = type_name(&tok, tok);
        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
            (ty->kind != TY_VOID && !is_numeric(ty) && ty->kind != TY_PTR))
            error_at(cast_tok->loc, "cast specifies non-scalar type");
        tok = skip(tok, ")");
        Node *operand = unary(rest, tok);
        if (!cast_compatible(ty, operand))
            error_at(cast_tok->loc, "invalid cast operand type");
        Node *node = new_unary(ND_CAST, operand);
        node->ty = ty;
        return node;
    }
'''
if s.count(old) != 1:
    raise SystemExit(f'cast block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/lvalue_semantics.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/cast_constraints.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = 'and semantic modifiable-lvalue/addressability checks for assignment, compound assignment, increment/decrement, address-of, and dereference\n'
replacement = 'and semantic modifiable-lvalue/addressability checks for assignment, compound assignment, increment/decrement, address-of, and dereference; explicit casts enforce scalar/void target constraints and the supported arithmetic, pointer, and integer-pointer conversion categories\n'
if s.count(needle) != 1:
    raise SystemExit(f'README anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))

Path('test/cast_constraints.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-cast.c
  ./minicc tmp-cast.c > tmp-cast.s
  cc -o tmp-cast tmp-cast.s
  set +e
  ./tmp-cast
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "cast constraint failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(cast constraint): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-cast-bad.c
  if ./minicc tmp-cast-bad.c > tmp-cast-bad.s 2>/dev/null; then
    echo "cast constraint unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(cast constraint): rejected invalid program"
}

# Arithmetic-to-arithmetic casts remain valid.
assert_run 3 'int main(){return (int)3.8;}'
assert_run 4 'int main(){double x=(double)4;return (int)x;}'
assert_run 1 'int main(){return (_Bool)7;}'

# Integer/pointer and pointer/pointer casts are permitted explicit conversions.
assert_run 1 'int main(){long x=1;int *p=(int*)x;return p!=0;}'
assert_run 7 'int main(){int x=7;void *v=(void*)&x;int *p=(int*)v;return *p;}'
assert_run 1 'int main(){int x;long n=(long)&x;return n!=0;}'

# Array and function designators decay before a scalar cast.
assert_run 6 'int main(){int a[2];a[0]=6;int *p=(int*)a;return *p;}'
assert_run 5 'int f(){return 5;}int main(){int (*p)()=(int (*)())f;return p();}'

# A cast to void may discard any expression, including aggregates and void.
assert_run 0 'struct S{int x;};int main(){struct S s;s.x=3;(void)s;return 0;}'
assert_run 0 'void f(){return;}int main(){(void)f();return 0;}'

# Non-void cast targets must be scalar, and aggregate operands cannot be cast
# to a scalar value.
assert_fail 'struct S{int x;};int main(){return ((struct S)1).x;}'
assert_fail 'struct S{int x;};int main(){struct S s;return (int)s;}'
assert_fail 'struct S{int x;};int main(){struct S s;return (void*)s!=0;}'
assert_fail 'struct S;int main(){return ((struct S)1).x;}'

# Floating-point values do not convert directly to/from pointer types in C.
assert_fail 'int main(){void *p=(void*)1.5;return p!=0;}'
assert_fail 'int main(){int x;return (double)&x!=0;}'
assert_fail 'int f(){return 1;}int main(){return (double)f!=0;}'

# A void-valued expression cannot be converted to a non-void scalar.
assert_fail 'void f(){return;}int main(){return (int)f();}'

# Arrays/functions may decay to pointers, but pointer-to-floating remains invalid.
assert_fail 'int main(){int a[2];return (double)a!=0;}'

# Cast targets that are arrays/functions remain invalid.
assert_fail 'int main(){return (int [2])0;}'
assert_fail 'int main(){return (int (int))0;}'

echo 'All cast-constraint tests passed!'
''')
