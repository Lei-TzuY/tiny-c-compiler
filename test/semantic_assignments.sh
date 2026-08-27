#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-semantic.c
  ./minicc tmp-semantic.c > tmp-semantic.s
  cc -o tmp-semantic tmp-semantic.s
  set +e
  ./tmp-semantic
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "semantic conversion failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic conversion): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-semantic-bad.c
  if ./minicc tmp-semantic-bad.c > tmp-semantic-bad.s 2>/dev/null; then
    echo "semantic conversion unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(semantic conversion): rejected invalid program"
}

# Numeric conversion, pointer compatibility, decay, null pointers and records.
assert_run 7 'int main(){int x=7;double d=x;return (int)d;}'
assert_run 6 'int main(){int a[2];int *p=a;p[1]=6;return a[1];}'
assert_run 5 'int main(){int x=5;int *p=&x;void *v=p;int *q=v;return *q;}'
assert_run 1 'int main(){int *p=0;return p==0;}'
assert_run 5 'int inc(int x){return x+1;} int main(){int (*fp)(int)=inc;return fp(4);}'
assert_run 9 'struct S{int x;}; int main(){struct S a;struct S b;a.x=9;b=a;return b.x;}'
assert_run 1 'int main(){int x=1;int *p=&x;_Bool b=p;return b;}'

# Returns and fixed arguments share assignment-conversion semantics.
assert_run 8 'int *id(int *p){return p;} int main(){int x=8;return *id(&x);}'
assert_run 1 'int *nil(void){return 0;} int main(){return nil()==0;}'
assert_run 4 'int first(int *p){return p[0];} int main(){int a[1];a[0]=4;return first(a);}'
assert_run 7 'int readp(void *v){int *p=v;return *p;} int main(){int x=7;return readp(&x);}'
assert_run 6 'int first(int *p){return p[0];} int main(){int a[1];a[0]=6;int (*fp)(int*)=first;return fp(a);}'
assert_run 0 'void done(void){return;} int main(){done();return 0;}'

# Incompatible assignments/initializers.
assert_fail 'int main(){int *p;double *q;p=q;return 0;}'
assert_fail 'int main(){int *p=1;return 0;}'
assert_fail 'int main(){int x;int *p=&x;x=p;return x;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){int (*fp)(int)=f;fp=g;return 0;}'
assert_fail 'struct A{int x;}; struct B{int x;}; int main(){struct A a;struct B b;a=b;return 0;}'
assert_fail 'int main(){int a[2];int b[2];a=b;return 0;}'

# Incompatible returns and direct/indirect fixed arguments.
assert_fail 'double *bad(int *p){return p;} int main(){return 0;}'
assert_fail 'void bad(void){return 1;} int main(){return 0;}'
assert_fail 'int take(int *p){return *p;} int main(){double x=1;return take(&x);}'
assert_fail 'int take(int *p){return *p;} int main(){double x=1;int (*fp)(int*)=take;return fp(&x);}'

# Explicit casts remain available for intentional low-level conversions.
assert_run 1 'int main(){long x=1;int *p=(int*)x;return p!=0;}'

echo 'All semantic-assignment tests passed!'
