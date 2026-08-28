from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


def add_default_qualify_arg(path):
    p = Path(path)
    text = p.read_text()
    needle = "qualify_type("
    out = []
    pos = 0
    changed = 0
    while True:
        start = text.find(needle, pos)
        if start < 0:
            out.append(text[pos:])
            break
        out.append(text[pos:start])
        open_paren = start + len("qualify_type")
        depth = 0
        i = open_paren
        while i < len(text):
            ch = text[i]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if i >= len(text):
            raise SystemExit(f"{path}: unterminated qualify_type call")
        call = text[start:i + 1]
        args_text = text[open_paren + 1:i]
        args = []
        last = 0
        nested = 0
        for j, ch in enumerate(args_text):
            if ch in '([{':
                nested += 1
            elif ch in ')]}':
                nested -= 1
            elif ch == ',' and nested == 0:
                args.append(args_text[last:j].strip())
                last = j + 1
        args.append(args_text[last:].strip())
        if len(args) == 3:
            call = call[:-1] + ", false)"
            changed += 1
        out.append(call)
        pos = i + 1
    p.write_text(''.join(out))
    return changed


if Path("test/restrict_qualifier.sh").exists():
    print("restrict qualifier migration already applied")
    raise SystemExit(0)

# Type model and public qualifier constructor.
replace_once(
    "minicc.h",
    "    bool is_const;\n    bool is_volatile;\n",
    "    bool is_const;\n    bool is_volatile;\n    bool is_restrict;\n",
)
replace_once(
    "minicc.h",
    "Type *qualify_type(Type *ty, bool is_const, bool is_volatile);\n",
    "Type *qualify_type(Type *ty, bool is_const, bool is_volatile, bool is_restrict);\n",
)
replace_once(
    "type.c",
    "Type *qualify_type(Type *ty, bool is_const, bool is_volatile) {\n"
    "    if (!ty || (!is_const && !is_volatile))\n",
    "Type *qualify_type(Type *ty, bool is_const, bool is_volatile, bool is_restrict) {\n"
    "    if (!ty || (!is_const && !is_volatile && !is_restrict))\n",
)

# First make every old three-argument call explicit with a false restrict bit.
for source in ["type.c", "parse.c"]:
    add_default_qualify_arg(source)

replace_once(
    "type.c",
    "        copy->base = qualify_type(ty->base, is_const, is_volatile, false);\n",
    "        copy->base = qualify_type(ty->base, is_const, is_volatile, is_restrict);\n",
)
replace_once(
    "type.c",
    "    copy->is_const = copy->is_const || is_const;\n"
    "    copy->is_volatile = copy->is_volatile || is_volatile;\n",
    "    copy->is_const = copy->is_const || is_const;\n"
    "    copy->is_volatile = copy->is_volatile || is_volatile;\n"
    "    copy->is_restrict = copy->is_restrict || is_restrict;\n",
)
replace_once(
    "type.c",
    "    if (!ignore_top_qual &&\n"
    "        (a->is_const != b->is_const || a->is_volatile != b->is_volatile))\n",
    "    if (!ignore_top_qual &&\n"
    "        (a->is_const != b->is_const || a->is_volatile != b->is_volatile ||\n"
    "         a->is_restrict != b->is_restrict))\n",
)
replace_once(
    "type.c",
    "    Type *base = qualify_type(a, b->is_const, b->is_volatile, false);\n",
    "    Type *base = qualify_type(a, b->is_const, b->is_volatile, b->is_restrict);\n",
)

# Tokenization and declaration/type-name starts.
replace_once(
    "tokenize.c",
    '                         "static", "extern", "const", "volatile",\n',
    '                         "static", "extern", "const", "volatile", "restrict",\n',
)
replace_once(
    "parse.c",
    '        equal(tok, "unsigned") ||\n'
    '        equal(tok, "_Bool") || equal(tok, "float") || equal(tok, "double"))\n',
    '        equal(tok, "unsigned") || equal(tok, "const") ||\n'
    '        equal(tok, "volatile") || equal(tok, "restrict") ||\n'
    '        equal(tok, "_Bool") || equal(tok, "float") || equal(tok, "double"))\n',
)
replace_once(
    "parse.c",
    '    if (equal(tok, "const") || equal(tok, "volatile")) return true;\n',
    '    if (equal(tok, "const") || equal(tok, "volatile") || equal(tok, "restrict")) return true;\n',
)

