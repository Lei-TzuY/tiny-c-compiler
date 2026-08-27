from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = '''static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident);\n'''
insert = anchor + '''static Type *type_name(Token **rest, Token *tok);\n'''
if anchor not in s:
    raise SystemExit('forward declaration anchor not found')
s = s.replace(anchor, insert, 1)

old = '''    if (equal(tok, "(")) {\n        Token *start = tok;\n'''
new = '''    // In an abstract declarator, a leading parameter list is a function\n    // suffix rather than a grouping. Grouping forms such as `(*)` still enter\n    // the recursive parenthesized path below.\n    if (allow_abstract && equal(tok, "(") &&\n        (equal(tok->next, ")") || is_typename(tok->next) ||\n         equal(tok->next, "const") || equal(tok->next, "volatile") ||\n         equal(tok->next, "register")))\n        return type_suffix(rest, tok, ty);\n\n    if (equal(tok, "(")) {\n        Token *start = tok;\n'''
if old not in s:
    raise SystemExit('recursive grouping anchor not found')
s = s.replace(old, new, 1)

anchor = '''static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident) {\n    return declarator_impl(rest, tok, ty, ident, true);\n}\n\n'''
insert = anchor + '''// type-name = declaration-specifiers abstract-declarator?\n//\n// Casts and sizeof(type-name) use the same recursive declarator machinery as\n// declarations, so pointer/array/function grouping has one source of truth.\nstatic Type *type_name(Token **rest, Token *tok) {\n    Type *ty = declspec(&tok, tok);\n    Token *ident = NULL;\n    ty = abstract_declarator(&tok, tok, ty, &ident);\n    if (ident)\n        error_at(ident->loc, "identifier is not allowed in a type name");\n    *rest = tok;\n    return ty;\n}\n\nstatic bool invalid_sizeof_type(Type *ty) {\n    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)\n        return true;\n    if (ty->kind == TY_ARRAY && ty->array_len == 0)\n        return true;\n    return is_incomplete_object_type(ty);\n}\n\n'''
if anchor not in s:
    raise SystemExit('abstract declarator anchor not found')
s = s.replace(anchor, insert, 1)

old = '''    if (equal(tok, "(") && is_typename(tok->next)) {\n        tok = tok->next;\n        Type *ty = declspec(&tok, tok);\n        while (consume(&tok, tok, "*"))\n            ty = pointer_to(ty);\n        tok = skip(tok, ")");\n        Node *node = new_unary(ND_CAST, unary(rest, tok));\n        node->ty = ty;\n        return node;\n    }\n'''
new = '''    if (equal(tok, "(") && is_typename(tok->next)) {\n        tok = tok->next;\n        Type *ty = type_name(&tok, tok);\n        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC)\n            error_at(tok->loc, "cast specifies non-scalar type");\n        tok = skip(tok, ")");\n        Node *node = new_unary(ND_CAST, unary(rest, tok));\n        node->ty = ty;\n        return node;\n    }\n'''
if old not in s:
    raise SystemExit('cast parser anchor not found')
s = s.replace(old, new, 1)

old = '''        if (equal(tok, "(") && is_typename(tok->next)) {\n            tok = tok->next;\n            Type *ty = declspec(&tok, tok);\n            while (consume(&tok, tok, "*"))\n                ty = pointer_to(ty);\n            if (is_incomplete_object_type(ty))\n                error_at(tok->loc, "invalid sizeof on incomplete type");\n            *rest = skip(tok, ")");\n            return new_num(ty->size);\n        }\n'''
new = '''        if (equal(tok, "(") && is_typename(tok->next)) {\n            tok = tok->next;\n            Type *ty = type_name(&tok, tok);\n            if (invalid_sizeof_type(ty))\n                error_at(tok->loc, "invalid operand type for sizeof");\n            *rest = skip(tok, ")");\n            return new_num(ty->size);\n        }\n'''
if old not in s:
    raise SystemExit('sizeof parser anchor not found')
s = s.replace(old, new, 1)

# sizeof expression has the same incomplete/void/function restriction.
old = '''        if (is_incomplete_object_type(n->ty))\n            error_at(tok->loc, "invalid sizeof on incomplete type");\n        return new_num(n->ty->size);\n'''
new = '''        if (invalid_sizeof_type(n->ty))\n            error_at(tok->loc, "invalid operand type for sizeof");\n        return new_num(n->ty->size);\n'''
if old not in s:
    raise SystemExit('sizeof expression anchor not found')
s = s.replace(old, new, 1)

p.write_text(s)

mk = Path('Makefile')
m = mk.read_text()
anchor = '\tbash ./test/recursive_declarators.sh\n'
if anchor not in m:
    raise SystemExit('Makefile anchor not found')
m = m.replace(anchor, anchor + '\tbash ./test/type_names.sh\n', 1)
mk.write_text(m)

readme = Path('README.md')
r = readme.read_text()
old = '- **Declarations**: recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
new = '- **Declarations**: recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), recursive abstract type names shared by casts and `sizeof(type-name)`, local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
if old not in r:
    raise SystemExit('README declaration line not found')
r = r.replace(old, new, 1)
readme.write_text(r)

Path('test/type_names.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-type-name.c
  ./minicc tmp-type-name.c > tmp-type-name.s
  cc -o tmp-type-name tmp-type-name.s
  set +e
  ./tmp-type-name
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(type name): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(type name): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-type-name-bad.c
  if ./minicc tmp-type-name-bad.c > tmp-type-name-bad.s 2>/dev/null; then
    echo "FAIL(type name): accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(type name): rejected invalid input"
}

assert_run 8 'int main(){return sizeof(int (*)(int));}'
assert_run 8 'int main(){return sizeof(int (*)[4]);}'
assert_run 24 'int main(){return sizeof(int [2][3]);}'
assert_run 24 'int main(){return sizeof(int (*[3])(int));}'
assert_run 5 'int inc(int x){return x+1;} int main(){return ((int (*)(int))inc)(4);}'
assert_run 16 'int main(){int a[4]; int (*p)[4]=(int (*)[4])&a; return sizeof(*p);}'
assert_run 7 'int inc(int x){return x+1;} int main(){int (*fp)(int)=inc; int (**pp)(int)=(int (**)(int))&fp; return (**pp)(6);}'
assert_run 8 'typedef int Fn(int); int main(){return sizeof(Fn *);}'
assert_reject 'int main(){return sizeof(void);}'
assert_reject 'int main(){return sizeof(int (int));}'
assert_reject 'int main(){return sizeof(int []);}'
assert_reject 'int main(){return (int [2])0;}'
assert_reject 'int main(){return (int (int))0;}'
assert_reject 'int main(){return sizeof(int named);}'

echo 'All recursive type-name tests passed!'
''')
print('Abstract type-name migration applied')
