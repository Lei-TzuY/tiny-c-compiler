#!/bin/bash
set -eu

MINICC="${MINICC:-./minicc}"

# Use the host compiler as an independent SysV AMD64 oracle.  The minicc side
# deliberately sees an old-style function type (no prototype) and then calls
# it indirectly, so default argument promotions and the variadic-style SSE
# register count must be produced by the function-pointer call path.
cat > tmp-oldstyle-host.c <<'EOF'
int host_oldstyle(int a, double b, unsigned int c, long d, double e) {
  return a == -7 && b == 3.5 && c == 250u && d == 11L && e == 9.25;
}
EOF

cc -std=c11 -c -o tmp-oldstyle-host.o tmp-oldstyle-host.c

cat > tmp-oldstyle-mini.c <<'EOF'
int host_oldstyle();

int main(void) {
  int (*fp)() = host_oldstyle;
  signed char a = -7;
  float b = 3.5f;
  unsigned char c = 250;
  short d = 11;
  float e = 9.25f;

  /* With no prototype, C default argument promotions require:
       signed char -> int
       float       -> double
       unsigned char -> int on this target
       short       -> int
       float       -> double
     The actual host callee observes the promoted SysV register classes. */
  return fp(a, b, c, d, e) ? 0 : 1;
}
EOF

"$MINICC" tmp-oldstyle-mini.c > tmp-oldstyle-mini.s
cc -o tmp-oldstyle tmp-oldstyle-mini.s tmp-oldstyle-host.o
./tmp-oldstyle

echo 'OK(old-style indirect ABI): default promotions across host boundary'

rm -f tmp-oldstyle-host.c tmp-oldstyle-host.o \
      tmp-oldstyle-mini.c tmp-oldstyle-mini.s tmp-oldstyle

echo 'All indirect old-style call ABI tests passed!'
