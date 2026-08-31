#!/bin/bash
set -eu

# Verify the caller side of the SysV ABI: integer types narrower than int must
# undergo the default argument promotions before a host-compiled variadic
# callee observes them through va_arg(int), while float must arrive as double.
cat > tmp-promote-host-callee.c <<'EOF'
#include <stdarg.h>
int host_probe(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int sc = va_arg(ap, int);
  int uc = va_arg(ap, int);
  int ss = va_arg(ap, int);
  int us = va_arg(ap, int);
  double f = va_arg(ap, double);
  va_end(ap);
  return sc == -5 && uc == 250 && ss == -1234 && us == 60000 && f == 1.25;
}
EOF
cc -c -o tmp-promote-host-callee.o tmp-promote-host-callee.c

cat > tmp-promote-minicc-caller.c <<'EOF'
int host_probe(int, ...);
int main(void) {
  signed char sc = -5;
  unsigned char uc = 250;
  short ss = -1234;
  unsigned short us = 60000;
  float f = 1.25f;
  return !host_probe(0, sc, uc, ss, us, f);
}
EOF
./minicc tmp-promote-minicc-caller.c > tmp-promote-minicc-caller.s
cc -o tmp-promote-minicc-caller tmp-promote-minicc-caller.s tmp-promote-host-callee.o
./tmp-promote-minicc-caller

# Cross the ABI in the other direction too. A host caller performs the same
# promotions, and a minicc variadic callee must recover the promoted values
# from the GP/SSE save areas with va_arg(int)/va_arg(double).
cat > tmp-promote-minicc-callee.c <<'EOF'
#include <stdarg.h>
int minicc_probe(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int sc = va_arg(ap, int);
  int uc = va_arg(ap, int);
  int ss = va_arg(ap, int);
  int us = va_arg(ap, int);
  double f = va_arg(ap, double);
  va_end(ap);
  return sc == -7 && uc == 240 && ss == -2222 && us == 50000 && f == 2.5;
}
EOF
./minicc tmp-promote-minicc-callee.c > tmp-promote-minicc-callee.s
cc -c -o tmp-promote-minicc-callee.o tmp-promote-minicc-callee.s

cat > tmp-promote-host-caller.c <<'EOF'
int minicc_probe(int, ...);
int main(void) {
  signed char sc = -7;
  unsigned char uc = 240;
  short ss = -2222;
  unsigned short us = 50000;
  float f = 2.5f;
  return !minicc_probe(0, sc, uc, ss, us, f);
}
EOF
cc -o tmp-promote-host-caller tmp-promote-host-caller.c tmp-promote-minicc-callee.o
./tmp-promote-host-caller

rm -f tmp-promote-host-callee.c tmp-promote-host-callee.o \
  tmp-promote-minicc-caller.c tmp-promote-minicc-caller.s tmp-promote-minicc-caller \
  tmp-promote-minicc-callee.c tmp-promote-minicc-callee.s tmp-promote-minicc-callee.o \
  tmp-promote-host-caller.c tmp-promote-host-caller

echo 'All variadic default-promotion ABI tests passed!'
