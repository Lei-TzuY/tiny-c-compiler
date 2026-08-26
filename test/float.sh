#!/bin/bash
set -e

assert_float() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-float.c
  "${MINICC:-./minicc}" tmp-float.c > tmp-float.s
  gcc -o tmp-float tmp-float.s
  set +e
  ./tmp-float
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(float): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(float): $actual"
}

assert_float 4 'int main() { return sizeof(float); }'
assert_float 8 'int main() { return sizeof(double); }'
assert_float 3 'int main() { float x=1.5f; return (int)(x*2.0f); }'
assert_float 4 'int main() { double x=1.5; return (int)(x+2.5); }'
assert_float 5 'int main() { double x=8.0; return (int)(x-3.0); }'
assert_float 4 'int main() { double x=9.0; return (int)(x/2.0); }'
assert_float 4 'int main() { int x=2; return (int)(x+2.75); }'
assert_float 1 'int main() { return 1.5 < 2.0; }'
assert_float 1 'int main() { return 2.0 >= 2.0; }'
assert_float 1 'int main() { float x=1.25f; return x==1.25f; }'
assert_float 9 'int main() { double x=0.5; if (x) return 9; return 1; }'
assert_float 7 'int main() { double x=0.0; if (x) return 1; return 7; }'
assert_float 1 'int main() { return !0.0; }'
assert_float 1 'int main() { return 0.0 || 2.0; }'
assert_float 1 'int main() { return 1.0 && 2.0; }'
assert_float 7 'int main() { double x=3.5; return (int)(x*2); }'
assert_float 3 'int main() { double x=1.0; x+=2.5; return (int)x; }'
assert_float 6 'int main() { float x=2.0f; x*=3.0f; return (int)x; }'
assert_float 3 'int main() { double x=2.0; ++x; return (int)x; }'
assert_float 2 'int main() { double x=2.0; return (int)x++; }'
assert_float 3 'int main() { return (int)(double)3; }'
assert_float 3 'int main() { return (int)(float)3; }'
assert_float 3 'int main() { return (int)(float)3.75; }'
assert_float 5 'double g=2.5; int main() { return (int)(g*2); }'
assert_float 6 'float g=3.0f; int main() { return (int)(g*2.0f); }'
assert_float 8 'int main() { static double x=4.0; return (int)(x*2); }'
assert_float 4 'int main() { return (int)(-1.5 + 5.5); }'

echo "All floating-point core tests passed!"
