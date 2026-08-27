#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-type-name.c
  ./minicc tmp-type-name.c > tmp-type-name.s
  cc -o tmp-type-name tmp-type-name.s
  set +e
  ./tmp-type-name
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(type name): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(type name): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-type-name-bad.c
  if ./minicc tmp-type-name-bad.c > tmp-type-name-bad.s 2>/dev/null; then
    echo "FAIL(type name): accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(type name): rejected invalid input"
}

assert_run 8 'int main(){return sizeof(int (*)(int));}'
assert_run 8 'int main(){return sizeof(int (*)[4]);}'
assert_run 24 'int main(){return sizeof(int [2][3]);}'
assert_run 24 'int main(){return sizeof(int (*[3])(int));}'
assert_run 5 'int inc(int x){return x+1;} int main(){return ((int (*)(int))inc)(4);}'
assert_run 16 'int main(){int a[4]; int (*p)[4]=(int (*)[4])&a; return sizeof(*p);}'
assert_run 7 'int inc(int x){return x+1;} int main(){int (*fp)(int)=inc; int (**pp)(int)=(int (**)(int))&fp; return (**pp)(6);}'
assert_run 8 'typedef int Fn(int); int main(){return sizeof(Fn *);}'
assert_reject 'int main(){return sizeof(void);}'
assert_reject 'int main(){return sizeof(int (int));}'
assert_reject 'int main(){return sizeof(int []);}'
assert_reject 'int main(){return (int [2])0;}'
assert_reject 'int main(){return (int (int))0;}'
assert_reject 'int main(){return sizeof(int named);}'

echo 'All recursive type-name tests passed!'
