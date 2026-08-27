#!/bin/bash
set -e

assert_abi() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-abi-stack.c
  "${MINICC:-./minicc}" tmp-abi-stack.c > tmp-abi-stack.s
  gcc -o tmp-abi-stack tmp-abi-stack.s
  set +e
  ./tmp-abi-stack
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stack ABI): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(stack ABI): $actual"
}

assert_abi 28 'int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;} int main(){return sum7(1,2,3,4,5,6,7);}'
assert_abi 55 'int sum10(int a,int b,int c,int d,int e,int f,int g,int h,int i,int j){return a+b+c+d+e+f+g+h+i+j;} int main(){return sum10(1,2,3,4,5,6,7,8,9,10);}'
assert_abi 45 'double sum9(double a,double b,double c,double d,double e,double f,double g,double h,double i){return a+b+c+d+e+f+g+h+i;} int main(){return (int)sum9(1,2,3,4,5,6,7,8,9);}'
assert_abi 55 'float sum10f(float a,float b,float c,float d,float e,float f,float g,float h,float i,float j){return a+b+c+d+e+f+g+h+i+j;} int main(){return (int)sum10f(1,2,3,4,5,6,7,8,9,10);}'
assert_abi 79 'int mixed(int a,int b,int c,int d,int e,int f,double d1,double d2,double d3,double d4,double d5,double d6,double d7,double d8,int g,double d9){return g*10+(int)d9;} int main(){return mixed(1,2,3,4,5,6,1,2,3,4,5,6,7,8,7,9);}'
assert_abi 12 'int f(int a,int b,int c,int d,int e,int f,int g,double x){return g+(int)x;} int main(){return f(1,2,3,4,5,6,7,5);}'
assert_abi 14 'int f(double a,double b,double c,double d,double e,double f,double g,double h,double i,int x){return (int)i+x;} int main(){return f(1,2,3,4,5,6,7,8,9,5);}'
assert_abi 56 'int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;} int main(){return sum7(1,2,3,4,5,6,7)+sum7(1,2,3,4,5,6,7);}'
assert_abi 28 'int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;} int main(){int (*fp)(int,int,int,int,int,int,int)=sum7; return fp(1,2,3,4,5,6,7);}'
assert_abi 7 'int sprintf(char *str, char *fmt, ...); int main(){char buf[32]; sprintf(buf,"%d%d%d%d%d%d%d",1,2,3,4,5,6,7); return buf[6]-48;}'
assert_abi 28 'int sum7(int a,int b,int c,int d,int e,int f,int g); int main(){return sum7(1,2,3,4,5,6,7);} int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;}'
assert_abi 250 'int pick(unsigned char a,unsigned char b,unsigned char c,unsigned char d,unsigned char e,unsigned char f,unsigned char g){return g;} int main(){return pick(1,2,3,4,5,6,250);}'
assert_abi 18 'float last9(float a,float b,float c,float d,float e,float f,float g,float h,float i){return i*2.0f;} int main(){return (int)last9(1,2,3,4,5,6,7,8,9);}'
assert_abi 100 'double last2(double a,double b,double c,double d,double e,double f,double g,double h,double i,double j){return i*10+j;} int main(){return (int)last2(1,2,3,4,5,6,7,8,9,10);}'

echo "All SysV stack-argument ABI tests passed!"
