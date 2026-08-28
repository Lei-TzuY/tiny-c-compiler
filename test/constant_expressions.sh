#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-constexpr.c
  ./minicc tmp-constexpr.c > tmp-constexpr.s
  cc -o tmp-constexpr tmp-constexpr.s
  set +e
  ./tmp-constexpr
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "constant-expression test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(constant expression): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-constexpr.c
  if ./minicc tmp-constexpr.c > tmp-constexpr.s 2>/dev/null; then
    echo "constant-expression test unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(constant expression): rejected invalid input"
}

# Unsigned comparisons, division/remainder, and shifts must preserve high bits.
assert_run 1 'int main(){enum { A = 0xffffffffffffffffULL > 0 }; return A;}'
assert_run 1 'int main(){enum { A = (0xffffffffffffffffULL >> 63) }; return A;}'
assert_run 1 'int main(){enum { A = (0xffffffffffffffffULL / 0x7fffffffffffffffULL) == 2 }; return A;}'
assert_run 1 'int main(){enum { A = (0xffffffffffffffffULL % 0x7fffffffffffffffULL) == 1 }; return A;}'
assert_run 1 'int main(){enum { A = ((unsigned int)-1 > 1) }; return A;}'
assert_run 1 'int main(){enum { A = (~0U >> 31) }; return A;}'
assert_run 1 'int main(){enum { A = ((0xffffffffU + 1U) == 0) }; return A;}'
assert_run 1 'int main(){enum { A = ((unsigned int)0xffffffffffffffffULL == 0xffffffffU) }; return A;}'
assert_run 1 'int main(){enum { A = ((0x80000000U << 1) == 0) }; return A;}'
assert_run 1 'int main(){enum { A = ((0xffffffffffffffffULL + 1ULL) == 0) }; return A;}'
assert_run 1 'int main(){enum { A = ((0x8000000000000000ULL << 1) == 0) }; return A;}'

# Signed arithmetic must stay inside the result type's representable range.
assert_run 1 'int main(){enum { A = (2147483646 + 1 == 2147483647) }; return A;}'
assert_run 1 'int main(){enum { A = ((-2147483647 - 1) + 1 == -2147483647) }; return A;}'
assert_run 1 'int main(){enum { A = ((1 << 30) == 1073741824) }; return A;}'
assert_run 1 'int main(){enum { A = ((0 && (2147483647 + 1)) == 0) }; return A;}'
assert_run 1 'int main(){enum { A = (1 ? 1 : 2147483647 + 1) }; return A;}'

# Equal-width long/long-long still obey rank and signedness conversions.
assert_run 0 'int main(){enum { A = ((long long)-1 < (unsigned long)1) }; return A;}'
assert_run 1 'int main(){enum { A = ((long long)-1 > (unsigned long)1) }; return A;}'
assert_run 1 'int main(){enum { A = ((1 ? -1 : 0U) == 0xffffffffU) }; return A;}'

# Unary integer operators apply integer promotions just like runtime C.
assert_run 4 'int main(){return sizeof(~(unsigned char)0);}'
assert_run 4 'int main(){return sizeof(-(unsigned short)1);}'
assert_run 1 'int main(){return ~(unsigned char)0 == -1;}'
assert_run 1 'int main(){enum { A = ((-2 >> 1) == -1) }; return A;}'

# case labels use the same typed evaluator and are converted to switch type.
assert_run 1 'int main(){unsigned long x=(unsigned long)-1; switch(x){case 0xffffffffffffffffULL:return 1;} return 0;}'
assert_run 1 'int main(){unsigned long x=6148914691236517205ULL; switch(x){case 0xffffffffffffffffULL/3ULL:return 1;} return 0;}'
assert_reject 'int main(){unsigned int x=0; switch(x){case -1:return 1; case 0xffffffffU:return 2;} return 0;}'

# Array bounds are now parsed as integer constant expressions.
assert_run 3 'int main(){int a[(0xffffffffU >> 31)+2]; return sizeof(a)/sizeof(int);}'
assert_run 4 'int main(){enum { N=(0xffffffffffffffffULL>>63)+3 }; int a[N]; return sizeof(a)/sizeof(int);}'
assert_run 3 'int main(){int a[1 ? 3 : 1/0]; return sizeof(a)/sizeof(int);}'
assert_run 6 'int main(){int a[sizeof(int)+2]; return sizeof(a)/sizeof(int);}'

# Invalid ICE operations/bounds are diagnosed instead of inheriting host int64 behavior.
assert_reject 'int main(){enum { A = 1U / 0U }; return A;}'
assert_reject 'int main(){enum { A = 1ULL % 0ULL }; return A;}'
assert_reject 'int main(){enum { A = 1U << 32 }; return A;}'
assert_reject 'int main(){enum { A = 1ULL >> 64 }; return A;}'
assert_reject 'int main(){enum { A = 2147483647 + 1 }; return A;}'
assert_reject 'int main(){enum { A = (-2147483647 - 1) - 1 }; return A;}'
assert_reject 'int main(){enum { A = 1073741824 * 2 }; return A;}'
assert_reject 'int main(){enum { A = -(-2147483647 - 1) }; return A;}'
assert_reject 'int main(){enum { A = 1 << 31 }; return A;}'
assert_reject 'int main(){enum { A = (-1) << 1 }; return A;}'
assert_reject 'int main(){enum { A = (-2147483647 - 1) / -1 }; return A;}'
assert_reject 'int main(){enum { A = (-2147483647 - 1) % -1 }; return A;}'
assert_reject 'long x = 9223372036854775807L + 1L; int main(){return 0;}'
assert_reject 'long x = 4611686018427387904L * 2L; int main(){return 0;}'
assert_reject '_Static_assert(2147483647 + 1, "overflow"); int main(){return 0;}'
assert_reject 'int a[2147483647 + 1]; int main(){return 0;}'
assert_reject 'int main(){switch(0){case 2147483647 + 1:return 1;}return 0;}'
assert_reject 'static int x = 2147483647 + 1; int main(){return x;}'
assert_reject '_Alignas(2147483647 + 1) int x; int main(){return 0;}'
assert_reject 'int main(){int x=3; int a[x]; return 0;}'
assert_reject 'int main(){int a[0]; return 0;}'
assert_reject 'int main(){int a[-1]; return 0;}'
assert_reject 'int main(){int a[0xffffffffffffffffULL]; return 0;}'

echo 'All typed integer constant-expression tests passed!'
