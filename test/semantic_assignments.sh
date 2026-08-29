#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-semassign.c
  ./minicc tmp-semassign.c > tmp-semassign.s
  cc -o tmp-semassign tmp-semassign.s
  set +e
  ./tmp-semassign
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "semantic assignment failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic assignment): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-semassign-bad.c
  if ./minicc tmp-semassign-bad.c > tmp-semassign-bad.s 2>/dev/null; then
    echo "semantic assignment unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic assignment): rejected invalid program"
}

# Numeric assignment/return conversions remain valid.
assert_run 3 'int main(){double x=3.8; int y=x; return y;}'
assert_run 7 'double f(){return 7;} int main(){return f();}'

# Compatible object pointers, void* conversions, null pointer constants.
assert_run 5 'int main(){int x=5; int *p=&x; void *v=p; int *q=v; return *q;}'
assert_run 1 'int main(){int *p=0; return p==0;}'
assert_run 4 'int f(int x){return x+1;} int main(){int (*fp)(int)=f; return fp(3);}'
assert_run 1 'int main(){int x=1; int *p=&x; _Bool b=p; return b;}'

# Array designators decay to pointers in scalar conversion contexts, so they
# are valid sources for _Bool assignment, parameter passing, and return.
assert_run 1 'int main(){int a[1]; _Bool b=a; return b;}'
assert_run 1 'int f(_Bool b){return b;} int main(){int a[1]; return f(a);}'
assert_run 1 '_Bool f(){int a[1];return a;} int main(){return f();}'

# Same record type assignment is valid and copied by codegen.
assert_run 9 'struct S{int x;}; int main(){struct S a; struct S b; b.x=9; a=b; return a.x;}'

# Return forms are constrained.
assert_run 0 'void f(){return;} int main(){f();return 0;}'

# Incompatible pointer/record assignments.
assert_fail 'int main(){int *p; double *q; p=q; return 0;}'
assert_fail 'int main(){int *p; p=1; return 0;}'
assert_fail 'int f(int x){return x;} int g(double x){return 0;} int main(){int (*p)(int)=g;return 0;}'
assert_fail 'struct A{int x;}; struct B{int x;}; int main(){struct A a; struct B b; a=b; return 0;}'

# Argument constraints for direct and indirect calls.
assert_fail 'int f(int *p){return 0;} int main(){double *q;return f(q);}'
assert_fail 'int f(int *p){return 0;} int main(){int (*fp)(int*)=f; double *q;return fp(q);}'
assert_run 0 'int f(void *p){return p!=0;} int main(){int x;return f(&x)==0;}'

# Return type constraints.
assert_fail 'int *f(){double *p;return p;} int main(){return 0;}'
assert_fail 'int f(){return;} int main(){return f();}'
assert_fail 'void f(){return 1;} int main(){f();return 0;}'

# Explicit casts remain the escape hatch for intentional conversions.
assert_run 1 'int main(){long x=1; int *p=(int*)x; return p!=0;}'

echo 'All semantic-assignment tests passed!'
