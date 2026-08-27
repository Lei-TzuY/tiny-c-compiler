#!/bin/bash
set -e

assert_call() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-callable.c
  "${MINICC:-./minicc}" tmp-callable.c > tmp-callable.s
  gcc -o tmp-callable tmp-callable.s
  set +e
  ./tmp-callable
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(callable declarator): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(callable declarator): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-callable-bad.c
  if "${MINICC:-./minicc}" tmp-callable-bad.c > tmp-callable-bad.s 2>/dev/null; then
    echo "FAIL(callable declarator): accepted invalid call"
    echo "$input"
    exit 1
  fi
  echo "OK(callable declarator): rejected non-callable expression"
}

assert_call 5 'double add2(double x){return x+2;} int main(){double (*fp)(double)=add2; return (int)(fp)(3);}'
assert_call 5 'double add2(double x){return x+2;} int main(){double (*fp)(double)=add2; return (int)(*fp)(3);}'
assert_call 8 'int add(int a,int b){return a+b;} int main(){return (add)(3,5);}'
assert_call 8 'int add(int a,int b){return a+b;} int main(){return (&add)(3,5);}'
assert_call 8 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add; int (**pp)(int,int)=&fp; return (**pp)(3,5);}'
assert_call 5 'int add1(int x){return x+1;} int add2(int x){return x+2;} int main(){int (*a)(int)=add1; int (*b)(int)=add2; return (0?a:b)(3);}'
assert_call 7 'int add4(int x){return x+4;} int main(){int (*fp)(int)=add4; return (0,fp)(3);}'
assert_call 5 'int apply(int (*)(int), int); int inc(int x){return x+1;} int apply(int (*f)(int),int x){return f(x);} int main(){return apply(inc,4);}'
assert_call 6 'typedef int (*Apply)(int (*)(int),int); int inc(int x){return x+1;} int apply(int (*f)(int),int x){return f(x);} int main(){Apply p=apply; return p(inc,5);}'
assert_call 1 'int sprintf(char *s,char *fmt,...); int main(){int (*fp)(char *,char *,...)=sprintf; char b[32]; float x=2.5f; (fp)(b,"%g",x); return b[0]==50;}'
assert_reject 'int main(){int x=3; return (x)(1);}'

echo "All callable-expression/declarator tests passed!"
