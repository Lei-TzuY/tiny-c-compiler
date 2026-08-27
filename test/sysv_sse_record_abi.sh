#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-sse-record.c
  ./minicc tmp-sse-record.c > tmp-sse-record.s
  cc -o tmp-sse-record tmp-sse-record.s
  set +e
  ./tmp-sse-record
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "SSE record ABI failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(SSE record ABI): $actual"
}

# Pure SSE records use XMM registers for one or two eightbytes and for returns.
assert_run 0 'struct F{double x;};double get(struct F s){return s.x;}int main(){struct F s={42.0};return get(s)==42.0?0:1;}'
assert_run 0 'struct F{double x;};struct F make(double x){struct F s={x};return s;}int main(){return make(42.0).x==42.0?0:1;}'
assert_run 0 'struct D{double a;double b;};double sum(struct D s){return s.a+s.b;}int main(){struct D s={20.0,22.0};return sum(s)==42.0?0:1;}'
assert_run 0 'struct D{double a;double b;};struct D make(){struct D s={19.0,23.0};return s;}int main(){struct D s=make();return s.a+s.b==42.0?0:1;}'
assert_run 0 'struct F2{float a;float b;};float sum(struct F2 s){return s.a+s.b;}int main(){struct F2 s={20.0f,22.0f};return sum(s)==42.0f?0:1;}'
assert_run 0 'struct A{double v[2];};double sum(struct A a){return a.v[0]+a.v[1];}int main(){struct A a={{20.0,22.0}};return sum(a)==42.0?0:1;}'

# Mixed records draw from GP and SSE pools independently; order of eightbytes
# controls the return register class, not a single aggregate-wide class.
assert_run 0 'struct M{double d;long i;};double sum(struct M m){return m.d+m.i;}int main(){struct M m={20.0,22};return sum(m)==42.0?0:1;}'
assert_run 0 'struct M{double d;long i;};struct M make(){struct M m={20.0,22};return m;}int main(){struct M m=make();return m.d+m.i==42.0?0:1;}'
assert_run 0 'struct R{long i;double d;};struct R make(){struct R r={22,20.0};return r;}int main(){struct R r=make();return r.i+r.d==42.0?0:1;}'

# INTEGER dominates SSE when both contribute to the same eightbyte.
assert_run 0 'struct P{float f;int i;};int get(struct P p){return p.i;}int main(){struct P p={1.0f,42};return get(p)==42?0:1;}'
assert_run 0 'union U{int i;double d;};int get(union U u){return u.i;}int main(){union U u;u.i=42;return get(u)==42?0:1;}'

# If the whole aggregate cannot fit in either required register class, SysV
# stack-passes it without consuming the other still-available class.
assert_run 0 'struct D{double a;double b;};double f(double a,double b,double c,double d,double e,double q,double g,struct D p,double z){return a+b+c+d+e+q+g+p.a+p.b+z;}int main(){struct D p={10.0,11.0};return f(1,1,1,1,1,1,1,p,14)==42.0?0:1;}'
assert_run 0 'struct M{double d;long i;};double f(long a,long b,long c,long d,long e,long q,struct M m,double z){return a+b+c+d+e+q+m.d+m.i+z;}int main(){struct M m={10.0,12};return f(1,1,1,1,1,1,m,14.0)==42.0?0:1;}'
assert_run 0 'struct M{double d;long i;};double f(double a,double b,double c,double d,double e,double q,double g,double h,struct M m,long z){return a+b+c+d+e+q+g+h+m.d+m.i+z;}int main(){struct M m={10.0,11};return f(1,1,1,1,1,1,1,1,m,13)==42.0?0:1;}'

