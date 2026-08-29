#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-empty-init.c
  ./minicc tmp-empty-init.c > tmp-empty-init.s
  cc -o tmp-empty-init tmp-empty-init.s
  set +e
  ./tmp-empty-init
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(empty initializer): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-empty-init-bad.c
  if ./minicc tmp-empty-init-bad.c > /dev/null 2>tmp-empty-init.err; then
    echo "FAIL(empty initializer): expected C11 rejection"
    echo "$input"
    exit 1
  fi
}

# Non-empty lists remain the standard spelling for zero/value initialization.
assert_run 0 'int main(void){int a[2]={0};return a[0]+a[1];}'
assert_run 3 'struct S{int x;int y;};int main(void){struct S s={.x=3};return s.x+s.y;}'
assert_run 4 'union U{int x;long y;};int main(void){union U u={.x=4};return u.x;}'
assert_run 5 'int main(void){return (int[2]){5,0}[0];}'
assert_run 120 'int main(void){char a[2]={"x"};return a[0];}'

# C11 does not have C23's empty initializer-list. Reject it for ordinary,
# static, nested and inferred aggregates rather than treating it as all-zero.
assert_reject 'int main(void){int a[2]={};return a[0];}'
assert_reject 'struct S{int x;};int main(void){struct S s={};return s.x;}'
assert_reject 'union U{int x;long y;};int main(void){union U u={};return u.x;}'
assert_reject 'int main(void){int a[]={};return 0;}'
assert_reject 'int main(void){static int a[2]={};return a[0];}'
assert_reject 'struct S{int x;};int main(void){static struct S s={};return s.x;}'
assert_reject 'int a[2]={};int main(void){return a[0];}'
assert_reject 'int a[]={};int main(void){return 0;}'
assert_reject 'struct S{int x;};struct S s={};int main(void){return s.x;}'
assert_reject 'union U{int x;long y;};union U u={};int main(void){return u.x;}'

# Nested explicit braces are initializer-lists too, so each must be non-empty.
assert_reject 'int main(void){int a[1][1]={{}};return 0;}'
assert_reject 'struct I{int x;};struct O{struct I i;};int main(void){struct O o={{}};return 0;}'
assert_reject 'struct I{int x;};struct O{struct I i;};int main(void){struct O o={.i={}};return 0;}'

# Compound literals reuse the same automatic/static aggregate parsers.
assert_reject 'int main(void){return (int[2]){}[0];}'
assert_reject 'struct S{int x;};int main(void){return (struct S){}.x;}'
assert_reject 'int *p=(int[2]){};int main(void){return p[0];}'
assert_reject 'struct S{int x;};struct S *p=&(struct S){};int main(void){return p->x;}'

# Scalar empty braces were already invalid and remain so.
assert_reject 'int main(void){int x={};return x;}'

rm -f tmp-empty-init.c tmp-empty-init.s tmp-empty-init \
      tmp-empty-init-bad.c tmp-empty-init.err

echo 'All C11 empty-initializer constraint tests passed!'
