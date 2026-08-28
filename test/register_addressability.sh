#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-register-address.c
  ./minicc tmp-register-address.c > tmp-register-address.s
  cc -o tmp-register-address tmp-register-address.s
  set +e
  ./tmp-register-address
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(register addressability): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-register-address-bad.c
  if ./minicc tmp-register-address-bad.c > /dev/null 2>tmp-register-address.err; then
    echo "FAIL(register addressability): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Ordinary addressable objects and function designators remain valid.
assert_run 0 'int main(void){int x=3;return *&x==3?0:1;}'
assert_run 0 'int main(void){static int x=4;return *&x==4?0:1;}'
assert_run 0 'int f(int x){return *&x==x?0:1;}int main(void){return f(7);}'
assert_run 0 'int f(void){return 1;}int main(void){return (&f==f)?0:1;}'

# register changes addressability, not ordinary value access.
assert_run 0 'int main(void){register int x=5;return x==5?0:1;}'
assert_run 0 'struct S{int x;};int main(void){register struct S s={6};return s.x==6?0:1;}'

# Dereferencing a register pointer addresses the pointee, not the pointer object.
assert_run 0 'int main(void){int x=8;register int *p=&x;return &*p==p?0:1;}'
assert_run 0 'struct S{int x;};int main(void){struct S s={9};register struct S *p=&s;return &p->x==&s.x?0:1;}'
assert_run 0 'int f(register int *p){return &*p==p?0:1;}int main(void){int x=1;return f(&x);}'

# Unary & may not be applied to an object declared with register storage class.
assert_reject 'int main(void){register int x=1;int *p=&x;return *p;}'
assert_reject 'int main(void){register const int x=1;const int *p=&(x);return *p;}'
assert_reject 'int main(void){register int *p=0;int **q=&p;return q!=0;}'
assert_reject 'int main(void){register int a[2]={1,2};int (*p)[2]=&a;return (*p)[0];}'
assert_reject 'struct S{int x;};int main(void){register struct S s={1};int *p=&s.x;return *p;}'
assert_reject 'struct I{int x;};struct S{struct I i;};int main(void){register struct S s={{1}};int *p=&s.i.x;return *p;}'
assert_reject 'union U{int x;long y;};int main(void){register union U u={1};int *p=&u.x;return *p;}'
assert_reject 'int f(register int x){int *p=&x;return *p;}int main(void){return f(1);}'
assert_reject 'int f(register int *p){int **q=&p;return q!=0;}int main(void){int x;return f(&x);}'

rm -f tmp-register-address.c tmp-register-address.s tmp-register-address \
      tmp-register-address-bad.c tmp-register-address.err

echo 'All register addressability tests passed!'
