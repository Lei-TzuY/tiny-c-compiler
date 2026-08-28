#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-comparison-scalar.c
  ./minicc tmp-comparison-scalar.c > tmp-comparison-scalar.s
  cc -o tmp-comparison-scalar tmp-comparison-scalar.s
  ./tmp-comparison-scalar
}

# Arithmetic values and pointer/array/function designators remain valid scalar
# comparison operands. Relational comparisons are valid for arithmetic values
# and pointers into the same object/array. Equality also permits the canonical
# integer null pointer constant 0 on either side.
compile_and_run <<'EOF'
int f(void) { return 1; }
int main(void) {
  int x = 3;
  int y = 4;
  int *p = &x;
  int *q = &y;
  int *z = 0;
  int a[2] = {0, 0};
  if ((x < y) != 1) return 1;
  if ((x == 3) != 1) return 2;
  if ((p != q) != 1) return 3;
  if ((a == &a[0]) != 1) return 4;
  if ((f == f) != 1) return 5;
  if ((&a[0] < &a[1]) != 1) return 6;
  if ((&a[1] >= &a[0]) != 1) return 7;
  if ((z == 0) != 1) return 8;
  if ((0 == z) != 1) return 9;
  if ((p != 0) != 1) return 10;
  return 0;
}
EOF

# Aggregate values are not scalar and therefore cannot participate directly in
# equality or relational comparisons. Relational operators additionally require
# both operands to be arithmetic, or both to be pointers to object types.
# Equality requires two arithmetic operands, two pointer/designator operands,
# or one pointer/designator and the integer null pointer constant 0.
for src in \
  'struct S{int x;}; int main(void){struct S a={1},b={1}; return a==b;}' \
  'struct S{int x;}; int main(void){struct S a={1},b={2}; return a!=b;}' \
  'struct S{int x;}; int main(void){struct S a={1},b={2}; return a<b;}' \
  'struct S{int x;}; int main(void){struct S a={1},b={2}; return a<=b;}' \
  'union U{int x; long y;}; int main(void){union U a={1},b={1}; return a==b;}' \
  'union U{int x; long y;}; int main(void){union U a={1},b={2}; return a<b;}' \
  'int main(void){int x=0; int *p=&x; return p==3;}' \
  'int main(void){int x=0; int *p=&x; return 3!=p;}' \
  'int main(void){int x=0; int *p=&x; return p==1.0;}' \
  'int main(void){int x=0; int *p=&x; return 1.0!=p;}' \
  'int main(void){int x=0; int *p=&x; return p<1;}' \
  'int main(void){int x=0; int *p=&x; return 1<=p;}' \
  'int main(void){int x=0; int *p=&x; return p>1;}' \
  'int f(void){return 0;} int main(void){return f<f;}' \
  'int f(void){return 0;} int main(void){int (*p)(void)=f; return p<=p;}' \
  'int main(void){void *p=0; void *q=0; return p<q;}'
do
  printf '%s\n' "$src" > tmp-comparison-scalar-bad.c
  if ./minicc tmp-comparison-scalar-bad.c >/dev/null 2>&1; then
    echo "expected comparison operand rejection: $src"
    exit 1
  fi
done

rm -f tmp-comparison-scalar.c tmp-comparison-scalar.s tmp-comparison-scalar \
      tmp-comparison-scalar-bad.c

echo 'All comparison scalar operand tests passed!'
