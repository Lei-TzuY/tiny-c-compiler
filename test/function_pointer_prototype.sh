#!/bin/bash
set -e

assert_fp() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-fp-proto.c
  "${MINICC:-./minicc}" tmp-fp-proto.c > tmp-fp-proto.s
  gcc -o tmp-fp-proto tmp-fp-proto.s
  set +e
  ./tmp-fp-proto
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function pointer prototype): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(function pointer prototype): $actual"
}

assert_fp 5 'double add2(double x){return x+2;} int main(){double (*fp)(double)=add2; return (int)fp(3);}'
assert_fp 6 'float twice(float x){return x*2;} int main(){float (*fp)(float)=twice; return (int)fp(3);}'
assert_fp 5 'double mix(int a,double b){return a+b;} int main(){double (*fp)(int,double)=mix; return (int)fp(2,3);}'
assert_fp 5 'double add1(double x){return x+1;} int apply(double (*cb)(double),int x){return (int)cb(x);} int main(){return apply(add1,4);}'
assert_fp 7 'typedef double (*Fn)(double); double add3(double x){return x+3;} int main(){Fn fp=add3; return (int)fp(4);}'
assert_fp 65 'int first(char *s){return s[0];} int main(){int (*fp)(char *)=first; return fp("A");}'
assert_fp 12 'double tail(int a,int b,int c,int d,int e,int f,int g,double x){return g+x;} int main(){double (*fp)(int,int,int,int,int,int,int,double)=tail; return (int)fp(1,2,3,4,5,6,7,5);}'
assert_fp 19 'int tail2(double a,double b,double c,double d,double e,double f,double g,double h,double i,int z){return (int)i+z;} int main(){int (*fp)(double,double,double,double,double,double,double,double,double,int)=tail2; return fp(1,2,3,4,5,6,7,8,9,10);}'
assert_fp 1 'int sprintf(char *s,char *fmt,...); int main(){int (*fp)(char *,char *,...)=sprintf; char b[32]; float x=1.5f; fp(b,"%g",x); return b[0]==49;}'
assert_fp 8 'double add_named(int a,double b){return a+b;} int main(){double (*fp)(int x,double y)=add_named; return (int)fp(3,5);}'

echo "All function-pointer prototype tests passed!"
