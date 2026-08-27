from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{path}: anchor count={count}')
    p.write_text(s.replace(old, new, 1))

# minicc.h: represent long long distinctly even on LP64, and expose canonical types.
replace_once('minicc.h', '''    TY_INT,\n    TY_LONG,\n    TY_CHAR,\n''', '''    TY_INT,\n    TY_LONG,\n    TY_LLONG,\n    TY_CHAR,\n''')
replace_once('minicc.h', '''extern Type *ty_int;\nextern Type *ty_long;\nextern Type *ty_char;\n''', '''extern Type *ty_int;\nextern Type *ty_long;\nextern Type *ty_llong;\nextern Type *ty_char;\n''')
replace_once('minicc.h', '''extern Type *ty_uint;\nextern Type *ty_ulong;\nextern Type *ty_uchar;\n''', '''extern Type *ty_uint;\nextern Type *ty_ulong;\nextern Type *ty_ullong;\nextern Type *ty_uchar;\n''')

# type.c: add canonical long-long types and rank-aware usual arithmetic conversions.
replace_once('type.c', '''Type *ty_int    = &(Type){TY_INT,    4, 4, false};\nType *ty_long   = &(Type){TY_LONG,   8, 8, false};\nType *ty_char   = &(Type){TY_CHAR,   1, 1, false};\n''', '''Type *ty_int    = &(Type){TY_INT,    4, 4, false};\nType *ty_long   = &(Type){TY_LONG,   8, 8, false};\nType *ty_llong  = &(Type){TY_LLONG,  8, 8, false};\nType *ty_char   = &(Type){TY_CHAR,   1, 1, false};\n''')
replace_once('type.c', '''Type *ty_uint   = &(Type){TY_INT,    4, 4, true};\nType *ty_ulong  = &(Type){TY_LONG,   8, 8, true};\nType *ty_uchar  = &(Type){TY_CHAR,   1, 1, true};\n''', '''Type *ty_uint   = &(Type){TY_INT,    4, 4, true};\nType *ty_ulong  = &(Type){TY_LONG,   8, 8, true};\nType *ty_ullong = &(Type){TY_LLONG,  8, 8, true};\nType *ty_uchar  = &(Type){TY_CHAR,   1, 1, true};\n''')
replace_once('type.c', '''bool is_integer(Type *ty) {\n    return ty->kind == TY_INT || ty->kind == TY_LONG ||\n           ty->kind == TY_CHAR || ty->kind == TY_SHORT ||\n           ty->kind == TY_BOOL;\n}\n''', '''bool is_integer(Type *ty) {\n    return ty->kind == TY_INT || ty->kind == TY_LONG ||\n           ty->kind == TY_LLONG || ty->kind == TY_CHAR ||\n           ty->kind == TY_SHORT || ty->kind == TY_BOOL;\n}\n''')
old_common = '''// Usual arithmetic conversions for the LP64 subset supported by minicc.\n// After integer promotion, rank follows size for the integer types we expose:\n// int < long.  If signedness differs, a wider signed type can represent every\n// value of the narrower unsigned type; otherwise the unsigned type wins.\nType *get_common_type(Type *ty1, Type *ty2) {\n    if (ty1->base)\n        return pointer_to(ty1->base);\n\n    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)\n        return ty_double;\n    if (ty1->kind == TY_FLOAT || ty2->kind == TY_FLOAT)\n        return ty_float;\n\n    ty1 = integer_promotion(ty1);\n    ty2 = integer_promotion(ty2);\n\n    if (ty1->is_unsigned == ty2->is_unsigned)\n        return ty1->size >= ty2->size ? ty1 : ty2;\n\n    Type *u = ty1->is_unsigned ? ty1 : ty2;\n    Type *s = ty1->is_unsigned ? ty2 : ty1;\n\n    if (u->size >= s->size)\n        return u;\n\n    // On x86-64 LP64, a wider signed integer type represents the complete\n    // range of every narrower unsigned integer type supported here.\n    return s;\n}\n'''
new_common = '''static int integer_rank(Type *ty) {\n    switch (ty->kind) {\n    case TY_BOOL:  return 1;\n    case TY_CHAR:  return 2;\n    case TY_SHORT: return 3;\n    case TY_INT:   return 4;\n    case TY_LONG:  return 5;\n    case TY_LLONG: return 6;\n    default:       return 0;\n    }\n}\n\nstatic Type *unsigned_integer_type(Type *ty) {\n    switch (ty->kind) {\n    case TY_CHAR:  return ty_uchar;\n    case TY_SHORT: return ty_ushort;\n    case TY_INT:   return ty_uint;\n    case TY_LONG:  return ty_ulong;\n    case TY_LLONG: return ty_ullong;\n    default:       return ty;\n    }\n}\n\n// Usual arithmetic conversions for the x86-64 LP64 target.  `long` and\n// `long long` are both 64-bit here but retain distinct C ranks, so size alone\n// is insufficient (notably unsigned long + long long -> unsigned long long).\nType *get_common_type(Type *ty1, Type *ty2) {\n    if (ty1->base)\n        return pointer_to(ty1->base);\n\n    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)\n        return ty_double;\n    if (ty1->kind == TY_FLOAT || ty2->kind == TY_FLOAT)\n        return ty_float;\n\n    ty1 = integer_promotion(ty1);\n    ty2 = integer_promotion(ty2);\n\n    int r1 = integer_rank(ty1);\n    int r2 = integer_rank(ty2);\n    if (ty1->is_unsigned == ty2->is_unsigned)\n        return r1 >= r2 ? ty1 : ty2;\n\n    Type *u = ty1->is_unsigned ? ty1 : ty2;\n    Type *s = ty1->is_unsigned ? ty2 : ty1;\n    int urank = integer_rank(u);\n    int srank = integer_rank(s);\n\n    if (urank >= srank)\n        return u;\n\n    // The higher-rank signed type wins only when it can represent every value\n    // of the lower-rank unsigned type. On this target that requires more bits.\n    if (s->size > u->size)\n        return s;\n\n    return unsigned_integer_type(s);\n}\n'''
replace_once('type.c', old_common, new_common)

