#!/bin/bash
set -e

MINICC="${MINICC:-./minicc}"

# Cross the host/minicc boundary in both directions. These signatures exhaust
# INTEGER and SSE register classes at different points while later arguments
# from the other class can still use registers. The remaining overflow
# arguments are therefore interleaved in source order rather than forming one
# simple tail, which stresses both stack packing and callee stack offsets.
cat > tmp-mixed-scalar-mini-provider.c <<'EOF'
int mini_gp_first(int a1, int a2, int a3, int a4, int a5, int a6,
                  double d1, double d2, double d3, double d4,
                  double d5, double d6, double d7,
                  int g, double d8, double d9, int h) {
  if (a1 != 1 || a6 != 6 || d1 != 1.5 || d7 != 7.5)
    return -1;
  return g * 100 + (int)d8 * 10 + (int)d9 + h * 1000;
}

int mini_sse_first(double d1, double d2, double d3, double d4,
                   double d5, double d6, double d7, double d8,
                   int a1, int a2, int a3, int a4, int a5,
                   double d9, int a6, int a7, double d10) {
  if (d1 != 1.5 || d8 != 8.5 || a1 != 1 || a5 != 5)
    return -1;
  return (int)d9 * 1000 + a6 * 100 + a7 * 10 + (int)d10;
}
EOF
"$MINICC" tmp-mixed-scalar-mini-provider.c > tmp-mixed-scalar-mini-provider.s
gcc -c -o tmp-mixed-scalar-mini-provider.o tmp-mixed-scalar-mini-provider.s

cat > tmp-mixed-scalar-host-caller.c <<'EOF'
int mini_gp_first(int, int, int, int, int, int,
                  double, double, double, double, double, double, double,
                  int, double, double, int);
int mini_sse_first(double, double, double, double, double, double, double, double,
                   int, int, int, int, int, double, int, int, double);

int main(void) {
  int gp = mini_gp_first(1, 2, 3, 4, 5, 6,
                         1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5,
                         7, 8.5, 9.5, 4);
  if (gp != 4789)
    return 1;

  int sse = mini_sse_first(1.5, 2.5, 3.5, 4.5,
                           5.5, 6.5, 7.5, 8.5,
                           1, 2, 3, 4, 5, 9.5, 6, 7, 10.5);
  if (sse != 9680)
    return 2;
  return 0;
}
EOF
gcc -std=c11 -o tmp-mixed-scalar-host-to-mini \
    tmp-mixed-scalar-host-caller.c tmp-mixed-scalar-mini-provider.o
./tmp-mixed-scalar-host-to-mini

echo 'OK(mixed scalar ABI): host caller -> minicc callee'

cat > tmp-mixed-scalar-host-provider.c <<'EOF'
int host_gp_first(int a1, int a2, int a3, int a4, int a5, int a6,
                  double d1, double d2, double d3, double d4,
                  double d5, double d6, double d7,
                  int g, double d8, double d9, int h) {
  if (a1 != 1 || a6 != 6 || d1 != 1.5 || d7 != 7.5)
    return -1;
  return g * 100 + (int)d8 * 10 + (int)d9 + h * 1000;
}

int host_sse_first(double d1, double d2, double d3, double d4,
                   double d5, double d6, double d7, double d8,
                   int a1, int a2, int a3, int a4, int a5,
                   double d9, int a6, int a7, double d10) {
  if (d1 != 1.5 || d8 != 8.5 || a1 != 1 || a5 != 5)
    return -1;
  return (int)d9 * 1000 + a6 * 100 + a7 * 10 + (int)d10;
}
EOF
gcc -std=c11 -c -o tmp-mixed-scalar-host-provider.o tmp-mixed-scalar-host-provider.c

cat > tmp-mixed-scalar-mini-caller.c <<'EOF'
int host_gp_first(int, int, int, int, int, int,
                  double, double, double, double, double, double, double,
                  int, double, double, int);
int host_sse_first(double, double, double, double, double, double, double, double,
                   int, int, int, int, int, double, int, int, double);

int main(void) {
  int (*gp_fp)(int, int, int, int, int, int,
               double, double, double, double, double, double, double,
               int, double, double, int) = host_gp_first;

  int gp = gp_fp(1, 2, 3, 4, 5, 6,
                 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5,
                 7, 8.5, 9.5, 4);
  if (gp != 4789)
    return 1;

  int sse = host_sse_first(1.5, 2.5, 3.5, 4.5,
                           5.5, 6.5, 7.5, 8.5,
                           1, 2, 3, 4, 5, 9.5, 6, 7, 10.5);
  if (sse != 9680)
    return 2;
  return 0;
}
EOF
"$MINICC" tmp-mixed-scalar-mini-caller.c > tmp-mixed-scalar-mini-caller.s
gcc -o tmp-mixed-scalar-mini-to-host \
    tmp-mixed-scalar-mini-caller.s tmp-mixed-scalar-host-provider.o
./tmp-mixed-scalar-mini-to-host

echo 'OK(mixed scalar ABI): minicc caller -> host callee (direct + indirect)'

rm -f tmp-mixed-scalar-mini-provider.c tmp-mixed-scalar-mini-provider.s \
      tmp-mixed-scalar-mini-provider.o tmp-mixed-scalar-host-caller.c \
      tmp-mixed-scalar-host-to-mini tmp-mixed-scalar-host-provider.c \
      tmp-mixed-scalar-host-provider.o tmp-mixed-scalar-mini-caller.c \
      tmp-mixed-scalar-mini-caller.s tmp-mixed-scalar-mini-to-host

echo 'All mixed scalar ABI interoperability tests passed!'
