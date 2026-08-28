#!/bin/bash
set -e

assert_pp_char() {
  expected="$1"
  input="$2"

  printf "%s\n" "$input" > tmp-pp-char.c
  "${MINICC:-./minicc}" tmp-pp-char.c > tmp-pp-char.s

  if command -v gcc >/dev/null; then
    gcc -o tmp-pp-char tmp-pp-char.s
  else
    as -o tmp-pp-char.o tmp-pp-char.s
    as -o tmp-pp-char-crt0.o test/crt0.s
    ld -o tmp-pp-char tmp-pp-char-crt0.o tmp-pp-char.o
  fi

  set +e
  ./tmp-pp-char
  actual="$?"
  set -e

  if [ "$actual" = "$expected" ]; then
    echo "OK(preprocessor-char): $actual"
  else
    echo "FAIL(preprocessor-char): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_pp_char_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-pp-char.c
  if "${MINICC:-./minicc}" tmp-pp-char.c > tmp-pp-char.s 2>/dev/null; then
    echo "FAIL(preprocessor-char): expected preprocessing failure"
    echo "$input"
    exit 1
  fi
  echo "OK(preprocessor-char): rejected invalid input"
}

# Ordinary character constants participate in #if arithmetic.
assert_pp_char 41 '#if '\''A'\'' == 65
int main() { return 41; }
#else
int main() { return 0; }
#endif'

# Standard simple, octal, and hexadecimal escapes are decoded.
assert_pp_char 42 '#if '\''\n'\'' == 10 && '\''\101'\'' == '\''A'\'' && '\''\x42'\'' == '\''B'\''
int main() { return 42; }
#else
int main() { return 0; }
#endif'

# Character constants introduced through object-like macros are evaluated too.
assert_pp_char 43 '#define LETTER '\''Z'\''
#if LETTER == 90
int main() { return 43; }
#else
int main() { return 0; }
#endif'

# Character constants compose with ordinary preprocessor arithmetic.
assert_pp_char 44 '#if '\''0'\'' + 9 == '\''9'\''
int main() { return 44; }
#else
int main() { return 0; }
#endif'

# Empty, multi-character, malformed hex, and out-of-range escapes are rejected.
assert_pp_char_fail '#if '\'''\''
int main() { return 0; }
#endif'
assert_pp_char_fail '#if '\''ab'\''
int main() { return 0; }
#endif'
assert_pp_char_fail '#if '\''\x'\''
int main() { return 0; }
#endif'
assert_pp_char_fail '#if '\''\x100'\''
int main() { return 0; }
#endif'

echo "All preprocessor character constant tests passed!"
