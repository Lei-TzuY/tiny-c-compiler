#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-inline.c
  ./minicc tmp-inline.c > tmp-inline.s
  cc -o tmp-inline tmp-inline.s
  set +e
  ./tmp-inline
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "inline function specifier failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(inline): $actual"
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-inline.c
  ./minicc tmp-inline.c > tmp-inline.s
  echo 'OK(inline): accepted valid function declaration'
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-inline-bad.c
  if ./minicc tmp-inline-bad.c > tmp-inline-bad.s 2>/dev/null; then
    echo 'inline function specifier unexpectedly accepted invalid declaration'
    echo "$input"
    exit 1
  fi
  echo 'OK(inline): rejected invalid declaration'
}

# C11 permits inline on function declarations/definitions and permits function
# specifiers to appear in any order among declaration specifiers. Repeating
# inline has the same effect as writing it once.
assert_run 0 'static inline int add(int a,int b){return a+b;}int main(void){return add(20,22)==42?0:1;}'
assert_run 0 'inline static int sub(int a,int b){return a-b;}int main(void){return sub(50,8)==42?0:1;}'
assert_run 0 'inline inline static int f(int x){return x+1;}int main(void){return f(41)==42?0:1;}'

# The specifier is not part of the function type: a prior inline declaration
# remains compatible with an ordinary later definition, including indirect use.
assert_run 0 'inline int f(int);int f(int x){return x+1;}int main(void){int (*p)(int)=f;return p(41)==42?0:1;}'
assert_compile 'inline int external_decl(int); int main(void){return 0;}'

# Function specifiers are constrained to declarations of functions. Keep these
# diagnostics separate from storage-class and declarator parsing regressions.
assert_fail 'inline int object;'
assert_fail 'int main(void){inline int local;return 0;}'
assert_fail 'typedef inline int Fn(void);'
assert_fail 'struct S{inline int member;};int main(void){return 0;}'
assert_fail 'int f(inline int x);int main(void){return 0;}'
assert_fail 'inline struct S{int x;} object;int main(void){return 0;}'

rm -f tmp-inline.c tmp-inline.s tmp-inline \
      tmp-inline-bad.c tmp-inline-bad.s

echo 'All inline function specifier tests passed!'
