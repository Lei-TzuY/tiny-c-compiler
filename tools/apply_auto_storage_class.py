from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:140]!r}")
    p.write_text(text.replace(old, new, 1))


if Path("test/storage_class_specifiers.sh").exists():
    print("auto/storage-class migration already applied")
    raise SystemExit(0)

# Track auto plus the number of explicit storage-class specifiers so duplicate
# or mixed classes are diagnosed uniformly during declaration-specifier parsing.
replace_once(
    "parse.c",
    '''typedef struct {
    bool is_static;
    bool is_extern;
    bool is_register;
    bool is_inline;
    bool is_noreturn;
    int align;
} DeclAttrs;
''',
    '''typedef struct {
    bool is_auto;
    bool is_static;
    bool is_extern;
    bool is_register;
    bool is_inline;
    bool is_noreturn;
    int storage_class_count;
    int align;
} DeclAttrs;
''',
)

replace_once(
    "parse.c",
    '''    if (equal(tok, "static") || equal(tok, "extern")) return true;
''',
    '''    if (equal(tok, "auto") || equal(tok, "static") || equal(tok, "extern")) return true;
''',
)

replace_once(
    "parse.c",
    '''static Type *declspec_impl(Token **rest, Token *tok, DeclAttrs *attrs) {
''',
    '''static void note_storage_class(DeclAttrs *attrs, Token *tok) {
    if (!attrs)
        error_at(tok->loc,
                 "storage class specifier is not allowed in this declaration context");
    attrs->storage_class_count++;
    if (attrs->storage_class_count > 1)
        error_at(tok->loc, "multiple storage class specifiers in one declaration");
}

static Type *declspec_impl(Token **rest, Token *tok, DeclAttrs *attrs) {
''',
)

replace_once(
    "parse.c",
    '''        if (consume(&tok, tok, "register")) {
            if (attrs) attrs->is_register = true;
            continue;
        }
        if (consume(&tok, tok, "inline")) {
            if (attrs) attrs->is_inline = true;
            continue;
        }
        Token *noreturn_tok = tok;
        if (consume(&tok, tok, "_Noreturn")) {
            if (!attrs)
                error_at(noreturn_tok->loc,
                         "_Noreturn is only allowed in a function declaration");
            attrs->is_noreturn = true;
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
''',
    '''        Token *storage_tok = tok;
        if (consume(&tok, tok, "auto")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_auto = true;
            continue;
        }
        storage_tok = tok;
        if (consume(&tok, tok, "register")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_register = true;
            continue;
        }
        Token *inline_tok = tok;
        if (consume(&tok, tok, "inline")) {
            if (!attrs)
                error_at(inline_tok->loc,
                         "inline is only allowed in a function declaration");
            attrs->is_inline = true;
            continue;
        }
        Token *noreturn_tok = tok;
        if (consume(&tok, tok, "_Noreturn")) {
            if (!attrs)
                error_at(noreturn_tok->loc,
                         "_Noreturn is only allowed in a function declaration");
            attrs->is_noreturn = true;
            continue;
        }
        storage_tok = tok;
        if (consume(&tok, tok, "static")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_static = true;
            continue;
        }
        storage_tok = tok;
        if (consume(&tok, tok, "extern")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_extern = true;
            continue;
        }
''',
)

# Record members cannot carry storage or function specifiers.
replace_once(
    "parse.c",
    '''        if (attrs.is_static || attrs.is_extern || attrs.is_register || attrs.is_inline ||
            attrs.is_noreturn)
''',
    '''        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||
            attrs.is_inline || attrs.is_noreturn)
''',
)

# Parameter declarations may use register, but no other storage class and no
# function/alignment specifiers. Preserve PR #89's parameter-array declarator
# mode when parsing the adjusted parameter type.
replace_once(
    "parse.c",
    '''        Type *basety = declspec(&tok, tok);
        Token *name = NULL;
        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true, true);
''',
    '''        DeclAttrs param_attrs = {};
        Token *param_spec = tok;
        Type *basety = declspec_with_attrs(&tok, tok, &param_attrs);
        if (param_attrs.storage_class_count && !param_attrs.is_register)
            error_at(param_spec->loc,
                     "only register storage class is allowed on a parameter");
        if (param_attrs.is_inline || param_attrs.is_noreturn)
            error_at(param_spec->loc,
                     "function specifier is not allowed on a parameter");
        if (param_attrs.align)
            error_at(param_spec->loc, "_Alignas is not allowed on a parameter");
        Token *name = NULL;
        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true, true);
''',
)

