#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-escape.c
  ./minicc tmp-escape.c > tmp-escape.s
  cc -o tmp-escape tmp-escape.s
  set +e
  ./tmp-escape
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "escape sequence failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(escape sequence): $actual"
}

assert_fail() {
  input="$1"
  printf "%s" "$input" > tmp-escape-bad.c
  if ./minicc tmp-escape-bad.c > tmp-escape-bad.s 2>/dev/null; then
    echo "escape sequence unexpectedly accepted invalid program"
    printf "%s\n" "$input"
    exit 1
  fi
  echo "OK(escape sequence): rejected invalid program"
}

# Numeric character escapes.
assert_run 65 "int main(){return '\\101';}"
assert_run 65 "int main(){return '\\x41';}"
assert_run 255 "int main(){return '\\377';}"
assert_run 127 "int main(){return '\\x7f';}"
assert_run 0 "int main(){return '\\000';}"

# Numeric escapes inside strings consume exactly the C-defined span.
assert_run 65 'int main(){char *s="\101B";return s[0];}'
assert_run 66 'int main(){char *s="\101B";return s[1];}'
assert_run 66 'int main(){char *s="\x41" "B";return s[1];}'
assert_run 4 'int main(){return sizeof("A\0B");}'
assert_run 0 'int main(){char *s="\0007";return s[0];}'
assert_run 55 'int main(){char *s="\0007";return s[1];}'

# Standard simple escapes remain supported, including question mark.
assert_run 10 "int main(){return '\\n';}"
assert_run 9 "int main(){return '\\t';}"
assert_run 63 "int main(){return '\\?';}"
assert_run 34 'int main(){char *s="\"";return s[0];}'
assert_run 92 'int main(){char *s="\\\\";return s[0];}'

# Ill-formed or out-of-range numeric escapes are diagnosed lexically.
assert_fail "int main(){return '\\\\x';}\n"
assert_fail "int main(){return '\\\\400';}\n"
assert_fail "int main(){return '\\\\x100';}\n"
assert_fail 'int main(){char *s="\x";return 0;}\n'
assert_fail 'int main(){char *s="\400";return 0;}\n'
assert_fail 'int main(){char *s="\x100";return 0;}\n'

# Raw newlines cannot appear inside ordinary character/string literals.
assert_fail $'int main(){char *s="abc\ndef";return 0;}\n'
assert_fail $'int main(){return \'a\n\';}\n'

echo 'All escape-sequence tests passed!'