# Minicc caller -> host GCC callee, including SSE exhaustion and a variadic
# aggregate whose XMM use must be reflected in AL.
cat > tmp-sse-record-host.c <<'EOF'
#include <stdarg.h>
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double host_d(struct D x){return x.a+x.b;}
struct M host_m(double d,long i){struct M x={d,i};return x;}
int host_p(struct P x){return x.i;}
double host_stack(double a,double b,double c,double d,double e,double f,double g,struct D p,double z){return a+b+c+d+e+f+g+p.a+p.b+z;}
double host_var(int tag,...){va_list ap;va_start(ap,tag);struct D x=va_arg(ap,struct D);va_end(ap);return x.a+x.b;}
EOF
cc -c -o tmp-sse-record-host.o tmp-sse-record-host.c
cat > tmp-sse-record-mini-caller.c <<'EOF'
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double host_d(struct D);
struct M host_m(double,long);
int host_p(struct P);
double host_stack(double,double,double,double,double,double,double,struct D,double);
double host_var(int,...);
int main(void){
  struct D d={20.0,22.0}; if(host_d(d)!=42.0) return 1;
  struct M m=host_m(20.0,22); if(m.d+m.i!=42.0) return 2;
  struct P p={1.0f,42}; if(host_p(p)!=42) return 3;
  struct D s={10.0,11.0}; if(host_stack(1,1,1,1,1,1,1,s,14)!=42.0) return 4;
  if(host_var(0,d)!=42.0) return 5;
  return 0;
}
EOF
./minicc tmp-sse-record-mini-caller.c > tmp-sse-record-mini-caller.s
cc -o tmp-sse-record-mini-caller tmp-sse-record-mini-caller.s tmp-sse-record-host.o
./tmp-sse-record-mini-caller
printf '%s\n' 'OK(SSE record ABI): minicc caller interoperates with host GCC'

# Host GCC caller -> minicc callee verifies incoming SSE/mixed values, mixed
# return registers, whole-record stack fallback, and named-record va_start state.
cat > tmp-sse-record-mini-callee.c <<'EOF'
#include <stdarg.h>
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double mini_d(struct D x){return x.a+x.b;}
struct M mini_m(double d,long i){struct M x={d,i};return x;}
int mini_p(struct P x){return x.i;}
double mini_stack(double a,double b,double c,double d,double e,double f,double g,struct D p,double z){return a+b+c+d+e+f+g+p.a+p.b+z;}
double mini_named_var(struct D fixed,int tag,...){va_list ap;va_start(ap,tag);double z=va_arg(ap,double);va_end(ap);return fixed.a+fixed.b+z;}
EOF
./minicc tmp-sse-record-mini-callee.c > tmp-sse-record-mini-callee.s
cat > tmp-sse-record-host-main.c <<'EOF'
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double mini_d(struct D);
struct M mini_m(double,long);
int mini_p(struct P);
double mini_stack(double,double,double,double,double,double,double,struct D,double);
double mini_named_var(struct D,int,...);
int main(void){
  struct D d={20.0,22.0}; if(mini_d(d)!=42.0) return 1;
  struct M m=mini_m(20.0,22); if(m.d+m.i!=42.0) return 2;
  struct P p={1.0f,42}; if(mini_p(p)!=42) return 3;
  struct D s={10.0,11.0}; if(mini_stack(1,1,1,1,1,1,1,s,14)!=42.0) return 4;
  struct D fixed={10.0,12.0}; if(mini_named_var(fixed,0,20.0)!=42.0) return 5;
  return 0;
}
EOF
cc -o tmp-sse-record-host-main tmp-sse-record-host-main.c tmp-sse-record-mini-callee.s
./tmp-sse-record-host-main
printf '%s\n' 'OK(SSE record ABI): host GCC caller interoperates with minicc callee'

rm -f tmp-sse-record.c tmp-sse-record.s tmp-sse-record \
      tmp-sse-record-host.c tmp-sse-record-host.o \
      tmp-sse-record-mini-caller.c tmp-sse-record-mini-caller.s tmp-sse-record-mini-caller \
      tmp-sse-record-mini-callee.c tmp-sse-record-mini-callee.s \
      tmp-sse-record-host-main.c tmp-sse-record-host-main

echo 'All SysV SSE/mixed record ABI tests passed!'
