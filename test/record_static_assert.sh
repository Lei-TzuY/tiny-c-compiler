#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-record-static-assert.c
  ./minicc tmp-record-static-assert.c > tmp-record-static-assert.s
  cc -o tmp-record-static-assert tmp-record-static-assert.s
  set +e
  ./tmp-record-static-assert
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(record _Static_assert): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-record-static-assert-bad.c
  if ./minicc tmp-record-static-assert-bad.c > /dev/null 2>tmp-record-static-assert.err; then
    echo "FAIL(record _Static_assert): expected rejection"
    echo "$input"
    exit 1
  fi
}

# C11 static assertions are valid struct-declarations and do not consume layout.
assert_run 3 'struct S{_Static_assert(sizeof(int)==4,"int width");int x;};int main(void){struct S s={3};return s.x;}'
assert_run 5 'union U{_Static_assert(_Alignof(long)==8,"long alignment");long x;int y;};int main(void){union U u={.x=5};return u.x;}'
assert_run 7 'enum E{K=7};struct S{int x;_Static_assert(K==7,"enum ICE");long y;};int main(void){struct S s={.x=7};return s.x;}'
assert_run 9 'struct O{struct I{_Static_assert(1,"nested");int x;} i;};int main(void){struct O o={{9}};return o.i.x;}'
assert_run 8 'struct S{char c;_Static_assert(1,"middle");int x;};int main(void){struct S s={.c=1,.x=7};return s.c+s.x;}'

# The existing evaluator and C11 two-argument grammar apply unchanged.
assert_reject 'struct S{_Static_assert(0,"record assertion failed");int x;};int main(void){return 0;}'
assert_reject 'union U{_Static_assert(2-2,"union assertion failed");int x;};int main(void){return 0;}'
assert_reject 'struct S{_Static_assert(1);int x;};int main(void){return 0;}'
assert_reject 'struct S{_Static_assert(1,123);int x;};int main(void){return 0;}'
assert_reject 'struct S{_Static_assert(sizeof(struct S)>0,"incomplete");int x;};int main(void){return 0;}'

rm -f tmp-record-static-assert.c tmp-record-static-assert.s tmp-record-static-assert \
      tmp-record-static-assert-bad.c tmp-record-static-assert.err

echo 'All record _Static_assert tests passed!'
