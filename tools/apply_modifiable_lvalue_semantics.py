from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = r'''static Node *new_long(int64_t val) {
    Node *node = new_node(ND_NUM);
    node->val = val;
    node->ty = ty_long;
    return node;
}

'''
insert = r'''static Node *new_long(int64_t val) {
    Node *node = new_node(ND_NUM);
    node->val = val;
    node->ty = ty_long;
    return node;
}

static bool is_lvalue(Node *node) {
    add_type(node);

    switch (node->kind) {
    case ND_VAR:
        return node->ty->kind != TY_FUNC;
    case ND_DEREF:
        return node->ty->kind != TY_FUNC && node->ty->kind != TY_VOID;
    case ND_MEMBER:
        return is_lvalue(node->lhs);
    default:
        return false;
    }
}

static bool is_modifiable_lvalue(Node *node) {
    if (!is_lvalue(node))
        return false;

    Type *ty = node->ty;
    if (!ty || ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
        ty->kind == TY_VOID || ty->is_incomplete)
        return false;
    return true;
}

static bool is_addressable_expr(Node *node) {
    add_type(node);

    // A function designator is not an lvalue in C, but unary & is explicitly
    // permitted on one. Both a named function and *function_pointer reach
    // here with TY_FUNC.
    if (node->ty->kind == TY_FUNC)
        return node->kind == ND_VAR || node->kind == ND_DEREF;
    return is_lvalue(node);
}

static Node *new_checked_addr(Node *operand, Token *op) {
    if (!is_addressable_expr(operand))
        error_at(op->loc, "address-of operand is not an lvalue or function designator");
    return new_unary(ND_ADDR, operand);
}

static Node *new_checked_deref(Node *operand, Token *op) {
    add_type(operand);

    Type *target = NULL;
    if (operand->ty->kind == TY_PTR || operand->ty->kind == TY_ARRAY)
        target = operand->ty->base;
    else if (operand->ty->kind == TY_FUNC)
        target = operand->ty;

    if (!target || target->kind == TY_VOID)
        error_at(op->loc, "invalid pointer dereference");

    Node *node = new_unary(ND_DEREF, operand);
    node->ty = target;
    return node;
}

'''
if s.count(anchor) != 1:
    raise SystemExit(f'new_long anchor count={s.count(anchor)}')
s = s.replace(anchor, insert, 1)

