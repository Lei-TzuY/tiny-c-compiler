from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:160]!r}")
    p.write_text(text.replace(old, new, 1))


if Path("test/type_specifier_combinations.sh").exists():
    print("type-specifier validation migration already applied")
    raise SystemExit(0)

replace_once(
    "parse.c",
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
    '''static void note_storage_class(DeclAttrs *attrs, Token *tok) {
    if (!attrs)
        error_at(tok->loc,
                 "storage class specifier is not allowed in this declaration context");
    attrs->storage_class_count++;
    if (attrs->storage_class_count > 1)
        error_at(tok->loc, "multiple storage class specifiers in one declaration");
}

typedef struct {
    Token *first;
    int n_bool;
    int n_float;
    int n_double;
    int n_char;
    int n_void;
    int n_short;
    int n_int;
    int n_long;
    int n_named;
} TypeSpecState;

static void mark_type_specifier(TypeSpecState *state, Token *tok) {
    if (!state->first)
        state->first = tok;
}

static void note_type_specifier(TypeSpecState *state, Token *tok, int *counter) {
    mark_type_specifier(state, tok);
    (*counter)++;
}

static void invalid_type_specifier_set(TypeSpecState *state) {
    error_at(state->first->loc, "invalid type specifier combination");
}

static void validate_type_specifier_set(TypeSpecState *state,
                                        bool saw_signed, bool saw_unsigned) {
    if (!state->first)
        return; // Preserve this compiler's existing implicit-int behavior.

    if (state->n_bool > 1 || state->n_float > 1 || state->n_double > 1 ||
        state->n_char > 1 || state->n_void > 1 || state->n_short > 1 ||
        state->n_int > 1 || state->n_long > 2 || state->n_named > 1)
        invalid_type_specifier_set(state);

    bool has_sign = saw_signed || saw_unsigned;
    int integer_specs = state->n_short + state->n_int + state->n_long;
    int primitive_specs = state->n_bool + state->n_float + state->n_double +
                          state->n_char + state->n_void + integer_specs;

    if (state->n_named) {
        if (primitive_specs || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_void) {
        if (primitive_specs != 1 || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_bool) {
        if (primitive_specs != 1 || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_char) {
        if (state->n_float || state->n_double || state->n_void || state->n_bool ||
            integer_specs)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_float) {
        if (primitive_specs != 1 || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_double) {
        if (state->n_bool || state->n_float || state->n_char || state->n_void ||
            state->n_short || state->n_int || has_sign || state->n_long > 1)
            invalid_type_specifier_set(state);
        if (state->n_long == 1)
            error_at(state->first->loc, "long double is not supported by this target");
        return;
    }

    // Remaining legal spellings are the signed/unsigned integer family:
    // [signed|unsigned] [short|long|long long] [int], in any order.
    if (state->n_short && state->n_long)
        invalid_type_specifier_set(state);
}

static Type *declspec_impl(Token **rest, Token *tok, DeclAttrs *attrs) {
''',
)

replace_once(
    "parse.c",
    '''    Token *restrict_tok = NULL;
    bool saw_signed = false;
''',
    '''    Token *restrict_tok = NULL;
    TypeSpecState specs = {};
    bool saw_signed = false;
''',
)

