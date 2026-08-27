#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-nested-string.c
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
  printf "%s\n" "$input" > tmp-nested-string-bad.c
  if ./minicc tmp-nested-string-bad.c > tmp-nested-string-bad.s 2>/dev/null; then
    echo "nested string initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(nested string initializer): rejected invalid program"
}

# Static/global aggregate character-array subobjects.
assert_run 1 'struct S{char name[4];int n;};struct S s={"abc",7};int main(){return s.name[0]==97&&s.name[2]==99&&s.name[3]==0&&s.n==7;}'
assert_run 1 'char rows[2][4]={"ab","xyz"};int main(){return rows[0][0]==97&&rows[0][2]==0&&rows[1][2]==122&&rows[1][3]==0;}'
assert_run 1 'struct S{char name[5];int n;};struct S s={.n=9,.name="hi"};int main(){return s.name[0]==104&&s.name[2]==0&&s.n==9;}'
assert_run 1 'int main(){struct S{char name[4];int n;};static struct S s={"ok",5};return s.name[1]==107&&s.name[2]==0&&s.n==5;}'
assert_run 1 'union U{char text[4];long x;};union U u={.text="abc"};int main(){return u.text[0]==97&&u.text[3]==0;}'
assert_run 1 'char rows[3][4]={[1]="xy"};int main(){return rows[0][0]==0&&rows[1][0]==120&&rows[1][2]==0&&rows[2][0]==0;}'
assert_run 1 'struct S{char name[3];int n;};struct S s={"abc",1};int main(){return s.name[0]==97&&s.name[2]==99&&s.n==1;}'
assert_run 1 'struct S{char name[4];int n;};struct S s={{"abc"},7};int main(){return s.name[1]==98&&s.name[3]==0&&s.n==7;}'

# Automatic aggregate character-array subobjects use element assignments and
# preserve aggregate zero-fill semantics for omitted rows/members.
assert_run 1 'int main(){struct S{char name[4];int n;};struct S s={"abc",7};return s.name[0]==97&&s.name[3]==0&&s.n==7;}'
assert_run 1 'int main(){char rows[2][4]={"ab","cd"};return rows[0][2]==0&&rows[1][0]==99&&rows[1][2]==0;}'
assert_run 1 'int main(){struct S{char name[5];int n;};struct S s={.n=4,.name="xy"};return s.name[1]==121&&s.name[2]==0&&s.n==4;}'
assert_run 1 'int main(){char rows[3][4]={[2]="z"};return rows[0][0]==0&&rows[1][0]==0&&rows[2][0]==122&&rows[2][1]==0;}'
assert_run 1 'int main(){union U{char text[4];long x;};union U u={.text="hey"};return u.text[0]==104&&u.text[3]==0;}'
assert_run 1 'int main(){struct S{char name[4];int n;};struct S s={{"abc"},2};return s.name[2]==99&&s.name[3]==0&&s.n==2;}'

# Pointer-from-string aggregate leaves remain scalar pointer initialization.
assert_run 1 'char *p[2]={"ab","cd"};int main(){return p[0][1]==98&&p[1][0]==99;}'
assert_run 1 'int main(){char *p[2]={"ab","cd"};return p[0][0]==97&&p[1][1]==100;}'

# String payload may omit the terminator only when the destination has exactly
# the payload width; genuinely overlong and non-character-array cases reject.
assert_fail 'struct S{char name[3];};struct S s={"abcd"};int main(){return 0;}'
assert_fail 'int main(){struct S{char name[3];};struct S s={"abcd"};return 0;}'
assert_fail 'struct S{int data[2];};struct S s={"x"};int main(){return 0;}'
assert_fail 'int main(){int rows[1][2]={"x"};return 0;}'

echo 'All nested string initializer tests passed!'
