#!/bin/bash
set -e

# Cross-check indirect calls whose callback signatures interleave SysV INTEGER
# and SSE classes. The overflow case deliberately exhausts both register banks
# so an indirect-call lowering bug cannot hide behind direct-call coverage.
cat > tmp-mixed-callback-mini.c <<'EOF'
double mini_apply_mixed(double (*fn)(int, double, int, double),
                        int a, double b, int c, double d) {
  return fn(a, b, c, d);
}

double mini_apply_overflow(
    double (*fn)(int, double, int, double, int, double, int, double,
                 int, double, int, double, int, double, double, double, double)) {
  return fn(1, 1.0, 2, 2.0, 3, 3.0, 4, 4.0,
            5, 5.0, 6, 6.0, 7, 7.0, 8.0, 9.0, 10.0);
}

double mini_mixed(int a, double b, int c, double d) {
  return a + b * 10.0 + c * 100.0 + d * 1000.0;
}

double mini_overflow(int a, double b, int c, double d, int e, double f,
                     int g, double h, int i, double j, int k, double l,
                     int m, double n, double o, double p, double q) {
  return a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q;
}
EOF
"${MINICC:-./minicc}" tmp-mixed-callback-mini.c > tmp-mixed-callback-mini.s
gcc -c -o tmp-mixed-callback-mini.o tmp-mixed-callback-mini.s

cat > tmp-mixed-callback-host.c <<'EOF'
double mini_apply_mixed(double (*)(int, double, int, double),
                        int, double, int, double);
double mini_apply_overflow(
    double (*)(int, double, int, double, int, double, int, double,
               int, double, int, double, int, double, double, double, double));

double host_mixed(int a, double b, int c, double d) {
  return a + b * 10.0 + c * 100.0 + d * 1000.0;
}

double host_overflow(int a, double b, int c, double d, int e, double f,
                     int g, double h, int i, double j, int k, double l,
                     int m, double n, double o, double p, double q) {
  return a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q;
}

int main(void) {
  if (mini_apply_mixed(host_mixed, 1, 2.0, 3, 4.0) != 4321.0)
    return 1;
  if (mini_apply_overflow(host_overflow) != 88.0)
    return 2;
  return 0;
}
EOF
gcc -std=c11 -o tmp-mixed-callback-host-to-mini \
    tmp-mixed-callback-host.c tmp-mixed-callback-mini.o
./tmp-mixed-callback-host-to-mini

echo 'OK(mixed callback ABI): host callbacks -> minicc callees'

cat > tmp-mixed-callback-host-provider.c <<'EOF'
double host_apply_mixed(double (*fn)(int, double, int, double),
                        int a, double b, int c, double d) {
  return fn(a, b, c, d);
}

double host_apply_overflow(
    double (*fn)(int, double, int, double, int, double, int, double,
                 int, double, int, double, int, double, double, double, double)) {
  return fn(1, 1.0, 2, 2.0, 3, 3.0, 4, 4.0,
            5, 5.0, 6, 6.0, 7, 7.0, 8.0, 9.0, 10.0);
}
EOF
gcc -std=c11 -c -o tmp-mixed-callback-host-provider.o \
    tmp-mixed-callback-host-provider.c

cat > tmp-mixed-callback-mini-caller.c <<'EOF'
double host_apply_mixed(double (*)(int, double, int, double),
                        int, double, int, double);
double host_apply_overflow(
    double (*)(int, double, int, double, int, double, int, double,
               int, double, int, double, int, double, double, double, double));

double mini_mixed(int a, double b, int c, double d) {
  return a + b * 10.0 + c * 100.0 + d * 1000.0;
}

double mini_overflow(int a, double b, int c, double d, int e, double f,
                     int g, double h, int i, double j, int k, double l,
                     int m, double n, double o, double p, double q) {
  return a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q;
}

int main(void) {
  if (host_apply_mixed(mini_mixed, 1, 2.0, 3, 4.0) != 4321.0)
    return 1;
  if (host_apply_overflow(mini_overflow) != 88.0)
    return 2;
  return 0;
}
EOF
"${MINICC:-./minicc}" tmp-mixed-callback-mini-caller.c > tmp-mixed-callback-mini-caller.s
gcc -o tmp-mixed-callback-mini-to-host \
    tmp-mixed-callback-mini-caller.s tmp-mixed-callback-host-provider.o
./tmp-mixed-callback-mini-to-host

echo 'OK(mixed callback ABI): minicc callbacks -> host callees'

rm -f tmp-mixed-callback-mini.c tmp-mixed-callback-mini.s tmp-mixed-callback-mini.o \
      tmp-mixed-callback-host.c tmp-mixed-callback-host-to-mini \
      tmp-mixed-callback-host-provider.c tmp-mixed-callback-host-provider.o \
      tmp-mixed-callback-mini-caller.c tmp-mixed-callback-mini-caller.s \
      tmp-mixed-callback-mini-to-host

echo 'All mixed callback ABI tests passed!'
