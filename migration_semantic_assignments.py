from pathlib import Path

p = Path('parse.c')
s = p.read_text()

# Add forward declarations and current return type tracking.
needle = "static Type *type_name(Token **rest, Token *tok);\n"
repl = needle + "static bool type_compatible(Type *a, Type *b);\nstatic bool assignment_compatible(Type *dst, Node *rhs);\n\nstatic Type *current_return_ty;\n"
assert needle in s
s = s.replace(needle, repl, 1)

# Add assignment compatibility helpers before assign().
needle = "static Node *assign(Token **rest, Token *tok) {\n"
helper = r'''static bool is_null_pointer_constant(Node *node) {
    add_type(node);
    return is_integer(node->ty) && node->kind == ND_NUM && node->val == 0;
}

static bool pointer_assignment_compatible(Type *dst, Type *src) {
    if (!dst || !src || dst->kind != TY_PTR)
        return false;

    // Function designators are assignable to compatible function pointers.
    if (src->kind == TY_FUNC)
        return dst->base && dst->base->kind == TY_FUNC &&
               type_compatible(dst->base, src);

    if (src->kind != TY_PTR)
        return false;
    if (type_compatible(dst->base, src->base))
        return true;

    // C permits object pointers to convert to/from void*. Function pointers
    // deliberately do not participate in this conversion.
    bool dst_void = dst->base && dst->base->kind == TY_VOID;
    bool src_void = src->base && src->base->kind == TY_VOID;
    bool dst_func = dst->base && dst->base->kind == TY_FUNC;
    bool src_func = src->base && src->base->kind == TY_FUNC;
    return !dst_func && !src_func && (dst_void || src_void);
}

static bool assignment_compatible(Type *dst, Node *rhs) {
    add_type(rhs);
    Type *src = rhs->ty;

    if (!dst || !src || dst->kind == TY_ARRAY || dst->kind == TY_FUNC)
        return false;
    if (is_numeric(dst) && is_numeric(src))
        return true;

    // _Bool accepts any scalar value, including pointers/function designators.
    if (dst->kind == TY_BOOL &&
        (src->kind == TY_PTR || src->kind == TY_FUNC))
        return true;

    if (dst->kind == TY_PTR)
        return pointer_assignment_compatible(dst, src) ||
               is_null_pointer_constant(rhs);

    if (dst->kind == TY_STRUCT && src->kind == TY_STRUCT)
        return type_compatible(dst, src);

    return type_compatible(dst, src);
}

static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op) {
    add_type(lhs);
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(op->loc, "incompatible types in assignment");
    return new_binary(ND_ASSIGN, lhs, rhs);
}

static Node *assign(Token **rest, Token *tok) {
'''
assert needle in s
s = s.replace(needle, helper, 1)

# Make ordinary assignments checked.
old = '''    if (equal(tok, "="))
        node = new_binary(ND_ASSIGN, node, assign(&tok, tok->next));
'''
new = '''    if (equal(tok, "=")) {
        Token *op = tok;
        node = new_checked_assign(node, assign(&tok, tok->next), op);
    }
'''
assert old in s
s = s.replace(old, new, 1)

# Check local initializer assignments created internally.
s = s.replace('Node *a = new_binary(ND_ASSIGN, member_node, e);', 'Node *a = new_checked_assign(member_node, e, tok);')
s = s.replace('Node *a = new_binary(ND_ASSIGN, lhs, e);', 'Node *a = new_checked_assign(lhs, e, tok);')
s = s.replace('Node *a = new_binary(ND_ASSIGN, vnode, rhs);', 'Node *a = new_checked_assign(vnode, rhs, tok);')

# Return constraints, including void/non-void forms.
old = '''    if (equal(tok, "return")) {
        Node *node = new_node(ND_RETURN);
        if (!equal(tok->next, ";"))
            node->lhs = expr(&tok, tok->next);
        else
            tok = tok->next;
        *rest = skip(tok, ";");
        return node;
    }
'''
new = '''    if (equal(tok, "return")) {
        Token *ret_tok = tok;
        Node *node = new_node(ND_RETURN);
        if (!equal(tok->next, ";")) {
            node->lhs = expr(&tok, tok->next);
            if (!current_return_ty || current_return_ty->kind == TY_VOID)
                error_at(ret_tok->loc, "void function should not return a value");
            if (!assignment_compatible(current_return_ty, node->lhs))
                error_at(ret_tok->loc, "incompatible return type");
        } else {
            tok = tok->next;
            if (current_return_ty && current_return_ty->kind != TY_VOID)
                error_at(ret_tok->loc, "non-void function should return a value");
        }
        *rest = skip(tok, ";");
        return node;
    }
'''
assert old in s
s = s.replace(old, new, 1)

