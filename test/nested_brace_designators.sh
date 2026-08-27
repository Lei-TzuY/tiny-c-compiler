#!/bin/bash
set -eu

run_case() {
  src="$1"
  cat > tmp-nested-brace-designators.c <<EOF
$src
EOF
  ./minicc tmp-nested-brace-designators.c > tmp-nested-brace-designators.s
  cc -o tmp-nested-brace-designators tmp-nested-brace-designators.s
  ./tmp-nested-brace-designators
  echo "OK(nested brace designator): $src"
}

reject_case() {
  src="$1"
  cat > tmp-nested-brace-designators-bad.c <<EOF
$src
EOF
  if ./minicc tmp-nested-brace-designators-bad.c >/dev/null 2>&1; then
    echo "expected nested-brace designator rejection: $src"
    exit 1
  fi
  echo "OK(reject nested brace designator): $src"
}

# Static paths were already recursive; keep them covered while automatic
# nested-brace parsing is brought to the same language surface.
run_case 'struct I { int x; int y; }; struct O { struct I inner; int z; }; struct O o = {.inner = {.y = 4, .x = 3}, .z = 5}; int main(void) { return !(o.inner.x == 3 && o.inner.y == 4 && o.z == 5); }'
run_case 'int a[2][3] = {[1] = {[2] = 7, [0] = 4}}; int main(void) { return !(a[0][0] == 0 && a[1][0] == 4 && a[1][1] == 0 && a[1][2] == 7); }'
run_case 'int f(void) { static struct I { int x; int y; } a[2] = {[1] = {.y = 8, .x = 6}}; return a[1].x + a[1].y; } int main(void) { return f() == 14 ? 0 : 1; }'

# Automatic nested braced initializer-lists.
run_case 'struct I { int x; int y; }; struct O { struct I inner; int z; }; int main(void) { struct O o = {.inner = {.y = 4, .x = 3}, .z = 5}; return !(o.inner.x == 3 && o.inner.y == 4 && o.z == 5); }'
run_case 'int main(void) { int a[2][3] = {[1] = {[2] = 7, [0] = 4}}; return !(a[0][0] == 0 && a[1][0] == 4 && a[1][1] == 0 && a[1][2] == 7); }'
run_case 'int main(void) { int a[2][3] = {{[1] = 2}, {[2] = 7}}; return !(a[0][0] == 0 && a[0][1] == 2 && a[1][0] == 0 && a[1][2] == 7); }'
run_case 'int main(void) { int a[1][3] = {{[1] = 5, 6}}; return !(a[0][0] == 0 && a[0][1] == 5 && a[0][2] == 6); }'
run_case 'struct I { int x; int y; int z; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.y = 2, 3}}; return !(o.inner.x == 0 && o.inner.y == 2 && o.inner.z == 3); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.x = 1, .x = 4, .y = 7}}; return !(o.inner.x == 4 && o.inner.y == 7); }'
run_case 'struct S { char rows[2][4]; }; int main(void) { struct S s = {.rows = {[1] = "hi"}}; return !(s.rows[0][0] == 0 && s.rows[1][0] == 104 && s.rows[1][1] == 105 && s.rows[1][2] == 0); }'
run_case 'struct P { int x; int y; }; int main(void) { struct P a[2] = {{.y = 2, .x = 1}, {.x = 3}}; return !(a[0].x == 1 && a[0].y == 2 && a[1].x == 3 && a[1].y == 0); }'
run_case 'int g = 21; struct I { int *p; int n; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.p = &g, .n = 2}}; return !(*o.inner.p == 21 && o.inner.n == 2); }'
run_case 'union U { long l; int i; }; struct W { union U u; int z; }; int main(void) { struct W w = {.u = {.l = 17}, .z = 3}; return !(w.u.l == 17 && w.z == 3); }'
run_case 'struct I { int x; int y; }; struct M { struct I inner; int m; }; struct O { struct M mid; }; int main(void) { struct O o = {.mid = {.inner = {.y = 9}, .m = 4}}; return !(o.mid.inner.x == 0 && o.mid.inner.y == 9 && o.mid.m == 4); }'
run_case 'struct I { int x; int y; int z; }; struct O { struct I inner; int tail; }; int main(void) { struct O o = {.inner = {.y = 5}, .tail = 8}; return !(o.inner.x == 0 && o.inner.y == 5 && o.inner.z == 0 && o.tail == 8); }'
run_case 'enum { R = 1, C = 2 }; int main(void) { int a[2][3] = {[R] = {[C] = 19}}; return a[1][2] == 19 ? 0 : 1; }'

# Nested path diagnostics must still be enforced inside the inner braces.
reject_case 'int main(void) { int a[1][2] = {{[2] = 1}}; return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.missing = 1}}; return 0; }'
reject_case 'int main(void) { int a[1][2] = {{.x = 1}}; return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {[0] = 1}}; return 0; }'
reject_case 'int main(void) { int n = 1; int a[1][2] = {{[n] = 1}}; return 0; }'
reject_case 'union U { int a; long b; }; struct O { union U u; }; int main(void) { struct O o = {.u = {.a = 1, .b = 2}}; return 0; }'
reject_case 'int main(void) { int a[1][3] = {{[2] = 7, 8}}; return 0; }'
reject_case 'struct I { int x; int y; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.y = 2, 3}}; return 0; }'

rm -f tmp-nested-brace-designators.c tmp-nested-brace-designators.s \
      tmp-nested-brace-designators tmp-nested-brace-designators-bad.c

echo 'All nested-brace designated initializer tests passed!'
