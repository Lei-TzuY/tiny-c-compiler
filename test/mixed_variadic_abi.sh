#!/bin/bash
set -eu

MINICC="${MINICC:-./minicc}"

# Variadic calls have an extra SysV AMD64 state machine beyond fixed-parameter
# calls: the caller reports used vector registers in %al, and the callee walks
# independent GP/SSE register-save cursors before both classes converge on the
# shared overflow_arg_area.  Keep INTEGER and SSE exhaustion interleaved so
# register arguments appear between stack-resident arguments in source order.
cat > tmp-mixed-va-mini-provider.c <<'EOF'
#include <stdarg.h>

int mini_varmix(int fixed_i, double fixed_d, ...) {
  va_list ap;
  va_start(ap, fixed_d);

  int i1 = va_arg(ap, int);
  double d1 = va_arg(ap, double);
  int i2 = va_arg(ap, int);
  double d2 = va_arg(ap, double);
  int i3 = va_arg(ap, int);
  double d3 = va_arg(ap, double);
  int i4 = va_arg(ap, int);
  double d4 = va_arg(ap, double);
  int i5 = va_arg(ap, int);
  double d5 = va_arg(ap, double);
  int i6 = va_arg(ap, int);
  double d6 = va_arg(ap, double);
  int i7 = va_arg(ap, int);
  double d7 = va_arg(ap, double);
  double d8 = va_arg(ap, double);
  va_end(ap);

  if (fixed_i != 9 || fixed_d != 0.5)
    return 1;
  if (i1 != 11 || i2 != 22 || i3 != 33 || i4 != 44 ||
      i5 != 55 || i6 != 66 || i7 != 77)
    return 2;
  if (d1 != 1.5 || d2 != 2.5 || d3 != 3.5 || d4 != 4.5 ||
      d5 != 5.5 || d6 != 6.5 || d7 != 7.5 || d8 != 8.5)
    return 3;
  return 0;
}
EOF
"$MINICC" tmp-mixed-va-mini-provider.c > tmp-mixed-va-mini-provider.s
gcc -c -o tmp-mixed-va-mini-provider.o tmp-mixed-va-mini-provider.s

# Host caller -> minicc variadic callee.  One named GP and one named SSE
# argument leave five GP and seven SSE registers for the variadic tail.
# i6 spills, d6 remains in XMM, i7 spills, d7 remains in XMM, then d8 spills.
# The resulting three stack slots therefore have live register arguments
# interspersed between them in source order.
cat > tmp-mixed-va-host-caller.c <<'EOF'
int mini_varmix(int, double, ...);

int main(void) {
  float promoted = 6.5f;
  return mini_varmix(9, 0.5,
                     11, 1.5,
                     22, 2.5,
                     33, 3.5,
                     44, 4.5,
                     55, 5.5,
                     66, promoted,
                     77, 7.5,
                     8.5);
}
EOF
gcc -std=c11 -o tmp-mixed-va-host-to-mini \
    tmp-mixed-va-host-caller.c tmp-mixed-va-mini-provider.o
./tmp-mixed-va-host-to-mini

echo 'OK(mixed variadic ABI): host caller -> minicc callee'

# Reverse the ABI boundary.  The host implementation of va_start/va_arg is now
# the independent oracle for minicc's variadic caller lowering, including %al,
# default float promotion, independent class exhaustion, stack packing, and an
# indirect variadic function-pointer call.
cat > tmp-mixed-va-host-provider.c <<'EOF'
#include <stdarg.h>

int host_varmix(int fixed_i, double fixed_d, ...) {
  va_list ap;
  va_start(ap, fixed_d);

  int i1 = va_arg(ap, int);
  double d1 = va_arg(ap, double);
  int i2 = va_arg(ap, int);
  double d2 = va_arg(ap, double);
  int i3 = va_arg(ap, int);
  double d3 = va_arg(ap, double);
  int i4 = va_arg(ap, int);
  double d4 = va_arg(ap, double);
  int i5 = va_arg(ap, int);
  double d5 = va_arg(ap, double);
  int i6 = va_arg(ap, int);
  double d6 = va_arg(ap, double);
  int i7 = va_arg(ap, int);
  double d7 = va_arg(ap, double);
  double d8 = va_arg(ap, double);
  va_end(ap);

  if (fixed_i != 9 || fixed_d != 0.5)
    return 1;
  if (i1 != 11 || i2 != 22 || i3 != 33 || i4 != 44 ||
      i5 != 55 || i6 != 66 || i7 != 77)
    return 2;
  if (d1 != 1.5 || d2 != 2.5 || d3 != 3.5 || d4 != 4.5 ||
      d5 != 5.5 || d6 != 6.5 || d7 != 7.5 || d8 != 8.5)
    return 3;
  return 0;
}
EOF
gcc -std=c11 -c -o tmp-mixed-va-host-provider.o tmp-mixed-va-host-provider.c

cat > tmp-mixed-va-mini-caller.c <<'EOF'
int host_varmix(int, double, ...);

int main(void) {
  int (*fp)(int, double, ...) = host_varmix;
  float promoted = 6.5f;
  return fp(9, 0.5,
            11, 1.5,
            22, 2.5,
            33, 3.5,
            44, 4.5,
            55, 5.5,
            66, promoted,
            77, 7.5,
            8.5);
}
EOF
"$MINICC" tmp-mixed-va-mini-caller.c > tmp-mixed-va-mini-caller.s
gcc -o tmp-mixed-va-mini-to-host \
    tmp-mixed-va-mini-caller.s tmp-mixed-va-host-provider.o
./tmp-mixed-va-mini-to-host

echo 'OK(mixed variadic ABI): minicc caller -> host callee (indirect)'

rm -f tmp-mixed-va-mini-provider.c tmp-mixed-va-mini-provider.s \
      tmp-mixed-va-mini-provider.o tmp-mixed-va-host-caller.c \
      tmp-mixed-va-host-to-mini tmp-mixed-va-host-provider.c \
      tmp-mixed-va-host-provider.o tmp-mixed-va-mini-caller.c \
      tmp-mixed-va-mini-caller.s tmp-mixed-va-mini-to-host

echo 'All mixed variadic ABI interoperability tests passed!'
