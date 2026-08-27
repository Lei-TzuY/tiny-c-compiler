from pathlib import Path

# minicc.h: retain qualifier metadata and identity links for qualified clones.
p = Path('minicc.h')
s = p.read_text()
old = '''    bool is_variadic; // TY_FUNC: variadic function (...)
    bool has_prototype; // TY_FUNC: distinguish f(void)/f(int) from old-style f()
};
'''
new = '''    bool is_variadic; // TY_FUNC: variadic function (...)
    bool has_prototype; // TY_FUNC: distinguish f(void)/f(int) from old-style f()

    // C type qualifiers. Qualified types are shallow clones; origin preserves
    // record identity and qual_next keeps incomplete tagged-record clones in
    // sync when the canonical tag is completed later.
    bool is_const;
    bool is_volatile;
    Type *origin;
    Type *qual_next;
};
'''
if s.count(old) != 1:
    raise SystemExit(f'Type fields anchor count={s.count(old)}')
s = s.replace(old, new, 1)
old = '''Type *pointer_to(Type *base);
Type *array_of(Type *base, int size);
Type *func_type(Type *return_ty);
Type *get_common_type(Type *ty1, Type *ty2);
'''
new = '''Type *pointer_to(Type *base);
Type *array_of(Type *base, int size);
Type *func_type(Type *return_ty);
Type *qualify_type(Type *ty, bool is_const, bool is_volatile);
Type *get_common_type(Type *ty1, Type *ty2);
'''
if s.count(old) != 1:
    raise SystemExit(f'type helper prototype anchor count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

# type.c: provide qualifier cloning and propagate aggregate qualifiers to members.
p = Path('type.c')
s = p.read_text()
anchor = '''bool is_numeric(Type *ty) {
    return is_integer(ty) || is_flonum(ty);
}

Type *pointer_to(Type *base) {
'''
insert = '''bool is_numeric(Type *ty) {
    return is_integer(ty) || is_flonum(ty);
}

Type *qualify_type(Type *ty, bool is_const, bool is_volatile) {
    if (!ty || (!is_const && !is_volatile))
        return ty;

    // Qualifying an array type through a typedef qualifies its element type.
    // Direct declarations such as `const int a[3]` already arrive in this
    // shape because the declaration specifiers qualify the element base first.
    if (ty->kind == TY_ARRAY) {
        Type *copy = calloc(1, sizeof(Type));
        *copy = *ty;
        copy->base = qualify_type(ty->base, is_const, is_volatile);
        copy->origin = ty->origin ? ty->origin : ty;
        copy->qual_next = NULL;
        return copy;
    }

    // Qualifiers on function types have no useful semantics in this compiler;
    // pointer qualifiers are attached to TY_PTR by the declarator parser.
    if (ty->kind == TY_FUNC)
        return ty;

    Type *copy = calloc(1, sizeof(Type));
    *copy = *ty;
    copy->origin = ty->origin ? ty->origin : ty;
    copy->is_const = copy->is_const || is_const;
    copy->is_volatile = copy->is_volatile || is_volatile;
    copy->qual_next = NULL;

    // A qualified clone of a forward-declared record must observe completion
    // of the canonical tag later in the translation unit.
    if (copy->kind == TY_STRUCT && copy->origin->is_incomplete) {
        copy->qual_next = copy->origin->qual_next;
        copy->origin->qual_next = copy;
    }
    return copy;
}

Type *pointer_to(Type *base) {
'''
if s.count(anchor) != 1:
    raise SystemExit(f'qualify_type anchor count={s.count(anchor)}')
s = s.replace(anchor, insert, 1)
old = '''    case ND_MEMBER:
        node->ty = node->member->ty;
        return;
'''
new = '''    case ND_MEMBER:
        // Accessing a member through a const/volatile aggregate carries those
        // qualifiers onto the member lvalue. This makes both `s.x` and
        // `p->x` honor a qualified struct/union object.
        node->ty = qualify_type(node->member->ty,
                                node->lhs->ty && node->lhs->ty->is_const,
                                node->lhs->ty && node->lhs->ty->is_volatile);
        return;
'''
if s.count(old) != 1:
    raise SystemExit(f'ND_MEMBER anchor count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

# parse.c: semantic qualifier rules.
p = Path('parse.c')
s = p.read_text()
old = '''static bool type_compatible(Type *a, Type *b);
static bool assignment_compatible(Type *dst, Node *rhs);
'''
new = '''static bool type_compatible(Type *a, Type *b);
static bool type_compatible_ignoring_top_qual(Type *a, Type *b);
static bool assignment_compatible(Type *dst, Node *rhs);
'''
if s.count(old) != 1:
    raise SystemExit(f'forward type_compatible anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''static bool is_modifiable_lvalue(Node *node) {
    if (!is_lvalue(node))
        return false;

    Type *ty = node->ty;
    if (!ty || ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
        ty->kind == TY_VOID || ty->is_incomplete)
        return false;
    return true;
}
'''
new = '''static bool type_has_const_subobject(Type *ty) {
    if (!ty)
        return false;
    if (ty->is_const)
        return true;
    if (ty->kind == TY_ARRAY)
        return type_has_const_subobject(ty->base);
    if (ty->kind == TY_STRUCT) {
        for (Member *m = ty->members; m; m = m->next)
            if (type_has_const_subobject(m->ty))
                return true;
    }
    return false;
}

static bool is_modifiable_lvalue(Node *node) {
    if (!is_lvalue(node))
        return false;

    Type *ty = node->ty;
    if (!ty || ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
        ty->kind == TY_VOID || ty->is_incomplete ||
        type_has_const_subobject(ty))
        return false;
    return true;
}
'''
if s.count(old) != 1:
    raise SystemExit(f'modifiable lvalue anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''        if (!type_compatible(lp->base, rp->base))
            error("incompatible pointer subtraction");
'''
new = '''        if (!type_compatible_ignoring_top_qual(lp->base, rp->base))
            error("incompatible pointer subtraction");
'''
if s.count(old) != 1:
    raise SystemExit(f'pointer subtraction compatibility anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Keep qualified clones of incomplete tagged records synchronized on completion.
old = '''    ty->align = align;
    ty->members = head.next;
    ty->is_incomplete = false;
    *rest = tok;
    return ty;
}
'''
new = '''    ty->align = align;
    ty->members = head.next;
    ty->is_incomplete = false;
    for (Type *q = ty->qual_next; q; q = q->qual_next) {
        q->size = ty->size;
        q->align = ty->align;
        q->members = ty->members;
        q->is_incomplete = false;
    }
    *rest = tok;
    return ty;
}
'''
if s.count(old) != 1:
    raise SystemExit(f'record completion anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Declaration specifiers now retain const/volatile instead of discarding them.
old = '''static Type *declspec(Token **rest, Token *tok) {
    Type *ty = NULL;

    while (is_decl_start(tok)) {
        if (consume(&tok, tok, "const") || consume(&tok, tok, "volatile") ||
            consume(&tok, tok, "register") || consume(&tok, tok, "inline") ||
            consume(&tok, tok, "static") || consume(&tok, tok, "extern"))
            continue;
'''
new = '''static Type *declspec(Token **rest, Token *tok) {
    Type *ty = NULL;
    bool is_const = false;
    bool is_volatile = false;

    while (is_decl_start(tok)) {
        if (consume(&tok, tok, "const")) {
            is_const = true;
            continue;
        }
        if (consume(&tok, tok, "volatile")) {
            is_volatile = true;
            continue;
        }
        if (consume(&tok, tok, "register") || consume(&tok, tok, "inline") ||
            consume(&tok, tok, "static") || consume(&tok, tok, "extern"))
            continue;
'''
if s.count(old) != 1:
    raise SystemExit(f'declspec prefix anchor count={s.count(old)}')
s = s.replace(old, new, 1)
old = '''    *rest = tok;
    return ty ? ty : ty_int;
}

static Type *adjust_param_type(Type *ty) {
'''
new = '''    *rest = tok;
    ty = ty ? ty : ty_int;
    return qualify_type(ty, is_const, is_volatile);
}

static Type *adjust_param_type(Type *ty) {
'''
if s.count(old) != 1:
    raise SystemExit(f'declspec return anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Attach qualifiers following each pointer star to the pointer type itself.
old = '''static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract) {
    while (consume(&tok, tok, "*"))
        ty = pointer_to(ty);

'''
new = '''static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract) {
    while (consume(&tok, tok, "*")) {
        ty = pointer_to(ty);
        bool ptr_const = false;
        bool ptr_volatile = false;
        while (equal(tok, "const") || equal(tok, "volatile")) {
            if (consume(&tok, tok, "const"))
                ptr_const = true;
            else if (consume(&tok, tok, "volatile"))
                ptr_volatile = true;
        }
        ty = qualify_type(ty, ptr_const, ptr_volatile);
    }

'''
if s.count(old) != 1:
    raise SystemExit(f'pointer declarator anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Initialization has assignment compatibility but does not require the freshly
# created object to be modifiable (const objects still need initial values).
old = '''static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op) {
    add_type(lhs);
    if (!is_modifiable_lvalue(lhs))
        error_at(op->loc, "left operand is not a modifiable lvalue");
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(op->loc, "incompatible types in assignment");
    return new_binary(ND_ASSIGN, lhs, rhs);
}

static Type *decay_value_type(Type *ty) {
'''
new = '''static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op) {
    add_type(lhs);
    if (!is_modifiable_lvalue(lhs))
        error_at(op->loc, "left operand is not a modifiable lvalue");
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(op->loc, "incompatible types in assignment");
    return new_binary(ND_ASSIGN, lhs, rhs);
}

static Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at) {
    add_type(lhs);
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(at->loc, "incompatible types in initializer");
    return new_binary(ND_ASSIGN, lhs, rhs);
}

static Type *decay_value_type(Type *ty) {
'''
if s.count(old) != 1:
    raise SystemExit(f'initializer helper anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Only declaration-time synthetic stores bypass modifiable-lvalue checking.
start = s.index('static Node *declaration(Token **rest, Token *tok, bool is_static, bool is_extern) {')
end = s.index('\nstatic bool is_label(Token *tok) {', start)
block = s[start:end]
count = block.count('new_checked_assign(')
if count != 5:
    raise SystemExit(f'expected 5 declaration initializer assignments, got {count}')
block = block.replace('new_checked_assign(', 'new_initializer_assign(')
s = s[:start] + block + s[end:]

# Pointer assignment follows C qualifier direction: qualifiers may be added at
# the immediate pointed-to level, but not discarded. Nested pointed-to type
# structure must otherwise remain compatible, rejecting int** -> const int**.
old = '''static bool pointer_assignment_compatible(Type *dst, Type *src) {
    if (!dst || !src || dst->kind != TY_PTR)
        return false;

    // Function designators are assignable to compatible function pointers.
    if (src->kind == TY_FUNC)
        return dst->base && dst->base->kind == TY_FUNC &&
               type_compatible(dst->base, src);

    // Array expressions decay to pointers to their first element in value
    // contexts such as assignment, initialization, return and arguments.
    if (src->kind == TY_ARRAY)
        return type_compatible(dst->base, src->base) ||
               (dst->base && dst->base->kind == TY_VOID);

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
'''
new = '''static bool qualifier_superset(Type *dst, Type *src) {
    return dst && src &&
           (!src->is_const || dst->is_const) &&
           (!src->is_volatile || dst->is_volatile);
}

static bool pointed_assignment_compatible(Type *dst, Type *src) {
    if (!dst || !src || !qualifier_superset(dst, src))
        return false;
    if (type_compatible_ignoring_top_qual(dst, src))
        return true;

    bool dst_void = dst->kind == TY_VOID;
    bool src_void = src->kind == TY_VOID;
    bool dst_func = dst->kind == TY_FUNC;
    bool src_func = src->kind == TY_FUNC;
    return !dst_func && !src_func && (dst_void || src_void);
}

static bool pointer_assignment_compatible(Type *dst, Type *src) {
    if (!dst || !src || dst->kind != TY_PTR)
        return false;

    // Function designators are assignable to compatible function pointers.
    if (src->kind == TY_FUNC)
        return dst->base && dst->base->kind == TY_FUNC &&
               type_compatible(dst->base, src);

    // Array expressions decay to pointers to their first element in value
    // contexts such as assignment, initialization, return and arguments.
    if (src->kind == TY_ARRAY)
        return pointed_assignment_compatible(dst->base, src->base);

    if (src->kind != TY_PTR)
        return false;
    return pointed_assignment_compatible(dst->base, src->base);
}
'''
if s.count(old) != 1:
    raise SystemExit(f'pointer assignment helper anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''static bool pointer_pair_compatible(Type *a, Type *b, bool relational_only) {
    a = decay_value_type(a);
    b = decay_value_type(b);
    if (!a || !b || a->kind != TY_PTR || b->kind != TY_PTR)
        return false;

    if (type_compatible(a->base, b->base)) {
        if (!relational_only)
            return true;
        return a->base && a->base->kind != TY_VOID && a->base->kind != TY_FUNC;
    }

    if (relational_only)
        return false;

    bool a_void = a->base && a->base->kind == TY_VOID;
    bool b_void = b->base && b->base->kind == TY_VOID;
    bool a_func = a->base && a->base->kind == TY_FUNC;
    bool b_func = b->base && b->base->kind == TY_FUNC;
    return !a_func && !b_func && (a_void || b_void);
}
'''
new = '''static bool pointer_pair_compatible(Type *a, Type *b, bool relational_only) {
    a = decay_value_type(a);
    b = decay_value_type(b);
    if (!a || !b || a->kind != TY_PTR || b->kind != TY_PTR)
        return false;

    if (type_compatible_ignoring_top_qual(a->base, b->base)) {
        if (!relational_only)
            return true;
        return a->base && a->base->kind != TY_VOID && a->base->kind != TY_FUNC;
    }

    if (relational_only)
        return false;

    bool a_void = a->base && a->base->kind == TY_VOID;
    bool b_void = b->base && b->base->kind == TY_VOID;
    bool a_func = a->base && a->base->kind == TY_FUNC;
    bool b_func = b->base && b->base->kind == TY_FUNC;
    return !a_func && !b_func && (a_void || b_void);
}
'''
if s.count(old) != 1:
    raise SystemExit(f'pointer pair anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''    if (tp && ep) {
        if (type_compatible(tt->base, et->base))
            return tt;

        bool t_void = tt->base && tt->base->kind == TY_VOID;
        bool e_void = et->base && et->base->kind == TY_VOID;
        bool t_func = tt->base && tt->base->kind == TY_FUNC;
        bool e_func = et->base && et->base->kind == TY_FUNC;
        if (!t_func && !e_func && (t_void || e_void))
            return pointer_to(ty_void);
    }
'''
new = '''    if (tp && ep) {
        bool merged_const = tt->base->is_const || et->base->is_const;
        bool merged_volatile = tt->base->is_volatile || et->base->is_volatile;

        if (type_compatible_ignoring_top_qual(tt->base, et->base))
            return pointer_to(qualify_type(tt->base, merged_const, merged_volatile));

        bool t_void = tt->base && tt->base->kind == TY_VOID;
        bool e_void = et->base && et->base->kind == TY_VOID;
        bool t_func = tt->base && tt->base->kind == TY_FUNC;
        bool e_func = et->base && et->base->kind == TY_FUNC;
        if (!t_func && !e_func && (t_void || e_void))
            return pointer_to(qualify_type(ty_void, merged_const, merged_volatile));
    }
'''
if s.count(old) != 1:
    raise SystemExit(f'conditional pointer anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Replace recursive type compatibility with qualifier-aware compatibility.
old_start = s.index('static bool type_compatible(Type *a, Type *b) {')
old_end = s.index('\nstatic Type *composite_redecl_type', old_start)
old_block = s[old_start:old_end]
new_block = '''static Type *type_identity(Type *ty) {
    return ty && ty->origin ? ty->origin : ty;
}

static bool type_compatible_impl(Type *a, Type *b, bool ignore_top_qual) {
    if (a == b)
        return true;
    if (!a || !b || a->kind != b->kind)
        return false;
    if (!ignore_top_qual &&
        (a->is_const != b->is_const || a->is_volatile != b->is_volatile))
        return false;

    switch (a->kind) {
    case TY_CHAR:
    case TY_SHORT:
    case TY_INT:
    case TY_LONG:
        return a->is_unsigned == b->is_unsigned;
    case TY_PTR:
        return type_compatible_impl(a->base, b->base, false);
    case TY_ARRAY:
        return type_compatible_impl(a->base, b->base, false) &&
               (!a->array_len || !b->array_len || a->array_len == b->array_len);
    case TY_STRUCT:
        return type_identity(a) == type_identity(b);
    case TY_FUNC: {
        if (!type_compatible_impl(a->return_ty, b->return_ty, false))
            return false;

        // Old-style f() remains compatible with a prototype. For prototype
        // comparison, C ignores only the top-level qualifiers on each parameter
        // after array/function parameter adjustment; nested pointer qualifiers
        // remain significant.
        if (!a->has_prototype || !b->has_prototype)
            return true;
        if (a->is_variadic != b->is_variadic)
            return false;

        Obj *pa = a->params;
        Obj *pb = b->params;
        while (pa && pb) {
            if (!type_compatible_impl(pa->ty, pb->ty, true))
                return false;
            pa = pa->param_next;
            pb = pb->param_next;
        }
        return !pa && !pb;
    }
    default:
        return true;
    }
}

static bool type_compatible(Type *a, Type *b) {
    return type_compatible_impl(a, b, false);
}

static bool type_compatible_ignoring_top_qual(Type *a, Type *b) {
    return type_compatible_impl(a, b, true);
}
'''
s = s[:old_start] + new_block + s[old_end:]
p.write_text(s)

# Makefile: add focused suite.
p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/lvalue_semantics.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile lvalue anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/type_qualifiers.sh\n', 1)
p.write_text(s)

# README: advertise semantic qualifier support.
p = Path('README.md')
s = p.read_text()
needle = '- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `unsigned`; enumerators accept integer constant expressions\n'
replacement = '- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `unsigned`, semantic `const`/`volatile` qualifiers (including pointer qualifiers and qualifier-safe pointer conversions); enumerators accept integer constant expressions\n'
if s.count(needle) != 1:
    raise SystemExit(f'README type line anchor count={s.count(needle)}')
s = s.replace(needle, replacement, 1)
p.write_text(s)

# Focused regression suite.
Path('test/type_qualifiers.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-qual.c
  ./minicc tmp-qual.c > tmp-qual.s
  cc -o tmp-qual tmp-qual.s
  set +e
  ./tmp-qual
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "type qualifier test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(type qualifier): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-qual-bad.c
  if ./minicc tmp-qual-bad.c > tmp-qual-bad.s 2>/dev/null; then
    echo "type qualifier test unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(type qualifier): rejected invalid program"
}

# Const objects may be initialized, then read, but volatile remains modifiable.
assert_run 3 'int main(){const int x=3;return x;}'
assert_run 5 'int main(){volatile int x=1;x=5;return x;}'
assert_run 4 'int main(){const int a[2]={3,4};return a[1];}'
assert_run 5 'typedef int A[2];int main(){const A a={2,5};return a[1];}'

# Pointer target qualifiers may be added, and pointer-object qualifiers apply to
# the pointer itself rather than its pointee.
assert_run 2 'int main(){int x=2;const int *p=&x;return *p;}'
assert_run 4 'int main(){const int x=4;const int *p=&x;return *p;}'
assert_run 7 'int main(){int x=1;int *p=&x;int *const q=p;*q=7;return x;}'
assert_run 6 'int main(){int x=1;volatile int *p=&x;*p=6;return x;}'
assert_run 8 'int main(){int x=8;void *p=&x;const int *q=p;return *q;}'
assert_run 9 'int main(){int x=9;int *p=&x;const void *q=p;return *(const int*)q;}'

# Top-level parameter qualifiers are ignored for function-type compatibility,
# while the parameter object in a definition retains its qualifier.
assert_run 6 'int f(const int x){return x;}int main(){return f(6);}'
assert_run 5 'int f(const int);int f(int x){return x;}int main(){return f(5);}'
assert_run 9 'int f(int *const p){return *p;}int main(){int x=9;return f(&x);}'
assert_run 7 'int f(int *const);int f(int *p){return *p;}int main(){int x=7;return f(&x);}'

# Qualified records propagate qualifiers through . and ->, and const members
# make the containing aggregate non-modifiable while still allowing init.
assert_run 3 'struct S{int x;};int main(){struct S s={3};const struct S *p=&s;return p->x;}'
assert_run 5 'struct S{int x;};int main(){const struct S s={5};return s.x;}'
assert_run 7 'struct S{const int x;};int main(){struct S s={7};return s.x;}'
assert_run 6 'struct S{int *const p;};int main(){int x=1;struct S s={&x};*s.p=6;return x;}'

# Qualified clones of forward-declared tagged records stay linked to completion.
assert_run 8 'struct S;const struct S *gp;struct S{int x;};int main(){struct S s;s.x=8;gp=&s;return gp->x;}'

# Pointer comparison/subtraction accept differently qualified versions of the
# same pointed-to object type; conditional pointers union immediate qualifiers.
assert_run 1 'int main(){int a[2];int *p=a;const int *q=a;return p==q;}'
assert_run 1 'int main(){int a[2];int *p=a;const int *q=a+1;return q-p;}'
assert_run 4 'int main(){int x=4;int *p=&x;const int *q=&x;const int *r=1?p:q;return *r;}'

# Same-qualified file-scope redeclarations remain compatible.
assert_run 3 'extern const int x;const int x=3;int main(){return x;}'

# Const objects/pointers and aggregates containing const subobjects are not
# modifiable lvalues.
assert_fail 'int main(){const int x=1;x=2;return x;}'
assert_fail 'int main(){const int x=1;x++;return x;}'
assert_fail 'int main(){const int x=1;x+=1;return x;}'
assert_fail 'int main(){int x=1,y=2;int *const p=&x;p=&y;return x;}'
assert_fail 'struct S{int x;};int main(){const struct S s={1};s.x=2;return s.x;}'
assert_fail 'struct S{int x;};int main(){struct S s={1};const struct S *p=&s;p->x=2;return s.x;}'
assert_fail 'struct S{const int x;};int main(){struct S a={1},b={2};a=b;return a.x;}'
assert_fail 'struct S{int *const p;};int main(){int x=1,y=2;struct S s={&x};s.p=&y;return x;}'

# Pointer conversion may add immediate target qualifiers but may never discard
# them, including through void*. Nested qualification changes remain unsafe.
assert_fail 'int main(){const int x=1;int *p=&x;return *p;}'
assert_fail 'int main(){volatile int x=1;int *p=&x;return *p;}'
assert_fail 'int main(){const int *p=0;int *q=p;return 0;}'
assert_fail 'int *f(const int *p){return p;}int main(){return 0;}'
assert_fail 'int f(int *p){return *p;}int main(){const int x=1;return f(&x);}'
assert_fail 'int main(){int **p=0;const int **q=p;return 0;}'
assert_fail 'int main(){const int **p=0;int **q=p;return 0;}'
assert_fail 'int main(){const int x=1;const int *p=&x;void *q=p;return 0;}'
assert_fail 'int main(){const void *p=0;int *q=p;return 0;}'

# Qualifiers are part of object and nested parameter type compatibility, but
# top-level parameter qualification alone is ignored.
assert_fail 'extern const int x;extern int x;int main(){return 0;}'
assert_fail 'int f(const int *);int f(int *);int main(){return 0;}'

# The conditional result retains the union of pointed-to qualifiers, so it
# cannot then be assigned to a pointer that would discard const.
assert_fail 'int main(){int x=1;int *p=&x;const int *q=&x;int *r=1?p:q;return *r;}'

echo 'All type qualifier tests passed!'
''')
