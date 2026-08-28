#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-unresolved-call.c
  ./minicc tmp-unresolved-call.c > tmp-unresolved-call.s
  cc -o tmp-unresolved-call tmp-unresolved-call.s
  set +e
  ./tmp-unresolved-call
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(unresolved call): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-unresolved-call-bad.c
  if ./minicc tmp-unresolved-call-bad.c > /dev/null 2>tmp-unresolved-call.err; then
    echo "FAIL(unresolved call): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Declared and defined direct calls remain valid, including old-style empty
# parameter lists and calls through function-pointer objects.
assert_run 7 'int f(void){return 7;}int main(void){return f();}'
assert_run 9 'int f();int main(void){return f();}int f(void){return 9;}'
assert_run 5 'int f(void){return 5;}int main(void){int (*p)(void)=f;return p();}'
assert_run 4 'extern int f(void);int f(void){return 4;}int main(void){return f();}'
assert_run 3 'int f(int n){if(n==0)return 3;return f(n-1);}int main(void){return f(2);}'
assert_run 4 'int g(int);int f(int n){return n?g(n-1):3;}int g(int n){return n?f(n-1)+1:4;}int main(void){return f(2);}'
assert_run 8 'int main(void){extern int f(void);return f();}int f(void){return 8;}'

# C99 and later require a function declaration to be visible at the call site.
# A later declaration/definition cannot retroactively legitimize an implicit call.
assert_reject 'int main(void){return missing();}'
assert_reject 'int main(void){missing(1,2,3);return 0;}'
assert_reject 'int main(void){return misspelled_name();}int real_name(void){return 1;}'
assert_reject 'int main(void){return f();}int f(void){return 6;}'
assert_reject 'int main(void){return f();}extern int f(void);int f(void){return 6;}'
assert_reject 'int main(void){int x=f();extern int f(void);return x;}int f(void){return 6;}'

rm -f tmp-unresolved-call.c tmp-unresolved-call.s tmp-unresolved-call \
      tmp-unresolved-call-bad.c tmp-unresolved-call.err

echo 'All unresolved direct function-call tests passed!'
