#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-logical-scalar.c
  ./minicc tmp-logical-scalar.c > tmp-logical-scalar.s
  cc -o tmp-logical-scalar tmp-logical-scalar.s
  ./tmp-logical-scalar
}

# Arithmetic and pointer operands are scalar and remain valid for !, && and ||.
compile_and_run <<'EOF'
int f(void) { return 1; }
int main(void) {
  int x = 1;
  int *p = &x;
  int a[1] = {1};
  if (!!x != 1) return 1;
  if ((!0.0) != 1) return 2;
  if ((!p) != 0) return 3;
  if ((p && x) != 1) return 4;
  if ((0 || p) != 1) return 5;
  if ((!a) != 0) return 6;
  if ((!f) != 0) return 7;
  return 0;
}
EOF

# Logical operators require scalar operands. Records/unions must be rejected
# instead of reaching code generation with an aggregate value.
for src in \
  'struct S{int x;}; int main(void){struct S s={1}; return !s;}' \
  'struct S{int x;}; int main(void){struct S s={1}; return s && 1;}' \
  'struct S{int x;}; int main(void){struct S s={1}; return 0 || s;}' \
  'union U{int x; long y;}; int main(void){union U u={1}; return !u;}' \
  'union U{int x; long y;}; int main(void){union U u={1}; return u && 1;}'
do
  printf '%s\n' "$src" > tmp-logical-scalar-bad.c
  if ./minicc tmp-logical-scalar-bad.c >/dev/null 2>&1; then
    echo "expected logical scalar-operand rejection: $src"
    exit 1
  fi
done

rm -f tmp-logical-scalar.c tmp-logical-scalar.s tmp-logical-scalar \
      tmp-logical-scalar-bad.c

echo 'All logical scalar operand tests passed!'
