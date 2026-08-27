#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-intlit.c
  ./minicc tmp-intlit.c > tmp-intlit.s
  cc -o tmp-intlit tmp-intlit.s
  set +e
  ./tmp-intlit
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "integer literal test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(integer literal): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-intlit-bad.c
  if ./minicc tmp-intlit-bad.c > /dev/null 2>tmp-intlit-bad.err; then
    echo "expected integer literal rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(rejected integer literal)"
}

# Unsuffixed candidate lists differ for decimal and hexadecimal/octal constants.
assert_run 4 'int main(){return sizeof(2147483647);}'
assert_run 8 'int main(){return sizeof(2147483648);}'
assert_run 8 'int main(){return sizeof(4294967295);}'
assert_run 4 'int main(){return sizeof(0xffffffff);}'
assert_run 8 'int main(){return sizeof(0x100000000);}'
assert_run 1 'int main(){return 0xffffffff>0;}'
assert_run 1 'int main(){return 0xffffffffffffffff>0;}'

# U/L/UL/LU/LL/ULL/LLU suffixes are consumed case-insensitively and typed.
assert_run 4 'int main(){return sizeof(2147483648U);}'
assert_run 8 'int main(){return sizeof(4294967296U);}'
assert_run 24 'int main(){return sizeof(1L)+sizeof(1UL)+sizeof(1LU);}'
assert_run 8 'int main(){return sizeof(1LL);}'
assert_run 8 'int main(){return sizeof(1ULL);}'
assert_run 8 'int main(){return sizeof(1LLU);}'
assert_run 1 'int main(){unsigned long long x=18446744073709551615ULL;return x==(unsigned long long)-1;}'
assert_run 1 'int main(){return 0xffffffffffffffffLL>0;}'
assert_run 1 'int main(){return (1ULL<<63)>0;}'

# long and long long remain distinct C types despite both being 8 bytes on LP64.
assert_fail 'long f(long); long long f(long long); int main(){return 0;}'
assert_run 1 'int main(){unsigned long x=(unsigned long)-1;long long y=0;return (x+y)>0;}'

# Literal typing feeds the full-range uint64 floating conversion lowering.
assert_run 1 'int main(){double d=18446744073709551615ULL;return d>18446744073709549568.0;}'
assert_run 1 'double f(){return 9223372036854775808ULL;} int main(){return f==f && f()>0;}'

# Decimal signed candidate lists must reject values beyond signed long long;
# explicit unsigned suffixes allow the complete uint64 range.
assert_fail 'int main(){return 9223372036854775808;}'
assert_fail 'int main(){return 9223372036854775808LL;}'
assert_fail 'int main(){return 18446744073709551616ULL;}'
assert_fail 'int main(){return 1UU;}'
assert_fail 'int main(){return 1LLL;}'
assert_fail 'int main(){return 08;}'

# Floating tokenization stays intact, including exponent and f suffix.
assert_run 1 'int main(){float x=1e1f;return x==10.0;}'

echo 'All integer-literal tests passed!'