# Validate fixed function arguments in all three call paths. Numeric casts remain.
old = '''        if (expected) {
            if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                arg->ty != expected->ty) {
'''
new = '''        if (expected) {
            if (!assignment_compatible(expected->ty, arg))
                error_at(tok->loc, "incompatible argument type");
            if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                arg->ty != expected->ty) {
'''
count = s.count(old)
assert count == 3, count
s = s.replace(old, new)

# Track current function return type while parsing the body.
old = '''            fn->is_static = is_static;
            fn->is_variadic = ty->is_variadic;

            Node *block = compound_stmt(&tok, tok);
'''
new = '''            fn->is_static = is_static;
            fn->is_variadic = ty->is_variadic;

            Type *saved_return_ty = current_return_ty;
            current_return_ty = ty->return_ty;
            Node *block = compound_stmt(&tok, tok);
            current_return_ty = saved_return_ty;
'''
assert old in s
s = s.replace(old, new, 1)

p.write_text(s)

# Add focused regression suite.
test = r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-semassign.c
  ./minicc tmp-semassign.c > tmp-semassign.s
  cc -o tmp-semassign tmp-semassign.s
  set +e
  ./tmp-semassign
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "semantic assignment failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic assignment): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-semassign-bad.c
  if ./minicc tmp-semassign-bad.c > tmp-semassign-bad.s 2>/dev/null; then
    echo "semantic assignment unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic assignment): rejected invalid program"
}

# Numeric assignment/return conversions remain valid.
assert_run 3 'int main(){double x=3.8; int y=x; return y;}'
assert_run 7 'double f(){return 7;} int main(){return f();}'

# Compatible object pointers, void* conversions, null pointer constants.
assert_run 5 'int main(){int x=5; int *p=&x; void *v=p; int *q=v; return *q;}'
assert_run 1 'int main(){int *p=0; return p==0;}'
assert_run 4 'int f(int x){return x+1;} int main(){int (*fp)(int)=f; return fp(3);}'
assert_run 1 'int main(){int x=1; int *p=&x; _Bool b=p; return b;}'

# Same record type assignment is valid and copied by codegen.
assert_run 9 'struct S{int x;}; int main(){struct S a; struct S b; b.x=9; a=b; return a.x;}'

# Return forms are constrained.
assert_run 0 'void f(){return;} int main(){f();return 0;}'

# Incompatible pointer/record assignments.
assert_fail 'int main(){int *p; double *q; p=q; return 0;}'
assert_fail 'int main(){int *p; p=1; return 0;}'
assert_fail 'int f(int x){return x;} int g(double x){return 0;} int main(){int (*p)(int)=g;return 0;}'
assert_fail 'struct A{int x;}; struct B{int x;}; int main(){struct A a; struct B b; a=b; return 0;}'

# Argument constraints for direct and indirect calls.
assert_fail 'int f(int *p){return 0;} int main(){double *q;return f(q);}'
assert_fail 'int f(int *p){return 0;} int main(){int (*fp)(int*)=f; double *q;return fp(q);}'
assert_run 0 'int f(void *p){return p!=0;} int main(){int x;return f(&x)==0;}'

# Return type constraints.
assert_fail 'int *f(){double *p;return p;} int main(){return 0;}'
assert_fail 'int f(){return;} int main(){return f();}'
assert_fail 'void f(){return 1;} int main(){f();return 0;}'

# Explicit casts remain the escape hatch for intentional conversions.
assert_run 1 'int main(){long x=1; int *p=(int*)x; return p!=0;}'

echo 'All semantic-assignment tests passed!'
'''
Path('test/semantic_assignments.sh').write_text(test)

m = Path('Makefile')
ms = m.read_text()
needle = '\tbash ./test/type_compatibility.sh\n'
assert needle in ms
ms = ms.replace(needle, needle + '\tbash ./test/semantic_assignments.sh\n', 1)
m.write_text(ms)

r = Path('README.md')
rs = r.read_text()
needle = 'prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
assert needle in rs
rs = rs.replace(needle, needle + ', and expression-level assignment/return/argument compatibility checking for numeric, pointer, function-pointer, `void *`, null-pointer, and record values', 1)
r.write_text(rs)
