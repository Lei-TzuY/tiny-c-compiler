from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    '''typedef struct {\n    bool is_auto;\n    bool is_static;\n    bool is_extern;\n    bool is_register;\n    bool is_inline;\n''',
    '''typedef struct {\n    bool is_auto;\n    bool is_static;\n    bool is_extern;\n    bool is_register;\n    bool is_typedef;\n    bool is_inline;\n''')

replace_once(
    "parse.c",
    '''    if (equal(tok, "auto") || equal(tok, "static") || equal(tok, "extern")) return true;\n    if (equal(tok, "const") || equal(tok, "volatile") || equal(tok, "restrict")) return true;\n''',
    '''    if (equal(tok, "auto") || equal(tok, "static") || equal(tok, "extern") ||\n        equal(tok, "typedef")) return true;\n    if (equal(tok, "const") || equal(tok, "volatile") || equal(tok, "restrict")) return true;\n''')

replace_once(
    "parse.c",
    '''        storage_tok = tok;\n        if (consume(&tok, tok, "extern")) {\n            note_storage_class(attrs, storage_tok);\n            attrs->is_extern = true;\n            continue;\n        }\n\n        Token *base_tok = tok;\n''',
    '''        storage_tok = tok;\n        if (consume(&tok, tok, "extern")) {\n            note_storage_class(attrs, storage_tok);\n            attrs->is_extern = true;\n            continue;\n        }\n        storage_tok = tok;\n        if (consume(&tok, tok, "typedef")) {\n            note_storage_class(attrs, storage_tok);\n            attrs->is_typedef = true;\n            continue;\n        }\n\n        Token *base_tok = tok;\n''')

# Insert one shared typedef-declaration parser immediately before ordinary
# block declarations. Both block and file scope route through it.
replace_once(
    "parse.c",
    '''\n\n// declaration = declspec (declarator ("=" (expr | "{" initializer "}"))?)\n//               ("," declarator ("=" (expr | "{" initializer "}"))?)* ";"\nstatic Node *declaration(Token **rest, Token *tok) {\n''',
    '''\n\nstatic Token *parse_typedef_declaration(Token *tok, Type *basety,\n                                        DeclAttrs *attrs) {\n    if (attrs->align)\n        error_at(tok->loc, "_Alignas is not allowed on a typedef declaration");\n    if (attrs->is_inline || attrs->is_noreturn)\n        error_at(tok->loc, "function specifier is not allowed on a typedef declaration");\n    if (equal(tok, ";"))\n        error_at(tok->loc, "typedef declaration requires a declarator");\n\n    for (;;) {\n        Token *ident;\n        Type *ty = declarator(&tok, tok, basety, &ident);\n        if (equal(tok, "="))\n            error_at(tok->loc, "typedef declaration cannot have an initializer");\n        push_typedef(ident, ty);\n        if (!consume(&tok, tok, ","))\n            break;\n    }\n    return skip(tok, ";");\n}\n\n// declaration = declspec (declarator ("=" (expr | "{" initializer "}"))?)\n//               ("," declarator ("=" (expr | "{" initializer "}"))?)* ";"\nstatic Node *declaration(Token **rest, Token *tok) {\n''')

replace_once(
    "parse.c",
    '''    Type *basety = declspec_with_attrs(&tok, tok, &attrs);\n    bool is_static = attrs.is_static;\n    bool is_extern = attrs.is_extern;\n''',
    '''    Type *basety = declspec_with_attrs(&tok, tok, &attrs);\n    if (attrs.is_typedef) {\n        *rest = parse_typedef_declaration(tok, basety, &attrs);\n        return new_node(ND_EXPR_STMT);\n    }\n    bool is_static = attrs.is_static;\n    bool is_extern = attrs.is_extern;\n''')

# Remove the old block-only first-token typedef special case.
replace_once(
    "parse.c",
    '''    if (equal(tok, "typedef")) {\n        tok = tok->next;\n        Type *basety = declspec(&tok, tok);\n        if (!equal(tok, ";")) {\n            for (;;) {\n                Token *ident;\n                Type *ty = declarator(&tok, tok, basety, &ident);\n                push_typedef(ident, ty);\n                if (!consume(&tok, tok, ","))\n                    break;\n            }\n        }\n        *rest = skip(tok, ";");\n        return new_node(ND_EXPR_STMT);\n    }\n\n''',
    '''''')

# Remove the old top-level first-token typedef special case.
replace_once(
    "parse.c",
    '''        // Top-level typedef\n        if (equal(tok, "typedef")) {\n            tok = tok->next;\n            Type *basety = declspec(&tok, tok);\n            if (!equal(tok, ";")) {\n                for (;;) {\n                    Token *ident;\n                    Type *ty = declarator(&tok, tok, basety, &ident);\n                    push_typedef(ident, ty);\n                    if (!consume(&tok, tok, ","))\n                        break;\n                }\n            }\n            tok = skip(tok, ";");\n            continue;\n        }\n\n''',
    '''''')

# Route top-level typedef declarations through the same helper.
replace_once(
    "parse.c",
    '''        DeclAttrs attrs = {};\n        Type *basety = declspec_with_attrs(&tok, tok, &attrs);\n        bool is_static = attrs.is_static;\n''',
    '''        DeclAttrs attrs = {};\n        Type *basety = declspec_with_attrs(&tok, tok, &attrs);\n        if (attrs.is_typedef) {\n            tok = parse_typedef_declaration(tok, basety, &attrs);\n            continue;\n        }\n        bool is_static = attrs.is_static;\n''')

