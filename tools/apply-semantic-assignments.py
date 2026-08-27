from pathlib import Path

p = Path('parse.c')
s = p.read_text()

def rep(old, new, count=None):
    global s
    n = s.count(old)
    if count is not None and n != count:
        raise SystemExit(f'expected {count} matches, got {n}: {old[:80]!r}')
    if count is None and n == 0:
        raise SystemExit(f'anchor not found: {old[:80]!r}')
    s = s.replace(old, new)

rep('static Type *type_name(Token **rest, Token *tok);\n',
    'static Type *type_name(Token **rest, Token *tok);\n'
    'static bool type_compatible(Type *a, Type *b);\n'
    'static bool assignment_compatible(Type *dst, Node *rhs);\n'
    'static Node *new_assignment(Node *lhs, Node *rhs);\n', 1)

rep('static Node *current_labels;\n',
    'static Node *current_labels;\nstatic Type *current_return_ty;\n', 1)

old_assign = '''static Node *assign(Token **rest, Token *tok) {
    Node *node = ternary(&tok, tok);
    if (equal(tok, "="))
        node = new_binary(ND_ASSIGN, node, assign(&tok, tok->next));
    else if (equal(tok, "+="))
'''
new_assign = '''static Node *assign(Token **rest, Token *tok) {
    Node *node = ternary(&tok, tok);
    if (equal(tok, "=")) {
        Node *rhs = assign(&tok, tok->next);
        node = new_assignment(node, rhs);
    } else if (equal(tok, "+="))
'''
rep(old_assign, new_assign, 1)

old_return = '''    if (equal(tok, "return")) {
        Node *node = new_node(ND_RETURN);
        if (!equal(tok->next, ";"))
            node->lhs = expr(&tok, tok->next);
        else
            tok = tok->next;
        *rest = skip(tok, ";");
        return node;
    }
'''
new_return = '''    if (equal(tok, "return")) {
        Node *node = new_node(ND_RETURN);
        if (!equal(tok->next, ";")) {
            node->lhs = expr(&tok, tok->next);
            if (current_return_ty) {
                if (current_return_ty->kind == TY_VOID)
                    error_at(tok->loc, "void function should not return a value");
                if (!assignment_compatible(current_return_ty, node->lhs))
                    error_at(tok->loc, "incompatible return type");
            }
        } else {
            tok = tok->next;
        }
        *rest = skip(tok, ";");
        return node;
    }
'''
rep(old_return, new_return, 1)

# Route local scalar/member/array initializers through the same semantic assignment check.
rep('new_binary(ND_ASSIGN, member_node, e)', 'new_assignment(member_node, e)', 2)
rep('new_binary(ND_ASSIGN, lhs, e)', 'new_assignment(lhs, e)', 2)
rep('new_binary(ND_ASSIGN, vnode, rhs)', 'new_assignment(vnode, rhs)', 1)

# Fixed arguments are assignment-converted to their declared parameter type.
old_arg = '''        if (expected) {
            if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                arg->ty != expected->ty) {
'''
new_arg = '''        if (expected) {
            if (!assignment_compatible(expected->ty, arg))
                error_at(tok->loc, "incompatible argument type");
            if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                arg->ty != expected->ty) {
'''
rep(old_arg, new_arg, 1)

old_arg_indented = '''                    if (expected) {
                        if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                            arg->ty != expected->ty) {
'''
new_arg_indented = '''                    if (expected) {
                        if (!assignment_compatible(expected->ty, arg))
                            error_at(tok->loc, "incompatible argument type");
                        if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                            arg->ty != expected->ty) {
'''
rep(old_arg_indented, new_arg_indented, 2)

helper = r'''static bool is_null_pointer_constant(Node *node) {
    add_type(node);
    return node->kind == ND_NUM && is_integer(node->ty) && node->val == 0;
}

static bool assignment_compatible(Type *dst, Node *rhs) {
    if (!dst || !rhs)
        return false;

    add_type(rhs);
    Type *src = rhs->ty;

    if (dst->kind == TY_BOOL) {
        if (is_numeric(src) || src->kind == TY_PTR || src->kind == TY_ARRAY ||
            src->kind == TY_FUNC)
            return true;
    }

    if (is_numeric(dst) && is_numeric(src))
        return true;

    if (dst->kind == TY_STRUCT)
        return type_compatible(dst, src);

    if (dst->kind != TY_PTR)
        return type_compatible(dst, src);

    if (is_null_pointer_constant(rhs))
        return true;

    // Array and function expressions decay to pointers in value context.
    if (src->kind == TY_ARRAY)
        src = pointer_to(src->base);
    else if (src->kind == TY_FUNC)
        src = pointer_to(src);

    if (src->kind != TY_PTR)
        return false;

    if (type_compatible(dst->base, src->base))
        return true;

    // C permits implicit conversion between void* and pointers to object or
    // incomplete object types, but not between void* and function pointers.
    if (dst->base->kind == TY_VOID && src->base->kind != TY_FUNC)
        return true;
    if (src->base->kind == TY_VOID && dst->base->kind != TY_FUNC)
        return true;

    return false;
}

static Node *new_assignment(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (lhs->ty->kind == TY_ARRAY || lhs->ty->kind == TY_FUNC ||
        lhs->ty->kind == TY_VOID)
        error("expression is not assignable");

    if (!assignment_compatible(lhs->ty, rhs))
        error("incompatible types in assignment");

    return new_binary(ND_ASSIGN, lhs, rhs);
}

'''
rep('static Type *composite_redecl_type(Type *old_ty, Type *new_ty) {\n',
    helper + 'static Type *composite_redecl_type(Type *old_ty, Type *new_ty) {\n', 1)

