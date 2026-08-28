from pathlib import Path


def replace_once(s, old, new, label):
    if old not in s:
        raise RuntimeError(f"missing anchor: {label}")
    return s.replace(old, new, 1)

# minicc.h: declaration-level alignment metadata belongs to objects/members,
# not Type identity.
p = Path('minicc.h')
s = p.read_text()
s = replace_once(s,
'''struct Member {
    Member *next;
    char *name;
    Type *ty;
    int offset;
};''',
'''struct Member {
    Member *next;
    char *name;
    Type *ty;
    int align;      // explicit _Alignas requirement, 0 = natural type alignment
    int offset;
};''', 'member align field')
s = replace_once(s,
'''    char *name;    // Variable name
    Type *ty;      // Variable type
    bool is_local; // local or global/constant
''',
'''    char *name;    // Variable name
    Type *ty;      // Variable type
    int align;     // explicit _Alignas requirement, 0 = natural type alignment
    bool is_local; // local or global/constant
''', 'object align field')
p.write_text(s)

# tokenize.c: make _Alignas a reserved keyword.
p = Path('tokenize.c')
s = p.read_text()
s = replace_once(s,
'''                         "static", "extern", "const", "volatile",
                         "inline", "register", "_Bool", "float", "double"};''',
'''                         "static", "extern", "const", "volatile",
                         "inline", "register", "_Bool", "float", "double",
                         "_Alignas"};''', 'Alignas keyword')
p.write_text(s)

# parse.c
p = Path('parse.c')
s = p.read_text()

# Declaration attributes and forward declarations.
s = replace_once(s,
'''static Type *declspec(Token **rest, Token *tok);
static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract);''',
'''typedef struct {
    bool is_static;
    bool is_extern;
    bool is_register;
    bool is_inline;
    int align;
} DeclAttrs;

static Type *declspec(Token **rest, Token *tok);
static Type *declspec_with_attrs(Token **rest, Token *tok, DeclAttrs *attrs);
static int validate_requested_alignment(Type *ty, int requested, Token *at);
static void apply_object_alignment(Obj *var, Type *ty, int requested, Token *at);
static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract);''', 'declaration attrs')

s = replace_once(s,
'''    if (equal(tok, "const") || equal(tok, "volatile")) return true;
    if (equal(tok, "register") || equal(tok, "inline")) return true;
''',
'''    if (equal(tok, "const") || equal(tok, "volatile")) return true;
    if (equal(tok, "register") || equal(tok, "inline")) return true;
    if (equal(tok, "_Alignas")) return true;
''', 'decl start Alignas')

# Record members consume alignment specifiers and feed them into layout.
rstart = s.index('static Type *record_decl(Token **rest, Token *tok, bool is_union) {')
rend = s.index('static int64_t cast_const_integer', rstart)
r = s[rstart:rend]
r = replace_once(r,
'''    while (!equal(tok, "}")) {
        Type *basety = declspec(&tok, tok);
        for (bool first = true; !consume(&tok, tok, ";"); first = false) {''',
'''    while (!equal(tok, "}")) {
        DeclAttrs attrs = {};
        Type *basety = declspec_with_attrs(&tok, tok, &attrs);
        if (attrs.is_static || attrs.is_extern || attrs.is_register || attrs.is_inline)
            error_at(tok->loc, "storage/function specifier is not allowed on a record member");
        for (bool first = true; !consume(&tok, tok, ";"); first = false) {''', 'record declspec attrs')
r = replace_once(r,
'''            m->name = strndup(ident->loc, ident->len);
            m->ty = mty;
            cur = cur->next = m;''',
'''            m->name = strndup(ident->loc, ident->len);
            m->ty = mty;
            m->align = validate_requested_alignment(mty, attrs.align, ident);
            cur = cur->next = m;''', 'member requested alignment')
r = r.replace('int ma = m->ty->align > 0 ? m->ty->align : 1;',
              'int ma = m->align > 0 ? m->align : (m->ty->align > 0 ? m->ty->align : 1);')
s = s[:rstart] + r + s[rend:]