# Block-scope declaration constraints. auto is the ordinary automatic-object
# storage class. Explicit storage classes without a declarator are rejected,
# and a block-scope function may only use extern explicitly.
replace_once(
    "parse.c",
    '''    if (equal(tok, ";")) {
        if (attrs.align)
            error_at(tok->loc, "_Alignas requires an object declarator");
        if (attrs.is_noreturn)
            error_at(tok->loc, "_Noreturn requires a function declarator");
        *rest = tok->next;
''',
    '''    if (equal(tok, ";")) {
        if (attrs.storage_class_count)
            error_at(tok->loc, "storage class specifier requires a declarator");
        if (attrs.align)
            error_at(tok->loc, "_Alignas requires an object declarator");
        if (attrs.is_inline || attrs.is_noreturn)
            error_at(tok->loc, "function specifier requires a function declarator");
        *rest = tok->next;
''',
)

replace_once(
    "parse.c",
    '''        if (attrs.is_noreturn && ty->kind != TY_FUNC)
            error_at(ident->loc, "_Noreturn may only declare a function");
''',
    '''        if ((attrs.is_inline || attrs.is_noreturn) && ty->kind != TY_FUNC)
            error_at(ident->loc, "function specifier may only declare a function");
''',
)

replace_once(
    "parse.c",
    '''        if (ty->kind == TY_FUNC) {
            if (is_static)
                error_at(ident->loc, "block-scope function declaration cannot be static");
            var = create_extern_ref(name, ty);
''',
    '''        if (ty->kind == TY_FUNC) {
            if (attrs.is_auto || attrs.is_register || is_static)
                error_at(ident->loc,
                         "block-scope function declaration may only use extern storage class");
            var = create_extern_ref(name, ty);
''',
)

# File-scope constraints: auto/register are invalid, explicit storage class on
# a standalone declaration is invalid, and function specifiers cannot qualify
# objects.
replace_once(
    "parse.c",
    '''        if (attrs.is_register)
            error_at(tok->loc, "register storage class is not allowed at file scope");
''',
    '''        if (attrs.is_auto)
            error_at(tok->loc, "auto storage class is not allowed at file scope");
        if (attrs.is_register)
            error_at(tok->loc, "register storage class is not allowed at file scope");
''',
)

replace_once(
    "parse.c",
    '''        if (consume(&tok, tok, ";")) {
            if (attrs.align)
                error_at(tok->loc, "_Alignas requires an object declarator");
            if (attrs.is_noreturn)
                error_at(tok->loc, "_Noreturn requires a function declarator");
            continue;
        }
''',
    '''        if (consume(&tok, tok, ";")) {
            if (attrs.storage_class_count)
                error_at(tok->loc, "storage class specifier requires a declarator");
            if (attrs.align)
                error_at(tok->loc, "_Alignas requires an object declarator");
            if (attrs.is_inline || attrs.is_noreturn)
                error_at(tok->loc, "function specifier requires a function declarator");
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''        Type *ty = declarator(&tok, tok, basety, &ident);

        if (ty->kind == TY_FUNC) {
''',
    '''        Type *ty = declarator(&tok, tok, basety, &ident);
        if ((attrs.is_inline || attrs.is_noreturn) && ty->kind != TY_FUNC)
            error_at(ident->loc, "function specifier may only declare a function");

        if (ty->kind == TY_FUNC) {
''',
)

# Tokenizer keyword support.
replace_once(
    "tokenize.c",
    '                         "static", "extern", "const", "volatile", "restrict",\n',
    '                         "auto", "static", "extern", "const", "volatile", "restrict",\n',
)

# Documentation and test integration.
replace_once(
    "README.md",
    '- **Declarations**: C11 `_Noreturn` function declarations',
    '- **Declarations**: block-scope `auto` objects with single-storage-class constraint checking, C11 `_Noreturn` function declarations',
)
replace_once(
    "Makefile",
    '\tbash ./test/restrict_qualifier.sh\n',
    '\tbash ./test/restrict_qualifier.sh\n\tbash ./test/storage_class_specifiers.sh\n',
)

