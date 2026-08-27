#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-brace-elision.c
  ./minicc tmp-brace-elision.c > tmp-brace-elision.s
  cc -o tmp-brace-elision tmp-brace-elision.s
  set +e
  ./tmp-brace-elision
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "brace elision failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(brace elision): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-brace-elision-bad.c
  if ./minicc tmp-brace-elision-bad.c > tmp-brace-elision-bad.s 2>/dev/null; then
    echo "brace elision unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(brace elision): rejected invalid program"
}

# Static/global positional brace elision.
assert_run 1 'int a[2][2]={1,2,3,4};int main(){return a[0][0]==1&&a[0][1]==2&&a[1][0]==3&&a[1][1]==4;}'
assert_run 1 'int a[][2]={1,2,3,4};int main(){return sizeof(a)/sizeof(a[0])==2&&a[1][1]==4;}'
assert_run 1 'struct S{int a[2];int b;};struct S s={1,2,3};int main(){return s.a[0]==1&&s.a[1]==2&&s.b==3;}'
assert_run 1 'struct I{int x;int y;};struct O{struct I i;int z;};struct O o={1,2,3};int main(){return o.i.x==1&&o.i.y==2&&o.z==3;}'
assert_run 1 'int a[2][2]={1};int main(){return a[0][0]==1&&a[0][1]==0&&a[1][0]==0&&a[1][1]==0;}'
assert_run 1 'union U{struct P{int x;int y;} p;long z;};union U u={1,2};int main(){return u.p.x==1&&u.p.y==2;}'
assert_run 1 'int main(){static int a[2][2]={5,6,7,8};return a[0][1]==6&&a[1][0]==7;}'
assert_run 1 'int x=3,y=4;struct S{int *p[2];int n;};struct S s={&x,&y,9};int main(){return *s.p[0]==3&&*s.p[1]==4&&s.n==9;}'
assert_run 1 'struct S{char rows[2][3];int n;};struct S s={"ab","c",7};int main(){return s.rows[0][1]==98&&s.rows[1][0]==99&&s.n==7;}'

# Automatic aggregates: elided and explicit nested braces share the same
# recursive subobject initializer and preserve implicit zero-fill.
assert_run 1 'int main(){int a[2][2]={1,2,3,4};return a[0][1]==2&&a[1][0]==3;}'
assert_run 1 'int main(){int a[2][2]={{1,2},{3,4}};return a[0][0]==1&&a[1][1]==4;}'
assert_run 1 'int main(){struct S{int a[2];int b;};struct S s={1,2,3};return s.a[1]==2&&s.b==3;}'
assert_run 1 'int main(){struct I{int x;int y;};struct O{struct I i;int z;};struct O o={1,2,3};return o.i.y==2&&o.z==3;}'
assert_run 1 'int main(){int a[2][2]={1};return a[0][0]==1&&a[0][1]==0&&a[1][1]==0;}'
assert_run 1 'int main(){union U{struct P{int x;int y;} p;long z;};union U u={1,2};return u.p.x==1&&u.p.y==2;}'
assert_run 1 'int main(){int x=3,y=4;struct S{int *p[2];int n;};struct S s={&x,&y,8};return *s.p[0]==3&&*s.p[1]==4&&s.n==8;}'
assert_run 1 'int main(){struct S{char rows[2][3];int n;};struct S s={"ab","c",6};return s.rows[0][1]==98&&s.rows[1][1]==0&&s.n==6;}'

# Fixed aggregate bounds still reject values that remain after all subobjects
# have been consumed.
assert_fail 'int a[1][2]={1,2,3};int main(){return 0;}'
assert_fail 'int main(){int a[1][2]={1,2,3};return 0;}'
assert_fail 'struct S{int a[1];int b;};struct S s={1,2,3};int main(){return 0;}'
assert_fail 'int main(){struct S{int a[1];int b;};struct S s={1,2,3};return 0;}'

echo 'All aggregate brace-elision tests passed!'
