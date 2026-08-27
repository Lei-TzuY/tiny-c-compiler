#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-typecompat.c
  ./minicc tmp-typecompat.c > tmp-typecompat.s
  cc -o tmp-typecompat tmp-typecompat.s
  set +e
  ./tmp-typecompat
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "type compatibility failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(type compatibility): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-typecompat-bad.c
  if ./minicc tmp-typecompat-bad.c > tmp-typecompat-bad.s 2>/dev/null; then
    echo "type compatibility unexpectedly accepted invalid redeclaration"
    echo "$input"
    exit 1
  fi
  echo "OK(type compatibility): rejected conflict"
}

# Compatible file-scope object redeclarations merge into one symbol.
assert_run 7 'int x; int x; int main(){x=7;return x;}'
assert_run 5 'extern int x; int x=5; int main(){return x;}'
assert_run 12 'extern int a[]; int a[3]; int main(){return sizeof(a);}'
assert_run 4 'int a[4]; extern int a[]; int main(){return sizeof(a)/sizeof(int);}'
assert_run 6 'int inc(int); int inc(int x){return x+1;} int main(){return inc(5);}'
assert_run 7 'int f(int); int f(); int f(int x){return x;} int main(){return f(7);}'
assert_run 8 'int inc(int x){return x+1;} int (*fp)(int); extern int (*fp)(int); int main(){fp=inc;return fp(7);}'
assert_run 9 'struct S{int x;}; struct S obj; extern struct S obj; int main(){obj.x=9;return obj.x;}'
assert_run 3 'struct S{int x;}; struct S *p; extern struct S *p; struct S s; int main(){p=&s;p->x=3;return p->x;}'

# Recursive incompatibilities are constraints, not duplicate symbols for ld.
assert_fail 'int x; double x; int main(){return 0;}'
assert_fail 'int *x; double *x; int main(){return 0;}'
assert_fail 'int a[2]; int a[3]; int main(){return 0;}'
assert_fail 'int f(int); double f(int); int main(){return 0;}'
assert_fail 'int f(int); int f(double); int main(){return 0;}'
assert_fail 'int f(int,...); int f(int); int main(){return 0;}'
assert_fail 'int f(int); int f; int main(){return 0;}'
assert_fail 'int f; int f(int); int main(){return 0;}'
assert_fail 'int (*fp)(int); int (*fp)(double); int main(){return 0;}'
assert_fail 'struct {int x;} a; struct {int x;} a; int main(){return 0;}'
assert_fail 'int f(int x){return x;} int f(int x){return x+1;} int main(){return f(1);}'
assert_fail 'int x=1; int x=2; int main(){return x;}'

echo 'All type-compatibility tests passed!'