Path("test/storage_class_specifiers.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-storage.c
  ./minicc tmp-storage.c > tmp-storage.s
  cc -o tmp-storage tmp-storage.s
  set +e
  ./tmp-storage
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(storage class): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-storage.c
  ./minicc tmp-storage.c > tmp-storage.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-storage-bad.c
  if ./minicc tmp-storage-bad.c > /dev/null 2>tmp-storage.err; then
    echo "FAIL(storage class): expected rejection"
    echo "$input"
    exit 1
  fi
}

# auto is a block-scope object storage class and composes with ordinary type
# specifiers/qualifiers in declaration-specifier order.
assert_run 3 'int main(void){auto int x=3;return x;}'
assert_run 4 'int main(void){int auto x=4;return x;}'
assert_run 5 'int main(void){auto const int x=5;return x;}'
assert_run 10 'int main(void){int s=0;for(auto int i=0;i<5;i++)s+=i;return s;}'
assert_run 7 'int main(void){struct S{int x;};auto struct S s={7};return s.x;}'
assert_run 9 'int main(void){auto int a=4,b=5;return a+b;}'

# register remains the one storage class permitted on parameters.
assert_run 7 'int f(register int x){return x;}int main(void){return f(7);}'
assert_compile 'int f(register int);int f(int);int main(void){return 0;}'

# Existing valid linkage/storage forms remain accepted.
assert_run 6 'int g=6;int main(void){extern int g;return g;}'
assert_run 3 'int main(void){static int x=3;return x;}'
assert_run 4 'inline int f(void){return 4;}int main(void){return f();}'
assert_compile 'int f(void);int main(void){inline int f(void);return 0;}'

# auto is not valid at file scope, on functions, parameters, or record members.
assert_reject 'auto int x;int main(void){return 0;}'
assert_reject 'int main(void){auto int f(void);return 0;}'
assert_reject 'int f(auto int x){return x;}int main(void){return 0;}'
assert_reject 'int f(static int x);int main(void){return 0;}'
assert_reject 'int f(extern int x);int main(void){return 0;}'
assert_reject 'struct S{auto int x;};int main(void){return 0;}'

# At most one storage-class specifier may occur in a declaration, including
# duplicate spellings of the same class.
assert_reject 'int main(void){auto register int x;return 0;}'
assert_reject 'int main(void){auto static int x;return 0;}'
assert_reject 'int main(void){auto extern int x;return 0;}'
assert_reject 'int main(void){static register int x;return 0;}'
assert_reject 'int main(void){extern register int x;return 0;}'
assert_reject 'int main(void){static extern int x;return 0;}'
assert_reject 'int main(void){auto auto int x;return 0;}'
assert_reject 'int main(void){register register int x;return 0;}'
assert_reject 'static static int x;int main(void){return 0;}'
assert_reject 'extern extern int x;int main(void){return 0;}'

# typedef is itself a storage class; a second storage class after typedef must
# not be silently swallowed by declspec parsing.
assert_reject 'typedef auto int T;int main(void){return 0;}'
assert_reject 'typedef static int T;int main(void){return 0;}'
assert_reject 'typedef register int T;int main(void){return 0;}'
assert_reject 'typedef extern int T;int main(void){return 0;}'
assert_reject 'int main(void){typedef auto int T;return 0;}'

# Function specifiers are valid only on function identifiers, not objects,
# parameters, record members, or typedef/type-name contexts.
assert_reject 'inline int x;int main(void){return 0;}'
assert_reject 'int main(void){inline int x;return 0;}'
assert_reject 'int f(inline int x);int main(void){return 0;}'
assert_reject 'struct S{inline int x;};int main(void){return 0;}'
assert_reject 'typedef inline int F(void);int main(void){return 0;}'

# Explicit storage classes require a declarator rather than an empty type-only
# declaration.
assert_reject 'int main(void){auto int;return 0;}'
assert_reject 'int main(void){register int;return 0;}'
assert_reject 'static int;int main(void){return 0;}'
assert_reject 'extern int;int main(void){return 0;}'

rm -f tmp-storage.c tmp-storage.s tmp-storage \
      tmp-storage-bad.c tmp-storage.err

echo 'All storage-class specifier tests passed!'
''')

print("auto/storage-class migration applied")
