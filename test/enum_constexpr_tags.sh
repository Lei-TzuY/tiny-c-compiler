#!/bin/bash
set -e

assert_enum() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-enum-ce.c
  "${MINICC:-./minicc}" tmp-enum-ce.c > tmp-enum-ce.s
  gcc -o tmp-enum-ce tmp-enum-ce.s
  set +e
  ./tmp-enum-ce
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(enum constexpr/tag): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(enum constexpr/tag): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-enum-ce-reject.c
  if "${MINICC:-./minicc}" tmp-enum-ce-reject.c > /dev/null 2>&1; then
    echo "FAIL(enum constexpr/tag): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(enum constexpr/tag): rejected invalid input"
}

assert_enum 8 'enum { A = 1 << 3 }; int main() { return A; }'
assert_enum 13 'enum { A = 3, B = A * 4 + 1 }; int main() { return B; }'
assert_enum 18 'enum { A = 1 << 4, B = A | 3, C = B ^ 1 }; int main() { return C; }'
assert_enum 3 'enum { A = ~0, B = !A, C = !0 }; int main() { return (A == -1) + (B == 0) + (C == 1); }'
assert_enum 4 'enum { A = 3 < 4, B = 5 == 5, C = A && B, D = 0 || C }; int main() { return A+B+C+D; }'
assert_enum 7 'enum { A = 0 ? 3 : 7 }; int main() { return A; }'
assert_enum 15 'enum { A = (2 + 3) * (8 - 5) }; int main() { return A; }'
assert_enum 9 'enum { A = sizeof(long) + sizeof(char) }; int main() { return A; }'
assert_enum 1 'enum { A = (char)257 }; int main() { return A; }'
assert_enum 1 'enum { A = 0 && (1/0), B = 1 || (1/0) }; int main() { return A+B; }'
assert_enum 6 'enum Color { RED = 6 }; int main() { enum Color x = RED; return x; }'
assert_enum 6 'enum Kind { OUT = 3 }; int main() { enum Kind a=OUT; { enum Kind { IN=5 }; enum Kind b=IN; if (b!=5) return 99; } enum Kind c=OUT; return a+c; }'
assert_enum 4 'struct T { int x; }; int main() { { enum T { A=7 }; enum T x=A; if (x!=7) return 99; } struct T y; y.x=4; return y.x; }'
assert_reject 'struct Clash; enum Clash { A=1 }; int main() { return 0; }'
assert_reject 'struct Clash; union Clash; int main() { return 0; }'
assert_reject 'int main() { enum Missing x; return 0; }'
assert_reject 'int x; enum { A = x }; int main() { return A; }'
assert_reject 'int f() { return 3; } enum { A = f() }; int main() { return A; }'

echo "All enum constant-expression/tag tests passed!"
