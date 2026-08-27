#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-nested-string.c
  ./minicc tmp-nested-string.c > tmp-nested-string.s
  cc -o tmp-nested-string tmp-nested-string.s
  set +e
  ./tmp-nested-string
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "nested string initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(nested string initializer): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-nested-string-bad.c
  if ./minicc tmp-nested-string-bad.c > tmp-nested-string-bad.s 2>/dev/null; then
    echo 'nested string initializer unexpectedly accepted invalid program'
    echo "$input"
    exit 1
  fi
  echo 'OK(nested string initializer): rejected invalid program'
}

# Automatic record members accept direct and designated string initializers.
assert_run 1 'struct S{char name[4];int n;};int main(){struct S s={"abc",7};return s.name[0]==97&&s.name[2]==99&&s.name[3]==0&&s.n==7;}'
assert_run 1 'struct S{int n;char name[5];};int main(){struct S s={.name="xy"};return s.n==0&&s.name[0]==120&&s.name[2]==0&&s.name[4]==0;}'
assert_run 1 'struct S{unsigned char name[4];};int main(){struct S s={.name="ab"};return s.name[1]==98&&s.name[2]==0;}'

# Character matrices use each string literal to initialize one nested array.
assert_run 1 'int main(){char a[2][4]={"abc","de"};return a[0][3]==0&&a[1][0]==100&&a[1][2]==0;}'
assert_run 1 'int main(){char a[3][4]={[1]="xy"};return a[0][0]==0&&a[1][1]==121&&a[1][2]==0&&a[2][0]==0;}'
assert_run 1 'int main(){char a[2][4]={{"a"},{"bc"}};return a[0][1]==0&&a[1][0]==98&&a[1][2]==0;}'

# A destination exactly as wide as the payload may omit the terminating NUL.
assert_run 1 'struct S{char tag[3];};int main(){struct S s={"abc"};return s.tag[0]==97&&s.tag[2]==99;}'

# Union initialization selects its character-array member without overlapping
# zero-fill clobbering the copied bytes.
assert_run 1 'int main(){union U{char name[4];int x;};union U u={"ab"};return u.name[0]==97&&u.name[1]==98&&u.name[2]==0;}'
assert_run 1 'int main(){union U{int x;char name[4];};union U u={.name="cd"};return u.name[0]==99&&u.name[1]==100&&u.name[2]==0;}'

# Global/static aggregate byte images apply the same rule.
assert_run 1 'struct S{char name[4];int n;};struct S s={"abc",9};int main(){return s.name[1]==98&&s.name[3]==0&&s.n==9;}'
assert_run 1 'struct S{int n;char name[5];};struct S s={.name="xy"};int main(){return s.n==0&&s.name[2]==0&&s.name[4]==0;}'
assert_run 1 'char a[2][4]={"abc","de"};int main(){return a[0][2]==99&&a[1][1]==101&&a[1][2]==0;}'
assert_run 1 'char a[3][4]={[2]="z"};int main(){return a[0][0]==0&&a[1][0]==0&&a[2][0]==122&&a[2][1]==0;}'
assert_run 1 'int main(){static struct S{char name[4];int n;} s={"hi",3};return s.name[0]==104&&s.name[2]==0&&s.n==3;}'
assert_run 1 'union U{char name[4];long x;};union U u={"ok"};int main(){return u.name[0]==111&&u.name[1]==107&&u.name[2]==0;}'

# String expressions for pointer members remain pointer initializers, not array
# byte copies.
assert_run 1 'struct S{char *p;char name[4];};struct S s={"ptr","xy"};int main(){return s.p[1]==116&&s.name[1]==121;}'

# Nested arrays retain normal width/type constraints.
assert_fail 'struct S{char name[2];};int main(){struct S s={"abc"};return 0;}'
assert_fail 'struct S{char name[2];};struct S s={.name="abc"};int main(){return 0;}'
assert_fail 'int main(){char a[1][2]={"abc"};return 0;}'
assert_fail 'struct S{int a[2];};int main(){struct S s={"ab"};return 0;}'

rm -f tmp-nested-string.c tmp-nested-string.s tmp-nested-string \
      tmp-nested-string-bad.c tmp-nested-string-bad.s

echo 'All nested string initializer tests passed!'
