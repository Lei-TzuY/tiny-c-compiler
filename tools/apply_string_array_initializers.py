from pathlib import Path

p = Path('minicc.h')
s = p.read_text()
old = '''    // Global variable or string literal\n    char *init_data;\n    int64_t init_val;    // for initialized global scalars\n'''
new = '''    // Global variable or string literal\n    char *init_data;\n    bool is_string_literal; // compiler-generated literal storage belongs in .rodata\n    int64_t init_val;    // for initialized global scalars\n'''
if s.count(old) != 1:
    raise SystemExit(f'minicc init_data anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

p = Path('parse.c')
s = p.read_text()
anchor = '''static double parse_const_double(Token **rest, Token *tok) {\n    bool neg = consume(&tok, tok, "-");\n    bool pos = false;\n    if (!neg) pos = consume(&tok, tok, "+");\n    (void)pos;\n    if (tok->kind != TK_NUM)\n        error_at(tok->loc, "expected numeric constant");\n    double val = tok->is_float ? tok->fval\n        : (tok->ty && tok->ty->is_unsigned ? (double)(uint64_t)tok->val\n                                            : (double)tok->val);\n    if (neg) val = -val;\n    *rest = tok->next;\n    return val;\n}\n\n'''
helper = r'''static double parse_const_double(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM)
        error_at(tok->loc, "expected numeric constant");
    double val = tok->is_float ? tok->fval
        : (tok->ty && tok->ty->is_unsigned ? (double)(uint64_t)tok->val
                                            : (double)tok->val);
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}

static Token *string_initializer_token(Token *tok, Token **after) {
    if (tok->kind == TK_STR) {
        *after = tok->next;
        return tok;
    }

    if (!equal(tok, "{") || tok->next->kind != TK_STR)
        return NULL;

    Token *str = tok->next;
    Token *end = str->next;
    if (equal(end, ","))
        end = end->next;
    if (!equal(end, "}"))
        return NULL;

    *after = end->next;
    return str;
}

static bool is_character_array(Type *ty) {
    return ty && ty->kind == TY_ARRAY && ty->base && ty->base->kind == TY_CHAR;
}

static void prepare_string_array_type(Obj *var, Type **ty, Token *str) {
    if (!is_character_array(*ty))
        error_at(str->loc, "string literal can initialize only a character array here");

    int source_len = str->ty->array_len;
    int payload_len = source_len - 1;

    if ((*ty)->array_len == 0) {
        *ty = array_of((*ty)->base, source_len);
        var->ty = *ty;
        return;
    }

    if ((*ty)->array_len < payload_len)
        error_at(str->loc, "initializer string is too long for character array");
}

static char *build_string_array_image(Type *ty, Token *str) {
    char *data = calloc(ty->array_len, 1);
    int copy = str->ty->array_len;
    if (copy > ty->array_len)
        copy = ty->array_len;
    memcpy(data, str->str, copy);
    return data;
}

'''
if s.count(anchor) != 1:
    raise SystemExit(f'parse const double anchor count={s.count(anchor)}')
s = s.replace(anchor, helper, 1)

anchor = '''        tok = tok->next; // skip '='\n\n        // Static/extern: constant initializer only\n        if (is_static || is_extern) {\n'''
replacement = r'''        tok = tok->next; // skip '='

        Token *after_string = NULL;
        Token *string_tok = string_initializer_token(tok, &after_string);
        if (string_tok && ty->kind == TY_ARRAY) {
            prepare_string_array_type(var, &ty, string_tok);

            if (is_static || is_extern) {
                var->init_data = build_string_array_image(ty, string_tok);
                tok = after_string;
                continue;
            }

            for (int i = 0; i < ty->array_len; i++) {
                int value = 0;
                if (i < string_tok->ty->array_len)
                    value = (unsigned char)string_tok->str[i];
                Node *lhs = new_unary(ND_DEREF,
                                      new_add(new_var_node(var), new_num(i)));
                Node *a = new_initializer_assign(lhs, new_num(value), string_tok);
                block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
            }
            tok = after_string;
            continue;
        }

        if (string_tok && (is_static || is_extern))
            error_at(string_tok->loc,
                     "static string initializer is supported only for character arrays");

        // Static/extern: constant initializer only
        if (is_static || is_extern) {
'''
if s.count(anchor) != 1:
    raise SystemExit(f'local initializer anchor count={s.count(anchor)}')
s = s.replace(anchor, replacement, 1)

anchor = '''        var->is_local = false;\n        var->init_data = tok->str;\n        var->next = globals;\n'''
replacement = '''        var->is_local = false;\n        var->init_data = tok->str;\n        var->is_string_literal = true;\n        var->next = globals;\n'''
if s.count(anchor) != 1:
    raise SystemExit(f'string literal object anchor count={s.count(anchor)}')
s = s.replace(anchor, replacement, 1)

old = r'''                if (consume(&tok, tok, "=")) {
                    if (equal(tok, "{")) {
                        tok = tok->next;
                        int cap = 16, cnt = 0;
                        int64_t *vals = calloc(cap, sizeof(int64_t));
                        while (!equal(tok, "}")) {
                            if (cnt > 0) tok = skip(tok, ",");
                            if (equal(tok, "}")) break;
                            if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                            vals[cnt++] = parse_const_int(&tok, tok);
                        }
                        tok = skip(tok, "}");

                        if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                            ty = array_of(ty->base, cnt);
                            var->ty = ty;
                        }

                        var->init_vals = vals;
                        var->init_vals_count = cnt;
                    } else if (tok->kind == TK_STR) {
                        // String initializer: char s[] = "hello";
                        var->init_data = tok->str;
                        if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                            ty = array_of(ty->base, tok->ty->array_len);
                            var->ty = ty;
                        }
                        tok = tok->next;
                    } else {
'''
new = r'''                if (consume(&tok, tok, "=")) {
                    Token *after_string = NULL;
                    Token *string_tok = string_initializer_token(tok, &after_string);
                    if (string_tok) {
                        if (!is_character_array(ty))
                            error_at(string_tok->loc,
                                     "global string initializer is supported only for character arrays");
                        prepare_string_array_type(var, &ty, string_tok);
                        var->init_data = build_string_array_image(ty, string_tok);
                        tok = after_string;
                    } else if (equal(tok, "{")) {
                        tok = tok->next;
                        int cap = 16, cnt = 0;
                        int64_t *vals = calloc(cap, sizeof(int64_t));
                        while (!equal(tok, "}")) {
                            if (cnt > 0) tok = skip(tok, ",");
                            if (equal(tok, "}")) break;
                            if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                            vals[cnt++] = parse_const_int(&tok, tok);
                        }
                        tok = skip(tok, "}");

                        if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                            ty = array_of(ty->base, cnt);
                            var->ty = ty;
                        }

                        var->init_vals = vals;
                        var->init_vals_count = cnt;
                    } else {
'''
if s.count(old) != 1:
    raise SystemExit(f'global initializer block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('codegen.c')
s = p.read_text()
old = '''        if (var->init_data) {\n            printf("  .section .rodata\\n");\n            printf("%s:\\n", var->name);\n            for (int i = 0; i < var->ty->array_len; i++)\n                printf("  .byte %d\\n", var->init_data[i]);\n        } else if (var->init_vals) {\n'''
new = '''        if (var->init_data) {\n            if (var->is_string_literal)\n                printf("  .section .rodata\\n");\n            else {\n                printf("  .data\\n");\n                if (!var->is_static)\n                    printf("  .globl %s\\n", var->name);\n            }\n            printf("%s:\\n", var->name);\n            for (int i = 0; i < var->ty->array_len; i++)\n                printf("  .byte %d\\n", (unsigned char)var->init_data[i]);\n        } else if (var->init_vals) {\n'''
if s.count(old) != 1:
    raise SystemExit(f'codegen init_data anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

Path('test/string_array_initializers.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-strinit.c
  ./minicc tmp-strinit.c > tmp-strinit.s
  cc -o tmp-strinit tmp-strinit.s
  set +e
  ./tmp-strinit
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "string initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(string initializer): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-strinit-bad.c
  if ./minicc tmp-strinit-bad.c > tmp-strinit-bad.s 2>/dev/null; then
    echo "string initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(string initializer): rejected invalid program"
}

assert_run 1 'int main(){char s[]="abc";return sizeof(s)==4&&s[0]==97&&s[3]==0;}'
assert_run 1 'int main(){char s[4]="abc";return s[2]==99&&s[3]==0;}'
assert_run 1 'int main(){char s[3]="abc";return sizeof(s)==3&&s[2]==99;}'
assert_run 1 'int main(){char s[6]="abc";return s[3]==0&&s[4]==0&&s[5]==0;}'
assert_run 1 'int main(){unsigned char s[]="A";return sizeof(s)==2&&s[0]==65&&s[1]==0;}'
assert_run 1 'int main(){char s[]={"hi"};return sizeof(s)==3&&s[1]==105&&s[2]==0;}'
assert_run 1 'int main(){char s[]={"hi",};return sizeof(s)==3&&s[2]==0;}'
assert_run 1 'int main(){char s[]="A\0B";return sizeof(s)==4&&s[0]==65&&s[1]==0&&s[2]==66&&s[3]==0;}'
assert_run 1 'int main(){char *p="abc";return p[0]==97&&p[3]==0;}'
assert_run 1 'char g[]="abc";int main(){g[0]=120;return g[0]==120&&g[3]==0;}'
assert_run 1 'char g[6]="abc";int main(){return g[3]==0&&g[4]==0&&g[5]==0;}'
assert_run 1 'char g[3]="abc";int main(){return sizeof(g)==3&&g[2]==99;}'
assert_run 1 'char g[]={"xy"};int main(){g[1]=122;return sizeof(g)==3&&g[1]==122&&g[2]==0;}'
assert_run 1 'int main(){static char s[]="a";s[0]=98;return sizeof(s)==2&&s[0]==98&&s[1]==0;}'
assert_fail 'int main(){char s[2]="abc";return 0;}'
assert_fail 'char s[2]="abc";int main(){return 0;}'
assert_fail 'int main(){int a[]="abc";return 0;}'
assert_fail 'int a[]="abc";int main(){return 0;}'
assert_fail 'char *p="abc";int main(){return 0;}'
assert_fail 'int main(){static char *p="abc";return 0;}'
echo 'All string-array initializer tests passed!'
''')

p = Path('Makefile')
s = p.read_text()
anchor = '\tbash ./test/call_arguments.sh\n'
if anchor not in s:
    anchor = '\tbash ./test/escape_sequences.sh\n'
if s.count(anchor) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(anchor)}')
s = s.replace(anchor, anchor + '\tbash ./test/string_array_initializers.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = 'local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer'
replacement = 'local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, character-array initialization from string literals with safe length inference/zero-fill, array length inference from initializer'
if s.count(needle) != 1:
    raise SystemExit(f'README initializer anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))
