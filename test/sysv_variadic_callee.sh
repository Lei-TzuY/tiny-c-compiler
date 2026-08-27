#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-va.c
  ./minicc tmp-va.c > tmp-va.s
  cc -o tmp-va tmp-va.s
  ./tmp-va
  echo "OK(sysv va): minicc caller/callee"
}

compile_and_run <<'EOF'
#include <stdarg.h>
int probe(double fixed, int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int a = va_arg(ap, int);
  double b = va_arg(ap, double);
  long c = va_arg(ap, long);
  double d = va_arg(ap, double);
  int x = 9;
  int *p = va_arg(ap, int *);
  va_end(ap);
  return fixed == 0.5 && tag == 3 && a == 7 && b == 1.5 &&
         c == 11 && d == 2.25 && *p == 9;
}
int main(void) {
  int x = 9;
  return !probe(0.5, 3, 7, 1.5f, 11L, 2.25, &x);
}
EOF

compile_and_run <<'EOF'
#include <stdarg.h>
int overflow(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int i1=va_arg(ap,int), i2=va_arg(ap,int), i3=va_arg(ap,int);
  int i4=va_arg(ap,int), i5=va_arg(ap,int), i6=va_arg(ap,int);
  double d1=va_arg(ap,double), d2=va_arg(ap,double), d3=va_arg(ap,double);
  double d4=va_arg(ap,double), d5=va_arg(ap,double), d6=va_arg(ap,double);
  double d7=va_arg(ap,double), d8=va_arg(ap,double), d9=va_arg(ap,double);
  return i1==1 && i2==2 && i3==3 && i4==4 && i5==5 && i6==6 &&
         d1==1.0 && d2==2.0 && d3==3.0 && d4==4.0 && d5==5.0 &&
         d6==6.0 && d7==7.0 && d8==8.0 && d9==9.0;
}
int main(void) {
  return !overflow(0,1,2,3,4,5,6,1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0);
}
EOF

# va_copy duplicates the cursor state, not an alias to mutable offsets.  Consume
# one list after copying and verify the copy still starts from the same point.
compile_and_run <<'EOF'
#include <stdarg.h>
int copy_probe(int tag, ...) {
  va_list ap, cp;
  va_start(ap, tag);
  int first = va_arg(ap, int);
  va_copy(cp, ap);

  int a1 = va_arg(ap, int);
  double d1 = va_arg(ap, double);
  int a2 = va_arg(ap, int);

  int c1 = va_arg(cp, int);
  double cd1 = va_arg(cp, double);
  int c2 = va_arg(cp, int);

  va_end(cp);
  va_end(ap);
  return first==10 && a1==20 && d1==1.5 && a2==30 &&
         c1==20 && cd1==1.5 && c2==30;
}
int main(void) { return !copy_probe(0,10,20,1.5,30); }
EOF

# Copy before exhausting either register class, then drain the original across
# both GP/SSE register-save areas and the shared overflow stack.  The copied
# cursor must independently reproduce the whole sequence afterwards.
compile_and_run <<'EOF'
#include <stdarg.h>
int copy_overflow(int tag, ...) {
  va_list ap, cp;
  va_start(ap, tag);
  __va_copy(cp, ap);

  int a1=va_arg(ap,int), a2=va_arg(ap,int), a3=va_arg(ap,int);
  int a4=va_arg(ap,int), a5=va_arg(ap,int), a6=va_arg(ap,int), a7=va_arg(ap,int);
  double d1=va_arg(ap,double), d2=va_arg(ap,double), d3=va_arg(ap,double);
  double d4=va_arg(ap,double), d5=va_arg(ap,double), d6=va_arg(ap,double);
  double d7=va_arg(ap,double), d8=va_arg(ap,double), d9=va_arg(ap,double);

  int c1=va_arg(cp,int), c2=va_arg(cp,int), c3=va_arg(cp,int);
  int c4=va_arg(cp,int), c5=va_arg(cp,int), c6=va_arg(cp,int), c7=va_arg(cp,int);
  double e1=va_arg(cp,double), e2=va_arg(cp,double), e3=va_arg(cp,double);
  double e4=va_arg(cp,double), e5=va_arg(cp,double), e6=va_arg(cp,double);
  double e7=va_arg(cp,double), e8=va_arg(cp,double), e9=va_arg(cp,double);

  return a1+a2+a3+a4+a5+a6+a7==28 && c1+c2+c3+c4+c5+c6+c7==28 &&
         d1+d2+d3+d4+d5+d6+d7+d8+d9==45.0 &&
         e1+e2+e3+e4+e5+e6+e7+e8+e9==45.0;
}
int main(void) {
  return !copy_overflow(0,1,2,3,4,5,6,7,
                        1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0);
}
EOF

# Compile variadic callees with minicc and call them from the host compiler.
cat > tmp-va-callee.c <<'EOF'
#include <stdarg.h>
int host_bridge(double fixed, int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int a = va_arg(ap, int);
  double b = va_arg(ap, double);
  unsigned long c = va_arg(ap, unsigned long);
  double d = va_arg(ap, double);
  return fixed==0.25 && tag==4 && a==12 && b==1.75 && c==33UL && d==2.5;
}
int host_overflow(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int a1=va_arg(ap,int), a2=va_arg(ap,int), a3=va_arg(ap,int);
  int a4=va_arg(ap,int), a5=va_arg(ap,int), a6=va_arg(ap,int);
  double d1=va_arg(ap,double), d2=va_arg(ap,double), d3=va_arg(ap,double);
  double d4=va_arg(ap,double), d5=va_arg(ap,double), d6=va_arg(ap,double);
  double d7=va_arg(ap,double), d8=va_arg(ap,double), d9=va_arg(ap,double);
  return a1+a2+a3+a4+a5+a6==21 && d1+d2+d3+d4+d5+d6+d7+d8+d9==45.0;
}
EOF
./minicc tmp-va-callee.c > tmp-va-callee.s
cc -c -o tmp-va-callee.o tmp-va-callee.s
cat > tmp-va-host.c <<'EOF'
int host_bridge(double, int, ...);
int host_overflow(int, ...);
int main(void) {
  if (!host_bridge(0.25,4,12,1.75f,33UL,2.5)) return 1;
  if (!host_overflow(0,1,2,3,4,5,6,1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0)) return 2;
  return 0;
}
EOF
cc -o tmp-va-host tmp-va-host.c tmp-va-callee.o
./tmp-va-host
echo "OK(sysv va): host caller -> minicc callee"

# Default promotions make these va_arg requests invalid in a conforming call.
for badtype in float char short; do
  cat > tmp-va-bad.c <<EOF
#include <stdarg.h>
int f(int n, ...) { va_list ap; va_start(ap,n); return va_arg(ap,$badtype); }
EOF
  if ./minicc tmp-va-bad.c >/dev/null 2>&1; then
    echo "expected va_arg($badtype) rejection"
    exit 1
  fi
done

cat > tmp-va-bad.c <<'EOF'
#include <stdarg.h>
int f(void) { va_list ap; va_start(ap, ap); return 0; }
EOF
if ./minicc tmp-va-bad.c >/dev/null 2>&1; then
  echo "expected va_start outside variadic function rejection"
  exit 1
fi

rm -f tmp-va.c tmp-va.s tmp-va tmp-va-callee.c tmp-va-callee.s tmp-va-callee.o tmp-va-host.c tmp-va-host tmp-va-bad.c

echo 'All SysV variadic callee tests passed!'
