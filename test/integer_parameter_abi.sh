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
EOF
./minicc tmp-intparam-mini-callee.c > tmp-intparam-mini-callee.s
cc -c -o tmp-intparam-mini-callee.o tmp-intparam-mini-callee.s

cat > tmp-intparam-host-caller.c <<'EOF'
int mini_regs(signed char, unsigned char, short, unsigned short);
int mini_stack(int, int, int, int, int, int, signed char, unsigned short);

int main(void) {
  if (!mini_regs(-7, 250, -300, 65000))
    return 1;
  if (!mini_stack(1, 2, 3, 4, 5, 6, -9, 64000))
    return 2;
  return 0;
}
EOF
cc -o tmp-intparam-host-to-mini tmp-intparam-host-caller.c tmp-intparam-mini-callee.o
./tmp-intparam-host-to-mini

echo 'OK(integer parameter ABI): host caller -> minicc callee'

# Minicc caller -> host callee: verify fixed-parameter conversions happen before
# the ABI boundary. The deliberately out-of-range unsigned arguments must wrap
# to their destination width, and the eighth integer-class argument exercises
# the stack path. Use an indirect call for the stack case as well.
cat > tmp-intparam-host-callee.c <<'EOF'
int host_regs(signed char a, unsigned char b, short c, unsigned short d) {
  return a == -7 && b == 250 && c == -300 && d == 65535;
}

int host_stack(int a, int b, int c, int d, int e, int f,
               signed char g, unsigned short h) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         g == -9 && h == 65535;
}
EOF
cc -c -o tmp-intparam-host-callee.o tmp-intparam-host-callee.c

cat > tmp-intparam-mini-caller.c <<'EOF'
int host_regs(signed char, unsigned char, short, unsigned short);
int host_stack(int, int, int, int, int, int, signed char, unsigned short);

int main(void) {
  int (*fp)(int, int, int, int, int, int, signed char, unsigned short) = host_stack;
  if (!host_regs(-7, 506, -300, 131071))
    return 1;
  if (!fp(1, 2, 3, 4, 5, 6, -9, -1))
    return 2;
  return 0;
}
EOF
./minicc tmp-intparam-mini-caller.c > tmp-intparam-mini-caller.s
cc -o tmp-intparam-mini-to-host tmp-intparam-mini-caller.s tmp-intparam-host-callee.o
./tmp-intparam-mini-to-host

echo 'OK(integer parameter ABI): minicc caller -> host callee'

echo 'All narrow integer fixed-parameter ABI tests passed!'
