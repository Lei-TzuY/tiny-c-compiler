#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-cond.c
  ./minicc tmp-cond.c > tmp-cond.s
  cc -o tmp-cond tmp-cond.s
  set +e
  ./tmp-cond
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "conditional operator failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(conditional operator): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-cond-bad.c
  if ./minicc tmp-cond-bad.c > tmp-cond-bad.s 2>/dev/null; then
    echo "conditional operator unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(conditional operator): rejected invalid program"
}

# A null pointer constant in either arm produces the pointer type.
assert_run 7 'int main(){int x=7; int *p=&x; int *q=0 ? 0 : p; return *q;}'
assert_run 5 'int main(){int x=5; int *p=1 ? &x : 0; return *p;}'

# Array and function designators decay in conditional value context.
assert_run 4 'int main(){int a[2];a[1]=4;int *p=1 ? a : 0;return p[1];}'
assert_run 6 'int f(int x){return x+1;} int main(){int (*p)(int)=0 ? 0 : f;return p(5);}'

# Compatible object pointers combine pointed-to qualifiers; void* wins
# when mixed with an object pointer.
assert_run 3 'int main(){int x=3; int *p=&x; const int *cp=&x; const int *q=1?p:cp; return *q;}'
assert_run 1 'int main(){int x=1; int *p=&x; void *v=0; void *q=1?p:v; return q!=0;}'

# The first operand must be scalar, and pointer arms must be compatible.
assert_fail 'struct S{int x;}; int main(){struct S s; return s ? 1 : 2;}'
assert_fail 'int main(){int *p=0; double *q=0; return (1 ? p : q)!=0;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){return (1 ? f : g)!=0;}'

echo 'All conditional-operator tests passed!'
