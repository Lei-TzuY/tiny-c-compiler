#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-exprop.c
  ./minicc tmp-exprop.c > tmp-exprop.s
  cc -o tmp-exprop tmp-exprop.s
  set +e
  ./tmp-exprop
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "expression operator failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(expression operator): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-exprop-bad.c
  if ./minicc tmp-exprop-bad.c > tmp-exprop-bad.s 2>/dev/null; then
    echo "expression operator unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(expression operator): rejected invalid program"
}

# Equality: arithmetic, compatible pointers, void*, null and function pointers.
assert_run 1 'int main(){int x=1;int *p=&x;return p==&x;}'
assert_run 1 'int main(){int x;int *p=&x;return p!=0;}'
assert_run 1 'int main(){int x;int *p=&x;void *v=p;return v==p;}'
assert_run 1 'int f(){return 1;} int main(){int (*p)()=f;return p==f;}'
assert_run 1 'int main(){double x=1.0;return x==1;}'

# Relational and logical operators require compatible scalar operands.
assert_run 1 'int main(){int a[2];return &a[0] < &a[1];}'
assert_run 1 'int main(){int x=1;int *p=&x;return p && 1;}'
assert_run 1 'int f(){return 1;} int main(){return f && 1;}'
assert_run 1 'int main(){int *p=0;return !p;}'

# Conditional operator computes a composite type and normalizes both branches.
assert_run 7 'int main(){int x=7;int *p=1 ? &x : 0;return *p;}'
assert_run 8 'int main(){int x=8;int *p=0 ? 0 : &x;return *p;}'
assert_run 3 'int main(){double x=1 ? 3 : 4.5;return (int)x;}'
assert_run 4 'int main(){double x=0 ? 3 : 4.5;return (int)x;}'
assert_run 6 'struct S{int x;}; int main(){struct S a;struct S b;struct S c;a.x=6;b.x=9;c=1?a:b;return c.x;}'
assert_run 5 'int f(int x){return x;} int g(int x){return x+1;} int main(){int (*p)(int)=1?f:g;return p(5);}'

# Invalid equality/relational operands.
assert_fail 'struct S{int x;}; int main(){struct S s;return s==s;}'
assert_fail 'int main(){int *p;double *q;return p==q;}'
assert_fail 'int main(){int *p;return p==1;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){return f==g;}'
assert_fail 'int main(){int *p;double *q;return p<q;}'
assert_fail 'int main(){int *p;return p<0;}'

# Structs are not scalar logical conditions/operands.
assert_fail 'struct S{int x;}; int main(){struct S s;return s&&1;}'
assert_fail 'struct S{int x;}; int main(){struct S s;return !s;}'
assert_fail 'struct S{int x;}; int main(){struct S s;return s?1:2;}'

# Unary minus requires an arithmetic operand.  The parser represents unary
# minus as `0 - operand`, so pointer/array operands must not be mistaken for
# the valid pointer-minus-integer form.
assert_fail 'int main(){int x;int *p=&x;return -p!=0;}'
assert_fail 'int main(){int a[2];return -a!=0;}'

# Conditional alternatives must have a valid common type.
assert_fail 'int main(){int x;double y;int *p=&x;double *q=&y;return (p?q:p)!=0;}'
assert_fail 'struct A{int x;};struct B{int x;};int main(){struct A a;struct B b;return (1?a:b).x;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){return (1?f:g)!=0;}'
assert_fail 'int main(){int *p;return (1?p:3)!=0;}'

echo 'All expression-operator semantic tests passed!'
