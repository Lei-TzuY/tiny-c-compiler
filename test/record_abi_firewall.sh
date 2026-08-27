#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-record-firewall.c
  ./minicc tmp-record-firewall.c > tmp-record-firewall.s
  cc -o tmp-record-firewall tmp-record-firewall.s
  set +e
  ./tmp-record-firewall
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "record ABI frontier failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(record ABI frontier): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-record-firewall-bad.c
  if ./minicc tmp-record-firewall-bad.c > tmp-record-firewall-bad.s 2>/dev/null; then
    echo 'record ABI frontier unexpectedly accepted unsupported shape'
    echo "$input"
    exit 1
  fi
  echo 'OK(record ABI frontier): rejected unsupported record ABI'
}

# Pointer boundaries and local record operations remain valid.
assert_run 7 'struct S{int x;};int get(struct S *p){return p->x;}int main(){struct S s;s.x=7;return get(&s);}'
assert_run 11 'struct S{int x;};struct S *id(struct S *p){return p;}int main(){struct S s;s.x=11;return id(&s)->x;}'
assert_run 9 'union U{int x;long y;};long get(union U *p){return p->y;}int main(){union U u;u.y=9;return get(&u);}'
assert_run 5 'struct S{int x;};int get(struct S a[]){return a[0].x;}int main(){struct S a[1];a[0].x=5;return get(a);}'

# PR #49's former blanket-rejection cases are now valid INTEGER-class ABI.
assert_run 7 'struct S{int x;};int f(struct S s){return s.x;}int main(){struct S s={7};return f(s);}'
assert_run 9 'union U{long x;};long f(union U u){return u.x;}int main(){union U u={.x=9};return f(u);}'
assert_run 6 'struct S{int x;};struct S f(void){struct S s={6};return s;}int main(){return f().x;}'
assert_run 8 'union U{long x;};union U f(void){union U u={.x=8};return u;}int main(){return f().x;}'
assert_run 4 'struct S{int x;};int id(struct S s){return s.x;}int main(){int (*fp)(struct S)=id;struct S s={4};return fp(s);}'

# Unsupported classes remain safely diagnosed at actual ABI boundaries.
assert_fail 'struct F{double x;};int f(struct F x){return 0;}int main(){return 0;}'
assert_fail 'struct M{double x;long y;};long f(struct M x){return x.y;}int main(){return 0;}'
assert_fail 'struct Big{long a;long b;long c;};long f(struct Big x){return x.a;}int main(){return 0;}'
assert_fail 'struct F{double x;};struct F f(void){struct F x={1.0};return x;}int main(){return 0;}'
assert_fail 'struct Big{long a;long b;long c;};struct Big f(void){struct Big x={1,2,3};return x;}int main(){return 0;}'

# Unsupported prototypes remain representable if never crossed.
assert_run 0 'struct F{double x;};struct F ext(struct F);int main(){return 0;}'

# Actual aggregate type still protects unprototyped/variadic paths.
assert_fail 'struct F{double x;};int f();int main(){struct F x={1.0};return f(x);}'
assert_fail 'struct F{double x;};int f(int,...);int main(){struct F x={1.0};return f(1,x);}'

echo 'All record-ABI frontier tests passed!'
