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
    '''static Obj *register_global_symbol(Token *ident, Type *ty, bool is_static,\n                                   bool is_extern) {\n''',
    '''static Obj *register_global_symbol(Token *ident, Type *ty, bool is_static,\n                                   bool is_extern, bool has_storage_class) {\n''')

replace_once(
    "parse.c",
    '''        if (is_static && !var->is_static)\n            error_at(ident->loc, "static declaration of '%s' follows non-static declaration", name);\n\n        var->ty = composite_redecl_type(var->ty, ty);\n''',
    '''        if (is_static && !var->is_static)\n            error_at(ident->loc, "static declaration of '%s' follows non-static declaration", name);\n        // For file-scope objects, a declaration with no storage-class\n        // specifier has external linkage. Unlike an explicit `extern`, it does\n        // not inherit a prior internal linkage declaration.\n        if (!has_storage_class && var->is_static)\n            error_at(ident->loc,\n                     "non-static declaration of '%s' follows static declaration", name);\n\n        var->ty = composite_redecl_type(var->ty, ty);\n''')

replace_once(
    "parse.c",
    '''                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);\n''',
    '''                Obj *var = register_global_symbol(ident, ty, is_static, is_extern,\n                                                  attrs.storage_class_count != 0);\n''')

makefile = Path("Makefile")
text = makefile.read_text()
old = '''\tbash ./test/implicit_int_constraints.sh\n\tbash ./test/unresolved_function_calls.sh\n'''
new = '''\tbash ./test/implicit_int_constraints.sh\n\tbash ./test/object_linkage_redeclarations.sh\n\tbash ./test/unresolved_function_calls.sh\n'''
if text.count(old) != 1:
    raise SystemExit("Makefile linkage test insertion point not unique")
makefile.write_text(text.replace(old, new, 1))

readme = Path("README.md")
text = readme.read_text()
needle = "compatible file-scope object/function redeclarations with recursive type checking and composite array/prototype retention"
replacement = "compatible file-scope object/function redeclarations with recursive type checking, object linkage-transition validation, and composite array/prototype retention"
if text.count(needle) != 1:
    raise SystemExit("README linkage insertion point not unique")
readme.write_text(text.replace(needle, replacement, 1))

test = Path("test/object_linkage_redeclarations.sh")
test.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-linkage.c
  ./minicc tmp-linkage.c > tmp-linkage.s
  cc -o tmp-linkage tmp-linkage.s
  set +e
  ./tmp-linkage
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(object linkage): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-linkage.c
  ./minicc tmp-linkage.c > tmp-linkage.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-linkage-bad.c
  if ./minicc tmp-linkage-bad.c > /dev/null 2>tmp-linkage.err; then
    echo "FAIL(object linkage): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Explicit extern inherits an existing internal linkage declaration.
assert_run 3 'static int x=3;extern int x;int main(void){return x;}'
assert_run 4 'static int x;extern int x=4;int main(void){return x;}'
assert_run 5 'static int x;extern int x;static int x=5;int main(void){return x;}'

# Ordinary external-linkage declarations continue to compose with extern.
assert_run 6 'extern int x;int x=6;int main(void){return x;}'
assert_run 7 'int x=7;extern int x;int main(void){return x;}'
assert_run 8 'int x;extern int x;int main(void){x=8;return x;}'
assert_run 9 'extern int x;extern int x;int x=9;int main(void){return x;}'

# Function linkage remains on its separate C rule: a no-storage-class function
# declaration behaves like extern and therefore inherits prior internal linkage.
assert_compile 'static int f(void);int f(void);static int f(void){return 1;}int main(void){return f()-1;}'
assert_compile 'static int f(void);extern int f(void);static int f(void){return 1;}int main(void){return f()-1;}'

# A file-scope object declaration with no storage class always specifies
# external linkage. It therefore conflicts after a prior internal declaration.
assert_reject 'static int x;int x;int main(void){return 0;}'
assert_reject 'static int x;int x=1;int main(void){return 0;}'
assert_reject 'static int x=1;int x;int main(void){return 0;}'
assert_reject 'static int x;const int x;int main(void){return 0;}'
assert_reject 'static int x;extern int x;int x;int main(void){return 0;}'
assert_reject 'static int x;extern int x=1;int x;int main(void){return 0;}'
assert_reject 'static int a,b;int a;int main(void){return 0;}'

# The opposite internal-after-external transition remains rejected as before.
assert_reject 'int x;static int x;int main(void){return 0;}'
assert_reject 'extern int x;static int x;int main(void){return 0;}'
assert_reject 'int x=1;static int x;int main(void){return 0;}'

rm -f tmp-linkage.c tmp-linkage.s tmp-linkage tmp-linkage-bad.c tmp-linkage.err

echo 'All object linkage redeclaration tests passed!'
''')

print("object linkage redeclaration migration applied")
