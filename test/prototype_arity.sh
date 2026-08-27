#!/bin/bash
set -e

assert_ok() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-arity.c
  "${MINICC:-./minicc}" tmp-arity.c > tmp-arity.s
  gcc -o tmp-arity tmp-arity.s
  set +e
  ./tmp-arity
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(prototype arity): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype arity): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-arity-bad.c
  if "${MINICC:-./minicc}" tmp-arity-bad.c > tmp-arity-bad.s 2>/dev/null; then
    echo "FAIL(prototype arity): accepted invalid argument count"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype arity): rejected invalid argument count"
}

# Real prototypes are strict.
assert_ok 3 'int zero(void){return 3;} int main(){return zero();}'
assert_ok 6 'int sum(int a,int b,...){return a+b;} int main(){return sum(1,5,7,9);}'
assert_ok 7 'int old(); int main(){return old(7);} int old(int x){return x;}'
assert_ok 5 'int one(int x){return x;} int main(){int (*fp)()=one; return fp(5);}'

assert_reject 'int add(int,int); int main(){return add(1);}'
assert_reject 'int add(int,int); int main(){return add(1,2,3);}'
assert_reject 'int zero(void); int main(){return zero(1);}'
assert_reject 'int sum(int,int,...); int main(){return sum(1);}'
assert_reject 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add; return fp(1);}'
assert_reject 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add; return (fp)(1,2,3);}'
assert_reject 'int apply(int (*)(int),int); int inc(int x){return x+1;} int main(){return apply(inc);}'
assert_reject 'int apply(int (*)(int),int); int inc(int x){return x+1;} int main(){return apply(inc,1,2);}'

# A prior prototype is not erased by a later old-style declaration.
assert_reject 'int add(int,int); int add(); int main(){return add(1);}'

echo "All prototype arity tests passed!"