old = r'''static Node *new_compound_assign(NodeKind kind, Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
'''
new = r'''static Node *new_compound_assign(NodeKind kind, Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (!is_modifiable_lvalue(lhs))
        error("left operand of compound assignment is not a modifiable lvalue");

    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
'''
if s.count(old) != 1:
    raise SystemExit(f'compound anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = r'''static Node *new_inc_dec(NodeKind kind, Node *expr) {
    add_type(expr);
    if (!is_numeric(expr->ty) && !pointer_arithmetic_type(expr->ty))
        error("invalid increment/decrement operand");
    return new_unary(kind, expr);
}
'''
new = r'''static Node *new_inc_dec(NodeKind kind, Node *expr) {
    add_type(expr);
    if (!is_modifiable_lvalue(expr))
        error("increment/decrement operand is not a modifiable lvalue");
    if (!is_numeric(expr->ty) && !pointer_arithmetic_type(expr->ty))
        error("invalid increment/decrement operand");
    return new_unary(kind, expr);
}
'''
if s.count(old) != 1:
    raise SystemExit(f'incdec anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = r'''static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op) {
    add_type(lhs);
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(op->loc, "incompatible types in assignment");
    return new_binary(ND_ASSIGN, lhs, rhs);
}
'''
new = r'''static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op) {
    add_type(lhs);
    if (!is_modifiable_lvalue(lhs))
        error_at(op->loc, "left operand is not a modifiable lvalue");
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(op->loc, "incompatible types in assignment");
    return new_binary(ND_ASSIGN, lhs, rhs);
}
'''
if s.count(old) != 1:
    raise SystemExit(f'checked assign anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '    if (equal(tok, "&"))  return new_unary(ND_ADDR, unary(rest, tok->next));\n    if (equal(tok, "*"))  return new_unary(ND_DEREF, unary(rest, tok->next));\n'
new = '''    if (equal(tok, "&")) {\n        Token *op = tok;\n        return new_checked_addr(unary(rest, tok->next), op);\n    }\n    if (equal(tok, "*")) {\n        Token *op = tok;\n        return new_checked_deref(unary(rest, tok->next), op);\n    }\n'''
if s.count(old) != 1:
    raise SystemExit(f'unary addr/deref anchor count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/pointer_arithmetic.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/lvalue_semantics.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = 'and expression-level assignment/return/argument compatibility checking for numeric, pointer, function-pointer, `void *`, null-pointer, and record values, with typed equality/relational/logical/conditional operators and conditional-result normalization\n'
replacement = 'and expression-level assignment/return/argument compatibility checking for numeric, pointer, function-pointer, `void *`, null-pointer, and record values, with typed equality/relational/logical/conditional operators, conditional-result normalization, and semantic modifiable-lvalue/addressability checks for assignment, compound assignment, increment/decrement, address-of, and dereference\n'
if s.count(needle) != 1:
    raise SystemExit(f'README anchor count={s.count(needle)}')
s = s.replace(needle, replacement, 1)
p.write_text(s)

Path('test/lvalue_semantics.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-lvalue.c
  ./minicc tmp-lvalue.c > tmp-lvalue.s
  cc -o tmp-lvalue tmp-lvalue.s
  set +e
  ./tmp-lvalue
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "lvalue test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-lvalue-bad.c
  if ./minicc tmp-lvalue-bad.c > tmp-lvalue-bad.s 2>/dev/null; then
    echo "lvalue test unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
}

assert_run 7 'int main(){int x=1;x=7;return x;}'
assert_run 9 'int main(){int x=1;int *p=&x;*p=9;return x;}'
assert_run 6 'struct S{int x;};int main(){struct S s;s.x=6;return s.x;}'
assert_run 8 'struct S{int x;};int main(){struct S s;struct S *p=&s;p->x=8;return s.x;}'
assert_run 5 'int main(){int x=4;int *p=&x;++*p;return x;}'
assert_run 7 'struct S{int x;};int main(){struct S s;s.x=2;s.x+=5;return s.x;}'
assert_run 3 'int main(){int a[2];a[0]=3;int (*p)[2]=&a;return (*p)[0];}'
assert_run 5 'int f(){return 5;}int main(){int (*p)()=&f;return (*p)();}'
assert_run 4 'int main(){int x=4;int *p=&x;int *q=&*p;return *q;}'
assert_run 6 'int f(){return 6;}int main(){int (*p)()=f;int (*q)()=&*p;return q();}'
assert_fail 'int main(){1=2;return 0;}'
assert_fail 'int main(){int x=1;(x+1)=3;return x;}'
assert_fail 'int main(){int x=1,y=2;(x,y)=3;return x;}'
assert_fail 'int main(){int x=1,y=2;(1?x:y)=3;return x;}'
assert_fail 'int main(){int a[2],b[2];a=b;return 0;}'
assert_fail 'int f(){return 1;}int g(){return 2;}int main(){f=g;return 0;}'
assert_fail 'int main(){int x=1;(x+1)+=2;return x;}'
assert_fail 'int main(){int a[2];a+=1;return 0;}'
assert_fail 'int main(){int x=1;++(x+1);return x;}'
assert_fail 'int main(){int x=1;(x+1)++;return x;}'
assert_fail 'int main(){int a[2];a++;return 0;}'
assert_fail 'int f(){return 1;}int main(){++f;return 0;}'
assert_fail 'int main(){int *p=&42;return 0;}'
assert_fail 'int main(){int x=1;int *p=&(x+1);return 0;}'
assert_fail 'int main(){int x=1;int *p=&(int)x;return 0;}'
assert_fail 'int main(){return *42;}'
assert_fail 'int main(){void *p=0;return *p;}'
assert_fail 'int main(){void *p=0;*p=1;return 0;}'

echo 'All lvalue semantic tests passed!'
''')
