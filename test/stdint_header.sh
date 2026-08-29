#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stdint.c
  "$MINICC" tmp-stdint.c > tmp-stdint.s
  cc -o tmp-stdint tmp-stdint.s
  set +e
  ./tmp-stdint
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stdint.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_run 0 '#include <stdint.h>
int main(void){return sizeof(int8_t)!=1||sizeof(uint8_t)!=1||sizeof(int16_t)!=2||sizeof(uint16_t)!=2||sizeof(int32_t)!=4||sizeof(uint32_t)!=4||sizeof(int64_t)!=8||sizeof(uint64_t)!=8;}'

assert_run 0 '#include <stdint.h>
int main(void){int8_t a=-1;uint8_t b=255;int16_t c=-1;uint16_t d=65535;int32_t e=-1;uint32_t f=4294967295U;int64_t g=-1;uint64_t h=18446744073709551615UL;return !(a<0&&b>0&&c<0&&d>0&&e<0&&f>0&&g<0&&h>0);}'

assert_run 0 '#include <stdint.h>
int main(void){return sizeof(int_least8_t)!=1||sizeof(uint_least8_t)!=1||sizeof(int_least16_t)!=2||sizeof(uint_least16_t)!=2||sizeof(int_least32_t)!=4||sizeof(uint_least32_t)!=4||sizeof(int_least64_t)!=8||sizeof(uint_least64_t)!=8;}'

assert_run 0 '#include <stdint.h>
int main(void){return sizeof(int_fast8_t)!=8||sizeof(uint_fast8_t)!=8||sizeof(int_fast16_t)!=8||sizeof(uint_fast16_t)!=8||sizeof(int_fast32_t)!=8||sizeof(uint_fast32_t)!=8||sizeof(int_fast64_t)!=8||sizeof(uint_fast64_t)!=8;}'

assert_run 0 '#include <stdint.h>
int main(void){return sizeof(intptr_t)!=sizeof(void*)||sizeof(uintptr_t)!=sizeof(void*)||sizeof(intmax_t)!=8||sizeof(uintmax_t)!=8;}'

assert_run 0 '#include <stdint.h>
int main(void){return INT8_MIN!=-128||INT8_MAX!=127||UINT8_MAX!=255||INT16_MIN!=-32768||INT16_MAX!=32767||UINT16_MAX!=65535||INT32_MIN!=(-2147483647-1)||INT32_MAX!=2147483647||UINT32_MAX!=4294967295U;}'

assert_run 0 '#include <stdint.h>
int main(void){return INT64_MIN!=(-9223372036854775807L-1)||INT64_MAX!=9223372036854775807L||UINT64_MAX!=18446744073709551615UL||INTPTR_MIN!=INT64_MIN||INTPTR_MAX!=INT64_MAX||UINTPTR_MAX!=UINT64_MAX;}'

assert_run 0 '#include <stdint.h>
int main(void){return INT_LEAST8_MIN!=INT8_MIN||INT_LEAST16_MAX!=INT16_MAX||UINT_LEAST32_MAX!=UINT32_MAX||INT_LEAST64_MIN!=INT64_MIN||UINT_LEAST64_MAX!=UINT64_MAX;}'

assert_run 0 '#include <stdint.h>
int main(void){return INT_FAST8_MIN!=INT64_MIN||INT_FAST16_MAX!=INT64_MAX||UINT_FAST32_MAX!=UINT64_MAX||INT_FAST64_MIN!=INT64_MIN||UINT_FAST64_MAX!=UINT64_MAX;}'

assert_run 0 '#include <stdint.h>
int main(void){return INTMAX_MIN!=(-9223372036854775807LL-1)||INTMAX_MAX!=9223372036854775807LL||UINTMAX_MAX!=18446744073709551615ULL;}'

assert_run 0 '#include <stdint.h>
int main(void){return sizeof(INT8_C(1))!=4||sizeof(UINT8_C(1))!=4||sizeof(INT16_C(1))!=4||sizeof(UINT16_C(1))!=4||sizeof(INT32_C(1))!=4||sizeof(UINT32_C(1))!=4||sizeof(INT64_C(1))!=8||sizeof(UINT64_C(1))!=8||sizeof(INTMAX_C(1))!=8||sizeof(UINTMAX_C(1))!=8;}'

assert_run 0 '#include <stdint.h>
int main(void){return INT64_C(9223372036854775807)!=INT64_MAX||UINT64_C(18446744073709551615)!=UINT64_MAX||INTMAX_C(9223372036854775807)!=INTMAX_MAX||UINTMAX_C(18446744073709551615)!=UINTMAX_MAX;}'

assert_run 0 '#include <stdint.h>
int main(void){int x=7;uintptr_t raw=(uintptr_t)&x;int *p=(int*)raw;return p!=&x||*p!=7;}'

rm -f tmp-stdint.c tmp-stdint.s tmp-stdint

echo 'All <stdint.h> tests passed!'