# Validate restrict where a declaration-specifier qualifier applies to a
# typedef-derived type. Arrays recursively qualify their element type.
replace_once(
    "parse.c",
    "static Type *declspec_impl(Token **rest, Token *tok, DeclAttrs *attrs) {\n",
    "static bool is_restrict_qualifiable_type(Type *ty) {\n"
    "    if (!ty)\n"
    "        return false;\n"
    "    if (ty->kind == TY_ARRAY)\n"
    "        return is_restrict_qualifiable_type(ty->base);\n"
    "    return ty->kind == TY_PTR && ty->base && ty->base->kind != TY_FUNC;\n"
    "}\n\n"
    "static Type *declspec_impl(Token **rest, Token *tok, DeclAttrs *attrs) {\n",
)
replace_once(
    "parse.c",
    "    bool is_const = false;\n    bool is_volatile = false;\n",
    "    bool is_const = false;\n    bool is_volatile = false;\n    bool is_restrict = false;\n    Token *restrict_tok = NULL;\n",
)
replace_once(
    "parse.c",
    "        if (consume(&tok, tok, \"volatile\")) {\n"
    "            is_volatile = true;\n"
    "            continue;\n"
    "        }\n",
    "        if (consume(&tok, tok, \"volatile\")) {\n"
    "            is_volatile = true;\n"
    "            continue;\n"
    "        }\n"
    "        Token *qual_tok = tok;\n"
    "        if (consume(&tok, tok, \"restrict\")) {\n"
    "            is_restrict = true;\n"
    "            if (!restrict_tok)\n"
    "                restrict_tok = qual_tok;\n"
    "            continue;\n"
    "        }\n",
)
replace_once(
    "parse.c",
    "    if ((saw_signed || saw_unsigned) && saw_non_signable_type)\n"
    "        error_at(sign_spec->loc, \"signed/unsigned type specifier requires an integer base type\");\n"
    "    return qualify_type(ty, is_const, is_volatile, false);\n",
    "    if ((saw_signed || saw_unsigned) && saw_non_signable_type)\n"
    "        error_at(sign_spec->loc, \"signed/unsigned type specifier requires an integer base type\");\n"
    "    if (is_restrict && !is_restrict_qualifiable_type(ty))\n"
    "        error_at(restrict_tok->loc,\n"
    "                 \"restrict qualifier requires a pointer to object or incomplete type\");\n"
    "    return qualify_type(ty, is_const, is_volatile, is_restrict);\n",
)

# Pointer-declarator qualifiers: `int *restrict p` is valid, but a restricted
# pointer-to-function is not.
replace_once(
    "parse.c",
    "        bool ptr_const = false;\n"
    "        bool ptr_volatile = false;\n"
    "        while (equal(tok, \"const\") || equal(tok, \"volatile\")) {\n"
    "            if (consume(&tok, tok, \"const\"))\n"
    "                ptr_const = true;\n"
    "            else if (consume(&tok, tok, \"volatile\"))\n"
    "                ptr_volatile = true;\n"
    "        }\n"
    "        ty = qualify_type(ty, ptr_const, ptr_volatile, false);\n",
    "        bool ptr_const = false;\n"
    "        bool ptr_volatile = false;\n"
    "        bool ptr_restrict = false;\n"
    "        Token *ptr_restrict_tok = NULL;\n"
    "        while (equal(tok, \"const\") || equal(tok, \"volatile\") ||\n"
    "               equal(tok, \"restrict\")) {\n"
    "            if (consume(&tok, tok, \"const\"))\n"
    "                ptr_const = true;\n"
    "            else if (consume(&tok, tok, \"volatile\"))\n"
    "                ptr_volatile = true;\n"
    "            else {\n"
    "                ptr_restrict_tok = tok;\n"
    "                consume(&tok, tok, \"restrict\");\n"
    "                ptr_restrict = true;\n"
    "            }\n"
    "        }\n"
    "        if (ptr_restrict && !is_restrict_qualifiable_type(ty))\n"
    "            error_at(ptr_restrict_tok->loc,\n"
    "                     \"restrict qualifier requires a pointer to object or incomplete type\");\n"
    "        ty = qualify_type(ty, ptr_const, ptr_volatile, ptr_restrict);\n",
)
replace_once(
    "parse.c",
    "        (equal(tok->next, \")\") || is_typename(tok->next) ||\n"
    "         equal(tok->next, \"const\") || equal(tok->next, \"volatile\") ||\n"
    "         equal(tok->next, \"register\")))\n",
    "        (equal(tok->next, \")\") || is_typename(tok->next) ||\n"
    "         equal(tok->next, \"const\") || equal(tok->next, \"volatile\") ||\n"
    "         equal(tok->next, \"restrict\") || equal(tok->next, \"register\")))\n",
)

# Complete qualifier identity in parser-side compatibility.
replace_once(
    "parse.c",
    "    if (!ignore_top_qual &&\n"
    "        (a->is_const != b->is_const || a->is_volatile != b->is_volatile))\n",
    "    if (!ignore_top_qual &&\n"
    "        (a->is_const != b->is_const || a->is_volatile != b->is_volatile ||\n"
    "         a->is_restrict != b->is_restrict))\n",
)
replace_once(
    "parse.c",
    "            if (name || param_ty->is_const || param_ty->is_volatile ||\n",
    "            if (name || param_ty->is_const || param_ty->is_volatile ||\n"
    "                param_ty->is_restrict ||\n",
)
replace_once(
    "parse.c",
    "    if (is_typename(tok) || equal(tok, \"const\") || equal(tok, \"volatile\")) {\n",
    "    if (is_typename(tok) || equal(tok, \"const\") || equal(tok, \"volatile\") ||\n"
    "        equal(tok, \"restrict\")) {\n",
)

