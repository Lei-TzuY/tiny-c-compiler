#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-agginit.c
  ./minicc tmp-agginit.c > tmp-agginit.s
  cc -o tmp-agginit tmp-agginit.s
  set +e
  ./tmp-agginit
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "aggregate initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(aggregate initializer): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-agginit-bad.c
  if ./minicc tmp-agginit-bad.c > tmp-agginit-bad.s 2>/dev/null; then
    echo "aggregate initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(aggregate initializer): rejected invalid program"
}

# Omitted automatic array elements receive static-style zero initialization.
assert_run 1 'int main(){int a[4]={7};return a[0]==7&&a[1]==0&&a[2]==0&&a[3]==0;}'
assert_run 1 'int main(){long a[3]={1,2};return a[2]==0;}'
assert_run 1 'int main(){double a[3]={1.5};return a[1]==0.0&&a[2]==0.0;}'
assert_run 1 'int main(){int *a[3]={0};return a[1]==0&&a[2]==0;}'

# Designators leave holes zeroed and incomplete arrays infer the largest index.
assert_run 1 'int main(){int a[5]={[3]=9};return a[0]==0&&a[1]==0&&a[2]==0&&a[3]==9&&a[4]==0;}'
assert_run 1 'int main(){int a[5]={[2]=3,4};return a[0]==0&&a[1]==0&&a[2]==3&&a[3]==4&&a[4]==0;}'
assert_run 1 'int main(){int a[]={[4]=7,[1]=2};return sizeof(a)==20&&a[0]==0&&a[1]==2&&a[4]==7;}'

# Omitted record members, including nested aggregates, are recursively zeroed.
assert_run 1 'struct S{int x;long y;int *p;};int main(){struct S s={5};return s.x==5&&s.y==0&&s.p==0;}'
assert_run 1 'struct S{int x;double y;};int main(){struct S s={.y=2.5};return s.x==0&&s.y==2.5;}'
assert_run 1 'struct I{int a;int b;};struct O{struct I i;int x;};int main(){struct O o={.x=3};return o.i.a==0&&o.i.b==0&&o.x==3;}'
assert_run 1 'struct S{int a[3];int x;};int main(){struct S s={.x=4};return s.a[0]==0&&s.a[1]==0&&s.a[2]==0&&s.x==4;}'

# Fixed-size aggregate initializers reject writes beyond the declared object.
assert_fail 'int main(){int a[2]={1,2,3};return 0;}'
assert_fail 'int main(){int a[2]={[2]=1};return 0;}'
assert_fail 'struct S{int a;int b;};int main(){struct S s={1,2,3};return 0;}'
assert_fail 'int main(){static int a[2]={1,2,3};return 0;}'

# Designator categories must match the aggregate being initialized.
assert_fail 'struct S{int a;};int main(){struct S s={[0]=1};return 0;}'
assert_fail 'int main(){int a[2]={.x=1};return 0;}'

# An incomplete array needs at least one element to determine its size.
assert_fail 'int main(){int a[]={};return 0;}'

echo 'All aggregate-initializer tests passed!'
