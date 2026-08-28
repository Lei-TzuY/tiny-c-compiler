from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1))


if Path("test/char_type_identity.sh").exists():
    print("distinct signed-char migration already applied")
    raise SystemExit(0)

replace_once(
    "minicc.h",
    "    bool is_unsigned; // true for unsigned integer types\n",
    "    bool is_unsigned; // true for unsigned integer types\n"
    "    bool is_plain_char; // distinguish plain char from signed/unsigned char\n",
)
replace_once(
    "minicc.h",
    "extern Type *ty_char;\nextern Type *ty_short;\n",
    "extern Type *ty_char;\nextern Type *ty_schar;\nextern Type *ty_short;\n",
)

replace_once(
    "type.c",
    "Type *ty_char   = &(Type){TY_CHAR,   1, 1, false};\n",
    "Type *ty_char   = &(Type){.kind=TY_CHAR, .size=1, .align=1, .is_plain_char=true};\n"
    "Type *ty_schar  = &(Type){TY_CHAR,   1, 1, false};\n",
)

compat_old = '''    case TY_CHAR:
    case TY_SHORT:
    case TY_INT:
    case TY_LONG:
    case TY_LLONG:
        return a->is_unsigned == b->is_unsigned;
'''
compat_new = '''    case TY_CHAR:
        return a->is_unsigned == b->is_unsigned &&
               a->is_plain_char == b->is_plain_char;
    case TY_SHORT:
    case TY_INT:
    case TY_LONG:
    case TY_LLONG:
        return a->is_unsigned == b->is_unsigned;
'''
replace_once("type.c", compat_old, compat_new)
replace_once("parse.c", compat_old, compat_new)

replace_once(
    "parse.c",
    '        if (consume(&tok, tok, "char"))   { ty = (ty && ty->is_unsigned) ? ty_uchar : ty_char; continue; }\n',
    '''        if (consume(&tok, tok, "char")) {
            if (saw_unsigned || (ty && ty->is_unsigned))
                ty = ty_uchar;
            else if (saw_signed)
                ty = ty_schar;
            else
                ty = ty_char;
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''            if (!ty)
                ty = ty_int;
            else if (ty != ty_int && ty != ty_char && ty != ty_short &&
                     ty != ty_long && ty != ty_llong)
                error_at(sign_tok->loc, "invalid type specifier combination with 'signed'");
''',
    '''            if (!ty)
                ty = ty_int;
            else if (ty == ty_char)
                ty = ty_schar;
            else if (ty != ty_int && ty != ty_schar && ty != ty_short &&
                     ty != ty_long && ty != ty_llong)
                error_at(sign_tok->loc, "invalid type specifier combination with 'signed'");
''',
)

replace_once(
    "README.md",
    '`char` (1B), `short` (2B), `int` (4B)',
    '`char`/`signed char`/`unsigned char` as distinct 1B types, `short` (2B), `int` (4B)',
)

replace_once(
    "Makefile",
    '\tbash ./test/signed_specifiers.sh\n',
    '\tbash ./test/signed_specifiers.sh\n\tbash ./test/char_type_identity.sh\n',
)

Path("test/char_type_identity.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-char-identity.c
  ./minicc tmp-char-identity.c > tmp-char-identity.s
  cc -o tmp-char-identity tmp-char-identity.s
  set +e
  ./tmp-char-identity
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(char type identity): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-char-identity-bad.c
  if ./minicc tmp-char-identity-bad.c > /dev/null 2>tmp-char-identity.err; then
    echo "FAIL(char type identity): expected rejection"
    echo "$input"
    exit 1
  fi
}

# C defines plain char, signed char, and unsigned char as three distinct types.
assert_run 0 'int main(void){ char c=0; signed char s=0; unsigned char u=0; if(_Generic(c,char:1,signed char:2,unsigned char:3,default:0)!=1)return 1; if(_Generic(s,char:1,signed char:2,unsigned char:3,default:0)!=2)return 2; if(_Generic(u,char:1,signed char:2,unsigned char:3,default:0)!=3)return 3; return 0; }'

# Representation stays one byte, while signed-char conversion uses signed semantics.
assert_run 0 'int main(void){ signed char s=(signed char)255; unsigned char u=(unsigned char)255; char c=1; return !(sizeof(c)==1 && sizeof(s)==1 && sizeof(u)==1 && s<0 && u>0); }'

# Typedefs and qualifiers preserve the signed-char identity.
assert_run 0 'typedef signed char SC; int main(void){ SC x=-1; const SC y=-2; if(_Generic(x,signed char:1,char:2,default:0)!=1)return 1; if(_Generic((SC)0,signed char:1,char:2,default:0)!=1)return 2; return !(x<0 && y<0); }'

# Distinct character pointer types are not compatible merely because their representation matches.
assert_reject 'int main(void){ char *p=0; signed char *q=0; p=q; return 0; }'
assert_reject 'int main(void){ char *p=0; signed char *q=0; return p==q; }'
assert_reject 'int main(void){ char *p=0; signed char *q=0; return (1?p:q)!=0; }'
assert_reject 'int f(char *); int f(signed char *); int main(void){return 0;}'
assert_reject 'int main(void){ signed char *p="x"; return p!=0; }'

# All three character types may coexist as distinct _Generic associations.
assert_run 0 'int kind_char(char x){return _Generic(x,char:1,signed char:2,unsigned char:3);} int kind_schar(signed char x){return _Generic(x,char:1,signed char:2,unsigned char:3);} int kind_uchar(unsigned char x){return _Generic(x,char:1,signed char:2,unsigned char:3);} int main(void){return !(kind_char(0)==1 && kind_schar(0)==2 && kind_uchar(0)==3);}'

rm -f tmp-char-identity.c tmp-char-identity.s tmp-char-identity \
      tmp-char-identity-bad.c tmp-char-identity.err

echo 'All character type-identity tests passed!'
''')

print("distinct signed-char migration applied")
