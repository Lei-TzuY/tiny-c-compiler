#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-register-addr.c
  ./minicc tmp-register-addr.c > tmp-register-addr.s
  cc -o tmp-register-addr tmp-register-addr.s
  set +e
  ./tmp-register-addr
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(register address): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-register-addr.c
  ./minicc tmp-register-addr.c > tmp-register-addr.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-register-addr-bad.c
  if ./minicc tmp-register-addr-bad.c > /dev/null 2>tmp-register-addr.err; then
    echo "FAIL(register address): expected rejection"
    echo "$input"
    exit 1
  fi
}

# register remains a normal automatic object for value access and mutation.
assert_run 7 'int main(void){register int x=3;x+=4;return x;}'
assert_run 8 'int f(register int x){return x+1;}int main(void){return f(7);}'
assert_run 3 'struct S{int x;};int main(void){register struct S s={3};return s.x;}'

# A register pointer can be used as a pointer. &*p addresses the pointed-to
# object, not the register pointer variable itself, so it remains valid.
assert_run 0 'int main(void){int x=9;register int *p=&x;return (&*p==&x)?0:1;}'
assert_run 9 'int main(void){int x=9;register int *p=&x;return *p;}'

# register on a prototype parameter is accepted and is not part of function
# type compatibility.
assert_compile 'int f(register int);int f(int x){return x;}int main(void){return f(1);}'
assert_compile 'int f(int);int f(register int x){return x;}int main(void){return f(1);}'

# Ordinary non-register objects remain addressable.
assert_run 4 'int main(void){int x=4;int *p=&x;return *p;}'
assert_run 5 'struct S{int x;};int main(void){struct S s={5};int *p=&s.x;return *p;}'

# The address of a register object cannot be computed explicitly.
assert_reject 'int main(void){register int x=1;return &x!=0;}'
assert_reject 'int main(void){register int x=1;return &(x)!=0;}'
assert_reject 'int f(register int x){return &x!=0;}int main(void){return f(1);}'
assert_reject 'int main(void){int x=1;register int *p=&x;return &p!=0;}'
assert_reject 'int main(void){register int a=1,b=2;return &b!=0;}'
assert_reject 'typedef int I;int main(void){register I x=1;return &x!=0;}'
assert_reject 'int main(void){register int a[2];return &a!=0;}'

# Computing the address of an explicitly selected part of a register aggregate
# is forbidden as well, including nested member chains.
assert_reject 'struct S{int x;};int main(void){register struct S s={1};return &s!=0;}'
assert_reject 'struct S{int x;};int main(void){register struct S s={1};return &s.x!=0;}'
assert_reject 'struct I{int x;};struct O{struct I i;};int main(void){register struct O o={{1}};return &o.i.x!=0;}'

rm -f tmp-register-addr.c tmp-register-addr.s tmp-register-addr \
      tmp-register-addr-bad.c tmp-register-addr.err

echo 'All register address constraint tests passed!'
