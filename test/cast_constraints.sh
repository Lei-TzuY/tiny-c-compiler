#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-cast.c
  ./minicc tmp-cast.c > tmp-cast.s
  cc -o tmp-cast tmp-cast.s
  set +e
  ./tmp-cast
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "cast constraint failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(cast constraint): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-cast-bad.c
  if ./minicc tmp-cast-bad.c > tmp-cast-bad.s 2>/dev/null; then
    echo "cast constraint unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(cast constraint): rejected invalid program"
}

# Arithmetic-to-arithmetic casts remain valid.
assert_run 3 'int main(){return (int)3.8;}'
assert_run 4 'int main(){double x=(double)4;return (int)x;}'
assert_run 1 'int main(){return (_Bool)7;}'

# Integer/pointer and pointer/pointer casts are permitted explicit conversions.
assert_run 1 'int main(){long x=1;int *p=(int*)x;return p!=0;}'
assert_run 7 'int main(){int x=7;void *v=(void*)&x;int *p=(int*)v;return *p;}'
assert_run 1 'int main(){int x;long n=(long)&x;return n!=0;}'

# Array and function designators decay before a scalar cast.
assert_run 6 'int main(){int a[2];a[0]=6;int *p=(int*)a;return *p;}'
assert_run 5 'int f(){return 5;}int main(){int (*p)()=(int (*)())f;return p();}'

# A cast to void may discard any expression, including aggregates and void.
assert_run 0 'struct S{int x;};int main(){struct S s;s.x=3;(void)s;return 0;}'
assert_run 0 'void f(){return;}int main(){(void)f();return 0;}'

# Non-void cast targets must be scalar, and aggregate operands cannot be cast
# to a scalar value.
assert_fail 'struct S{int x;};int main(){return ((struct S)1).x;}'
assert_fail 'struct S{int x;};int main(){struct S s;return (int)s;}'
assert_fail 'struct S{int x;};int main(){struct S s;return (void*)s!=0;}'
assert_fail 'struct S;int main(){return ((struct S)1).x;}'

# Floating-point values do not convert directly to/from pointer types in C.
assert_fail 'int main(){void *p=(void*)1.5;return p!=0;}'
assert_fail 'int main(){int x;return (double)&x!=0;}'
assert_fail 'int f(){return 1;}int main(){return (double)f!=0;}'

# A void-valued expression cannot be converted to a non-void scalar.
assert_fail 'void f(){return;}int main(){return (int)f();}'

# Arrays/functions may decay to pointers, but pointer-to-floating remains invalid.
assert_fail 'int main(){int a[2];return (double)a!=0;}'

# Cast targets that are arrays/functions remain invalid.
assert_fail 'int main(){return (int [2])0;}'
assert_fail 'int main(){return (int (int))0;}'

echo 'All cast-constraint tests passed!'