# parse.c: distinguish long long declarations, compatibility, literal node type,
# and unsigned integer constants used in static floating initializers.
old_long = '''        if (consume(&tok, tok, "long")) {\n            if (consume(&tok, tok, "long")) {}\n            consume(&tok, tok, "int");\n            ty = (ty && ty->is_unsigned) ? ty_ulong : ty_long;\n            continue;\n        }\n\n        if (consume(&tok, tok, "unsigned")) {\n            if (ty == ty_char) ty = ty_uchar;\n            else if (ty == ty_short) ty = ty_ushort;\n            else if (ty == ty_long) ty = ty_ulong;\n            else ty = ty_uint;\n            continue;\n        }\n'''
new_long = '''        if (consume(&tok, tok, "long")) {\n            bool already_long = ty == ty_long || ty == ty_ulong;\n            bool already_llong = ty == ty_llong || ty == ty_ullong;\n            bool adjacent_long = consume(&tok, tok, "long");\n            if (already_llong)\n                error_at(tok->loc, "too many 'long' specifiers");\n            consume(&tok, tok, "int");\n            bool is_unsigned = ty && ty->is_unsigned;\n            bool is_llong = already_long || adjacent_long;\n            ty = is_llong ? (is_unsigned ? ty_ullong : ty_llong)\n                          : (is_unsigned ? ty_ulong : ty_long);\n            continue;\n        }\n\n        if (consume(&tok, tok, "unsigned")) {\n            if (ty == ty_char) ty = ty_uchar;\n            else if (ty == ty_short) ty = ty_ushort;\n            else if (ty == ty_long) ty = ty_ulong;\n            else if (ty == ty_llong) ty = ty_ullong;\n            else ty = ty_uint;\n            continue;\n        }\n'''
replace_once('parse.c', old_long, new_long)
replace_once('parse.c', '''    case TY_INT:\n    case TY_LONG:\n        return a->is_unsigned == b->is_unsigned;\n''', '''    case TY_INT:\n    case TY_LONG:\n    case TY_LLONG:\n        return a->is_unsigned == b->is_unsigned;\n''')
replace_once('parse.c', '''    double val = tok->is_float ? tok->fval : (double)tok->val;\n''', '''    double val = tok->is_float ? tok->fval\n        : (tok->ty && tok->ty->is_unsigned ? (double)(uint64_t)tok->val\n                                            : (double)tok->val);\n''')
replace_once('parse.c', '''    if (tok->kind == TK_NUM) {\n        Node *node = new_num(tok->val);\n        if (tok->is_float) {\n            node->fval = tok->fval;\n            node->ty = tok->ty;\n        }\n        *rest = tok->next;\n        return node;\n    }\n''', '''    if (tok->kind == TK_NUM) {\n        Node *node = new_num(tok->val);\n        if (tok->is_float)\n            node->fval = tok->fval;\n        if (tok->ty)\n            node->ty = tok->ty;\n        *rest = tok->next;\n        return node;\n    }\n''')

# codegen.c: both unsigned long and unsigned long long are full-width uint64.
p = Path('codegen.c')
s = p.read_text()
s2 = s.replace('from->kind == TY_LONG && from->is_unsigned',
               'from->size == 8 && from->is_unsigned')
s2 = s2.replace('to->kind == TY_LONG && to->is_unsigned',
                'to->size == 8 && to->is_unsigned')
if s2 == s:
    raise SystemExit('codegen uint64 conversion anchors not found')
