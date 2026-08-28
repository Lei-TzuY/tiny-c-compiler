#!/bin/bash
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
