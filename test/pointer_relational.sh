#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-pointer-relational.c
  ./minicc tmp-pointer-relational.c > tmp-pointer-relational.s
  cc -o tmp-pointer-relational tmp-pointer-relational.s
  set +e
  ./tmp-pointer-relational
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "pointer relational test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-pointer-relational-bad.c
  if ./minicc tmp-pointer-relational-bad.c >/dev/null 2>&1; then
    echo "expected invalid pointer relational comparison rejection"
    echo "$input"
    exit 1
  fi
}

# Compatible object pointers may be relationally compared. Top-level
# pointed-to qualifiers do not make otherwise-compatible object types
# incompatible, and array designators undergo the usual decay.
assert_run 0 'int main(void){int a[3];int *p=&a[0];const int *q=&a[2];if(!(p<q))return 1;if(!(q>p))return 2;if(!(p<=q))return 3;if(!(q>=p))return 4;if(!(a<&a[1]))return 5;return 0;}'

# Distinct elements of a struct array use the same object-pointer ordering
# rules as scalar array elements.
assert_run 0 'struct S{int x;};int main(void){struct S a[2];struct S *p=&a[0];const struct S *q=&a[1];return (p<q&&q>p&&p<=q&&q>=p)?0:1;}'

# Relational comparisons are more restrictive than equality: void pointers,
# function pointers, incompatible object pointers, null pointer constants, and
# incompatible nested qualification are all constraint violations.
reject 'int main(void){void *p=0,*q=0;return p<q;}'
reject 'int f(void){return 0;} int g(void){return 1;} int main(void){return f<g;}'
reject 'int main(void){int *p=0;double *q=0;return p<q;}'
reject 'int main(void){int *p=0;return p<0;}'
reject 'int main(void){int **p=0;const int **q=0;return p<q;}'

rm -f tmp-pointer-relational.c tmp-pointer-relational.s tmp-pointer-relational \
      tmp-pointer-relational-bad.c

echo 'All pointer relational comparison tests passed!'
