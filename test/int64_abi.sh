#!/bin/bash
set -eu

cleanup() {
  rm -f tmp-int64-*.c tmp-int64-*.s tmp-int64-*.o tmp-int64-host-to-mini tmp-int64-mini-to-host
}
trap cleanup EXIT

# Host caller -> minicc callee: exercise signed/unsigned 64-bit INTEGER-class
# parameters and returns, including the seventh integer argument on the stack.
cat > tmp-int64-mini-callee.c <<'EOF'
long mini_neg(void) { return -0x123456789ABCDEFL; }
unsigned long mini_high(void) { return 0xFEDCBA9876543210UL; }

int mini_regs(long a, unsigned long b) {
  return a == -0x123456789ABCDEFL && b == 0xFEDCBA9876543210UL;
}

int mini_stack(long a, long b, long c, long d, long e, long f,
               unsigned long g) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         g == 0xFEDCBA9876543210UL;
}
EOF
./minicc tmp-int64-mini-callee.c > tmp-int64-mini-callee.s
cc -c -o tmp-int64-mini-callee.o tmp-int64-mini-callee.s

cat > tmp-int64-host-caller.c <<'EOF'
long mini_neg(void);
unsigned long mini_high(void);
int mini_regs(long, unsigned long);
int mini_stack(long, long, long, long, long, long, unsigned long);

int main(void) {
  if (mini_neg() != -0x123456789ABCDEFL) return 1;
  if (mini_high() != 0xFEDCBA9876543210UL) return 2;
  if (!mini_regs(-0x123456789ABCDEFL, 0xFEDCBA9876543210UL)) return 3;
  if (!mini_stack(1, 2, 3, 4, 5, 6, 0xFEDCBA9876543210UL)) return 4;
  return 0;
}
EOF
cc -std=c11 -o tmp-int64-host-to-mini tmp-int64-host-caller.c tmp-int64-mini-callee.o
./tmp-int64-host-to-mini

echo 'OK(int64 ABI): host caller -> minicc callee'

# Minicc caller -> host callee: verify full-width values survive both direct and
# indirect calls and that signed negative returns preserve their high bits.
cat > tmp-int64-host-callee.c <<'EOF'
long host_neg(void) { return -0x123456789ABCDEFL; }
unsigned long host_high(void) { return 0xFEDCBA9876543210UL; }

int host_regs(long a, unsigned long b) {
  return a == -0x123456789ABCDEFL && b == 0xFEDCBA9876543210UL;
}

int host_stack(long a, long b, long c, long d, long e, long f,
               unsigned long g) {
  return a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 &&
         g == 0xFEDCBA9876543210UL;
}
EOF
cc -std=c11 -c -o tmp-int64-host-callee.o tmp-int64-host-callee.c

cat > tmp-int64-mini-caller.c <<'EOF'
long host_neg(void);
unsigned long host_high(void);
int host_regs(long, unsigned long);
int host_stack(long, long, long, long, long, long, unsigned long);

int main(void) {
  int (*fp)(long, long, long, long, long, long, unsigned long) = host_stack;
  if (host_neg() != -0x123456789ABCDEFL) return 1;
  if (host_high() != 0xFEDCBA9876543210UL) return 2;
  if (!host_regs(-0x123456789ABCDEFL, 0xFEDCBA9876543210UL)) return 3;
  if (!fp(1, 2, 3, 4, 5, 6, 0xFEDCBA9876543210UL)) return 4;
  return 0;
}
EOF
./minicc tmp-int64-mini-caller.c > tmp-int64-mini-caller.s
cc -o tmp-int64-mini-to-host tmp-int64-mini-caller.s tmp-int64-host-callee.o
./tmp-int64-mini-to-host

echo 'OK(int64 ABI): minicc caller -> host callee'

echo 'All 64-bit integer ABI tests passed!'
