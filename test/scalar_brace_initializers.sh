#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-scalar-brace.c
  ./minicc tmp-scalar-brace.c > tmp-scalar-brace.s
  cc -o tmp-scalar-brace tmp-scalar-brace.s
  set +e
  ./tmp-scalar-brace
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(scalar brace initializer): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-scalar-brace-bad.c
  if ./minicc tmp-scalar-brace-bad.c > /dev/null 2>tmp-scalar-brace.err; then
    echo "FAIL(scalar brace initializer): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Automatic scalar objects: one scalar initializer may be recursively braced,
# with an optional trailing comma at each brace level.
assert_run 5 'int main(void){int x={5};return x;}'
assert_run 8 'int main(void){int x={8,};return x;}'
assert_run 9 'int main(void){int x={{9}};return x;}'
assert_run 10 'int main(void){int x={{{10,},},};return x;}'
assert_run 4 'int main(void){int x=4;int *p={{&x}};return *p;}'
assert_run 1 'int main(void){_Bool x={{9}};return x;}'
assert_run 3 'int main(void){double x={{3.5}};return x>3.0 && x<4.0 ? 3 : 0;}'

# Static/file-scope scalar paths use the same recursive rule.
assert_run 6 'int x={{6}};int main(void){return x;}'
assert_run 7 'int main(void){static int x={{{7}}};return x;}'

# Scalar leaves inside automatic aggregates and designated initializers.
assert_run 9 'int main(void){int a[2]={{3},{{6,}}};return a[0]+a[1];}'
assert_run 11 'struct S{int x;};int main(void){struct S s={{{11}}};return s.x;}'
assert_run 12 'struct S{int x;};int main(void){struct S s={.x={{12,}}};return s.x;}'
assert_run 13 'int main(void){int a[2]={[1]={{{13}}}};return a[1];}'
assert_run 15 'struct I{int x;};struct O{struct I i;};int main(void){struct O o={.i.x={{15}}};return o.i.x;}'

# Integration with C99 compound literals and #113 unknown-bound inference.
assert_run 14 'struct S{int x;};int main(void){return (struct S){.x={{14}}}.x;}'
assert_run 5 'int main(void){return (int[]){{4},{{5}}}[1];}'
assert_run 17 'int main(void){return (int){{17}};}'
assert_run 16 'int *p=&(int){{16}};int main(void){return *p;}'

# A scalar still has exactly one underlying expression.
assert_reject 'int main(void){int x={};return x;}'
assert_reject 'int main(void){int x={1,2};return x;}'
assert_reject 'int main(void){int x={{1,2}};return x;}'
assert_reject 'int main(void){int x={{1},2};return x;}'
assert_reject 'int main(void){int a[1]={{{1,2}}};return a[0];}'
assert_reject 'struct S{int x;};int main(void){struct S s={.x={{1,2}}};return s.x;}'
assert_reject 'int main(void){int *p={1};return p!=0;}'
assert_reject 'int *p=&(int){{1,2}};int main(void){return *p;}'

rm -f tmp-scalar-brace.c tmp-scalar-brace.s tmp-scalar-brace \
      tmp-scalar-brace-bad.c tmp-scalar-brace.err

echo 'All scalar brace initializer tests passed!'
