#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-compound-once.c
  ./minicc tmp-compound-once.c > tmp-compound-once.s
  cc -o tmp-compound-once tmp-compound-once.s
  set +e
  ./tmp-compound-once
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "compound-assignment single-evaluation test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(compound-assignment single evaluation): $actual"
}

# C compound assignment evaluates its left operand only once.  These cases
# deliberately put observable side effects in different lvalue shapes so a
# lowering equivalent to `E1 = E1 op E2` is caught immediately.
assert_run 0 'int main(void){int a[2]={1,9};int i=0;a[i++]+=5;return !(i==1&&a[0]==6&&a[1]==9);}'

assert_run 0 'int main(void){int a[2]={4,7};int *p=a;*p++*=3;return !(p==a+1&&a[0]==12&&a[1]==7);}'

assert_run 0 'struct S{int x;};int main(void){struct S a[2]={{8},{20}};int i=0;a[i++].x-=3;return !(i==1&&a[0].x==5&&a[1].x==20);}'

assert_run 0 'int calls;int x=10;int *getp(void){calls++;return &x;}int main(void){*getp()/=2;return !(calls==1&&x==5);}'

assert_run 0 'int calls;unsigned x=13;unsigned *getp(void){calls++;return &x;}int main(void){*getp()%=5;return !(calls==1&&x==3);}'

assert_run 0 'int calls;int x=3;int *getp(void){calls++;return &x;}int main(void){*getp()<<=2;return !(calls==1&&x==12);}'

rm -f tmp-compound-once.c tmp-compound-once.s tmp-compound-once

echo 'All compound-assignment single-evaluation tests passed!'