# Pointer-conversion qualifier safety uses immediate target qualifier sets.
# Extend every const/volatile pair test in parse.c that describes qualifier
# inclusion/equality to include restrict as well.
p = Path("parse.c")
text = p.read_text()
text = text.replace(
    "src->is_volatile && !dst->is_volatile",
    "src->is_volatile && !dst->is_volatile")
# Known pointer-target inclusion spelling used by the current semantic checker.
text = text.replace(
    "(src->is_const && !dst->is_const) ||\n        (src->is_volatile && !dst->is_volatile)",
    "(src->is_const && !dst->is_const) ||\n        (src->is_volatile && !dst->is_volatile) ||\n        (src->is_restrict && !dst->is_restrict)")
text = text.replace(
    "(from->is_const && !to->is_const) ||\n        (from->is_volatile && !to->is_volatile)",
    "(from->is_const && !to->is_const) ||\n        (from->is_volatile && !to->is_volatile) ||\n        (from->is_restrict && !to->is_restrict)")
p.write_text(text)

# Documentation and regression integration.
replace_once(
    "README.md",
    "semantic `const`/`volatile` qualifiers",
    "semantic `const`/`volatile`/`restrict` qualifiers",
)
replace_once(
    "Makefile",
    "\tbash ./test/type_qualifiers.sh\n",
    "\tbash ./test/type_qualifiers.sh\n\tbash ./test/restrict_qualifier.sh\n",
)

Path("test/restrict_qualifier.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-restrict.c
  ./minicc tmp-restrict.c > tmp-restrict.s
  cc -o tmp-restrict tmp-restrict.s
  set +e
  ./tmp-restrict
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(restrict qualifier): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-restrict.c
  ./minicc tmp-restrict.c > tmp-restrict.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-restrict-bad.c
  if ./minicc tmp-restrict-bad.c > /dev/null 2>tmp-restrict.err; then
    echo "FAIL(restrict qualifier): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Direct pointer qualifiers and combinations with const/volatile are accepted.
assert_run 0 'int main(void){int x=3;int *restrict p=&x;*p=7;return x==7?0:1;}'
assert_run 0 'int main(void){int x=4;int *restrict const p=&x;return *p==4?0:1;}'
assert_run 0 'int main(void){int x=5;int *const restrict p=&x;return *p==5?0:1;}'
assert_run 0 'int main(void){int x=6;void *restrict p=&x;return p==&x?0:1;}'

# A typedef can expose a pointer type that is then restrict-qualified.
assert_run 0 'typedef int *IP;int main(void){int x=9;IP restrict p=&x;return *p==9?0:1;}'
assert_run 0 'typedef int *IP;typedef IP A[2];int main(void){int x=2;restrict A a={&x,&x};return *a[1]==2?0:1;}'

# Top-level parameter qualifiers are ignored for function compatibility, but
# nested restrict qualification remains part of the pointed-to type identity.
assert_run 0 'int f(int *restrict p);int f(int *p){return *p;}int main(void){int x=0;return f(&x);}'
assert_compile 'int f(int *restrict);int f(int *);int main(void){return 0;}'
assert_reject 'int f(int *restrict *);int f(int **);int main(void){return 0;}'

# Address-of preserves the restricted pointer object's nested type identity.
assert_run 0 'int main(void){int *restrict p=0;return _Generic(&p,int *restrict *:0,default:1);}'

# Same-qualified object redeclarations remain compatible; dropping the object
# qualifier in a redeclaration is a conflicting type.
assert_compile 'extern int *restrict p;extern int *restrict p;int main(void){return 0;}'
assert_reject 'extern int *restrict p;extern int *p;int main(void){return 0;}'

# restrict applies only to pointer types derived from object/incomplete types.
assert_reject 'restrict int x;int main(void){return 0;}'
assert_reject 'int restrict x;int main(void){return 0;}'
assert_reject 'restrict int *p;int main(void){return 0;}'
assert_reject 'restrict void *p;int main(void){return 0;}'
assert_reject 'int f(int restrict x);int main(void){return 0;}'
assert_reject 'struct S{int restrict x;};int main(void){return 0;}'
assert_reject 'typedef int I;restrict I x;int main(void){return 0;}'
assert_reject 'typedef int F(void);restrict F f;int main(void){return 0;}'
assert_reject 'int main(void){int (*restrict fp)(void);return 0;}'
assert_reject 'int main(void){return sizeof(restrict int);}'

rm -f tmp-restrict.c tmp-restrict.s tmp-restrict \
      tmp-restrict-bad.c tmp-restrict.err

echo 'All restrict qualifier tests passed!'
''')

print("restrict qualifier migration applied")
