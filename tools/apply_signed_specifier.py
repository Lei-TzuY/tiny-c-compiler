from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1))


if Path("test/signed_specifiers.sh").exists():
    print("signed specifier migration already applied")
    raise SystemExit(0)

replace_once(
    "tokenize.c",
    '                         "short", "long", "unsigned", "goto",\n',
    '                         "short", "long", "signed", "unsigned", "goto",\n',
)

replace_once(
    "parse.c",
    '        equal(tok, "short") || equal(tok, "long") || equal(tok, "unsigned") ||\n',
    '        equal(tok, "short") || equal(tok, "long") || equal(tok, "signed") ||\n'
    '        equal(tok, "unsigned") ||\n',
)

replace_once(
    "parse.c",
    '    Type *ty = NULL;\n'
    '    bool is_const = false;\n'
    '    bool is_volatile = false;\n',
    '    Type *ty = NULL;\n'
    '    bool is_const = false;\n'
    '    bool is_volatile = false;\n'
    '    bool saw_signed = false;\n'
    '    bool saw_unsigned = false;\n'
    '    bool saw_non_signable_type = false;\n'
    '    bool saw_typedef_type = false;\n'
    '    Token *sign_spec = NULL;\n',
)

for spelling, replacement in [
    ('if (consume(&tok, tok, "_Bool"))  { ty = ty_bool; continue; }',
     'if (consume(&tok, tok, "_Bool"))  { saw_non_signable_type = true; ty = ty_bool; continue; }'),
    ('if (consume(&tok, tok, "float"))  { ty = ty_float; continue; }',
     'if (consume(&tok, tok, "float"))  { saw_non_signable_type = true; ty = ty_float; continue; }'),
    ('if (consume(&tok, tok, "double")) { ty = ty_double; continue; }',
     'if (consume(&tok, tok, "double")) { saw_non_signable_type = true; ty = ty_double; continue; }'),
    ('if (consume(&tok, tok, "void"))   { ty = ty_void; continue; }',
     'if (consume(&tok, tok, "void"))   { saw_non_signable_type = true; ty = ty_void; continue; }'),
]:
    replace_once("parse.c", spelling, replacement)

old_unsigned = '''        if (consume(&tok, tok, "unsigned")) {
            if (ty == ty_char) ty = ty_uchar;
            else if (ty == ty_short) ty = ty_ushort;
            else if (ty == ty_long) ty = ty_ulong;
            else if (ty == ty_llong) ty = ty_ullong;
            else ty = ty_uint;
            continue;
        }
'''
new_unsigned = '''        Token *sign_tok = tok;
        if (consume(&tok, tok, "signed")) {
            if (saw_signed)
                error_at(sign_tok->loc, "duplicate 'signed' type specifier");
            if (saw_unsigned)
                error_at(sign_tok->loc, "cannot combine 'signed' and 'unsigned'");
            if (saw_non_signable_type || saw_typedef_type)
                error_at(sign_tok->loc, "invalid type specifier combination with 'signed'");
            saw_signed = true;
            sign_spec = sign_tok;
            if (!ty)
                ty = ty_int;
            else if (ty != ty_int && ty != ty_char && ty != ty_short &&
                     ty != ty_long && ty != ty_llong)
                error_at(sign_tok->loc, "invalid type specifier combination with 'signed'");
            continue;
        }

        sign_tok = tok;
        if (consume(&tok, tok, "unsigned")) {
            if (saw_unsigned)
                error_at(sign_tok->loc, "duplicate 'unsigned' type specifier");
            if (saw_signed)
                error_at(sign_tok->loc, "cannot combine 'signed' and 'unsigned'");
            if (saw_non_signable_type || saw_typedef_type)
                error_at(sign_tok->loc, "invalid type specifier combination with 'unsigned'");
            saw_unsigned = true;
            sign_spec = sign_tok;
            if (ty == ty_char) ty = ty_uchar;
            else if (ty == ty_short) ty = ty_ushort;
            else if (ty == ty_long) ty = ty_ulong;
            else if (ty == ty_llong) ty = ty_ullong;
            else if (!ty || ty == ty_int) ty = ty_uint;
            else error_at(sign_tok->loc, "invalid type specifier combination with 'unsigned'");
            continue;
        }
'''
replace_once("parse.c", old_unsigned, new_unsigned)

