#!/bin/bash
set -eu

run_case() {
  src="$1"
  cat > tmp-nested-designators.c <<EOF
$src
EOF
  ./minicc tmp-nested-designators.c > tmp-nested-designators.s
  cc -o tmp-nested-designators tmp-nested-designators.s
  ./tmp-nested-designators
  echo "OK(nested designator): $src"
}

reject_case() {
  src="$1"
  cat > tmp-nested-designators-bad.c <<EOF
$src
EOF
  if ./minicc tmp-nested-designators-bad.c >/dev/null 2>&1; then
    echo "expected nested designator rejection: $src"
    exit 1
  fi
  echo "OK(reject nested designator): $src"
}

# Static/global chains.
run_case 'int a[2][3] = {[1][2] = 7}; int main(void) { return !(a[0][0] == 0 && a[1][0] == 0 && a[1][2] == 7); }'
run_case 'struct I { int x; int y; }; struct O { int h; struct I inner; int t; }; struct O o = {.inner.y = 9, .h = 2}; int main(void) { return !(o.h == 2 && o.inner.x == 0 && o.inner.y == 9 && o.t == 0); }'
run_case 'struct S { int a[3]; int z; }; struct S s = {.a[1] = 5, .z = 7}; int main(void) { return !(s.a[0] == 0 && s.a[1] == 5 && s.a[2] == 0 && s.z == 7); }'
run_case 'struct P { int x; int y; }; struct P a[2] = {[1].x = 4, [1].y = 6}; int main(void) { return !(a[0].x == 0 && a[1].x == 4 && a[1].y == 6); }'
run_case 'struct I { int x; int y; }; struct O { struct I v[2]; }; struct O o = {.v[1].y = 12}; int main(void) { return !(o.v[0].x == 0 && o.v[1].x == 0 && o.v[1].y == 12); }'
run_case 'int g = 33; struct I { int *p; }; struct O { struct I inner; }; struct O o = {.inner.p = &g}; int main(void) { return *o.inner.p == 33 ? 0 : 1; }'
run_case 'struct S { char rows[2][4]; }; struct S s = {.rows[1] = "hi"}; int main(void) { return !(s.rows[0][0] == 0 && s.rows[1][0] == 104 && s.rows[1][1] == 105 && s.rows[1][2] == 0); }'
run_case 'union U { long a; int b; }; struct W { union U u; int z; }; struct W w = {.u.b = 17, .z = 3}; int main(void) { return !(w.u.b == 17 && w.z == 3); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; struct O o = {.inner.x = 3, .inner.y = 4}; int main(void) { return !(o.inner.x == 3 && o.inner.y == 4); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; struct O o = {.inner.x = 3, .inner.x = 8}; int main(void) { return o.inner.x == 8 ? 0 : 1; }'
run_case 'enum { R = 1, C = 2 }; int a[2][3] = {[R][C] = 19}; int main(void) { return a[1][2] == 19 ? 0 : 1; }'
run_case 'int f(void) { static struct S { int a[2]; int z; } s = {.a[1] = 7, .z = 8}; return s.a[1] + s.z; } int main(void) { return f() == 15 ? 0 : 1; }'

# Automatic/local chains use the same parsed path, but lower it to lvalue ASTs.
run_case 'int main(void) { int a[2][3] = {[1][2] = 7}; return !(a[0][0] == 0 && a[1][0] == 0 && a[1][2] == 7); }'
run_case 'struct I { int x; int y; }; struct O { int h; struct I inner; int t; }; int main(void) { struct O o = {.inner.y = 9, .h = 2}; return !(o.h == 2 && o.inner.x == 0 && o.inner.y == 9 && o.t == 0); }'
run_case 'struct P { int x; int y; }; int main(void) { struct P a[2] = {[1].x = 4, [1].y = 6}; return !(a[0].x == 0 && a[1].x == 4 && a[1].y == 6); }'
run_case 'struct I { int x; int y; }; struct O { struct I v[2]; }; int main(void) { struct O o = {.v[1].y = 12}; return !(o.v[0].x == 0 && o.v[1].x == 0 && o.v[1].y == 12); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner.x = 3, .inner.y = 4}; return !(o.inner.x == 3 && o.inner.y == 4); }'
run_case 'struct S { char rows[2][4]; }; int main(void) { struct S s = {.rows[1] = "hi"}; return !(s.rows[0][0] == 0 && s.rows[1][0] == 104 && s.rows[1][1] == 105 && s.rows[1][2] == 0); }'
run_case 'int g = 21; struct I { int *p; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner.p = &g}; return *o.inner.p == 21 ? 0 : 1; }'

# Constraint and range diagnostics at any point in a chain.
reject_case 'int a[2][3] = {[2][0] = 1}; int main(void) { return 0; }'
reject_case 'int a[2][3] = {[0][3] = 1}; int main(void) { return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; struct O o = {.inner.missing = 1}; int main(void) { return 0; }'
reject_case 'struct S { int x; }; struct S s = {.x[0] = 1}; int main(void) { return 0; }'
reject_case 'int a[2] = {[0].x = 1}; int main(void) { return 0; }'
reject_case 'struct S { int x; }; struct S s = {[0] = 1}; int main(void) { return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; struct O o = {.inner[0] = 1}; int main(void) { return 0; }'
reject_case 'int n = 1; int a[2][2] = {[n][0] = 1}; int main(void) { return 0; }'
reject_case 'struct S { int a[2]; }; struct S s = {.a = 1}; int main(void) { return 0; }'

rm -f tmp-nested-designators.c tmp-nested-designators.s tmp-nested-designators \
      tmp-nested-designators-bad.c

echo 'All nested designated-initializer chain tests passed!'