# Replace declspec with an attribute-aware implementation. _Alignas is allowed
# only in true object/member declaration contexts; type names and parameters use
# the existing plain wrapper and therefore diagnose it.
s = replace_once(s,
'''static Type *declspec(Token **rest, Token *tok) {
    Type *ty = NULL;
    bool is_const = false;
    bool is_volatile = false;

    while (is_decl_start(tok)) {''',
'''static int parse_alignment_specifier(Token **rest, Token *tok) {
    Token *kw = tok;
    tok = skip(tok->next, "(");
    int align = 0;

    if (is_typename(tok) || equal(tok, "const") || equal(tok, "volatile")) {
        Type *aty = type_name(&tok, tok);
        if (!aty || aty->kind == TY_VOID || aty->kind == TY_FUNC ||
            is_incomplete_object_type(aty))
            error_at(kw->loc, "_Alignas type must be a complete object type");
        align = aty->align > 0 ? aty->align : 1;
    } else {
        Node *expr_node = ternary(&tok, tok);
        add_type(expr_node);
        if (!is_integer(expr_node->ty))
            error_at(kw->loc, "_Alignas requires an integer constant expression or type name");
        int64_t raw = eval_const_expr(expr_node);
        if (expr_node->ty->is_unsigned) {
            uint64_t value = (uint64_t)cast_const_integer(raw, expr_node->ty);
            if (value > INT32_MAX)
                error_at(kw->loc, "_Alignas value is out of range");
            align = (int)value;
        } else {
            int64_t value = cast_const_integer(raw, expr_node->ty);
            if (value < 0 || value > INT32_MAX)
                error_at(kw->loc, "_Alignas value is out of range");
            align = (int)value;
        }
    }

    tok = skip(tok, ")");
    if (align != 0 && ((align & (align - 1)) != 0 || align > 16))
        error_at(kw->loc, "unsupported _Alignas value; expected 0 or a power of two up to 16");
    *rest = tok;
    return align;
}

static int validate_requested_alignment(Type *ty, int requested, Token *at) {
    if (!requested)
        return 0;
    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)
        error_at(at->loc, "_Alignas may only be applied to an object type");
    int natural = ty->align > 0 ? ty->align : 1;
    if (requested < natural)
        error_at(at->loc, "_Alignas cannot weaken the natural alignment");
    return requested;
}

static void apply_object_alignment(Obj *var, Type *ty, int requested, Token *at) {
    requested = validate_requested_alignment(ty, requested, at);
    if (!requested)
        return;
    if (var->align && var->align != requested)
        error_at(at->loc, "conflicting _Alignas requirements for '%s'", var->name);
    var->align = requested;
}

static Type *declspec_impl(Token **rest, Token *tok, DeclAttrs *attrs) {
    Type *ty = NULL;
    bool is_const = false;
    bool is_volatile = false;

    while (is_decl_start(tok)) {
        if (equal(tok, "_Alignas")) {
            if (!attrs)
                error_at(tok->loc, "_Alignas is not allowed in this declaration context");
            int a = parse_alignment_specifier(&tok, tok);
            if (a > attrs->align)
                attrs->align = a;
            continue;
        }''', 'declspec implementation')

s = replace_once(s,
'''        if (consume(&tok, tok, "register") || consume(&tok, tok, "inline") ||
            consume(&tok, tok, "static") || consume(&tok, tok, "extern"))
            continue;
''',
'''        if (consume(&tok, tok, "register")) {
            if (attrs) attrs->is_register = true;
            continue;
        }
        if (consume(&tok, tok, "inline")) {
            if (attrs) attrs->is_inline = true;
            continue;
        }
        if (consume(&tok, tok, "static")) {
            if (attrs) attrs->is_static = true;
            continue;
        }
        if (consume(&tok, tok, "extern")) {
            if (attrs) attrs->is_extern = true;
            continue;
        }
''', 'storage attrs')

s = replace_once(s,
'''    ty = ty ? ty : ty_int;
    return qualify_type(ty, is_const, is_volatile);
}

static Type *adjust_param_type(Type *ty) {''',
'''    ty = ty ? ty : ty_int;
    return qualify_type(ty, is_const, is_volatile);
}

static Type *declspec(Token **rest, Token *tok) {
    return declspec_impl(rest, tok, NULL);
}

static Type *declspec_with_attrs(Token **rest, Token *tok, DeclAttrs *attrs) {
    *attrs = (DeclAttrs){};
    return declspec_impl(rest, tok, attrs);
}

static Type *adjust_param_type(Type *ty) {''', 'declspec wrappers')

