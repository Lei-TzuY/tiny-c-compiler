#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-va-record.c
  ./minicc tmp-va-record.c > tmp-va-record.s
  cc -o tmp-va-record tmp-va-record.s
  ./tmp-va-record
  echo "OK(sysv record va_arg): minicc caller/callee"
}

# INTEGER, SSE, mixed and union records come from independent register-save
# cursors. The 12-byte record checks a partial final eightbyte.
compile_and_run <<'EOF'
#include <stdarg.h>
struct I { long a,b; };
struct D { double a,b; };
struct M { double x; long y; };
struct T { int a,b,c; };
union U { long i; double d; };
int probe(int tag, ...) {
  va_list ap; va_start(ap, tag);
  struct I i=va_arg(ap,struct I);
  struct D d=va_arg(ap,struct D);
  struct M m=va_arg(ap,struct M);
  struct T t=va_arg(ap,struct T);
  union U u=va_arg(ap,union U);
  return i.a==10 && i.b==11 && d.a==1.5 && d.b==2.5 &&
         m.x==3.5 && m.y==12 && t.a==4 && t.b==5 && t.c==6 && u.i==42;
}
int main(void) {
  struct I i={10,11}; struct D d={1.5,2.5}; struct M m={3.5,12};
  struct T t={4,5,6}; union U u={.i=42};
  return !probe(0,i,d,m,t,u);
}
EOF

# Five named GP arguments leave one GP register. A two-GP record must fall back
# wholly to overflow_arg_area, while the following long still uses the last GP.
compile_and_run <<'EOF'
#include <stdarg.h>
struct P { long a,b; };
int probe(long a,long b,long c,long d,long e, ...) {
  va_list ap; va_start(ap,e);
  struct P p=va_arg(ap,struct P);
  long z=va_arg(ap,long);
  return a+b+c+d+e+p.a+p.b+z==42;
}
int main(void){struct P p={6,7};return !probe(1,2,3,4,5,p,14L);}
EOF

# Seven named SSE arguments leave xmm7 only. A two-SSE record falls back as a
# whole, and the following double must still be recovered from xmm7.
compile_and_run <<'EOF'
#include <stdarg.h>
struct D { double a,b; };
int probe(double a,double b,double c,double d,double e,double f,double g,int tag,...) {
  va_list ap; va_start(ap,tag);
  struct D p=va_arg(ap,struct D);
  double z=va_arg(ap,double);
  return a+b+c+d+e+f+g+p.a+p.b+z==42.0;
}
int main(void){struct D p={7.0,8.0};return !probe(1,2,3,4,5,6,7,0,p,-1.0);}
EOF

# A mixed GP/SSE record also falls back as one unit. Exhausting GP registers must
# not advance the still-available FP cursor; the following double remains xmm0.
compile_and_run <<'EOF'
#include <stdarg.h>
struct M { long a; double b; };
int probe(long a,long b,long c,long d,long e,long f,...) {
  va_list ap; va_start(ap,f);
  struct M m=va_arg(ap,struct M);
  double z=va_arg(ap,double);
  return a+b+c+d+e+f+m.a+m.b+z==42.0;
}
int main(void){struct M m={7,8.0};return !probe(1,2,3,4,5,6,m,6.0);}
EOF

# MEMORY records advance overflow_arg_area only. Later GP/SSE varargs retain
# their register-save cursor positions.
compile_and_run <<'EOF'
#include <stdarg.h>
struct B { long a,b,c; };
int probe(int tag,...) {
  va_list ap; va_start(ap,tag);
  struct B b=va_arg(ap,struct B);
  long x=va_arg(ap,long);
  double y=va_arg(ap,double);
  return b.a+b.b+b.c+x+(long)y==42;
}
int main(void){struct B b={10,11,12};return !probe(0,b,4L,5.0);}
EOF

