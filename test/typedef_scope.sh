#!/bin/bash
set -e

assert_scope() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-typedef.c
  "${MINICC:-./minicc}" tmp-typedef.c > tmp-typedef.s
  gcc -o tmp-typedef tmp-typedef.s
  set +e
  ./tmp-typedef
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(typedef scope): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(typedef scope): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-typedef-reject.c
  if "${MINICC:-./minicc}" tmp-typedef-reject.c > /dev/null 2>&1; then
    echo "FAIL(typedef scope): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(typedef scope): rejected out-of-scope typedef"
}

assert_scope 4 'typedef int T; int main() { T x=3; return sizeof(x); }'
assert_scope 4 'typedef int T; int main() { { typedef char T; T x=3; if (sizeof(x)!=1) return 99; } T y=7; return sizeof(y); }'
assert_scope 7 'int main() { { typedef char T; T x=1; if (sizeof(x)!=1) return 1; } { typedef long T; T y=2; if (sizeof(y)!=8) return 2; } return 7; }'
assert_scope 6 'typedef int T; int main() { { int T=5; T=T+1; return T; } }'
assert_scope 7 'typedef int T; int main() { { int T=5; } T x=7; return x; }'
assert_scope 1 'int T; int main() { { typedef char T; T x=3; return sizeof(x); } }'
assert_reject 'int main() { { typedef int Local; Local x=3; } Local y; return 0; }'

echo "All typedef scope tests passed!"