# Local declarations now parse storage/alignment attributes in one order-agnostic
# pass instead of pre-consuming only a canonical prefix.
s = replace_once(s,
'''static Node *declaration(Token **rest, Token *tok, bool is_static, bool is_extern) {
    Type *basety = declspec(&tok, tok);
    if (equal(tok, ";")) {
        *rest = tok->next;
        return new_node(ND_EXPR_STMT);
    }
''',
'''static Node *declaration(Token **rest, Token *tok) {
    DeclAttrs attrs = {};
    Type *basety = declspec_with_attrs(&tok, tok, &attrs);
    bool is_static = attrs.is_static;
    bool is_extern = attrs.is_extern;
    if (is_static && is_extern)
        error_at(tok->loc, "declaration cannot be both static and extern");
    if (attrs.align && attrs.is_register)
        error_at(tok->loc, "_Alignas is not allowed on a register object");
    if (equal(tok, ";")) {
        if (attrs.align)
            error_at(tok->loc, "_Alignas requires an object declarator");
        *rest = tok->next;
        return new_node(ND_EXPR_STMT);
    }
''', 'local declaration attrs')

s = replace_once(s,
'''        Type *ty = declarator(&tok, tok, basety, &ident);
        bool inferable_array = is_unknown_bound_array_with_complete_element(ty) &&''',
'''        Type *ty = declarator(&tok, tok, basety, &ident);
        if (attrs.align && ty->kind == TY_FUNC)
            error_at(ident->loc, "_Alignas is not allowed on a function declaration");
        bool inferable_array = is_unknown_bound_array_with_complete_element(ty) &&''', 'local function align rejection')

s = replace_once(s,
'''        } else {
            var = create_lvar(name);
            var->ty = ty;
        }

        if (!equal(tok, "="))''',
'''        } else {
            var = create_lvar(name);
            var->ty = ty;
        }
        apply_object_alignment(var, ty, attrs.align, ident);

        if (!equal(tok, "="))''', 'apply local alignment')

# stmt()/for declarations no longer pre-consume storage specifiers.
s = replace_once(s,
'''        } else if (is_decl_start(tok)) {
            bool is_s = consume(&tok, tok, "static");
            bool is_e = consume(&tok, tok, "extern");
            consume(&tok, tok, "register");
            consume(&tok, tok, "inline");
            node->init = declaration(&tok, tok, is_s, is_e);
        } else {''',
'''        } else if (is_decl_start(tok)) {
            node->init = declaration(&tok, tok);
        } else {''', 'for declaration call')

s = replace_once(s,
'''    // Declaration (with optional static/extern)
    if (is_decl_start(tok)) {
        bool is_s = consume(&tok, tok, "static");
        bool is_e = consume(&tok, tok, "extern");
        consume(&tok, tok, "register");
        consume(&tok, tok, "inline");
        return declaration(rest, tok, is_s, is_e);
    }
''',
'''    // Declaration (storage classes, qualifiers and alignment specifiers may
    // appear in any declaration-specifier order).
    if (is_decl_start(tok))
        return declaration(rest, tok);
''', 'statement declaration call')

# File-scope declarations use the same attribute-aware declspec path.
s = replace_once(s,
'''        // Storage class specifiers
        bool is_static = consume(&tok, tok, "static");
        bool is_extern = consume(&tok, tok, "extern");
        consume(&tok, tok, "inline");

        Type *basety = declspec(&tok, tok);

        // Standalone type declaration
        if (consume(&tok, tok, ";"))
            continue;
''',
'''        DeclAttrs attrs = {};
        Type *basety = declspec_with_attrs(&tok, tok, &attrs);
        bool is_static = attrs.is_static;
        bool is_extern = attrs.is_extern;
        if (is_static && is_extern)
            error_at(tok->loc, "declaration cannot be both static and extern");
        if (attrs.is_register)
            error_at(tok->loc, "register storage class is not allowed at file scope");

        // Standalone type declaration
        if (consume(&tok, tok, ";")) {
            if (attrs.align)
                error_at(tok->loc, "_Alignas requires an object declarator");
            continue;
        }
''', 'file declaration attrs')

s = replace_once(s,
'''        Type *ty = declarator(&tok, tok, basety, &ident);

        if (ty->kind == TY_FUNC) {''',
'''        Type *ty = declarator(&tok, tok, basety, &ident);

        if (ty->kind == TY_FUNC) {
            if (attrs.align)
                error_at(ident->loc, "_Alignas is not allowed on a function declaration");''', 'file function align rejection')

s = replace_once(s,
'''                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);
                ty = var->ty;

                if (equal(tok, "=")''',
'''                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);
                apply_object_alignment(var, ty, attrs.align, ident);
                ty = var->ty;

                if (equal(tok, "=")''', 'apply global alignment')

p.write_text(s)

# codegen.c: honor explicit object alignment for data labels and stack locals.
p = Path('codegen.c')
s = p.read_text()
s = replace_once(s,
'''static void emit_data_alignment(Obj *var) {
    int align = var->ty && var->ty->align > 0 ? var->ty->align : 1;''',
'''static void emit_data_alignment(Obj *var) {
    int align = var->align > 0 ? var->align
                               : (var->ty && var->ty->align > 0 ? var->ty->align : 1);''', 'data alignment')
