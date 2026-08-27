from pathlib import Path

p = Path('parse.c')
s = p.read_text()

old = r'''static Node *new_add(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_ADD, lhs, rhs);

    if (lhs->ty->base && is_integer(rhs->ty))
        return new_binary(ND_ADD, lhs, new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size)));

    if (is_integer(lhs->ty) && rhs->ty->base)
        return new_binary(ND_ADD, rhs, new_binary(ND_MUL, lhs, new_long(rhs->ty->base->size)));

    error("invalid operands");
}

static Node *new_sub(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_SUB, lhs, rhs);

    if (lhs->ty->base && is_integer(rhs->ty))
        return new_binary(ND_SUB, lhs, new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size)));

    if (lhs->ty->base && rhs->ty->base) {
        Node *node = new_binary(ND_SUB, lhs, rhs);
        node->ty = ty_long;
        return new_binary(ND_DIV, node, new_long(lhs->ty->base->size));
    }

    error("invalid operands");
}

static Node *new_compound_assign(NodeKind kind, Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
        if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
            return new_binary(kind, lhs, rhs);

        if (lhs->ty->kind == TY_PTR && is_integer(rhs->ty)) {
            rhs = new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size));
            return new_binary(kind, lhs, rhs);
        }

        error("invalid operands");
    }

    if ((kind == ND_MUL_EQ || kind == ND_DIV_EQ) &&
        is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(kind, lhs, rhs);

    if (is_integer(lhs->ty) && is_integer(rhs->ty))
        return new_binary(kind, lhs, rhs);

    error("invalid operands");
}

static Node *new_inc_dec(NodeKind kind, Node *expr) {
    add_type(expr);
    if (!is_numeric(expr->ty) && expr->ty->kind != TY_PTR)
        error("invalid operand");
    return new_unary(kind, expr);
}
'''

new = r'''static Type *pointer_arithmetic_type(Type *ty) {
    if (!ty)
        return NULL;

    // Array expressions decay to a pointer to their first element in value
    // contexts.  Keep that decay explicit here so `array + n` has pointer
    // result type instead of accidentally retaining TY_ARRAY.
    if (ty->kind == TY_ARRAY)
        ty = pointer_to(ty->base);

    if (ty->kind != TY_PTR || !ty->base)
        return NULL;

    Type *base = ty->base;
    // Standard C pointer arithmetic is defined only for pointers to complete
    // object types.  In particular, void* and function pointers are not
    // arithmetic pointers (even though some host compilers accept extensions).
    if (base->kind == TY_VOID || base->kind == TY_FUNC ||
        base->is_incomplete || base->size <= 0)
        return NULL;
    return ty;
}

static Node *new_add(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_ADD, lhs, rhs);

    Type *lp = pointer_arithmetic_type(lhs->ty);
    Type *rp = pointer_arithmetic_type(rhs->ty);

    if (lp && is_integer(rhs->ty)) {
        Node *node = new_binary(ND_ADD, lhs,
                                new_binary(ND_MUL, rhs, new_long(lp->base->size)));
        node->ty = lp;
        return node;
    }

    if (is_integer(lhs->ty) && rp) {
        Node *node = new_binary(ND_ADD, rhs,
                                new_binary(ND_MUL, lhs, new_long(rp->base->size)));
        node->ty = rp;
        return node;
    }

    error("invalid operands to pointer addition");
}

static Node *new_sub(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_SUB, lhs, rhs);

    Type *lp = pointer_arithmetic_type(lhs->ty);
    Type *rp = pointer_arithmetic_type(rhs->ty);

    if (lp && is_integer(rhs->ty)) {
        Node *node = new_binary(ND_SUB, lhs,
                                new_binary(ND_MUL, rhs, new_long(lp->base->size)));
        node->ty = lp;
        return node;
    }

    if (lp && rp) {
        if (!type_compatible(lp->base, rp->base))
            error("incompatible pointer subtraction");

        Node *diff = new_binary(ND_SUB, lhs, rhs);
        diff->ty = ty_long;
        Node *node = new_binary(ND_DIV, diff, new_long(lp->base->size));
        node->ty = ty_long;
        return node;
    }

    error("invalid operands to pointer subtraction");
}

static Node *new_compound_assign(NodeKind kind, Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
        if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
            return new_binary(kind, lhs, rhs);

        Type *ptr = pointer_arithmetic_type(lhs->ty);
        if (ptr && lhs->ty->kind == TY_PTR && is_integer(rhs->ty)) {
            rhs = new_binary(ND_MUL, rhs, new_long(ptr->base->size));
            return new_binary(kind, lhs, rhs);
        }

        error("invalid operands to pointer compound assignment");
    }

    if ((kind == ND_MUL_EQ || kind == ND_DIV_EQ) &&
        is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(kind, lhs, rhs);

    if (is_integer(lhs->ty) && is_integer(rhs->ty))
        return new_binary(kind, lhs, rhs);

    error("invalid operands");
}

static Node *new_inc_dec(NodeKind kind, Node *expr) {
    add_type(expr);
    if (!is_numeric(expr->ty) && !pointer_arithmetic_type(expr->ty))
        error("invalid increment/decrement operand");
    return new_unary(kind, expr);
}
'''