replace_once(
    "parse.c",
    '''        if (consume(&tok, tok, "_Bool"))  { saw_non_signable_type = true; ty = ty_bool; continue; }
        if (consume(&tok, tok, "float"))  { saw_non_signable_type = true; ty = ty_float; continue; }
        if (consume(&tok, tok, "double")) { saw_non_signable_type = true; ty = ty_double; continue; }
        if (consume(&tok, tok, "char")) {
            if (saw_unsigned || (ty && ty->is_unsigned))
                ty = ty_uchar;
            else if (saw_signed)
                ty = ty_schar;
            else
                ty = ty_char;
            continue;
        }
        if (consume(&tok, tok, "void"))   { saw_non_signable_type = true; ty = ty_void; continue; }
        if (consume(&tok, tok, "short"))  { ty = (ty && ty->is_unsigned) ? ty_ushort : ty_short; continue; }
''',
    '''        Token *base_tok = tok;
        if (consume(&tok, tok, "_Bool")) {
            note_type_specifier(&specs, base_tok, &specs.n_bool);
            saw_non_signable_type = true;
            ty = ty_bool;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "float")) {
            note_type_specifier(&specs, base_tok, &specs.n_float);
            saw_non_signable_type = true;
            ty = ty_float;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "double")) {
            note_type_specifier(&specs, base_tok, &specs.n_double);
            saw_non_signable_type = true;
            ty = ty_double;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "char")) {
            note_type_specifier(&specs, base_tok, &specs.n_char);
            if (saw_unsigned || (ty && ty->is_unsigned))
                ty = ty_uchar;
            else if (saw_signed)
                ty = ty_schar;
            else
                ty = ty_char;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "void")) {
            note_type_specifier(&specs, base_tok, &specs.n_void);
            saw_non_signable_type = true;
            ty = ty_void;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "short")) {
            note_type_specifier(&specs, base_tok, &specs.n_short);
            ty = (ty && ty->is_unsigned) ? ty_ushort : ty_short;
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''        if (consume(&tok, tok, "long")) {
            bool already_long = ty == ty_long || ty == ty_ulong;
            bool already_llong = ty == ty_llong || ty == ty_ullong;
            bool adjacent_long = consume(&tok, tok, "long");
            if (already_llong)
                error_at(tok->loc, "too many 'long' specifiers");
            consume(&tok, tok, "int");
            bool is_unsigned = ty && ty->is_unsigned;
            bool is_llong = already_long || adjacent_long;
            ty = is_llong ? (is_unsigned ? ty_ullong : ty_llong)
                          : (is_unsigned ? ty_ulong : ty_long);
            continue;
        }
''',
    '''        Token *long_tok = tok;
        if (consume(&tok, tok, "long")) {
            note_type_specifier(&specs, long_tok, &specs.n_long);
            bool already_long = ty == ty_long || ty == ty_ulong;
            bool already_llong = ty == ty_llong || ty == ty_ullong;
            Token *second_long_tok = tok;
            bool adjacent_long = consume(&tok, tok, "long");
            if (adjacent_long)
                note_type_specifier(&specs, second_long_tok, &specs.n_long);
            if (already_llong)
                error_at(tok->loc, "too many 'long' specifiers");
            Token *long_int_tok = tok;
            if (consume(&tok, tok, "int"))
                note_type_specifier(&specs, long_int_tok, &specs.n_int);
            bool is_unsigned = ty && ty->is_unsigned;
            bool is_llong = already_long || adjacent_long;
            ty = is_llong ? (is_unsigned ? ty_ullong : ty_llong)
                          : (is_unsigned ? ty_ulong : ty_long);
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''        Token *sign_tok = tok;
        if (consume(&tok, tok, "signed")) {
            if (saw_signed)
''',
    '''        Token *sign_tok = tok;
        if (consume(&tok, tok, "signed")) {
            mark_type_specifier(&specs, sign_tok);
            if (saw_signed)
''',
)

replace_once(
    "parse.c",
    '''        sign_tok = tok;
        if (consume(&tok, tok, "unsigned")) {
            if (saw_unsigned)
''',
    '''        sign_tok = tok;
        if (consume(&tok, tok, "unsigned")) {
            mark_type_specifier(&specs, sign_tok);
            if (saw_unsigned)
''',
)

replace_once(
    "parse.c",
    '''        if (consume(&tok, tok, "int")) {
            if (!ty) ty = ty_int;
            continue;
        }
''',
    '''        Token *int_tok = tok;
        if (consume(&tok, tok, "int")) {
            note_type_specifier(&specs, int_tok, &specs.n_int);
            if (!ty) ty = ty_int;
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''        if (equal(tok, "union")) {
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, true);
            continue;
        }

        if (equal(tok, "struct")) {
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, false);
            continue;
        }

        if (equal(tok, "enum")) {
            saw_non_signable_type = true;
            ty = enum_decl(&tok, tok->next);
            continue;
        }
''',
    '''        if (equal(tok, "union")) {
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, true);
            continue;
        }

        if (equal(tok, "struct")) {
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, false);
            continue;
        }

        if (equal(tok, "enum")) {
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
            ty = enum_decl(&tok, tok->next);
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''            TypeDef *td = find_typedef(tok);
            if (td) {
                tok = tok->next;
                ty = td->ty;
                saw_typedef_type = true;
                continue;
            }
''',
    '''            TypeDef *td = find_typedef(tok);
            if (td) {
                note_type_specifier(&specs, tok, &specs.n_named);
                tok = tok->next;
                ty = td->ty;
                saw_typedef_type = true;
                continue;
            }
''',
)

replace_once(
    "parse.c",
    '''    if ((saw_signed || saw_unsigned) && saw_non_signable_type)
        error_at(sign_spec->loc, "signed/unsigned type specifier requires an integer base type");
    if (is_restrict && !is_restrict_qualifiable_type(ty))
''',
    '''    if ((saw_signed || saw_unsigned) && saw_non_signable_type)
        error_at(sign_spec->loc, "signed/unsigned type specifier requires an integer base type");
    validate_type_specifier_set(&specs, saw_signed, saw_unsigned);
    if (is_restrict && !is_restrict_qualifiable_type(ty))
''',
)

replace_once(
    "README.md",
    '- **Declarations**: block-scope `auto` objects with single-storage-class constraint checking, C11 `_Noreturn` function declarations',
    '- **Declarations**: validated C type-specifier sets (including order-independent signed/unsigned integer forms and explicit rejection of unsupported `long double`), block-scope `auto` objects with single-storage-class constraint checking, C11 `_Noreturn` function declarations',
)

replace_once(
    "Makefile",
    '\tbash ./test/signed_specifiers.sh\n',
    '\tbash ./test/signed_specifiers.sh\n\tbash ./test/type_specifier_combinations.sh\n',
)

