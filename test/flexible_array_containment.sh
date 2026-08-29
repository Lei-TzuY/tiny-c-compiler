#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-fam-containment.c
  ./minicc tmp-fam-containment.c > tmp-fam-containment.s
  cc -o tmp-fam-containment tmp-fam-containment.s
  set +e
  ./tmp-fam-containment
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(flexible-array containment): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-fam-containment-bad.c
  if ./minicc tmp-fam-containment-bad.c > /dev/null 2>tmp-fam-containment.err; then
    echo "FAIL(flexible-array containment): expected rejection"
    echo "$input"
    exit 1
  fi
}

# C11 allows a structure with a flexible array member to be a union member.
# Such unions remain complete ordinary object types and may nest through unions.
assert_run 0 'struct F{int n;int data[];};union U{struct F f;long raw;};int main(void){return sizeof(union U)!=8;}'
assert_run 0 'struct F{int n;int data[];};union U{struct F f;long raw;};union V{union U u;double d;};int main(void){return sizeof(union V)!=8;}'
assert_run 0 'struct F{int n;int data[];};union U{struct F f;long raw;};struct H{union U *p;};int main(void){return sizeof(struct H)!=8;}'
assert_run 0 'struct F;typedef const struct F CF;struct F{int n;int data[];};union U{CF f;long raw;};int main(void){return sizeof(union U)!=8;}'

# Typedef aliases preserve the underlying containment semantics. In particular,
# aliasing the direct-FAM structure does not prevent legal union containment.
assert_run 0 'struct F{int n;int data[];};typedef struct F F;union U{F f;long raw;};int main(void){return sizeof(union U)!=8;}'

# The same rule applies to anonymous record members: an anonymous FAM struct may
# live in a union, and the resulting union becomes a restricted carrier.
assert_run 0 'union U{struct{int n;int data[];};long raw;};int main(void){return sizeof(union U)!=8;}'
assert_run 0 'union U{struct{int n;int data[];};long raw;};union V{union{union U u;long x;};double d;};int main(void){return sizeof(union V)!=8;}'

# A direct-FAM structure, or any union recursively carrying one, may not become
# a member of a structure.
assert_reject 'struct F{int n;int data[];};struct H{struct F f;};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};struct H{union U u;};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};union V{union U u;int x;};struct H{union V v;};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};struct H{union{struct F f;long raw;};};int main(void){return 0;}'
assert_reject 'struct H{union{struct{int n;int data[];} f;long raw;};};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};typedef union U Carrier;struct H{Carrier u;};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};typedef union U Carrier;union V{Carrier u;int x;};typedef union V Nested;struct H{Nested v;};int main(void){return 0;}'

# Anonymous direct-FAM structs are likewise forbidden when the containing
# record is a structure rather than a union.
assert_reject 'struct H{struct{int n;int data[];};};int main(void){return 0;}'

# Restricted carriers may not be array elements, including recursively nested,
# qualified, and typedef-aliased carrier unions.
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};union U a[2];int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};union V{union U u;int x;};union V a[2];int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};typedef const union U CU;CU a[2];int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};typedef union U Carrier;Carrier a[2];int main(void){return 0;}'

rm -f tmp-fam-containment.c tmp-fam-containment.s tmp-fam-containment \
      tmp-fam-containment-bad.c tmp-fam-containment.err

echo 'All recursive flexible-array containment tests passed!'
