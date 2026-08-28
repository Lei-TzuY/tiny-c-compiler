#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-block-extern.c
  ./minicc tmp-block-extern.c > tmp-block-extern.s
  cc -o tmp-block-extern tmp-block-extern.s
  set +e
  ./tmp-block-extern
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(block extern initializer): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-block-extern.c
  ./minicc tmp-block-extern.c > tmp-block-extern.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-block-extern-bad.c
  if ./minicc tmp-block-extern-bad.c > /dev/null 2>tmp-block-extern.err; then
    echo "FAIL(block extern initializer): expected rejection"
    echo "$input"
    exit 1
  fi
}

# File-scope extern declarations with initializers are definitions and remain legal.
assert_run 7 'extern int x=7;int main(void){return x;}'
assert_run 3 'extern int a[3]={1,2,3};int main(void){return a[2];}'
assert_run 9 'struct S{int x;};extern struct S s={9};int main(void){return s.x;}'
assert_run 65 'extern char s[]="A";int main(void){return s[0];}'

# Ordinary block-scope extern references remain legal and reuse file-scope symbols.
assert_run 6 'int x=6;int main(void){extern int x;return x;}'
assert_run 8 'int a[2]={4,8};int main(void){extern int a[2];return a[1];}'
assert_compile 'int f(void);int main(void){extern int f(void);return 0;}'

# A block-scope extern declaration may never carry an initializer.
assert_reject 'int x;int main(void){extern int x=1;return 0;}'
assert_reject 'int main(void){extern int x=1;return 0;}'
assert_reject 'int main(void){extern int a[2]={1,2};return 0;}'
assert_reject 'struct S{int x;};int main(void){extern struct S s={3};return 0;}'
assert_reject 'int main(void){extern char s[]="x";return 0;}'
assert_reject 'int main(void){extern int x,y=2;return 0;}'
assert_reject 'int main(void){extern int x=1,y;return 0;}'

# Typedefs and declaration-specifier ordering do not bypass the constraint.
assert_reject 'typedef int I;int main(void){extern I x=1;return 0;}'
assert_reject 'int main(void){const extern int x=1;return 0;}'
assert_reject 'int main(void){extern const int x=1;return 0;}'

rm -f tmp-block-extern.c tmp-block-extern.s tmp-block-extern \
      tmp-block-extern-bad.c tmp-block-extern.err

echo 'All block-scope extern initializer tests passed!'
