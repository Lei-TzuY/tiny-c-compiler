#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-unary-plus.c
  ./minicc tmp-unary-plus.c > tmp-unary-plus.s
  cc -o tmp-unary-plus tmp-unary-plus.s
  ./tmp-unary-plus
}

# Unary + preserves arithmetic values for all currently supported arithmetic
# categories.
compile_and_run <<'EOF'
int main(void) {
  int i = -7;
  unsigned int u = 9U;
  float f = 1.25f;
  double d = -2.5;
  return !(+i == -7 && +u == 9U && +f == 1.25f && +d == -2.5);
}
EOF

# C requires integer promotions for unary +. _Generic makes the result type
# observable without relying on backend representation details.
compile_and_run <<'EOF'
int main(void) {
  char c = 1;
  unsigned char uc = 2;
  short s = 3;
  unsigned short us = 4;
  _Bool b = 1;
  if (_Generic(+c, int: 1, default: 0) != 1) return 1;
  if (_Generic(+uc, int: 1, default: 0) != 1) return 2;
  if (_Generic(+s, int: 1, default: 0) != 1) return 3;
  if (_Generic(+us, int: 1, default: 0) != 1) return 4;
  if (_Generic(+b, int: 1, default: 0) != 1) return 5;
  return 0;
}
EOF

# Wider integer and floating operands keep their type.
compile_and_run <<'EOF'
int main(void) {
  long l = 1;
  unsigned long ul = 2;
  float f = 3;
  double d = 4;
  if (_Generic(+l, long: 1, default: 0) != 1) return 1;
  if (_Generic(+ul, unsigned long: 1, default: 0) != 1) return 2;
  if (_Generic(+f, float: 1, default: 0) != 1) return 3;
  if (_Generic(+d, double: 1, default: 0) != 1) return 4;
  return 0;
}
EOF

# Pointer, array, record, and function operands are not arithmetic types and
# must be diagnosed instead of silently passing through unchanged.
for src in \
  'int main(void){int x; int *p=&x; return +p!=0;}' \
  'int main(void){int a[2]; return +a!=0;}' \
  'struct S{int x;}; int main(void){struct S s={1}; return +s.x + (+s);}' \
  'int f(void){return 1;} int main(void){return +f!=0;}'
do
  printf '%s\n' "$src" > tmp-unary-plus-bad.c
  if ./minicc tmp-unary-plus-bad.c >/dev/null 2>&1; then
    echo "expected unary plus rejection: $src"
    exit 1
  fi
done

rm -f tmp-unary-plus.c tmp-unary-plus.s tmp-unary-plus \
      tmp-unary-plus-bad.c

echo 'All unary plus semantic tests passed!'
