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
    '''static void validate_type_specifier_set(TypeSpecState *state,\n                                        bool saw_signed, bool saw_unsigned) {\n    if (!state->first)\n        return; // Preserve this compiler's existing implicit-int behavior.\n\n''',
    '''static void validate_type_specifier_set(TypeSpecState *state,\n                                        bool saw_signed, bool saw_unsigned,\n                                        Token *end) {\n    if (!state->first)\n        error_at(end->loc, "declaration requires a type specifier");\n\n''')

replace_once(
    "parse.c",
    '''    validate_type_specifier_set(&specs, saw_signed, saw_unsigned);\n''',
    '''    validate_type_specifier_set(&specs, saw_signed, saw_unsigned, tok);\n''')

makefile = Path("Makefile")
text = makefile.read_text()
old = '''\tbash ./test/typedef_storage_class.sh\n\tbash ./test/cast_constraints.sh\n'''
new = '''\tbash ./test/typedef_storage_class.sh\n\tbash ./test/implicit_int_constraints.sh\n\tbash ./test/cast_constraints.sh\n'''
if text.count(old) != 1:
    raise SystemExit("Makefile implicit-int test insertion point not unique")
makefile.write_text(text.replace(old, new, 1))

readme = Path("README.md")
text = readme.read_text()
needle = "validated C type-specifier sets (including order-independent signed/unsigned integer forms and explicit rejection of unsupported `long double`)"
replacement = "validated C type-specifier sets (including required explicit type specifiers, order-independent signed/unsigned integer forms, and explicit rejection of unsupported `long double`)"
if text.count(needle) != 1:
    raise SystemExit("README implicit-int insertion point not unique")
readme.write_text(text.replace(needle, replacement, 1))

test = Path("test/implicit_int_constraints.sh")
test.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-implicit-int.c
  ./minicc tmp-implicit-int.c > tmp-implicit-int.s
  cc -o tmp-implicit-int tmp-implicit-int.s
  set +e
  ./tmp-implicit-int
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(implicit int): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-implicit-int.c
  ./minicc tmp-implicit-int.c > tmp-implicit-int.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-implicit-int-bad.c
  if ./minicc tmp-implicit-int-bad.c > /dev/null 2>tmp-implicit-int.err; then
    echo "FAIL(implicit int): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Explicit integer shorthand specifiers still imply int within the integer
# type-specifier family; only a completely missing type specifier is rejected.
assert_run 3 'int main(void){signed x=1;unsigned y=2;return x+y;}'
assert_run 8 'int main(void){short x=3;long y=5;return x+y;}'
assert_run 4 'int main(void){const int x=4;return x;}'
assert_run 5 'typedef int I;int main(void){const I x=5;return x;}'
assert_run 7 'int f(){return 7;}int main(void){return f();}'
assert_compile 'extern int f();int f(){return 1;}int main(void){return f();}'

# File-scope declarations and definitions need an explicit type specifier.
assert_reject 'x;int main(void){return 0;}'
assert_reject 'static x;int main(void){return 0;}'
assert_reject 'extern x;int main(void){return 0;}'
assert_reject 'const x;int main(void){return 0;}'
assert_reject 'volatile x;int main(void){return 0;}'
assert_reject '_Alignas(8) x;int main(void){return 0;}'
assert_reject 'inline f(void){return 1;}int main(void){return f();}'
assert_reject '_Noreturn f(void);int main(void){return 0;}'
assert_reject 'f(){return 1;}int main(void){return f();}'

# Block declarations cannot synthesize int from only qualifiers/storage class.
assert_reject 'int main(void){auto x=1;return x;}'
assert_reject 'int main(void){register x=1;return x;}'
assert_reject 'int main(void){static x=1;return x;}'
assert_reject 'int main(void){extern x;return 0;}'
assert_reject 'int main(void){const x=1;return x;}'
assert_reject 'int main(void){volatile x=1;return x;}'
assert_reject 'int main(void){_Alignas(8) x;return 0;}'

# typedef is a storage class, not a substitute for a type specifier.
assert_reject 'typedef T;int main(void){return 0;}'
assert_reject 'int main(void){typedef T;return 0;}'

# Parameters require declared types; the old-style empty parameter list remains
# supported, but undeclared identifier-list parameters are not synthesized int.
assert_reject 'int f(x){return x;}int main(void){return f(1);}'
assert_reject 'int f(x);int main(void){return 0;}'
assert_reject 'int f(static x);int main(void){return 0;}'
assert_reject 'int f(const x);int main(void){return 0;}'

# Type-name contexts likewise require an actual type specifier.
assert_reject 'int main(void){return sizeof(const);}'
assert_reject 'int main(void){return sizeof(volatile);}'
assert_reject 'int main(void){return sizeof(restrict);}'

rm -f tmp-implicit-int.c tmp-implicit-int.s tmp-implicit-int \
      tmp-implicit-int-bad.c tmp-implicit-int.err

echo 'All implicit-int constraint tests passed!'
''')

print("implicit-int rejection migration applied")
