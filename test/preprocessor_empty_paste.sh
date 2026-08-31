#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

run_case() {
  expected="$1"
  input="$2"

  printf '%s\n' "$input" > tmp-pp-empty-paste.c

  # Keep GCC/Clang as an independent oracle for the C preprocessing semantics.
  cc -std=c11 -pedantic-errors -o tmp-pp-empty-paste-host tmp-pp-empty-paste.c
  set +e
  ./tmp-pp-empty-paste-host
  host_actual="$?"
  set -e
  if [ "$host_actual" != "$expected" ]; then
    echo "FAIL(empty-paste host oracle): expected $expected, got $host_actual"
    exit 1
  fi

  "$MINICC" tmp-pp-empty-paste.c > tmp-pp-empty-paste.s
  cc -o tmp-pp-empty-paste tmp-pp-empty-paste.s
  set +e
  ./tmp-pp-empty-paste
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(empty-paste): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(empty-paste): $actual"
}

# C placemarker semantics: an empty actual argument adjacent to ## behaves as
# an empty preprocessing token, so the non-empty side survives unchanged.
run_case 0 '#define CAT(a,b) a ## b
int left=17; int main(void){return CAT(left,)!=17;}'
run_case 0 '#define CAT(a,b) a ## b
int right=19; int main(void){return CAT(,right)!=19;}'

# A placemarker in the middle of a paste chain disappears, allowing the two
# real neighboring tokens to form the final preprocessing token.
run_case 0 '#define CAT3(a,b,c) a ## b ## c
int xy=23; int main(void){return CAT3(x,,y)!=23;}'

# The token that survives a placemarker paste must still be rescanned for macro
# expansion after substitution, just like an ordinary ## result.
run_case 0 '#define VALUE 29
#define CAT(a,b) a ## b
int main(void){return CAT(VALUE,)!=29;}'

rm -f tmp-pp-empty-paste.c tmp-pp-empty-paste.s tmp-pp-empty-paste \
      tmp-pp-empty-paste-host

echo 'All empty token-paste tests passed!'
