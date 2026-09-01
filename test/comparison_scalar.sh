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
  const int *cp = &a[1];
  if ((&a[0] < cp) != 1) return 11;
  return 0;
}
EOF

# IEEE NaNs are unordered. C equality/relational operators must therefore make
# ==, <, <=, >, and >= false while != remains true, regardless of which operand
# carries the NaN. This specifically exercises the parity-flag handling required
# after x86 ucomiss/ucomisd rather than only ordinary ordered comparisons.
compile_and_run <<'EOF'
int main(void) {
  volatile float zf = 0.0f;
  volatile double zd = 0.0;
  float nf = zf / zf;
  double nd = zd / zd;

  if ((nf == 1.0f) != 0) return 1;
  if ((nf != 1.0f) != 1) return 2;
  if ((nf < 1.0f) != 0) return 3;
  if ((nf <= 1.0f) != 0) return 4;
  if ((nf > 1.0f) != 0) return 5;
  if ((nf >= 1.0f) != 0) return 6;
  if ((1.0f == nf) != 0) return 7;
  if ((1.0f != nf) != 1) return 8;
  if ((1.0f < nf) != 0) return 9;
  if ((1.0f <= nf) != 0) return 10;
  if ((1.0f > nf) != 0) return 11;
  if ((1.0f >= nf) != 0) return 12;

  if ((nd == 1.0) != 0) return 13;
  if ((nd != 1.0) != 1) return 14;
  if ((nd < 1.0) != 0) return 15;
  if ((nd <= 1.0) != 0) return 16;
  if ((nd > 1.0) != 0) return 17;
  if ((nd >= 1.0) != 0) return 18;
  if ((1.0 == nd) != 0) return 19;
  if ((1.0 != nd) != 1) return 20;
  if ((1.0 < nd) != 0) return 21;
  if ((1.0 <= nd) != 0) return 22;
  if ((1.0 > nd) != 0) return 23;
  if ((1.0 >= nd) != 0) return 24;
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
  'int main(void){void *p=0; void *q=0; return p<q;}' \
  'int main(void){int x=0; double y=0; return &x<&y;}' \
  'int main(void){struct A{int x;} a; struct B{int x;} b; return &a<=&b;}' \
  'int main(void){int x=0; int *p=&x; const int *cp=&x; int **pp=&p; const int **cpp=&cp; return pp<cpp;}'
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