if s.count(old) != 1:
    raise SystemExit(f'pointer helper block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/expression_operators.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/pointer_arithmetic.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = '- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, prefix/postfix `++/--`, all compound assignments (`+= -= *= /= %= &= |= ^= <<= >>=`), type cast\n'
replacement = '- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, prefix/postfix `++/--`, all compound assignments (`+= -= *= /= %= &= |= ^= <<= >>=`), type cast; pointer arithmetic follows complete-object rules with array decay, element-size scaling, compatible pointer subtraction, and rejection of `void *`/function-pointer arithmetic\n'
if s.count(needle) != 1:
    raise SystemExit(f'README operator anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))

Path('test/pointer_arithmetic.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-ptrarith.c
  ./minicc tmp-ptrarith.c > tmp-ptrarith.s
  cc -o tmp-ptrarith tmp-ptrarith.s
  set +e
  ./tmp-ptrarith
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "pointer arithmetic failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(pointer arithmetic): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-ptrarith-bad.c
  if ./minicc tmp-ptrarith-bad.c > tmp-ptrarith-bad.s 2>/dev/null; then
    echo "pointer arithmetic unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(pointer arithmetic): rejected invalid program"
}

# Object-pointer arithmetic scales by the pointed-to object size.
assert_run 7 'int main(){int a[4];a[2]=7;int *p=a;return *(p+2);}'
assert_run 9 'int main(){int a[4];a[2]=9;int *p=a;return *(2+p);}'
assert_run 5 'int main(){int a[4];a[1]=5;int *p=a+2;p-=1;return *p;}'
assert_run 8 'int main(){int a[5];a[3]=8;int *p=a;p+=3;return *p;}'
assert_run 3 'int main(){int a[6];return (&a[4]-&a[1]);}'
assert_run 4 'int main(){char a[8];return (&a[6]-&a[2]);}'
assert_run 2 'struct S{int x;int y;};int main(){struct S a[4];struct S *p=&a[3];struct S *q=&a[1];return p-q;}'
assert_run 6 'int main(){int a[3];a[1]=6;int *p=a;p++;return *p;}'
assert_run 4 'int main(){int a[3];a[1]=4;int *p=a+2;--p;return *p;}'
assert_run 1 'int main(){int a[2][3];int (*p)[3]=a;p++;return p-a;}'

# void*, function pointers, incomplete objects and non-integral offsets are not
# valid pointer-arithmetic operands in standard C.
assert_fail 'int main(){void *p; p=p+1; return 0;}'
assert_fail 'int main(){void *p; p=1+p; return 0;}'
assert_fail 'int main(){void *p; p=p-1; return 0;}'
assert_fail 'int main(){void *p; p+=1; return 0;}'
assert_fail 'int main(){void *p; p++; return 0;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f; p=p+1; return 0;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f; p=p-1; return 0;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f; ++p; return 0;}'
assert_fail 'struct S; int main(){struct S *p; p=p+1; return 0;}'
assert_fail 'int main(){int a[2];int *p=a;p=p+1.5;return 0;}'
assert_fail 'int main(){int a[2];int *p=a;int *q=a;p=p+q;return 0;}'
assert_fail 'int main(){int a[2];int *p=a;return 1-p;}'
assert_fail 'int main(){int a[2];double b[2];return a-b;}'
assert_fail 'int f(){return 0;} int main(){int (*p)()=f;int (*q)()=f;return p-q;}'

echo 'All pointer-arithmetic tests passed!'
''')
