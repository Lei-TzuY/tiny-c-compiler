#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-alignas.c
  "${MINICC:-./minicc}" tmp-alignas.c > tmp-alignas.s
  cc -o tmp-alignas tmp-alignas.s
  set +e
  ./tmp-alignas
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(_Alignas): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(_Alignas): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-alignas-reject.c
  if "${MINICC:-./minicc}" tmp-alignas-reject.c > /dev/null 2>&1; then
    echo "FAIL(_Alignas): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(_Alignas): rejected"
}

# File/static/local object alignment, including storage-class ordering.
assert_run 0 '_Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 'static _Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(16) static char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 'int main(void){_Alignas(16) char x; return (unsigned long)&x % 16;}'
assert_run 0 'int main(void){static _Alignas(16) char x; return (unsigned long)&x % 16;}'

# Type-name and integer-constant-expression forms, 0, and multiple specifiers.
assert_run 0 '_Alignas(double) char g; int main(void){return (unsigned long)&g % 8;}'
assert_run 0 'enum{A=16}; _Alignas(A) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(1<<4) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(0) char g; int main(void){return g;}'
assert_run 0 '_Alignas(8) _Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 '_Alignas(16) char a,b; int main(void){return ((unsigned long)&a % 16) || ((unsigned long)&b % 16);}'

# Record/union member alignment participates in offsets, aggregate alignment and size.
assert_run 0 'struct S{char a; _Alignas(8) int b;}; int main(void){struct S s; return sizeof(struct S)!=16 || _Alignof(struct S)!=8 || (char*)&s.b-(char*)&s!=8;}'
assert_run 0 'union U{_Alignas(16) char c; long x;}; int main(void){return sizeof(union U)!=16 || _Alignof(union U)!=16;}'
assert_run 0 'struct S{_Alignas(double) char c; char d;}; int main(void){return sizeof(struct S)!=8 || _Alignof(struct S)!=8;}'

# Alignment survives compatible file-scope redeclarations, including omitted specifier.
assert_run 0 'extern _Alignas(16) char g; char g; int main(void){return (unsigned long)&g % 16;}'
assert_run 0 'extern _Alignas(16) char g; _Alignas(16) char g; int main(void){return (unsigned long)&g % 16;}'

# Invalid values/contexts and conflicting declarations.
assert_reject '_Alignas(3) int x; int main(void){return 0;}'
assert_reject '_Alignas(32) char x; int main(void){return 0;}'
assert_reject '_Alignas(2) int x; int main(void){return 0;}'
assert_reject 'int n=8; _Alignas(n) char x; int main(void){return 0;}'
assert_reject '_Alignas(1.5) char x; int main(void){return 0;}'
assert_reject '_Alignas(void) char x; int main(void){return 0;}'
assert_reject '_Alignas(int(void)) char x; int main(void){return 0;}'
assert_reject '_Alignas(16) int f(void); int main(void){return 0;}'
assert_reject 'int f(_Alignas(16) int x){return x;}'
assert_reject 'typedef _Alignas(16) int T; int main(void){return 0;}'
assert_reject 'int main(void){_Alignas(16) register char x; return 0;}'
assert_reject 'extern _Alignas(8) char g; _Alignas(16) char g; int main(void){return 0;}'
assert_reject 'struct S{_Alignas(1) int x;}; int main(void){return 0;}'

echo 'All _Alignas tests passed!'
