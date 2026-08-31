#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-typespec.c
  ./minicc tmp-typespec.c > tmp-typespec.s
  cc -o tmp-typespec tmp-typespec.s
  set +e
  ./tmp-typespec
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(type specifiers): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-typespec.c
  ./minicc tmp-typespec.c > tmp-typespec.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-typespec-bad.c
  if ./minicc tmp-typespec-bad.c > /dev/null 2>tmp-typespec.err; then
    echo "FAIL(type specifiers): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Legal integer specifier sets remain order-independent.
assert_run 1 'int main(void){signed char x=-1;return x<0;}'
assert_run 1 'int main(void){char signed x=-1;return x<0;}'
assert_run 1 'int main(void){unsigned char x=255;return x>0;}'
assert_run 2 'int main(void){short int x=2;return x;}'
assert_run 3 'int main(void){int short x=3;return x;}'
assert_run 4 'int main(void){signed short int x=4;return x;}'
assert_run 5 'int main(void){short unsigned int x=5;return x;}'
assert_run 6 'int main(void){long int x=6;return x;}'
assert_run 7 'int main(void){int long x=7;return x;}'
assert_run 8 'int main(void){long long int x=8;return x;}'
assert_run 9 'int main(void){long int long x=9;return x;}'
assert_run 10 'int main(void){unsigned long long int x=10;return x;}'
assert_run 11 'int main(void){long unsigned int long x=11;return x;}'
assert_run 12 'int main(void){signed x=12;return x;}'
assert_run 13 'int main(void){unsigned x=13;return x;}'
assert_run 14 'int main(void){short x=14;return x;}'
assert_run 15 'int main(void){long x=15;return x;}'
assert_run 16 'int main(void){long long x=16;return x;}'

# Typedef-name/declarator disambiguation must survive stricter validation.
assert_run 17 'typedef int T;int main(void){T T=17;return T;}'
assert_run 18 'typedef char T;int main(void){int T=18;return T;}'
assert_compile 'typedef unsigned long U;const U x=1;int main(void){return 0;}'

# Duplicate primitive base specifiers are not legal C type-specifier sets.
assert_reject 'int int x;int main(void){return 0;}'
assert_reject 'char char x;int main(void){return 0;}'
assert_reject 'short short x;int main(void){return 0;}'
assert_reject 'float float x;int main(void){return 0;}'
assert_reject 'double double x;int main(void){return 0;}'
assert_reject 'void void f(void);int main(void){return 0;}'
assert_reject '_Bool _Bool x;int main(void){return 0;}'

# Incompatible primitive families must not silently overwrite one another.
assert_reject 'int char x;int main(void){return 0;}'
assert_reject 'char int x;int main(void){return 0;}'
assert_reject 'short char x;int main(void){return 0;}'
assert_reject 'char short x;int main(void){return 0;}'
assert_reject 'short double x;int main(void){return 0;}'
assert_reject 'double short x;int main(void){return 0;}'
assert_reject 'long float x;int main(void){return 0;}'
assert_reject 'float long x;int main(void){return 0;}'
assert_reject 'long _Bool x;int main(void){return 0;}'
assert_reject '_Bool long x;int main(void){return 0;}'
assert_reject 'long void x;int main(void){return 0;}'
assert_reject 'void long x;int main(void){return 0;}'
assert_reject 'int double x;int main(void){return 0;}'
assert_reject 'double int x;int main(void){return 0;}'
assert_reject 'short long x;int main(void){return 0;}'
assert_reject 'long short x;int main(void){return 0;}'
assert_reject 'long long long x;int main(void){return 0;}'

# C permits long double in either declaration-specifier order. The x86-64
# target represents it as a 16-byte object with 16-byte alignment.
assert_run 16 'long double x;int main(void){return sizeof(x);}'
assert_run 16 'double long x;int main(void){return sizeof(x);}'
assert_reject 'long long double x;int main(void){return 0;}'

# Named/typedef types cannot be combined with another type-specifier family.
assert_reject 'struct S{int x;};struct S int y;int main(void){return 0;}'
assert_reject 'struct A{int x;};struct B{int y;};struct A struct B z;int main(void){return 0;}'
assert_reject 'enum E{A};enum E int x;int main(void){return 0;}'
assert_reject 'typedef int T;T int x;int main(void){return 0;}'
assert_reject 'typedef int T;T double x;int main(void){return 0;}'

# Signedness cannot qualify non-integer families.
assert_reject 'signed float x;int main(void){return 0;}'
assert_reject 'unsigned double x;int main(void){return 0;}'
assert_reject 'signed _Bool x;int main(void){return 0;}'
assert_reject 'unsigned void f(void);int main(void){return 0;}'

rm -f tmp-typespec.c tmp-typespec.s tmp-typespec \
      tmp-typespec-bad.c tmp-typespec.err

echo 'All type-specifier combination tests passed!'
