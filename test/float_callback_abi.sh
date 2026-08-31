#!/bin/bash
set -e

# Exercise function pointers whose arguments and return values use the SysV SSE
# class across an independent compiler boundary. This catches indirect-call bugs
# that direct float/double calls can miss while also validating callback typing.
cat > tmp-float-callback-mini.c <<'EOF'
double mini_apply_double(double (*fn)(double), double x) {
  return fn(x);
}

float mini_apply_float(float (*fn)(float), float x) {
  return fn(x);
}

/* Consume all eight SSE argument registers before the callback's own call. */
double mini_apply_after_sse(double a, double b, double c, double d,
                            double e, double f, double g, double h,
                            double (*fn)(double), double x) {
  return a+b+c+d+e+f+g+h+fn(x);
}

double mini_double(double x) { return x * 2.0; }
float mini_half(float x) { return x / 2.0f; }
EOF
"${MINICC:-./minicc}" tmp-float-callback-mini.c > tmp-float-callback-mini.s
gcc -c -o tmp-float-callback-mini.o tmp-float-callback-mini.s

cat > tmp-float-callback-host.c <<'EOF'
double mini_apply_double(double (*)(double), double);
float mini_apply_float(float (*)(float), float);
double mini_apply_after_sse(double, double, double, double,
                            double, double, double, double,
                            double (*)(double), double);

double host_add_quarter(double x) { return x + 0.25; }
float host_triple(float x) { return x * 3.0f; }

int main(void) {
  if (mini_apply_double(host_add_quarter, 4.0) != 4.25)
    return 1;
  if (mini_apply_float(host_triple, 2.5f) != 7.5f)
    return 2;
  if (mini_apply_after_sse(1,2,3,4,5,6,7,8,host_add_quarter,1.0) != 37.25)
    return 3;
  return 0;
}
EOF
gcc -std=c11 -o tmp-float-callback-host-to-mini \
    tmp-float-callback-host.c tmp-float-callback-mini.o
./tmp-float-callback-host-to-mini

echo 'OK(float callback ABI): host callbacks -> minicc callees'

cat > tmp-float-callback-host-provider.c <<'EOF'
double host_apply_double(double (*fn)(double), double x) {
  return fn(x);
}
float host_apply_float(float (*fn)(float), float x) {
  return fn(x);
}
double host_apply_after_sse(double a, double b, double c, double d,
                            double e, double f, double g, double h,
                            double (*fn)(double), double x) {
  return a+b+c+d+e+f+g+h+fn(x);
}
EOF
gcc -std=c11 -c -o tmp-float-callback-host-provider.o \
    tmp-float-callback-host-provider.c

cat > tmp-float-callback-mini-caller.c <<'EOF'
double host_apply_double(double (*)(double), double);
float host_apply_float(float (*)(float), float);
double host_apply_after_sse(double, double, double, double,
                            double, double, double, double,
                            double (*)(double), double);

double mini_double(double x) { return x * 2.0; }
float mini_half(float x) { return x / 2.0f; }

int main(void) {
  if (host_apply_double(mini_double, 3.25) != 6.5)
    return 1;
  if (host_apply_float(mini_half, 7.0f) != 3.5f)
    return 2;
  if (host_apply_after_sse(1,2,3,4,5,6,7,8,mini_double,1.5) != 39.0)
    return 3;
  return 0;
}
EOF
"${MINICC:-./minicc}" tmp-float-callback-mini-caller.c > tmp-float-callback-mini-caller.s
gcc -o tmp-float-callback-mini-to-host \
    tmp-float-callback-mini-caller.s tmp-float-callback-host-provider.o
./tmp-float-callback-mini-to-host

echo 'OK(float callback ABI): minicc callbacks -> host callees'

rm -f tmp-float-callback-mini.c tmp-float-callback-mini.s tmp-float-callback-mini.o \
      tmp-float-callback-host.c tmp-float-callback-host-to-mini \
      tmp-float-callback-host-provider.c tmp-float-callback-host-provider.o \
      tmp-float-callback-mini-caller.c tmp-float-callback-mini-caller.s \
      tmp-float-callback-mini-to-host

echo 'All floating callback ABI tests passed!'