makefile = Path("Makefile")
text = makefile.read_text()
old = '''\tbash ./test/register_addressability.sh\n\tbash ./test/cast_constraints.sh\n'''
new = '''\tbash ./test/register_addressability.sh\n\tbash ./test/typedef_storage_class.sh\n\tbash ./test/cast_constraints.sh\n'''
if text.count(old) != 1:
    raise SystemExit("Makefile typedef test insertion point not unique")
makefile.write_text(text.replace(old, new, 1))

readme = Path("README.md")
text = readme.read_text()
needle = "block-scope `auto`/`register` objects with single-storage-class constraint checking and C address-taking restrictions for register objects/parameters"
replacement = "order-independent `typedef` storage-class declarations, block-scope `auto`/`register` objects with single-storage-class constraint checking and C address-taking restrictions for register objects/parameters"
if text.count(needle) != 1:
    raise SystemExit("README typedef insertion point not unique")
readme.write_text(text.replace(needle, replacement, 1))

test = Path("test/typedef_storage_class.sh")
test.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-typedef-sc.c
  ./minicc tmp-typedef-sc.c > tmp-typedef-sc.s
  cc -o tmp-typedef-sc tmp-typedef-sc.s
  set +e
  ./tmp-typedef-sc
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(typedef storage): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-typedef-sc.c
  ./minicc tmp-typedef-sc.c > tmp-typedef-sc.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-typedef-sc-bad.c
  if ./minicc tmp-typedef-sc-bad.c > /dev/null 2>tmp-typedef-sc.err; then
    echo "FAIL(typedef storage): expected rejection"
    echo "$input"
    exit 1
  fi
}

# typedef is a storage-class specifier and may be intermingled with type
# specifiers/qualifiers rather than appearing only as the first token.
assert_run 7 'int typedef I;I x=7;int main(void){return x;}'
assert_run 5 'const typedef int CI;int main(void){CI x=5;return x;}'
assert_run 0 'unsigned typedef long U;int main(void){return sizeof(U)==8?0:1;}'
assert_run 0 'long typedef unsigned U;int main(void){return sizeof(U)==8?0:1;}'
assert_run 4 'struct S{int x;} typedef S;int main(void){S s={4};return s.x;}'
assert_run 6 'int main(void){int typedef I;I x=6;return x;}'
assert_run 8 'int main(void){const typedef int I;I x=8;return x;}'

# Complex declarators and comma-separated typedef declarators keep working.
assert_run 3 'typedef int I,*IP,A[3];int main(void){I x=3;IP p=&x;A a={1,2,3};return *p+a[0]-1;}'
assert_run 9 'typedef int F(int);int add1(int x){return x+1;}int main(void){F *fp=add1;return fp(8);}'
assert_run 5 'int typedef F(int);int f(int x){return x;}int main(void){F *fp=f;return fp(5);}'
assert_compile 'typedef struct Node Node;struct Node{int x;Node *next;};int main(void){return 0;}'

# A nearer ordinary identifier still shadows an outer typedef name.
assert_run 3 'typedef int T;int main(void){int T=3;return T;}'
assert_run 4 'typedef int T;int main(void){{int typedef U;U T=4;return T;}return 0;}'

# A typedef declaration requires at least one declarator and cannot initialize.
assert_reject 'typedef int;int main(void){return 0;}'
assert_reject 'int typedef;int main(void){return 0;}'
assert_reject 'const typedef int;int main(void){return 0;}'
assert_reject 'typedef int I=3;int main(void){return 0;}'
assert_reject 'int typedef I=3;int main(void){return 0;}'
assert_reject 'typedef int I,J=3;int main(void){return 0;}'

# typedef participates in the one-storage-class constraint.
assert_reject 'typedef typedef int I;int main(void){return 0;}'
assert_reject 'typedef static int I;int main(void){return 0;}'
assert_reject 'static typedef int I;int main(void){return 0;}'
assert_reject 'extern typedef int I;int main(void){return 0;}'
assert_reject 'register typedef int I;int main(void){return 0;}'
assert_reject 'auto typedef int I;int main(void){return 0;}'

# Alignment/function specifiers cannot be attached to a typedef declaration.
assert_reject '_Alignas(8) typedef long I;int main(void){return 0;}'
assert_reject 'typedef _Alignas(8) long I;int main(void){return 0;}'
assert_reject 'inline typedef int F(void);int main(void){return 0;}'
assert_reject '_Noreturn typedef void F(void);int main(void){return 0;}'

# Storage-class context rules now also apply when typedef is not first.
assert_reject 'int f(typedef int x);int main(void){return 0;}'
assert_reject 'struct S{typedef int x;};int main(void){return 0;}'
assert_reject 'int main(void){return sizeof(typedef int);}'

rm -f tmp-typedef-sc.c tmp-typedef-sc.s tmp-typedef-sc \
      tmp-typedef-sc-bad.c tmp-typedef-sc.err

echo 'All typedef storage-class tests passed!'
''')

print("typedef storage-class migration applied")
