#!/bin/bash
set -e

assert_enum() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-enum.c
  "${MINICC:-./minicc}" tmp-enum.c > tmp-enum.s
  gcc -o tmp-enum tmp-enum.s
  set +e
  ./tmp-enum
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(enum scope): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(enum scope): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-enum-reject.c
  if "${MINICC:-./minicc}" tmp-enum-reject.c > /dev/null 2>&1; then
    echo "FAIL(enum scope): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(enum scope): rejected out-of-scope enumerator"
}

assert_enum 3 'enum { A=3 }; int main() { return A; }'
assert_enum 3 'enum { A=3 }; int main() { { enum { A=5 }; if (A!=5) return 99; } return A; }'
assert_enum 7 'enum { X=3 }; int main() { { int X=7; return X; } }'
assert_enum 3 'enum { X=3 }; int main() { { int X=7; } return X; }'
assert_enum 9 'int X; int main() { { enum { X=9 }; return X; } }'
assert_enum 1 'enum { T=9 }; int main() { { typedef char T; T x=3; return sizeof(x); } }'
assert_reject 'int main() { { enum { LOCAL=5 }; } return LOCAL; }'

echo "All enum scope tests passed!"
