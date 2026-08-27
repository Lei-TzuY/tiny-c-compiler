#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-record-abi.c
  ./minicc tmp-record-abi.c > tmp-record-abi.s
  cc -o tmp-record-abi tmp-record-abi.s
  set +e
  ./tmp-record-abi
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "record ABI firewall failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(record ABI firewall): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-record-abi-bad.c
  if ./minicc tmp-record-abi-bad.c > tmp-record-abi-bad.s 2>/dev/null; then
    echo 'record ABI firewall unexpectedly accepted unsupported program'
    echo "$input"
    exit 1
  fi
  echo 'OK(record ABI firewall): rejected unsupported record ABI'
}

# Record object operations and pointer-based function boundaries remain valid.
assert_run 7 'struct S{int x;};int get(struct S *p){return p->x;}int main(){struct S s;s.x=7;return get(&s);}'
assert_run 11 'struct S{int x;};struct S *id(struct S *p){return p;}int main(){struct S s;s.x=11;return id(&s)->x;}'
assert_run 9 'union U{int x;long y;};long get(union U *p){return p->y;}int main(){union U u;u.y=9;return get(&u);}'
assert_run 5 'struct S{int x;};int get(struct S a[]){return a[0].x;}int main(){struct S a[1];a[0].x=5;return get(a);}'

# Declarations may still describe a future/extern aggregate ABI if never used.
assert_run 0 'struct S{int x;};struct S ext(struct S);int main(){return 0;}'

# Definitions cannot require unsupported callee-side record-by-value lowering.
assert_fail 'struct S{int x;};int f(struct S s){return s.x;}int main(){return 0;}'
assert_fail 'union U{int x;};int f(union U u){return u.x;}int main(){return 0;}'
assert_fail 'struct S{int x;};struct S f(void){struct S s;s.x=1;return s;}int main(){return 0;}'
assert_fail 'union U{long x;};union U f(void){union U u;u.x=1;return u;}int main(){return 0;}'
assert_fail 'struct Big{long a;long b;long c;};struct Big f(void){struct Big x;return x;}int main(){return 0;}'

# Direct and indirect calls cannot cross an unsupported record value boundary.
assert_fail 'struct S{int x;};int f(struct S);int main(){struct S s;s.x=1;return f(s);}'
assert_fail 'struct S{int x;};struct S f(void);int main(){f();return 0;}'
assert_fail 'struct S{int x;};int (*fp)(struct S);int main(){struct S s;s.x=1;return fp(s);}'
assert_fail 'struct S{int x;};struct S (*fp)(void);int main(){fp();return 0;}'

# No-prototype and variadic tails are checked from the actual argument type.
assert_fail 'struct S{int x;};int f();int main(){struct S s;s.x=1;return f(s);}'
assert_fail 'struct S{int x;};int f(int,...);int main(){struct S s;s.x=1;return f(1,s);}'

echo 'All record-ABI firewall tests passed!'
