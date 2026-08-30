#!/bin/bash
set -eu

MINICC="${MINICC:-./minicc}"

# Compile the variadic callees with the host compiler so GCC is the independent
# SysV AMD64 oracle.  The minicc side below is caller-only: any aggregate
# classification, whole-record fallback, register-count, or overflow-stack bug
# therefore cannot be hidden by a matching minicc va_arg implementation.
cat > tmp-va-record-caller-host.c <<'EOF'
#include <stdarg.h>

struct I { long a, b; };
struct D { double a, b; };
struct M { double x; long y; };
struct B { long a, b, c; };
struct P { long a, b; };

int host_records(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  struct I i = va_arg(ap, struct I);
  struct D d = va_arg(ap, struct D);
  struct M m = va_arg(ap, struct M);
  struct B b = va_arg(ap, struct B);
  long z = va_arg(ap, long);
  double q = va_arg(ap, double);
  va_end(ap);
  return tag == 9 &&
         i.a == 1 && i.b == 2 &&
         d.a == 3.0 && d.b == 4.0 &&
         m.x == 5.0 && m.y == 6 &&
         b.a == 7 && b.b == 8 && b.c == 9 &&
         z == 10 && q == 11.0;
}

/* Five named GP arguments leave one GP register.  P needs two INTEGER
   eightbytes, so it must fall back wholly to overflow_arg_area; z still gets
   the final GP register. */
int host_gp_fallback(long a, long b, long c, long d, long e, ...) {
  va_list ap;
  va_start(ap, e);
  struct P p = va_arg(ap, struct P);
  long z = va_arg(ap, long);
  va_end(ap);
  return a + b + c + d + e + p.a + p.b + z == 42;
}

/* Seven named SSE arguments leave xmm7.  A two-SSE record cannot be split:
   it must go wholly to overflow_arg_area, while z remains in xmm7. */
int host_sse_fallback(double a, double b, double c, double d,
                      double e, double f, double g, int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  struct D p = va_arg(ap, struct D);
  double z = va_arg(ap, double);
  va_end(ap);
  return a + b + c + d + e + f + g + p.a + p.b + z == 42.0;
}

/* Exhaust all six GP registers before a mixed INTEGER/SSE record.  The mixed
   record falls back as a unit, and its failed SSE allocation must not consume
   xmm0; the following double is still register-passed. */
int host_mixed_fallback(long a, long b, long c, long d, long e, long f, ...) {
  va_list ap;
  va_start(ap, f);
  struct M m = va_arg(ap, struct M);
  double z = va_arg(ap, double);
  va_end(ap);
  return a + b + c + d + e + f + m.x + m.y + z == 42.0;
}
EOF

gcc -std=c11 -c -o tmp-va-record-caller-host.o tmp-va-record-caller-host.c

cat > tmp-va-record-caller-mini.c <<'EOF'
struct I { long a, b; };
struct D { double a, b; };
struct M { double x; long y; };
struct B { long a, b, c; };
struct P { long a, b; };

int host_records(int, ...);
int host_gp_fallback(long, long, long, long, long, ...);
int host_sse_fallback(double, double, double, double, double, double, double,
                      int, ...);
int host_mixed_fallback(long, long, long, long, long, long, ...);

int main(void) {
  struct I i = {1, 2};
  struct D d = {3.0, 4.0};
  struct M m = {5.0, 6};
  struct B b = {7, 8, 9};

  /* Use an indirect variadic call for the broad mixed-record case.  This also
     makes the caller set the variadic vector-register count through the
     function-pointer lowering path. */
  int (*fp)(int, ...) = host_records;
  if (!fp(9, i, d, m, b, 10L, 11.0))
    return 1;

  struct P p = {6, 7};
  if (!host_gp_fallback(1, 2, 3, 4, 5, p, 14L))
    return 2;

  struct D sd = {7.0, 8.0};
  if (!host_sse_fallback(1, 2, 3, 4, 5, 6, 7, 0, sd, -1.0))
    return 3;

  struct M mm = {7.0, 8};
  if (!host_mixed_fallback(1, 2, 3, 4, 5, 6, mm, 6.0))
    return 4;

  return 0;
}
EOF

"$MINICC" tmp-va-record-caller-mini.c > tmp-va-record-caller-mini.s
gcc -o tmp-va-record-caller tmp-va-record-caller-mini.s tmp-va-record-caller-host.o
./tmp-va-record-caller

echo 'OK(variadic record caller ABI): minicc caller -> host GCC callee'

rm -f tmp-va-record-caller-host.c tmp-va-record-caller-host.o \
      tmp-va-record-caller-mini.c tmp-va-record-caller-mini.s \
      tmp-va-record-caller

echo 'All variadic record caller ABI interoperability tests passed!'
