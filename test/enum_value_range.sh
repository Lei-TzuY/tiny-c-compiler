#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-enum-range.c
  ./minicc tmp-enum-range.c > tmp-enum-range.s
  cc -o tmp-enum-range tmp-enum-range.s
  set +e
  ./tmp-enum-range
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(enum value range): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  pattern="$2"
  printf '%s\n' "$input" > tmp-enum-range-bad.c
  if ./minicc tmp-enum-range-bad.c > /dev/null 2>tmp-enum-range.err; then
    echo "FAIL(enum value range): expected rejection"
    echo "$input"
    exit 1
  fi
  if ! grep -q "$pattern" tmp-enum-range.err; then
    echo "FAIL(enum value range): missing diagnostic '$pattern'"
    cat tmp-enum-range.err
    exit 1
  fi
}

# C11 permits the full signed-int range, including values expressed with wider
# signed/unsigned integer constant expressions when the resulting value fits.
assert_run 0 'enum E{A=-2147483648L,B=2147483647L};int main(void){return A==-2147483648L&&B==2147483647L?0:1;}'
assert_run 0 'enum E{A=2147483645L,B,C};int main(void){return B==2147483646&&C==2147483647?0:1;}'
assert_run 0 'enum E{A=2147483647L,B=0,C};int main(void){return B==0&&C==1?0:1;}'
assert_run 0 'enum E{A=7,B=7,C};int main(void){return A==B&&C==8?0:1;}'
assert_run 0 'enum E{A=2147483647U};int main(void){return A==2147483647?0:1;}'
assert_run 0 'enum E{A=(int)2147483648L};int main(void){return A==-2147483648L?0:1;}'

# Enumerator identifiers themselves have type int and remain ordinary integer
# constant expressions usable by _Generic, switch, and _Static_assert.
assert_run 0 'enum E{A=3};int main(void){return _Generic(A,int:0,default:1);}'
assert_run 0 'enum E{A=5};_Static_assert(A+1==6,"enum ICE");int main(void){switch(5){case A:return 0;default:return 1;}}'

# Explicit values outside the target int range are constraints violations.
assert_reject 'enum E{A=2147483648L};int main(void){return 0;}' 'enumerator value is not representable as int'
assert_reject 'enum E{A=2147483648U};int main(void){return 0;}' 'enumerator value is not representable as int'
assert_reject 'enum E{A=18446744073709551615ULL};int main(void){return 0;}' 'enumerator value is not representable as int'
assert_reject 'enum E{A=-2147483649L};int main(void){return 0;}' 'enumerator value is not representable as int'
assert_reject 'enum E{A=(1ULL<<63)};int main(void){return 0;}' 'enumerator value is not representable as int'
assert_reject 'enum E{A=0?1:2147483648L};int main(void){return 0;}' 'enumerator value is not representable as int'

# After INT_MAX there is no representable implicit successor. A later explicit
# initializer may reset the sequence, which is covered by the positive case above.
assert_reject 'enum E{A=2147483647L,B};int main(void){return 0;}' 'implicit enumerator value is not representable as int'
assert_reject 'enum E{A=2147483646L,B,C};int main(void){return 0;}' 'implicit enumerator value is not representable as int'

rm -f tmp-enum-range.c tmp-enum-range.s tmp-enum-range \
      tmp-enum-range-bad.c tmp-enum-range.err

echo 'All enum value range tests passed!'
