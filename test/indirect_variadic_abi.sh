#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

# Exercise an indirect call from minicc into a host-compiled variadic callee.
# The argument mix intentionally exhausts both SysV AMD64 register classes:
# the seventh variadic integer spills after the fixed marker consumes one GP
# register, while the ninth double spills after all eight SSE registers are used.
cat > tmp-indirect-vararg-host-callee.c <<'EOF'
#include <stdarg.h>

int host_probe(int marker, ...) {
  va_list ap;
  va_start(ap, marker);
  int i1 = va_arg(ap, int);
  int i2 = va_arg(ap, int);
  int i3 = va_arg(ap, int);
  int i4 = va_arg(ap, int);
  int i5 = va_arg(ap, int);
  int i6 = va_arg(ap, int);
  int i7 = va_arg(ap, int);
  double d1 = va_arg(ap, double);
  double d2 = va_arg(ap, double);
  double d3 = va_arg(ap, double);
  double d4 = va_arg(ap, double);
  double d5 = va_arg(ap, double);
  double d6 = va_arg(ap, double);
  double d7 = va_arg(ap, double);
  double d8 = va_arg(ap, double);
  double d9 = va_arg(ap, double);
  va_end(ap);
  return marker == 77 &&
         i1 == -5 && i2 == 2 && i3 == 3 && i4 == 4 && i5 == 5 && i6 == 6 && i7 == 70000 &&
         d1 == 1.25 && d2 == 2.0 && d3 == 3.0 && d4 == 4.0 && d5 == 5.0 &&
         d6 == 6.0 && d7 == 7.0 && d8 == 8.0 && d9 == 9.5;
}
EOF
cc -std=c11 -pedantic-errors -c -o tmp-indirect-vararg-host-callee.o tmp-indirect-vararg-host-callee.c

cat > tmp-indirect-vararg-minicc-caller.c <<'EOF'
int host_probe(int, ...);

int main(void) {
  int (*fp)(int, ...) = host_probe;
  signed char first = -5;
  float f = 1.25f;
  return !fp(77, first, 2, 3, 4, 5, 6, 70000,
             f, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.5);
}
EOF
"$MINICC" tmp-indirect-vararg-minicc-caller.c > tmp-indirect-vararg-minicc-caller.s
cc -o tmp-indirect-vararg-minicc-caller tmp-indirect-vararg-minicc-caller.s tmp-indirect-vararg-host-callee.o
./tmp-indirect-vararg-minicc-caller

# Cross the same boundary in the other direction.  A host caller invokes a
# minicc variadic callee through a function pointer, validating minicc's GP/SSE
# register-save cursors and overflow-area advancement under the same mixed load.
cat > tmp-indirect-vararg-minicc-callee.c <<'EOF'
#include <stdarg.h>

int minicc_probe(int marker, ...) {
  va_list ap;
  va_start(ap, marker);
  int i1 = va_arg(ap, int);
  int i2 = va_arg(ap, int);
  int i3 = va_arg(ap, int);
  int i4 = va_arg(ap, int);
  int i5 = va_arg(ap, int);
  int i6 = va_arg(ap, int);
  int i7 = va_arg(ap, int);
  double d1 = va_arg(ap, double);
  double d2 = va_arg(ap, double);
  double d3 = va_arg(ap, double);
  double d4 = va_arg(ap, double);
  double d5 = va_arg(ap, double);
  double d6 = va_arg(ap, double);
  double d7 = va_arg(ap, double);
  double d8 = va_arg(ap, double);
  double d9 = va_arg(ap, double);
  va_end(ap);
  return marker == 88 &&
         i1 == -7 && i2 == 12 && i3 == 13 && i4 == 14 && i5 == 15 && i6 == 16 && i7 == 80000 &&
         d1 == 1.5 && d2 == 2.5 && d3 == 3.5 && d4 == 4.5 && d5 == 5.5 &&
         d6 == 6.5 && d7 == 7.5 && d8 == 8.5 && d9 == 9.5;
}
EOF
"$MINICC" tmp-indirect-vararg-minicc-callee.c > tmp-indirect-vararg-minicc-callee.s
cc -c -o tmp-indirect-vararg-minicc-callee.o tmp-indirect-vararg-minicc-callee.s

cat > tmp-indirect-vararg-host-caller.c <<'EOF'
int minicc_probe(int, ...);

int main(void) {
  int (*fp)(int, ...) = minicc_probe;
  signed char first = -7;
  float f = 1.5f;
  return !fp(88, first, 12, 13, 14, 15, 16, 80000,
             f, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5);
}
EOF
cc -std=c11 -pedantic-errors -o tmp-indirect-vararg-host-caller \
  tmp-indirect-vararg-host-caller.c tmp-indirect-vararg-minicc-callee.o
./tmp-indirect-vararg-host-caller

rm -f tmp-indirect-vararg-host-callee.c tmp-indirect-vararg-host-callee.o \
  tmp-indirect-vararg-minicc-caller.c tmp-indirect-vararg-minicc-caller.s tmp-indirect-vararg-minicc-caller \
  tmp-indirect-vararg-minicc-callee.c tmp-indirect-vararg-minicc-callee.s tmp-indirect-vararg-minicc-callee.o \
  tmp-indirect-vararg-host-caller.c tmp-indirect-vararg-host-caller

echo 'All indirect variadic ABI tests passed!'
