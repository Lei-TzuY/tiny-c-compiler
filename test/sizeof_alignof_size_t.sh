#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-sizeof-type.c
  ./minicc tmp-sizeof-type.c > tmp-sizeof-type.s
  cc -o tmp-sizeof-type tmp-sizeof-type.s
  ./tmp-sizeof-type
}

# C defines both sizeof and _Alignof to have type size_t. On this LP64 target
# size_t is unsigned long.
compile_and_run <<'EOF'
int main(void) {
  int x = 0;
  if (!_Generic(sizeof(int), unsigned long: 1, default: 0)) return 1;
  if (!_Generic(sizeof x, unsigned long: 1, default: 0)) return 2;
  if (!_Generic(_Alignof(long), unsigned long: 1, default: 0)) return 3;
  if (!_Generic(_Alignof(int[3]), unsigned long: 1, default: 0)) return 4;
  return 0;
}
EOF

# The unsigned result type must participate in the usual arithmetic conversions.
# If sizeof/_Alignof were incorrectly typed as int, these comparisons would be true.
compile_and_run <<'EOF'
int main(void) {
  if (sizeof(int) > -1) return 1;
  if (_Alignof(long) > -1) return 2;
  if (!_Generic(sizeof(int) + 1, unsigned long: 1, default: 0)) return 3;
  if (!_Generic(_Alignof(double) + 1L, unsigned long: 1, default: 0)) return 4;
  return 0;
}
EOF

# Constant-expression consumers must observe the same unsigned-long type.
compile_and_run <<'EOF'
_Static_assert(_Generic(sizeof(char), unsigned long: 1, default: 0), "sizeof type");
_Static_assert(_Generic(_Alignof(double), unsigned long: 1, default: 0), "alignof type");
_Static_assert(!(sizeof(int) > -1), "sizeof unsigned conversion");
_Static_assert(!(_Alignof(long) > -1), "alignof unsigned conversion");
int main(void) { return 0; }
EOF

# Ordinary values and typedef spelling remain usable without a built-in size_t typedef.
compile_and_run <<'EOF'
typedef unsigned long my_size_t;
struct S { char c; long x; };
int main(void) {
  my_size_t a = sizeof(struct S);
  my_size_t b = _Alignof(struct S);
  return a == 16 && b == 8 ? 0 : 1;
}
EOF

rm -f tmp-sizeof-type.c tmp-sizeof-type.s tmp-sizeof-type

echo 'All sizeof/_Alignof size_t type tests passed!'
