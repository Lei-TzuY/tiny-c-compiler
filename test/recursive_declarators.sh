#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-recursive.c
  "${MINICC:-./minicc}" tmp-recursive.c > tmp-recursive.s
  gcc -o tmp-recursive tmp-recursive.s
  set +e
  ./tmp-recursive
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "recursive declarator failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(recursive declarator): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-recursive-bad.c
  if "${MINICC:-./minicc}" tmp-recursive-bad.c > tmp-recursive-bad.s 2>/dev/null; then
    echo "recursive declarator unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(recursive declarator): rejected invalid input"
}

assert_run 10 'int inc(int x){return x+1;} int dbl(int x){return x*2;} int main(){int (*table[2])(int); table[0]=inc; table[1]=dbl; return table[0](3)+table[1](3);}'
assert_run 16 'int main(){int (*table[2])(int); return sizeof(table);}'
assert_run 6 'int inc(int x){return x+1;} int (*factory(void))(int){return inc;} int main(){return factory()(5);}'
assert_run 8 'int (*factory(void))(int); int add3(int x){return x+3;} int (*factory(void))(int){return add3;} int main(){return factory()(5);}'
assert_run 32 'int main(){int (*(*p)[4])(double); return sizeof(*p);}'
assert_run 9 'typedef int Fn(int); int inc(int x){return x+1;} int main(){Fn *p=inc; return p(8);}'
assert_run 7 'int pick(int a[3]){return a[1];} int main(){int a[3]; a[1]=7; return pick(a);}'
assert_run 6 'int inc(int x){return x+1;} int apply(int cb(int), int x){return cb(x);} int main(){return apply(inc,5);}'
assert_run 8 'int inc(int x){return x+1;} int dbl(int x){return x*2;} int main(){int (*table[2])(int); int (*(*p)[2])(int)=&table; (*p)[0]=inc; (*p)[1]=dbl; return (*p)[1](4);}'
assert_run 12 'typedef int (*Fn)(int); int add4(int x){return x+4;} Fn factory(void){return add4;} int main(){return factory()(8);}'
assert_run 11 'int add5(int x){return x+5;} int (*table[2])(int); int main(){table[1]=add5; return table[1](6);}'
assert_fail 'int bad[2](int); int main(){return 0;}'

echo 'All recursive declarator tests passed!'