replace_once(
    "parse.c",
    '''        if (equal(tok, "union")) {
            ty = record_decl(&tok, tok->next, true);
            continue;
        }

        if (equal(tok, "struct")) {
            ty = record_decl(&tok, tok->next, false);
            continue;
        }

        if (equal(tok, "enum")) {
            ty = enum_decl(&tok, tok->next);
            continue;
        }
''',
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
)

replace_once(
    "parse.c",
    '''            if (td) {
                tok = tok->next;
                ty = td->ty;
                continue;
            }
''',
    '''            if (td) {
                tok = tok->next;
                ty = td->ty;
                saw_typedef_type = true;
                continue;
            }
''',
)

replace_once(
    "parse.c",
    '''    *rest = tok;
    ty = ty ? ty : ty_int;
    return qualify_type(ty, is_const, is_volatile);
''',
    '''    *rest = tok;
    ty = ty ? ty : ty_int;
    if ((saw_signed || saw_unsigned) && saw_non_signable_type)
        error_at(sign_spec->loc, "signed/unsigned type specifier requires an integer base type");
    return qualify_type(ty, is_const, is_volatile);
''',
)

replace_once(
    "README.md",
    '`struct`, `union`, tagged `enum`, `typedef`, `unsigned`, typed integer literal suffixes',
    '`struct`, `union`, tagged `enum`, `typedef`, `signed`/`unsigned` integer type specifiers, typed integer literal suffixes',
)

replace_once(
    "Makefile",
    '\tbash ./test/integer_literals.sh\n',
    '\tbash ./test/integer_literals.sh\n\tbash ./test/signed_specifiers.sh\n',
)

Path("test/signed_specifiers.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-signed.c
  ./minicc tmp-signed.c > tmp-signed.s
  cc -o tmp-signed tmp-signed.s
  set +e
  ./tmp-signed
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(signed specifier): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-signed-bad.c
  if ./minicc tmp-signed-bad.c > /dev/null 2>tmp-signed.err; then
    echo "FAIL(signed specifier): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Every standard signed integer spelling is accepted in either legal order.
assert_run 0 'int main(void){ signed a=-1; signed int b=-2; int signed c=-3; return !(a<0 && b<0 && c<0); }'
assert_run 0 'int main(void){ signed char a=-1; char signed b=-2; return !(a<0 && b<0 && sizeof(a)==1); }'
assert_run 0 'int main(void){ signed short a=-1; short signed b=-2; return !(a<0 && b<0 && sizeof(a)==2); }'
assert_run 0 'int main(void){ signed long a=-1; long signed b=-2; return !(a<0 && b<0 && sizeof(a)==8); }'
assert_run 0 'int main(void){ signed long long a=-1; long long signed b=-2; return !(a<0 && b<0 && sizeof(a)==8); }'

# Type identity for the ranked signed integer types is observable through _Generic.
assert_run 0 'int main(void){ signed x=0; signed short s=0; signed long l=0; signed long long ll=0; if(!_Generic(x,int:1,default:0))return 1; if(!_Generic(s,short:1,default:0))return 2; if(!_Generic(l,long:1,default:0))return 3; if(!_Generic(ll,long long:1,default:0))return 4; return 0; }'

# Signed spellings compose with typedef declarations, parameters, pointers and qualifiers.
assert_run 0 'typedef signed long SL; signed add(signed a, signed b){return a+b;} int main(void){ const signed int x=-3; signed int *p=(signed int *)&x; SL y=-4; return !(*p==-3 && y<0 && add(2,3)==5); }'

# Sign specifiers cannot conflict, repeat, qualify non-integer base types, or follow typedef type names.
assert_reject 'signed unsigned int x; int main(void){return 0;}'
assert_reject 'unsigned signed int x; int main(void){return 0;}'
assert_reject 'signed signed int x; int main(void){return 0;}'
assert_reject 'unsigned unsigned int x; int main(void){return 0;}'
assert_reject 'signed float x; int main(void){return 0;}'
assert_reject 'float signed x; int main(void){return 0;}'
assert_reject 'signed double x; int main(void){return 0;}'
assert_reject 'signed _Bool x; int main(void){return 0;}'
assert_reject 'signed void *p; int main(void){return 0;}'
assert_reject 'struct S{int x;}; signed struct S x; int main(void){return 0;}'
assert_reject 'enum E{A}; enum E signed x; int main(void){return 0;}'
assert_reject 'typedef int I; I signed x; int main(void){return 0;}'

rm -f tmp-signed.c tmp-signed.s tmp-signed tmp-signed-bad.c tmp-signed.err

echo 'All signed type-specifier tests passed!'
''')

print("signed specifier migration applied")
