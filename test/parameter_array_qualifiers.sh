#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-param-array.c
  ./minicc tmp-param-array.c > tmp-param-array.s
  cc -o tmp-param-array tmp-param-array.s
  set +e
  ./tmp-param-array
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(parameter array): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(parameter array): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-param-array-bad.c
  if ./minicc tmp-param-array-bad.c > /dev/null 2>tmp-param-array.err; then
    echo "FAIL(parameter array): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(parameter array): rejected"
}

# C11 outermost parameter-array syntax adjusts to a pointer and keeps indexing.
assert_run 7 'int f(int a[static 3]){return a[2];} int main(void){int a[3]={1,2,7};return f(a);}'
assert_run 8 'int f(int a[const static 3]){return a[2];} int main(void){int a[3]={1,2,8};return f(a);}'
assert_run 9 'int f(int a[static const 3]){return a[2];} int main(void){int a[3]={1,2,9};return f(a);}'
assert_run 10 'int f(int a[volatile static 3]){return a[2];} int main(void){int a[3]={1,2,10};return f(a);}'
assert_run 11 'int f(int a[restrict static 3]){return a[2];} int main(void){int a[3]={1,2,11};return f(a);}'
assert_run 12 'int f(int a[static const volatile restrict 3]){return a[2];} int main(void){int a[3]={1,2,12};return f(a);}'
assert_run 13 'int f(int a[const restrict]){return a[0];} int main(void){int a[1]={13};return f(a);}'

# Bracket qualifiers qualify the adjusted pointer itself. They are ignored for
# function type compatibility as top-level parameter qualifiers, but const is
# observable on the parameter object inside a definition.
assert_run 14 'int f(int a[const 3]); int f(int *a){return a[0];} int main(void){int a[3]={14};return f(a);}'
assert_run 15 'int f(int *); int f(int a[restrict 3]){return a[0];} int main(void){int a[3]={15};return f(a);}'
assert_run 16 'int f(int a[static 3]); int f(int *a){return a[0];} int main(void){int a[3]={16};return f(a);}'
assert_run 17 'typedef int F(int a[const 3]); typedef int G(int *a); int id(int *a){return *a;} int main(void){F *f=id;G *g=f;int x=17;return g(&x);}'
assert_reject 'int f(int a[const 3]){a=0;return 0;} int main(void){return 0;}'

# Only the direct outermost array derivation may carry the special syntax.
assert_run 18 'int f(int a[static 2][3]){return a[1][2];} int main(void){int a[2][3]={{0},{0,0,18}};return f(a);}'
assert_run 19 'int f(int *a[static 2]){return *a[1];} int main(void){int x=0,y=19;int *a[2]={&x,&y};return f(a);}'
assert_run 20 'int f(int (a)[const 3]){return a[0];} int main(void){int a[3]={20};return f(a);}'
assert_run 21 'int f(int ((a))[restrict static 3]){return a[0];} int main(void){int a[3]={21};return f(a);}'
assert_reject 'int f(int a[3][const 4]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[3][static 4]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int (*a)[static 3]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int (*a)[const 3]){return 0;} int main(void){return 0;}'

# Parameter-only syntax must not leak into ordinary array declarators/type names.
assert_reject 'int a[const 3]; int main(void){return 0;}'
assert_reject 'int a[static 3]; int main(void){return 0;}'
assert_reject 'int main(void){int a[restrict 3];return 0;}'
assert_reject 'int main(void){return sizeof(int [const 3]);}'

# static requires a bound; VLA-star parameter forms stay outside the current
# compiler subset rather than being silently misparsed as pointer syntax.
assert_reject 'int f(int a[static]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[const static]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[static static 3]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[*]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[const *]){return 0;} int main(void){return 0;}'

rm -f tmp-param-array.c tmp-param-array.s tmp-param-array \
      tmp-param-array-bad.c tmp-param-array.err

echo 'All parameter-array qualifier tests passed!'
