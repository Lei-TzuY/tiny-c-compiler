#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-union-init.c
  ./minicc tmp-union-init.c > tmp-union-init.s
  cc -o tmp-union-init tmp-union-init.s
  set +e
  ./tmp-union-init
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "union initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(union initializer): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-union-init-bad.c
  if ./minicc tmp-union-init-bad.c > tmp-union-init-bad.s 2>/dev/null; then
    echo "union initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(union initializer): rejected invalid program"
}

# Positional union initialization selects exactly the first member.
assert_run 7 'int main(){union U{int x; long y;}; union U u={7}; return u.x;}'
assert_run 1 'int main(){union U{char c; long x;}; return sizeof(union U)==8;}'

# A member designator selects a non-first member without later implicit zeroing
# overwriting the shared storage.
assert_run 9 'int main(){union U{int x; long y;}; union U u={.y=9}; return u.y;}'
assert_run 13 'int main(){union U{int x; long y;}; union U u={.x=13}; return u.x;}'

# Static/global union images follow the same active-member rule and preserve
# full-size zeroed storage/padding.
assert_run 11 'union U{int x; long y;}; union U u={11}; int main(){return u.x;}'
assert_run 17 'union U{int x; long y;}; union U u={.y=17}; int main(){return u.y;}'
assert_run 19 'int main(){union U{int x; long y;}; static union U u={.y=19}; return u.y;}'
assert_run 1 'union U{char c; long x;}; union U u={.c=3}; int main(){return sizeof(u)==8 && u.c==3;}'

# Relocations inside a selected static union member use offset zero correctly.
assert_run 1 'int g=5; union U{int *p; long x;}; union U u={.p=&g}; int main(){return u.p==&g;}'
assert_run 1 'int f(){return 7;} union U{int (*fp)(); long x;}; union U u={.fp=f}; int main(){return u.fp()==7;}'
assert_run 1 'union U{char *p; long x;}; union U u={.p="ok"}; int main(){return u.p[0]==111 && u.p[1]==107;}'

# Union metadata survives qualifiers/forward completion.
assert_run 23 'union U; typedef const union U CU; union U{int x; long y;}; int main(){union U u={.y=23}; CU *p=&u; return p->y;}'

# C designated initializers may override an earlier union member selection;
# the last designated initializer determines the resulting stored value.
assert_run 2 'int main(){union U{int x; int y;}; union U u={.x=1,.y=2}; return u.y;}'
assert_run 7 'int main(){union U{int x; int y;}; union U u={.x=3,.x=7}; return u.x;}'
assert_run 5 'union U{int x; long y;}; union U u={.y=99,.x=5}; int main(){return u.x;}'
assert_run 8 'int main(){union U{struct {int a; int b;} s; long y;}; union U u={.s.a=3,.s.b=5}; return u.s.a+u.s.b;}'
assert_run 8 'union U{struct {int a; int b;} s; long y;}; static union U u={.s.a=3,.s.b=5}; int main(){return u.s.a+u.s.b;}'
assert_run 8 'struct W{int h;union U{struct {int a;int b;} s;long y;} u;}; static struct W w={.u.s.a=3,.u.s.b=5}; int main(){return w.u.s.a+w.u.s.b;}'
assert_run 6 'int main(){union U{struct {int a; int b;} s; long y;}; union U u={.s.a=9,.y=4,.s.b=6}; return u.s.a+u.s.b;}'

# Positional elements after the selected union member remain excess elements.
assert_fail 'int main(){union U{int x; int y;}; union U u={1,2}; return u.x;}'
assert_fail 'int main(){union U{int x; int y;}; union U u={.y=1,2}; return 0;}'
assert_fail 'union U{int x; int y;}; static union U u={1,2}; int main(){return 0;}'

# Existing struct semantics remain multi-member.
assert_run 3 'int main(){struct S{int x;int y;}; struct S s={1,2}; return s.x+s.y;}'
assert_run 7 'struct S{int x;int y;}; struct S s={3,4}; int main(){return s.x+s.y;}'

echo 'All union-initializer tests passed!'