p.write_text(s2)

# tokenize.c: parse integer suffixes and choose the standard candidate type.
p = Path('tokenize.c')
s = p.read_text()
if '#include <errno.h>' not in s:
    s = s.replace('#include "minicc.h"\n', '#include "minicc.h"\n#include <errno.h>\n#include <limits.h>\n', 1)
helper_anchor = '''// Tokenize a given string and returns new tokens.\nToken *tokenize(char *p) {\n'''
helper = r'''static Type *integer_literal_type(uint64_t val, int base, bool has_u,
                                  int long_count, char *loc) {
    bool decimal = base == 10;

    if (long_count == 0 && !has_u) {
        if (val <= INT_MAX)
            return ty_int;
        if (!decimal && val <= UINT_MAX)
            return ty_uint;
        if (val <= INT64_MAX)
            return ty_long;
        if (!decimal)
            return ty_ulong;
        error_at(loc, "decimal integer constant is too large for signed long long");
    }

    if (long_count == 0 && has_u)
        return val <= UINT_MAX ? ty_uint : ty_ulong;

    if (long_count == 1 && !has_u) {
        if (val <= INT64_MAX)
            return ty_long;
        if (!decimal)
            return ty_ulong;
        error_at(loc, "decimal long constant is too large");
    }

    if (long_count == 1 && has_u)
        return ty_ulong;

    if (long_count == 2 && !has_u) {
        if (val <= INT64_MAX)
            return ty_llong;
        if (!decimal)
            return ty_ullong;
        error_at(loc, "decimal long long constant is too large");
    }

    if (long_count == 2 && has_u)
        return ty_ullong;

    error_at(loc, "invalid integer suffix");
}

// Tokenize a given string and returns new tokens.
Token *tokenize(char *p) {
'''
if s.count(helper_anchor) != 1:
    raise SystemExit('tokenize helper anchor not found')
s = s.replace(helper_anchor, helper, 1)
old_numeric = r'''        // Numeric literal (integer or floating-point)
        if (isdigit(*p) || (*p == '.' && isdigit(p[1]))) {
            char *q = p;
            char *end;
            double fval = strtod(p, &end);
            // Check if floating-point constant (contains '.', 'e', 'E', or 'f'/'F' suffix)
            bool is_flonum = false;
            for (char *c = p; c < end; c++) {
                if (*c == '.' || *c == 'e' || *c == 'E') {
                    is_flonum = true;
                    break;
                }
            }
            bool is_float_suffix = false;
            if (*end == 'f' || *end == 'F') {
                is_flonum = true;
                is_float_suffix = true;
                end++;
            }

            if (is_flonum) {
                p = end;
                cur = cur->next = new_token(TK_NUM, q, p);
                cur->line_no = line;
                cur->is_float = true;
                cur->fval = fval;
                cur->ty = is_float_suffix ? ty_float : ty_double;
                continue;
            }

            // Integer literal
            cur = cur->next = new_token(TK_NUM, p, p);
            cur->line_no = line;
            cur->val = strtoul(p, &p, 0);
            cur->len = p - q;
            continue;
        }
'''
new_numeric = r'''        // Numeric literal (integer or floating-point)
        if (isdigit(*p) || (*p == '.' && isdigit(p[1]))) {
            char *q = p;
            bool hex = p[0] == '0' && (p[1] == 'x' || p[1] == 'X');

            // Let strtod identify decimal/hex floating syntax.  In a hex
            // integer, e/E are ordinary digits, so only p/P denotes an exponent.
            char *fend;
            double fval = strtod(p, &fend);
            bool is_flonum = *p == '.';
            for (char *c = p; c < fend; c++) {
                if (*c == '.' || (!hex && (*c == 'e' || *c == 'E')) ||
                    (hex && (*c == 'p' || *c == 'P'))) {
                    is_flonum = true;
                    break;
                }
            }
            bool is_float_suffix = false;
            if (*fend == 'f' || *fend == 'F') {
                is_flonum = true;
                is_float_suffix = true;
                fend++;
            }

            if (is_flonum) {
                if (is_ident2(*fend))
                    error_at(q, "invalid floating suffix");
                p = fend;
                cur = cur->next = new_token(TK_NUM, q, p);
                cur->line_no = line;
                cur->is_float = true;
                cur->fval = fval;
                cur->ty = is_float_suffix ? ty_float : ty_double;
                continue;
            }

            int base = 10;
            if (q[0] == '0' && (q[1] == 'x' || q[1] == 'X'))
                base = 16;
            else if (q[0] == '0')
                base = 8;

            errno = 0;
            char *end;
            uint64_t val = strtoull(p, &end, 0);
            if (errno == ERANGE)
                error_at(q, "integer constant is too large");
            if (end == p)
                error_at(q, "invalid integer constant");

            bool has_u = false;
            int long_count = 0;
            for (;;) {
                if ((*end == 'u' || *end == 'U') && !has_u) {
                    has_u = true;
                    end++;
                    continue;
                }
                if ((*end == 'l' || *end == 'L') && long_count == 0) {
                    char first = *end++;
                    long_count = 1;
                    if (*end == first) {
                        long_count = 2;
                        end++;
                    }
                    continue;
                }
                break;
            }

            if (is_ident2(*end))
                error_at(q, "invalid integer suffix or digit");

            cur = cur->next = new_token(TK_NUM, q, end);
            cur->line_no = line;
            cur->val = (int64_t)val;
            cur->ty = integer_literal_type(val, base, has_u, long_count, q);
            p = end;
            continue;
        }
'''
if s.count(old_numeric) != 1:
    raise SystemExit(f'tokenize numeric anchor count={s.count(old_numeric)}')
