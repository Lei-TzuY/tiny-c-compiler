#!/bin/bash
set -e

assert_pp_integer() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-pp-int-semantics.c
  "${MINICC:-./minicc}" tmp-pp-int-semantics.c > tmp-pp-int-semantics.s
  if command -v gcc >/dev/null; then
    gcc -o tmp-pp-int-semantics tmp-pp-int-semantics.s
  else
    as -o tmp-pp-int-semantics.o tmp-pp-int-semantics.s
    as -o tmp-pp-int-semantics-crt0.o test/crt0.s
    ld -o tmp-pp-int-semantics tmp-pp-int-semantics-crt0.o tmp-pp-int-semantics.o
  fi
  set +e
  ./tmp-pp-int-semantics
  actual="$?"
  set -e
  if [ "$actual" = "$expected" ]; then
    echo "OK(preprocessor-integer-semantics): $actual"
  else
    echo "FAIL(preprocessor-integer-semantics): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_pp_integer_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-pp-int-semantics.c
  if "${MINICC:-./minicc}" tmp-pp-int-semantics.c > tmp-pp-int-semantics.s 2>/dev/null; then
    echo "FAIL(preprocessor-integer-semantics): expected preprocessing failure"
    echo "$input"
    exit 1
  fi
  echo "OK(preprocessor-integer-semantics): rejected invalid input"
}

assert_pp_integer 51 '#if 18446744073709551615ULL > 0
int main() { return 51; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 52 '#if -1 < 1ULL
int main() { return 0; }
#else
int main() { return 52; }
#endif'

assert_pp_integer 53 '#if (18446744073709551615ULL + 1) == 0
int main() { return 53; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 54 '#if (18446744073709551615ULL / 3) == 6148914691236517205ULL
int main() { return 54; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 55 '#if 0xffffffff < -1
int main() { return 55; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 56 '#if 0x100000000 > -1
int main() { return 56; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 57 '#if (1 ? -1 : 1ULL) < 0
int main() { return 0; }
#else
int main() { return 57; }
#endif'

assert_pp_integer 58 '#if 1 || (18446744073709551615ULL / 0)
int main() { return 58; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 59 '#if (18446744073709551615ULL >> 63) == 1
int main() { return 59; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 60 '#if 0xffffffffL > -1
int main() { return 60; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 61 '#if -1ULL == 18446744073709551615ULL
int main() { return 61; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 62 '#if (-5 % 3ULL) == 2
int main() { return 62; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 63 '#if (~0ULL) > 0
int main() { return 63; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 64 '#if (0 ? 1ULL : -1) > 0
int main() { return 64; }
#else
int main() { return 0; }
#endif'

assert_pp_integer 65 '#if 9223372036854775808U > 0
int main() { return 65; }
#else
int main() { return 0; }
#endif'

assert_pp_integer_fail '#if 18446744073709551615
int main() { return 0; }
#endif'

assert_pp_integer_fail '#if 1uLLL
int main() { return 0; }
#endif'

echo "All preprocessor integer-semantics tests passed!"
