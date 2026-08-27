#!/bin/bash
set -e

assert_proto() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-proto.c
  "${MINICC:-./minicc}" tmp-proto.c > tmp-proto.s
  gcc -o tmp-proto tmp-proto.s
  set +e
  ./tmp-proto
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(prototype params): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype params): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-proto-reject.c
  if "${MINICC:-./minicc}" tmp-proto-reject.c > /dev/null 2>&1; then
    echo "FAIL(prototype params): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype params): rejected invalid definition"
}

assert_proto 28 'int sum7(int,int,int,int,int,int,int); int main(){return sum7(1,2,3,4,5,6,7);} int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;}'
assert_proto 4 'double add(double,double); int main(){return (int)add(1,3);} double add(double a,double b){return a+b;}'
assert_proto 65 'int first(char *); int main(){return first("ABC");} int first(char *s){return s[0];}'
assert_proto 9 'int mix(int a,int,double c); int main(){return mix(1,3,5);} int mix(int a,int b,double c){return a+b+(int)c;}'
assert_proto 7 'int sprintf(char *, char *, ...); int main(){char buf[16]; sprintf(buf,"%d",7); return buf[0]-48;}'
assert_proto 11 'typedef int I; int add(I,I); int main(){return add(5,6);} int add(I a,I b){return a+b;}'
assert_proto 5 'int f(void); int main(){return f();} int f(void){return 5;}'
assert_reject 'int f(int) { return 1; } int main(){return f(3);}'

echo "All unnamed prototype parameter tests passed!"
