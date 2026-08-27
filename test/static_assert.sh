#!/bin/bash
set -eu

compile_ok() {
  cat > tmp-static-assert.c
  ./minicc tmp-static-assert.c > tmp-static-assert.s
  cc -o tmp-static-assert tmp-static-assert.s
  ./tmp-static-assert
  echo "OK(_Static_assert): $1"
}

compile_fail() {
  name="$1"
  shift
  cat > tmp-static-assert-bad.c
  if ./minicc tmp-static-assert-bad.c > /dev/null 2> tmp-static-assert.err; then
    echo "expected _Static_assert failure: $name"
    exit 1
  fi
  for needle in "$@"; do
    if ! grep -F "$needle" tmp-static-assert.err >/dev/null; then
      echo "missing diagnostic '$needle' for: $name"
      cat tmp-static-assert.err
      exit 1
    fi
  done
  echo "OK(_Static_assert reject): $name"
}

compile_ok "file and block scope constant expressions" <<'EOF'
enum { COUNT = 4 };
struct Pair { long a; int b; };
_Static_assert(1, "basic truth");
_Static_assert(COUNT * 2 == 8, "enum arithmetic");
_Static_assert(sizeof(long) == 8, "LP64 long size");
_Static_assert(_Alignof(struct Pair) == 8, "record alignment");
_Static_assert((unsigned)-1 > 0, "typed integer constant expression");

int main(void) {
  _Static_assert(sizeof(char[7]) == 7, "array sizeof");
  _Static_assert((1 ? 3 : 0) == 3, "conditional ICE");
  {
    _Static_assert(COUNT == 4, "nested block scope");
  }
  return 0;
}
EOF

compile_ok "assertions interleaved with declarations" <<'EOF'
_Static_assert(sizeof(int) == 4, "int width");
int x = 7;
_Static_assert(sizeof(x) == 4, "sizeof expression is constant");
int f(void) {
  int y = 3;
  _Static_assert(sizeof(y) == 4, "local sizeof is constant");
  return y;
}
int main(void) { return f() == 3 ? 0 : 1; }
EOF

compile_fail "false assertion reports user message" "static assertion failed: layout contract broke" <<'EOF'
_Static_assert(sizeof(int) == 8, "layout contract broke");
int main(void) { return 0; }
EOF

compile_fail "runtime expression is not an integer constant expression" "not an integer constant expression" <<'EOF'
int x;
_Static_assert(x, "runtime object");
int main(void) { return 0; }
EOF

compile_fail "floating condition is rejected" "requires an integer constant expression" <<'EOF'
_Static_assert(1.0, "floating condition");
int main(void) { return 0; }
EOF

compile_fail "string message is required" "requires a string literal message" <<'EOF'
_Static_assert(1, 123);
int main(void) { return 0; }
EOF

compile_fail "block-scope false assertion" "static assertion failed: inside function" <<'EOF'
int main(void) {
  _Static_assert(0, "inside function");
  return 0;
}
EOF

rm -f tmp-static-assert.c tmp-static-assert.s tmp-static-assert \
      tmp-static-assert-bad.c tmp-static-assert.err

echo 'All C11 _Static_assert tests passed!'