Path("test/type_specifier_combinations.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-typespec.c
  ./minicc tmp-typespec.c > tmp-typespec.s
  cc -o tmp-typespec tmp-typespec.s
  set +e
  ./tmp-typespec
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(type specifiers): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-typespec.c
  ./minicc tmp-typespec.c > tmp-typespec.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-typespec-bad.c
  if ./minicc tmp-typespec-bad.c > /dev/null 2>tmp-typespec.err; then
    echo "FAIL(type specifiers): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Legal integer specifier sets remain order-independent.
assert_run 1 'int main(void){signed char x=-1;return x<0;}'
assert_run 1 'int main(void){char signed x=-1;return x<0;}'
assert_run 1 'int main(void){unsigned char x=255;return x>0;}'
assert_run 2 'int main(void){short int x=2;return x;}'
assert_run 3 'int main(void){int short x=3;return x;}'
assert_run 4 'int main(void){signed short int x=4;return x;}'
assert_run 5 'int main(void){short unsigned int x=5;return x;}'
assert_run 6 'int main(void){long int x=6;return x;}'
assert_run 7 'int main(void){int long x=7;return x;}'
assert_run 8 'int main(void){long long int x=8;return x;}'
assert_run 9 'int main(void){long int long x=9;return x;}'
assert_run 10 'int main(void){unsigned long long int x=10;return x;}'
assert_run 11 'int main(void){long unsigned int long x=11;return x;}'
assert_run 12 'int main(void){signed x=12;return x;}'
assert_run 13 'int main(void){unsigned x=13;return x;}'
assert_run 14 'int main(void){short x=14;return x;}'
assert_run 15 'int main(void){long x=15;return x;}'
assert_run 16 'int main(void){long long x=16;return x;}'

# Typedef-name/declarator disambiguation must survive stricter validation.
assert_run 17 'typedef int T;int main(void){T T=17;return T;}'
assert_run 18 'typedef char T;int main(void){int T=18;return T;}'
assert_compile 'typedef unsigned long U;const U x=1;int main(void){return 0;}'

# Duplicate primitive base specifiers are not legal C type-specifier sets.
assert_reject 'int int x;int main(void){return 0;}'
assert_reject 'char char x;int main(void){return 0;}'
assert_reject 'short short x;int main(void){return 0;}'
assert_reject 'float float x;int main(void){return 0;}'
assert_reject 'double double x;int main(void){return 0;}'
assert_reject 'void void f(void);int main(void){return 0;}'
assert_reject '_Bool _Bool x;int main(void){return 0;}'

# Incompatible primitive families must not silently overwrite one another.
assert_reject 'int char x;int main(void){return 0;}'
assert_reject 'char int x;int main(void){return 0;}'
assert_reject 'short char x;int main(void){return 0;}'
assert_reject 'char short x;int main(void){return 0;}'
assert_reject 'short double x;int main(void){return 0;}'
assert_reject 'double short x;int main(void){return 0;}'
assert_reject 'long float x;int main(void){return 0;}'
assert_reject 'float long x;int main(void){return 0;}'
assert_reject 'long _Bool x;int main(void){return 0;}'
assert_reject '_Bool long x;int main(void){return 0;}'
assert_reject 'long void x;int main(void){return 0;}'
assert_reject 'void long x;int main(void){return 0;}'
assert_reject 'int double x;int main(void){return 0;}'
assert_reject 'double int x;int main(void){return 0;}'
assert_reject 'short long x;int main(void){return 0;}'
assert_reject 'long short x;int main(void){return 0;}'
assert_reject 'long long long x;int main(void){return 0;}'

# long double is valid C, but this backend has no long-double representation;
# diagnose it explicitly rather than compiling it with double semantics.
assert_reject 'long double x;int main(void){return 0;}'
assert_reject 'double long x;int main(void){return 0;}'
assert_reject 'long long double x;int main(void){return 0;}'

# Named/typedef types cannot be combined with another type-specifier family.
assert_reject 'struct S{int x;};struct S int y;int main(void){return 0;}'
assert_reject 'struct A{int x;};struct B{int y;};struct A struct B z;int main(void){return 0;}'
assert_reject 'enum E{A};enum E int x;int main(void){return 0;}'
assert_reject 'typedef int T;T int x;int main(void){return 0;}'
assert_reject 'typedef int T;T double x;int main(void){return 0;}'

# Signedness cannot qualify non-integer families.
assert_reject 'signed float x;int main(void){return 0;}'
assert_reject 'unsigned double x;int main(void){return 0;}'
assert_reject 'signed _Bool x;int main(void){return 0;}'
assert_reject 'unsigned void f(void);int main(void){return 0;}'

rm -f tmp-typespec.c tmp-typespec.s tmp-typespec \
      tmp-typespec-bad.c tmp-typespec.err

echo 'All type-specifier combination tests passed!'
''')

print("type-specifier validation migration applied")