# Aggregate va_arg is still an ordinary address-valued record expression.
compile_and_run <<'EOF'
#include <stdarg.h>
struct M { double x; long y; };
long probe(int tag,...){va_list ap;va_start(ap,tag);return va_arg(ap,struct M).y;}
int main(void){struct M m={1.0,42};return probe(0,m)==42?0:1;}
EOF

# va_copy duplicates both aggregate register cursors rather than aliasing them.
compile_and_run <<'EOF'
#include <stdarg.h>
struct M { double x; long y; };
int probe(int tag,...) {
  va_list ap,cp; va_start(ap,tag); va_copy(cp,ap);
  struct M a=va_arg(ap,struct M), b=va_arg(cp,struct M);
  return a.x==1.5 && a.y==20 && b.x==1.5 && b.y==20;
}
int main(void){struct M m={1.5,20};return !probe(0,m);}
EOF

# Host GCC caller -> minicc callee catches matching caller/callee bugs. Exercise
# register records, MEMORY records, post-MEMORY scalars and GP fallback.
cat > tmp-va-record-mini.c <<'EOF'
#include <stdarg.h>
struct I { long a,b; };
struct D { double a,b; };
struct M { double x; long y; };
struct B { long a,b,c; };
struct P { long a,b; };
int mini_records(int tag,...) {
  va_list ap; va_start(ap,tag);
  struct I i=va_arg(ap,struct I);
  struct D d=va_arg(ap,struct D);
  struct M m=va_arg(ap,struct M);
  struct B b=va_arg(ap,struct B);
  long z=va_arg(ap,long); double q=va_arg(ap,double);
  return i.a==1 && i.b==2 && d.a==3.0 && d.b==4.0 &&
         m.x==5.0 && m.y==6 && b.a==7 && b.b==8 && b.c==9 && z==10 && q==11.0;
}
int mini_gp_fallback(long a,long b,long c,long d,long e,...) {
  va_list ap;va_start(ap,e);
  struct P p=va_arg(ap,struct P); long z=va_arg(ap,long);
  return a+b+c+d+e+p.a+p.b+z==42;
}
EOF
./minicc tmp-va-record-mini.c > tmp-va-record-mini.s
cc -c -o tmp-va-record-mini.o tmp-va-record-mini.s
cat > tmp-va-record-host.c <<'EOF'
struct I { long a,b; };
struct D { double a,b; };
struct M { double x; long y; };
struct B { long a,b,c; };
struct P { long a,b; };
int mini_records(int,...);
int mini_gp_fallback(long,long,long,long,long,...);
int main(void) {
  struct I i={1,2}; struct D d={3,4}; struct M m={5,6}; struct B b={7,8,9};
  if(!mini_records(0,i,d,m,b,10L,11.0)) return 1;
  struct P p={6,7};
  if(!mini_gp_fallback(1,2,3,4,5,p,14L)) return 2;
  return 0;
}
EOF
cc -o tmp-va-record-host tmp-va-record-host.c tmp-va-record-mini.o
./tmp-va-record-host
echo "OK(sysv record va_arg): host GCC caller -> minicc callee"

cat > tmp-va-record-bad.c <<'EOF'
#include <stdarg.h>
struct F;
int f(int n,...){va_list ap;va_start(ap,n);va_arg(ap,struct F);return 0;}
EOF
if ./minicc tmp-va-record-bad.c >/dev/null 2>&1; then
  echo "expected incomplete record va_arg rejection"
  exit 1
fi

cat > tmp-va-record-bad.c <<'EOF'
#include <stdarg.h>
int f(int n,...){va_list ap;va_start(ap,n);return va_arg(ap,int[2])[0];}
EOF
if ./minicc tmp-va-record-bad.c >/dev/null 2>&1; then
  echo "expected array va_arg rejection"
  exit 1
fi

rm -f tmp-va-record.c tmp-va-record.s tmp-va-record \
      tmp-va-record-mini.c tmp-va-record-mini.s tmp-va-record-mini.o \
      tmp-va-record-host.c tmp-va-record-host tmp-va-record-bad.c

echo 'All SysV variadic record va_arg tests passed!'
