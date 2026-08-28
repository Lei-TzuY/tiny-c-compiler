#!/bin/bash
set -eu

compile_asm() {
  input="$1"
  printf '%s\n' "$input" > tmp-fn-linkage.c
  ./minicc tmp-fn-linkage.c > tmp-fn-linkage.s
}

assert_internal() {
  expected="$1"
  input="$2"
  compile_asm "$input"
  if grep -Eq '^[[:space:]]*\.globl[[:space:]]+f([[:space:]]|$)' tmp-fn-linkage.s; then
    echo "FAIL(function linkage): internal f was emitted global"
    echo "$input"
    exit 1
  fi
  cc -o tmp-fn-linkage tmp-fn-linkage.s
  set +e
  ./tmp-fn-linkage
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function linkage): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_external() {
  expected="$1"
  input="$2"
  compile_asm "$input"
  if ! grep -Eq '^[[:space:]]*\.globl[[:space:]]+f([[:space:]]|$)' tmp-fn-linkage.s; then
    echo "FAIL(function linkage): external f was not emitted global"
    echo "$input"
    exit 1
  fi
  cc -o tmp-fn-linkage tmp-fn-linkage.s
  set +e
  ./tmp-fn-linkage
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function linkage): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# A no-storage-class function declaration has extern semantics. When a prior
# visible declaration established internal linkage, later declarations and the
# definition inherit that linkage even if `static` is not repeated.
assert_internal 3 'static int f(void);int f(void){return 3;}int main(void){return f();}'
assert_internal 4 'static int f(void);extern int f(void);int f(void){return 4;}int main(void){return f();}'
assert_internal 5 'static int f(void);extern int f(void){return 5;}int main(void){return f();}'
assert_internal 6 'static int f(void);int f(void);int f(void){return 6;}int main(void){return f();}'
assert_internal 7 'static int f();int f(void){return 7;}int main(void){return f();}'
assert_internal 8 'static int f(void);static int f(void);int f(void){return 8;}int main(void){return f();}'

# Functions with no prior internal-linkage declaration remain externally visible.
assert_external 9 'int f(void);int f(void){return 9;}int main(void){return f();}'
assert_external 10 'extern int f(void);int f(void){return 10;}int main(void){return f();}'
assert_external 11 'int f(void){return 11;}int main(void){return f();}'

rm -f tmp-fn-linkage.c tmp-fn-linkage.s tmp-fn-linkage

echo 'All function linkage emission tests passed!'