s = replace_once(s,
'''        for (Obj *var = fn->locals; var; var = var->next) {
            int align = var->ty->align > 0 ? var->ty->align : 1;''',
'''        for (Obj *var = fn->locals; var; var = var->next) {
            int align = var->align > 0 ? var->align
                                       : (var->ty->align > 0 ? var->ty->align : 1);''', 'local alignment')
p.write_text(s)

# Makefile
p = Path('Makefile')
s = p.read_text()
s = replace_once(s, '\tbash ./test/alignof.sh\n',
                    '\tbash ./test/alignof.sh\n\tbash ./test/alignas.sh\n', 'Makefile alignas test')
p.write_text(s)

# README: concise permanent capability note.
p = Path('README.md')
s = p.read_text()
needle = '- **Target**: x86-64 AT&T syntax assembly, Linux System V ABI\n'
if needle in s:
    s = s.replace(needle,
        '- **Alignment**: C11 `_Alignof` and `_Alignas` for object/member declarations, with explicit alignment carried through stack layout, static data emission, and record layout\n' + needle, 1)
else:
    s += '\n- C11 `_Alignas` object/member alignment is supported up to 16 bytes on the current x86-64 backend.\n'
p.write_text(s)

# Regression suite
Path('test/alignas.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-alignas.c
  "${MINICC:-./minicc}" tmp-alignas.c > tmp-alignas.s
  cc -o tmp-alignas tmp-alignas.s
  set +e
  ./tmp-alignas
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(_Alignas): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(_Alignas): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-alignas-reject.c
  if "${MINICC:-./minicc}" tmp-alignas-reject.c > /dev/null 2>&1; then
    echo "FAIL(_Alignas): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(_Alignas): rejected"
}

# File/static/local object alignment, including storage-class ordering.
assert_run 0 '_Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 'static _Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(16) static char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 'int main(void){_Alignas(16) char x; return (unsigned long)&x % 16;}'
assert_run 0 'int main(void){static _Alignas(16) char x; return (unsigned long)&x % 16;}'

# Type-name and integer-constant-expression forms, 0, and multiple specifiers.
assert_run 0 '_Alignas(double) char g; int main(void){return (unsigned long)&g % 8;}'
assert_run 0 'enum{A=16}; _Alignas(A) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(1<<4) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(0) char g; int main(void){return g;}'
assert_run 0 '_Alignas(8) _Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(16) char a,b; int main(void){return ((unsigned long)&a % 16) || ((unsigned long)&b % 16);}'

# Record/union member alignment participates in offsets, aggregate alignment and size.
assert_run 0 'struct S{char a; _Alignas(8) int b;}; int main(void){struct S s; return sizeof(struct S)!=16 || _Alignof(struct S)!=8 || (char*)&s.b-(char*)&s!=8;}'
assert_run 0 'union U{_Alignas(16) char c; long x;}; int main(void){return sizeof(union U)!=16 || _Alignof(union U)!=16;}'
assert_run 0 'struct S{_Alignas(double) char c; char d;}; int main(void){return sizeof(struct S)!=8 || _Alignof(struct S)!=8;}'

# Alignment survives compatible file-scope redeclarations, including omitted specifier.
assert_run 0 'extern _Alignas(16) char g; char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 'extern _Alignas(16) char g; _Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'

# Invalid values/contexts and conflicting declarations.
assert_reject '_Alignas(3) int x; int main(void){return 0;}'
assert_reject '_Alignas(32) char x; int main(void){return 0;}'
assert_reject '_Alignas(2) int x; int main(void){return 0;}'
assert_reject 'int n=8; _Alignas(n) char x; int main(void){return 0;}'
assert_reject '_Alignas(1.5) char x; int main(void){return 0;}'
assert_reject '_Alignas(void) char x; int main(void){return 0;}'
assert_reject '_Alignas(int(void)) char x; int main(void){return 0;}'
assert_reject '_Alignas(16) int f(void); int main(void){return 0;}'
assert_reject 'int f(_Alignas(16) int x){return x;}'
assert_reject 'typedef _Alignas(16) int T; int main(void){return 0;}'
assert_reject 'int main(void){_Alignas(16) register char x; return 0;}'
assert_reject 'extern _Alignas(8) char g; _Alignas(16) char g; int main(void){return 0;}'
assert_reject 'struct S{_Alignas(1) int x;}; int main(void){return 0;}'

echo 'All _Alignas tests passed!'
''')
