#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-comparison-scalar.c
  ./minicc tmp-comparison-scalar.c > tmp-comparison-scalar.s
  cc -o tmp-comparison-scalar tmp-comparison-scalar.s
  ./tmp-comparison-scalar
}

# Arithmetic values and pointer/array/function designators remain valid scalar
# comparison operands.
compile_and_run <<'EOF'
int f(void) { return 1; }
int main(void) {
  int x = 3;
  int y = 4;
  int *p = &x;
  int *q = &y;
  int a[1] = {0};
  if ((x < y) != 1) return 1;
  if ((x == 3) != 1) return 2;
  if ((p != q) != 1) return 3;
  if ((a == &a[0]) != 1) return 4;
  if ((f == f) != 1) return 5;
  return 0;
}
EOF

# Aggregate values are not scalar and therefore cannot participate directly in
# equality or relational comparisons.
for src in \
  'struct S{int x;}; int main(void){struct S a={1},b={1}; return a==b;}' \
  'struct S{int x;}; int main(void){struct S a={1},b={2}; return a!=b;}' \
  'struct S{int x;}; int main(void){struct S a={1},b={2}; return a<b;}' \
  'struct S{int x;}; int main(void){struct S a={1},b={2}; return a<=b;}' \
  'union U{int x; long y;}; int main(void){union U a={1},b={1}; return a==b;}' \
  'union U{int x; long y;}; int main(void){union U a={1},b={2}; return a<b;}'
do
  printf '%s\n' "$src" > tmp-comparison-scalar-bad.c
  if ./minicc tmp-comparison-scalar-bad.c >/dev/null 2>&1; then
    echo "expected comparison scalar-operand rejection: $src"
    exit 1
  fi
done

rm -f tmp-comparison-scalar.c tmp-comparison-scalar.s tmp-comparison-scalar \
      tmp-comparison-scalar-bad.c

echo 'All comparison scalar operand tests passed!'
