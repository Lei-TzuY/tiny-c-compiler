#!/bin/bash
set -eu

run_case() {
  expected="$1"
  src="$2"
  cat > tmp-static-fp.c <<EOF
$src
EOF
  ./minicc tmp-static-fp.c > tmp-static-fp.s
  cc -o tmp-static-fp tmp-static-fp.s
  ./tmp-static-fp
  got=$?
  if [ "$got" -ne "$expected" ]; then
    echo "expected exit $expected, got $got: $src"
    exit 1
  fi
  echo "OK(static fp): $src"
}

reject_case() {
  src="$1"
  cat > tmp-static-fp-bad.c <<EOF
$src
EOF
  if ./minicc tmp-static-fp-bad.c >/dev/null 2>&1; then
    echo "expected static floating initializer rejection: $src"
    exit 1
  fi
  echo "OK(reject static fp): $src"
}

run_case 0 'double g = 1.5 + 2.25 * 2.0; int main(void) { return g == 6.0 ? 0 : 1; }'
run_case 0 'float g = 1.25f + 2.5f; int main(void) { return g == 3.75f ? 0 : 1; }'
run_case 0 'double g = (double)(1 + 2 * 3); int main(void) { return g == 7.0 ? 0 : 1; }'
run_case 0 'double g = (int)3.9 + 0.5; int main(void) { return g == 3.5 ? 0 : 1; }'
run_case 0 'double g = 0 ? 1.0 / 0.0 : 2.5; int main(void) { return g == 2.5 ? 0 : 1; }'
run_case 0 'double g = (1.5 < 2.0) ? 4.25 : 9.0; int main(void) { return g == 4.25 ? 0 : 1; }'
run_case 0 'double g = (0.0 || 3.0) ? 8.0 : 1.0; int main(void) { return g == 8.0 ? 0 : 1; }'
run_case 0 'double g = 18446744073709551615ULL; int main(void) { return g > 1.8e19 ? 0 : 1; }'
run_case 0 'static double g = (float)(1.0 / 3.0); int main(void) { return g > 0.3333333 && g < 0.3333334 ? 0 : 1; }'
run_case 0 'double a[3] = {1.0 + 2.0, (double)(4 * 2), 1 ? 9.5 : 0.0}; int main(void) { return a[0] == 3.0 && a[1] == 8.0 && a[2] == 9.5 ? 0 : 1; }'
run_case 0 'struct S { double x; float y; }; struct S s = {1.25 + 0.75, 2.0f * 3.0f}; int main(void) { return s.x == 2.0 && s.y == 6.0f ? 0 : 1; }'
run_case 0 'int f(void) { static double x = 1.0 + 2.0 * 4.0; return x == 9.0; } int main(void) { return f() ? 0 : 1; }'
run_case 0 'enum { N = 5 }; double g = N * 0.5; int main(void) { return g == 2.5 ? 0 : 1; }'
run_case 0 'double g = (1.0 == 1.0) + 0.25; int main(void) { return g == 1.25 ? 0 : 1; }'

reject_case 'double x = 1.0; double g = x + 1.0; int main(void) { return 0; }'
reject_case 'double f(void) { return 1.0; } double g = f(); int main(void) { return 0; }'
reject_case 'int x; double g = (double)&x; int main(void) { return 0; }'
reject_case 'double g = (1.0, 2.0); int main(void) { return 0; }'
reject_case 'double g = (1.0 = 2.0); int main(void) { return 0; }'

rm -f tmp-static-fp.c tmp-static-fp.s tmp-static-fp tmp-static-fp-bad.c

echo 'All static floating constant-expression initializer tests passed!'
