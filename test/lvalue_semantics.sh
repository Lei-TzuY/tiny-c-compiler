#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-lvalue.c
  ./minicc tmp-lvalue.c > tmp-lvalue.s
  cc -o tmp-lvalue tmp-lvalue.s
  set +e
  ./tmp-lvalue
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "lvalue test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-lvalue-bad.c
  if ./minicc tmp-lvalue-bad.c > tmp-lvalue-bad.s 2>/dev/null; then
    echo "lvalue test unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
}

assert_run 7 'int main(){int x=1;x=7;return x;}'
assert_run 9 'int main(){int x=1;int *p=&x;*p=9;return x;}'
assert_run 6 'struct S{int x;};int main(){struct S s;s.x=6;return s.x;}'
assert_run 8 'struct S{int x;};int main(){struct S s;struct S *p=&s;p->x=8;return s.x;}'
assert_run 5 'int main(){int x=4;int *p=&x;++*p;return x;}'
assert_run 7 'struct S{int x;};int main(){struct S s;s.x=2;s.x+=5;return s.x;}'
assert_run 3 'int main(){int a[2];a[0]=3;int (*p)[2]=&a;return (*p)[0];}'
assert_run 5 'int f(){return 5;}int main(){int (*p)()=&f;return (*p)();}'
assert_run 4 'int main(){int x=4;int *p=&x;int *q=&*p;return *q;}'
assert_run 6 'int f(){return 6;}int main(){int (*p)()=f;int (*q)()=&*p;return q();}'
assert_run 8 'int main(){double x=3;x*=2.5;return x;}'
assert_run 3 'int main(){unsigned x=13;x%=5;return x;}'
assert_run 4 'int main(){int x=1;x<<=2;return x;}'
assert_run 7 'int main(){int a[3]={1,7,9};int *p=a;p+=1;return *p;}'
assert_run 9 'int main(){int a[3]={1,7,9};int *p=a+2;p-=1;return p[1];}'
assert_fail 'int main(){1=2;return 0;}'
assert_fail 'int main(){int x=1;(x+1)=3;return x;}'
assert_fail 'int main(){int x=1,y=2;(x,y)=3;return x;}'
assert_fail 'int main(){int x=1,y=2;(1?x:y)=3;return x;}'
assert_fail 'int main(){int a[2],b[2];a=b;return 0;}'
assert_fail 'int f(){return 1;}int g(){return 2;}int main(){f=g;return 0;}'
assert_fail 'int main(){int x=1;(x+1)+=2;return x;}'
assert_fail 'int main(){int a[2];a+=1;return 0;}'
assert_fail 'int main(){int x=1;++(x+1);return x;}'
assert_fail 'int main(){int x=1;(x+1)++;return x;}'
assert_fail 'int main(){int a[2];a++;return 0;}'
assert_fail 'int f(){return 1;}int main(){++f;return 0;}'
assert_fail 'struct S{int x;};int main(){struct S s={1};s++;return 0;}'
assert_fail 'struct S{int x;};int main(){struct S s={1};--s;return 0;}'
assert_fail 'union U{int x;long y;};int main(){union U u;u.x=1;++u;return 0;}'
assert_fail 'union U{int x;long y;};int main(){union U u;u.x=1;u--;return 0;}'
assert_fail 'int main(){int *p=&42;return 0;}'
assert_fail 'int main(){int x=1;int *p=&(x+1);return 0;}'
assert_fail 'int main(){int x=1;int *p=&(int)x;return 0;}'
assert_fail 'int main(){return *42;}'
assert_fail 'int main(){void *p=0;return *p;}'
assert_fail 'int main(){void *p=0;*p=1;return 0;}'
assert_fail 'int main(){double x=3;x%=2;return 0;}'
assert_fail 'int main(){double x=3;x&=1;return 0;}'
assert_fail 'int main(){int x=3;x<<=1.5;return 0;}'
assert_fail 'int main(){int *p=0;p*=2;return 0;}'
assert_fail 'int main(){int *p=0;p+=1.5;return 0;}'
assert_fail 'int main(){void *p=0;p+=1;return 0;}'
assert_fail 'int f(){return 0;}int main(){int (*p)()=f;p-=1;return 0;}'
assert_fail 'struct S{int x;};int main(){struct S s={1};s+=1;return 0;}'

echo 'All lvalue semantic tests passed!'