s = s.replace(old_numeric, new_numeric, 1)
p.write_text(s)

# Focused tests.
Path('test/integer_literals.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-intlit.c
  ./minicc tmp-intlit.c > tmp-intlit.s
  cc -o tmp-intlit tmp-intlit.s
  set +e
  ./tmp-intlit
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "integer literal test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(integer literal): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-intlit-bad.c
  if ./minicc tmp-intlit-bad.c > /dev/null 2>tmp-intlit-bad.err; then
    echo "expected integer literal rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(rejected integer literal)"
}

# Unsuffixed candidate lists differ for decimal and hexadecimal/octal constants.
assert_run 4 'int main(){return sizeof(2147483647);}'
assert_run 8 'int main(){return sizeof(2147483648);}'
assert_run 8 'int main(){return sizeof(4294967295);}'
assert_run 4 'int main(){return sizeof(0xffffffff);}'
assert_run 8 'int main(){return sizeof(0x100000000);}'
assert_run 1 'int main(){return 0xffffffff>0;}'
assert_run 1 'int main(){return 0xffffffffffffffff>0;}'

# U/L/UL/LU/LL/ULL/LLU suffixes are consumed case-insensitively and typed.
assert_run 4 'int main(){return sizeof(2147483648U);}'
assert_run 8 'int main(){return sizeof(4294967296U);}'
assert_run 8 'int main(){return sizeof(1L)+sizeof(1UL)+sizeof(1LU);}'
assert_run 8 'int main(){return sizeof(1LL);}'
assert_run 8 'int main(){return sizeof(1ULL);}'
assert_run 8 'int main(){return sizeof(1LLU);}'
assert_run 1 'int main(){unsigned long long x=18446744073709551615ULL;return x==(unsigned long long)-1;}'
assert_run 1 'int main(){return 0xffffffffffffffffLL>0;}'
assert_run 1 'int main(){return (1ULL<<63)>0;}'

# long and long long remain distinct C types despite both being 8 bytes on LP64.
assert_fail 'long f(long); long long f(long long); int main(){return 0;}'
assert_run 1 'int main(){unsigned long x=(unsigned long)-1;long long y=0;return (x+y)>0;}'

# Literal typing feeds the full-range uint64 floating conversion lowering.
assert_run 1 'int main(){double d=18446744073709551615ULL;return d>18446744073709549568.0;}'
assert_run 1 'double f(){return 9223372036854775808ULL;} int main(){return f==f && f()>0;}'

# Decimal signed candidate lists must reject values beyond signed long long;
# explicit unsigned suffixes allow the complete uint64 range.
assert_fail 'int main(){return 9223372036854775808;}'
assert_fail 'int main(){return 9223372036854775808LL;}'
assert_fail 'int main(){return 18446744073709551616ULL;}'
assert_fail 'int main(){return 1UU;}'
assert_fail 'int main(){return 1LLL;}'
assert_fail 'int main(){return 08;}'

# Floating tokenization stays intact, including exponent and f suffix.
assert_run 1 'int main(){float x=1e1f;return x==10.0;}'

echo 'All integer-literal tests passed!'
''')

# Wire suite into make test.
replace_once('Makefile', '\tbash ./test/uint64_fp_conversions.sh\n',
             '\tbash ./test/uint64_fp_conversions.sh\n\tbash ./test/integer_literals.sh\n')

# README feature summary.
p = Path('README.md')
s = p.read_text()
old = '- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `unsigned`, semantic `const`/`volatile` qualifiers'
new = '- **Types**: `char` (1B), `short` (2B), `int` (4B), `long`/`long long` (8B with distinct C ranks), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `unsigned`, typed integer literal suffixes (`U`, `L`, `UL`, `LL`, `ULL`), semantic `const`/`volatile` qualifiers'
if old not in s:
    raise SystemExit('README type summary anchor not found')
p.write_text(s.replace(old, new, 1))
