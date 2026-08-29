from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


# record_decl appears before the existing parser implementation, so expose a
# local forward declaration rather than duplicating static-assert evaluation.
replace_once(
    "parse.c",
    '''static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident);\n''',
    '''static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident);\nstatic Token *parse_static_assertion(Token *tok);\n''')

# C11 permits static_assert-declaration as a struct-declaration. Reuse the same
# parser/evaluator as file/block scope; successful assertions do not create a
# Member and therefore do not affect record layout.
replace_once(
    "parse.c",
    '''    bool has_flexible_member = false;\n    while (!equal(tok, "}")) {\n        DeclAttrs attrs = {};\n''',
    '''    bool has_flexible_member = false;\n    while (!equal(tok, "}")) {\n        if (equal(tok, "_Static_assert")) {\n            tok = parse_static_assertion(tok);\n            continue;\n        }\n\n        DeclAttrs attrs = {};\n''')

Path("test/record_static_assert.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-record-static-assert.c
  ./minicc tmp-record-static-assert.c > tmp-record-static-assert.s
  cc -o tmp-record-static-assert tmp-record-static-assert.s
  set +e
  ./tmp-record-static-assert
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(record _Static_assert): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-record-static-assert-bad.c
  if ./minicc tmp-record-static-assert-bad.c > /dev/null 2>tmp-record-static-assert.err; then
    echo "FAIL(record _Static_assert): expected rejection"
    echo "$input"
    exit 1
  fi
}

# C11 static assertions are valid struct-declarations and do not consume layout.
assert_run 3 'struct S{_Static_assert(sizeof(int)==4,"int width");int x;};int main(void){struct S s={3};return s.x;}'
assert_run 5 'union U{_Static_assert(_Alignof(long)==8,"long alignment");long x;int y;};int main(void){union U u={.x=5};return u.x;}'
assert_run 7 'enum E{K=7};struct S{int x;_Static_assert(K==7,"enum ICE");long y;};int main(void){struct S s={.x=7};return s.x;}'
assert_run 9 'struct O{struct I{_Static_assert(1,"nested");int x;} i;};int main(void){struct O o={{9}};return o.i.x;}'
assert_run 8 'struct S{char c;_Static_assert(1,"middle");int x;};int main(void){struct S s={.c=1,.x=7};return s.c+s.x;}'

# The existing evaluator and C11 two-argument grammar apply unchanged.
assert_reject 'struct S{_Static_assert(0,"record assertion failed");int x;};int main(void){return 0;}'
assert_reject 'union U{_Static_assert(2-2,"union assertion failed");int x;};int main(void){return 0;}'
assert_reject 'struct S{_Static_assert(1);int x;};int main(void){return 0;}'
assert_reject 'struct S{_Static_assert(1,123);int x;};int main(void){return 0;}'
assert_reject 'struct S{_Static_assert(sizeof(struct S)>0,"incomplete");int x;};int main(void){return 0;}'

rm -f tmp-record-static-assert.c tmp-record-static-assert.s tmp-record-static-assert \
      tmp-record-static-assert-bad.c tmp-record-static-assert.err

echo 'All record _Static_assert tests passed!'
''')

makefile = Path("Makefile")
text = makefile.read_text()
needle = "\tbash ./test/duplicate_record_members.sh\n"
if text.count(needle) != 1:
    raise SystemExit("Makefile duplicate-member test anchor not unique")
makefile.write_text(text.replace(needle, needle + "\tbash ./test/record_static_assert.sh\n", 1))

readme = Path("README.md")
text = readme.read_text()
old = "C11 `_Static_assert(integer-constant-expression, \"message\")` at file and block scope"
new = "C11 `_Static_assert(integer-constant-expression, \"message\")` at file, block, and struct/union definition scope"
if text.count(old) != 1:
    raise SystemExit("README static-assert wording not unique")
readme.write_text(text.replace(old, new, 1))

print("record _Static_assert support applied")