old_body = '''            Node *block = compound_stmt(&tok, tok);
            fn->body = block->body;
'''
new_body = '''            Type *saved_return_ty = current_return_ty;
            current_return_ty = ty->return_ty;
            Node *block = compound_stmt(&tok, tok);
            current_return_ty = saved_return_ty;
            fn->body = block->body;
'''
rep(old_body, new_body, 1)

p.write_text(s)

# Add focused regression suite to Makefile.
m = Path('Makefile').read_text()
anchor = '\tbash ./test/type_compatibility.sh\n'
if anchor not in m:
    raise SystemExit('Makefile anchor missing')
m = m.replace(anchor, anchor + '\tbash ./test/semantic_assignments.sh\n')
Path('Makefile').write_text(m)

# Document expression-level semantic checking.
r = Path('README.md').read_text()
anchor = 'and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
if anchor not in r:
    raise SystemExit('README anchor missing')
r = r.replace(anchor, anchor + ', plus recursive assignment/initializer/return/argument compatibility checking for numeric, pointer, function-pointer, and record types')
Path('README.md').write_text(r)

Path('test/semantic_assignments.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-semantic.c
  ./minicc tmp-semantic.c > tmp-semantic.s
  cc -o tmp-semantic tmp-semantic.s
  set +e
  ./tmp-semantic
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
  printf "%s\n" "$input" > tmp-semantic-bad.c
  if ./minicc tmp-semantic-bad.c > tmp-semantic-bad.s 2>/dev/null; then
    echo "semantic assignment unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic assignment): rejected invalid conversion"
}

# Legal assignment conversions and decay.
assert_run 7 'int main(){int x=7;double d=x;return (int)d;}'
assert_run 6 'int main(){int a[2];int *p=a;p[1]=6;return a[1];}'
assert_run 5 'int main(){int x=5;int *p=&x;void *v=p;int *q=v;return *q;}'
assert_run 1 'int main(){int *p=0;return p==0;}'
assert_run 5 'int inc(int x){return x+1;} int main(){int (*fp)(int)=inc;return fp(4);}'
assert_run 9 'struct S{int x;}; int main(){struct S a;struct S b;a.x=9;b=a;return b.x;}'
assert_run 8 'int *id(int *p){return p;} int main(){int x=8;return *id(&x);}'
assert_run 1 'int *nil(void){return 0;} int main(){return nil()==0;}'
assert_run 4 'int first(int *p){return p[0];} int main(){int a[1];a[0]=4;return first(a);}'
assert_run 7 'int readp(void *v){int *p=v;return *p;} int main(){int x=7;return readp(&x);}'
assert_run 6 'int first(int *p){return p[0];} int main(){int a[1];a[0]=6;int (*fp)(int*)=first;return fp(a);}'
assert_run 1 'int main(){int x=1;int *p=&x;_Bool b=p;return b;}'

# Incompatible assignments and initializers are compile-time errors.
assert_fail 'int main(){int *p;double *q;p=q;return 0;}'
assert_fail 'int main(){int *p=1;return 0;}'
assert_fail 'int main(){int x;int *p=&x;x=p;return x;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){int (*fp)(int)=f;fp=g;return 0;}'
assert_fail 'struct A{int x;}; struct B{int x;}; int main(){struct A a;struct B b;a=b;return 0;}'
assert_fail 'int main(){int a[2];int b[2];a=b;return 0;}'

# Return and fixed-parameter conversions use the same compatibility rules.
assert_fail 'double *bad(int *p){return p;} int main(){return 0;}'
assert_fail 'void bad(void){return 1;} int main(){return 0;}'
assert_fail 'int take(int *p){return *p;} int main(){double x=1;return take(&x);}'
assert_fail 'int take(int *p){return *p;} int main(){double x=1;int (*fp)(int*)=take;return fp(&x);}'

echo 'All semantic-assignment tests passed!'
''')
