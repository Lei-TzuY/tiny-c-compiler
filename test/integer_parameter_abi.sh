#!/bin/bash
set -eu

cleanup() {
  rm -f tmp-intparam-*.c tmp-intparam-*.s tmp-intparam-*.o tmp-intparam-host-to-mini tmp-intparam-mini-to-host
}
trap cleanup EXIT

# Host caller -> minicc callee: verify that minicc reads narrow fixed parameters
# with the declared signedness in both register and stack argument slots.
cat > tmp-intparam-mini-callee.c <<'EOF'
int mini_regs(signed char a, unsigned char b, short c, unsigned short d) {
  return a == -7 && b == 250 && c == -300 && d == 65000;
}

int mini_stack(int a, int b, int c, int d, int e, int f,
               signed char g, unsigned short h) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         g == -9 && h == 64000;
}

int mini_bool_regs(_Bool a, _Bool b, _Bool c) {
  return a == 0 && b == 1 && c == 1;
}

int mini_bool_stack(int a, int b, int c, int d, int e, int f, _Bool g) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 && g == 1;
}

_Bool mini_bool_return_int(int x) {
  return x;
}

_Bool mini_bool_return_double(double x) {
  return x;
}
EOF
./minicc tmp-intparam-mini-callee.c > tmp-intparam-mini-callee.s
cc -c -o tmp-intparam-mini-callee.o tmp-intparam-mini-callee.s

cat > tmp-intparam-host-caller.c <<'EOF'
int mini_regs(signed char, unsigned char, short, unsigned short);
int mini_stack(int, int, int, int, int, int, signed char, unsigned short);
int mini_bool_regs(_Bool, _Bool, _Bool);
int mini_bool_stack(int, int, int, int, int, int, _Bool);
_Bool mini_bool_return_int(int);
_Bool mini_bool_return_double(double);

int main(void) {
  if (!mini_regs(-7, 250, -300, 65000))
    return 1;
  if (!mini_stack(1, 2, 3, 4, 5, 6, -9, 64000))
    return 2;
  if (!mini_bool_regs(0, 1, 7))
    return 3;
  if (!mini_bool_stack(1, 2, 3, 4, 5, 6, -9))
    return 4;
  if (mini_bool_return_int(0) != 0 || mini_bool_return_int(-7) != 1)
    return 5;
  if (mini_bool_return_double(0.0) != 0 || mini_bool_return_double(2.5) != 1)
    return 6;
  return 0;
}
EOF
cc -o tmp-intparam-host-to-mini tmp-intparam-host-caller.c tmp-intparam-mini-callee.o
./tmp-intparam-host-to-mini

echo 'OK(integer parameter ABI): host caller -> minicc callee'

# Minicc caller -> host callee: verify fixed-parameter conversions happen before
# the ABI boundary. The deliberately out-of-range unsigned arguments must wrap
# to their destination width, and the eighth integer-class argument exercises
# the stack path. Use an indirect call for the stack case as well. _Bool fixed
# parameters additionally verify that arbitrary scalar values are normalized to
# exactly 0 or 1 before crossing either register or stack ABI paths.
cat > tmp-intparam-host-callee.c <<'EOF'
int host_regs(signed char a, unsigned char b, short c, unsigned short d) {
  return a == -7 && b == 250 && c == -300 && d == 65535;
}

int host_stack(int a, int b, int c, int d, int e, int f,
               signed char g, unsigned short h) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         g == -9 && h == 65535;
}

int host_bool_regs(_Bool a, _Bool b, _Bool c) {
  return a == 0 && b == 1 && c == 1;
}

int host_bool_stack(int a, int b, int c, int d, int e, int f, _Bool g) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 && g == 1;
}

_Bool host_bool_return_int(int x) {
  return x;
}

_Bool host_bool_return_double(double x) {
  return x;
}
EOF
cc -c -o tmp-intparam-host-callee.o tmp-intparam-host-callee.c

cat > tmp-intparam-mini-caller.c <<'EOF'
int host_regs(signed char, unsigned char, short, unsigned short);
int host_stack(int, int, int, int, int, int, signed char, unsigned short);
int host_bool_regs(_Bool, _Bool, _Bool);
int host_bool_stack(int, int, int, int, int, int, _Bool);
_Bool host_bool_return_int(int);
_Bool host_bool_return_double(double);

int main(void) {
  int (*fp)(int, int, int, int, int, int, signed char, unsigned short) = host_stack;
  int (*boolfp)(int, int, int, int, int, int, _Bool) = host_bool_stack;
  _Bool (*retfp)(int) = host_bool_return_int;
  if (!host_regs(-7, 506, -300, 131071))
    return 1;
  if (!fp(1, 2, 3, 4, 5, 6, -9, -1))
    return 2;
  if (!host_bool_regs(0, 2, -3))
    return 3;
  if (!boolfp(1, 2, 3, 4, 5, 6, 99))
    return 4;
  if (retfp(0) != 0 || retfp(-7) != 1)
    return 5;
  if (host_bool_return_double(0.0) != 0 || host_bool_return_double(-2.5) != 1)
    return 6;
  return 0;
}
EOF
./minicc tmp-intparam-mini-caller.c > tmp-intparam-mini-caller.s
cc -o tmp-intparam-mini-to-host tmp-intparam-mini-caller.s tmp-intparam-host-callee.o
./tmp-intparam-mini-to-host

echo 'OK(integer parameter ABI): minicc caller -> host callee'

echo 'All narrow integer and _Bool fixed-parameter/return ABI tests passed!'
