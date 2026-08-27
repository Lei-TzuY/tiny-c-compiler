from pathlib import Path
import re

p = Path('parse.c')
s = p.read_text()

# Shared semantic helpers are used by declarations, statements, assignments,
# and all fixed-parameter call paths, so forward-declare them near the parser API.
needle = 'static Type *type_name(Token **rest, Token *tok);\n'
assert s.count(needle) == 1
s = s.replace(needle, needle +
    'static bool type_compatible(Type *a, Type *b);\n'
    'static bool assignment_compatible(Type *dst, Node *rhs);\n'
    'static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op);\n', 1)

needle = 'static Node *current_labels;\n'
assert s.count(needle) == 1
s = s.replace(needle, needle + 'static Type *current_return_ty;\n', 1)

# Insert assignment-conversion semantics before assign().
needle = 'static Node *assign(Token **rest, Token *tok) {\n'
assert s.count(needle) == 1
helper = r'''static bool is_null_pointer_constant(Node *node) {
    add_type(node);
    return node->kind == ND_NUM && is_integer(node->ty) && node->val == 0;
}

static bool pointer_assignment_compatible(Type *dst, Type *src) {
    if (!dst || !src || dst->kind != TY_PTR)
        return false;

    if (src->kind == TY_FUNC)
        return dst->base && dst->base->kind == TY_FUNC &&
               type_compatible(dst->base, src);

    if (src->kind != TY_PTR)
        return false;

    if (type_compatible(dst->base, src->base))
        return true;

    // Object/incomplete-object pointers implicitly convert to and from void*.
    // Function pointers remain a separate pointer domain.
    bool dst_void = dst->base && dst->base->kind == TY_VOID;
    bool src_void = src->base && src->base->kind == TY_VOID;
    bool dst_func = dst->base && dst->base->kind == TY_FUNC;
    bool src_func = src->base && src->base->kind == TY_FUNC;
    return !dst_func && !src_func && (dst_void || src_void);
}

static bool assignment_compatible(Type *dst, Node *rhs) {
    if (!dst || !rhs)
        return false;

    add_type(rhs);
    Type *src = rhs->ty;
    if (!src)
        return false;

    // Array expressions decay before assignment/argument/return conversion.
    if (src->kind == TY_ARRAY)
        src = pointer_to(src->base);

    if (dst->kind == TY_ARRAY || dst->kind == TY_FUNC || dst->kind == TY_VOID)
        return false;

    if (is_numeric(dst) && is_numeric(src))
        return true;

    // _Bool accepts scalar values, including object/function pointers.
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
s = s.replace(needle, helper, 1)

old = '''    if (equal(tok, "="))
        node = new_binary(ND_ASSIGN, node, assign(&tok, tok->next));
'''
new = '''    if (equal(tok, "=")) {
        Token *op = tok;
        node = new_checked_assign(node, assign(&tok, tok->next), op);
    }
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

# Compiler-generated local initializer assignments obey the same constraints.
s = s.replace('Node *a = new_binary(ND_ASSIGN, member_node, e);',
              'Node *a = new_checked_assign(member_node, e, tok);')
s = s.replace('Node *a = new_binary(ND_ASSIGN, lhs, e);',
              'Node *a = new_checked_assign(lhs, e, tok);')
s = s.replace('Node *a = new_binary(ND_ASSIGN, vnode, rhs);',
              'Node *a = new_checked_assign(vnode, rhs, tok);')

# Return values use assignment conversion to the declared function return type.
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
            if (current_return_ty && current_return_ty->kind == TY_VOID)
                error_at(ret_tok->loc, "void function should not return a value");
            if (current_return_ty &&
                !assignment_compatible(current_return_ty, node->lhs))
                error_at(ret_tok->loc, "incompatible return type");
        } else {
            tok = tok->next;
        }
        *rest = skip(tok, ";");
        return node;
    }
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

