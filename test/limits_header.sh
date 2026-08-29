#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-limits.c
  "$MINICC" tmp-limits.c > tmp-limits.s
  cc -o tmp-limits tmp-limits.s
  set +e
  ./tmp-limits
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(limits.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# Fundamental byte/character limits for this 8-bit-byte target.
assert_run 0 '#include <limits.h>
int main(void){return CHAR_BIT!=8||SCHAR_MIN!=-128||SCHAR_MAX!=127||UCHAR_MAX!=255||CHAR_MIN!=-128||CHAR_MAX!=127||MB_LEN_MAX!=1;}'

# short/int limits match the compiler target model and preserve unsigned types.
assert_run 0 '#include <limits.h>
int main(void){unsigned short us=USHRT_MAX;unsigned int ui=UINT_MAX;return SHRT_MIN!=-32768||SHRT_MAX!=32767||USHRT_MAX!=65535||INT_MIN!=(-2147483647-1)||INT_MAX!=2147483647||UINT_MAX!=4294967295U||us!=65535||ui!=4294967295U;}'

# LP64 long limits and unsigned-long maximum.
assert_run 0 '#include <limits.h>
int main(void){unsigned long u=ULONG_MAX;return LONG_MIN!=(-9223372036854775807L-1)||LONG_MAX!=9223372036854775807L||ULONG_MAX!=18446744073709551615UL||u!=ULONG_MAX;}'

# long long limits remain available independently of LP64 long.
assert_run 0 '#include <limits.h>
int main(void){unsigned long long u=ULLONG_MAX;return LLONG_MIN!=(-9223372036854775807LL-1)||LLONG_MAX!=9223372036854775807LL||ULLONG_MAX!=18446744073709551615ULL||u!=ULLONG_MAX;}'

# Macro values work in integer constant-expression contexts.
assert_run 0 '#include <limits.h>
enum { BITS = CHAR_BIT, IMAX_OK = INT_MAX == 2147483647, LMAX_OK = LONG_MAX == 9223372036854775807L };
int a[BITS==8?1:-1];
int main(void){return !IMAX_OK||!LMAX_OK||sizeof(a)!=sizeof(int);}'

# Signed plain char is part of this compiler target model; verify header and code agree.
assert_run 0 '#include <limits.h>
int main(void){char c=CHAR_MIN;char d=CHAR_MAX;return !(c<0&&d>0&&sizeof(c)==1);}'

# The same limit macros must preserve their C integer types when expanded inside
# preprocessing conditional expressions.  In particular, the 64-bit unsigned
# maxima must not be reinterpreted as negative signed values, and mixed
# signed/unsigned comparisons must follow the usual arithmetic conversions.
assert_run 0 '#include <limits.h>
#include <limits.h>
#if CHAR_BIT != 8
#error "CHAR_BIT lost in #if"
#endif
#if LONG_MAX != 9223372036854775807L
#error "LONG_MAX lost in #if"
#endif
#if ULONG_MAX <= LONG_MAX
#error "ULONG_MAX signedness lost in #if"
#endif
#if ULLONG_MAX != 18446744073709551615ULL
#error "ULLONG_MAX value lost in #if"
#endif
#if (ULLONG_MAX + 1ULL) != 0
#error "unsigned wraparound broken in #if"
#endif
#if (-1LL < 1ULL)
#error "mixed signed/unsigned conversion broken in #if"
#endif
int main(void){return 0;}'

rm -f tmp-limits.c tmp-limits.s tmp-limits

echo 'All <limits.h> tests passed!'