# Validate every fixed argument before existing numeric coercion. The same
# textual shape appears at three indentation levels, so use an indentation-aware regex.
pat = re.compile(r'(?m)^(?P<i>\s*)if \(expected\) \{\n(?P=i)    if \(is_numeric\(arg->ty\) && is_numeric\(expected->ty\) &&\n(?P=i)        arg->ty != expected->ty\) \{')
def repl(m):
    i = m.group('i')
    return (f'{i}if (expected) {{\n'
            f'{i}    if (!assignment_compatible(expected->ty, arg))\n'
            f'{i}        error_at(tok->loc, "incompatible argument type");\n'
            f'{i}    if (is_numeric(arg->ty) && is_numeric(expected->ty) &&\n'
            f'{i}        arg->ty != expected->ty) {{')
s, n = pat.subn(repl, s)
assert n == 3, n

# Make the declared return type available while statements are parsed.
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
assert s.count(old) == 1
s = s.replace(old, new, 1)
p.write_text(s)

# Focused regression suite.
t = Path('test/semantic_assignments.sh')
t.write_text(r'''#!/bin/bash
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
    echo "semantic conversion failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic conversion): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-semantic-bad.c
  if ./minicc tmp-semantic-bad.c > tmp-semantic-bad.s 2>/dev/null; then
    echo "semantic conversion unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic conversion): rejected invalid program"
}

# Numeric conversion, pointer compatibility, decay, null pointers and records.
assert_run 7 'int main(){int x=7;double d=x;return (int)d;}'
assert_run 6 'int main(){int a[2];int *p=a;p[1]=6;return a[1];}'
assert_run 5 'int main(){int x=5;int *p=&x;void *v=p;int *q=v;return *q;}'
assert_run 1 'int main(){int *p=0;return p==0;}'
assert_run 5 'int inc(int x){return x+1;} int main(){int (*fp)(int)=inc;return fp(4);}'
assert_run 9 'struct S{int x;}; int main(){struct S a;struct S b;a.x=9;b=a;return b.x;}'
assert_run 1 'int main(){int x=1;int *p=&x;_Bool b=p;return b;}'

# Returns and fixed arguments share assignment-conversion semantics.
assert_run 8 'int *id(int *p){return p;} int main(){int x=8;return *id(&x);}'
assert_run 1 'int *nil(void){return 0;} int main(){return nil()==0;}'
assert_run 4 'int first(int *p){return p[0];} int main(){int a[1];a[0]=4;return first(a);}'
assert_run 7 'int readp(void *v){int *p=v;return *p;} int main(){int x=7;return readp(&x);}'
assert_run 6 'int first(int *p){return p[0];} int main(){int a[1];a[0]=6;int (*fp)(int*)=first;return fp(a);}'
assert_run 0 'void done(void){return;} int main(){done();return 0;}'

# Incompatible assignments/initializers.
assert_fail 'int main(){int *p;double *q;p=q;return 0;}'
assert_fail 'int main(){int *p=1;return 0;}'
assert_fail 'int main(){int x;int *p=&x;x=p;return x;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){int (*fp)(int)=f;fp=g;return 0;}'
assert_fail 'struct A{int x;}; struct B{int x;}; int main(){struct A a;struct B b;a=b;return 0;}'
assert_fail 'int main(){int a[2];int b[2];a=b;return 0;}'

# Incompatible returns and direct/indirect fixed arguments.
assert_fail 'double *bad(int *p){return p;} int main(){return 0;}'
assert_fail 'void bad(void){return 1;} int main(){return 0;}'
assert_fail 'int take(int *p){return *p;} int main(){double x=1;return take(&x);}'
assert_fail 'int take(int *p){return *p;} int main(){double x=1;int (*fp)(int*)=take;return fp(&x);}'

# Explicit casts remain available for intentional low-level conversions.
assert_run 1 'int main(){long x=1;int *p=(int*)x;return p!=0;}'

echo 'All semantic-assignment tests passed!'
''')

m = Path('Makefile')
ms = m.read_text()
anchor = '\tbash ./test/type_compatibility.sh\n'
assert ms.count(anchor) == 1
m.write_text(ms.replace(anchor, anchor + '\tbash ./test/semantic_assignments.sh\n', 1))

r = Path('README.md')
rs = r.read_text()
anchor = 'and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
assert rs.count(anchor) == 1
r.write_text(rs.replace(anchor, anchor + ', plus expression-level assignment, initializer, return, and fixed-argument conversion checks for numeric, pointer, function-pointer, `void *`, null-pointer, array-decay, and record values', 1))
