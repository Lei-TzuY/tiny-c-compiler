#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-memory-record.c
  ./minicc tmp-memory-record.c > tmp-memory-record.s
  cc -o tmp-memory-record tmp-memory-record.s
  set +e
  ./tmp-memory-record
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "MEMORY record ABI failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(MEMORY record ABI): $actual"
}

# >16-byte records are passed as rounded stack objects and copied into callee
# locals, preserving ordinary by-value semantics.
assert_run 0 'struct B{long a,b,c;};long sum(struct B b){return b.a+b.b+b.c;}int main(){struct B b={10,12,20};return sum(b)==42?0:1;}'
assert_run 0 'struct M{double a;long b;double c;};double sum(struct M m){return m.a+m.b+m.c;}int main(){struct M m={10.0,12,20.0};return sum(m)==42.0?0:1;}'
assert_run 0 'union U{long v[3];double d[3];};long sum(union U u){return u.v[0]+u.v[1]+u.v[2];}int main(){union U u;u.v[0]=10;u.v[1]=12;u.v[2]=20;return sum(u)==42?0:1;}'

# MEMORY returns use a hidden RDI destination and remain address-valued after the
# call, so member access, assignment, and return-to-argument chaining work.
assert_run 0 'struct B{long a,b,c;};struct B make(long a,long b,long c){struct B x={a,b,c};return x;}int main(){struct B x=make(10,12,20);return x.a+x.b+x.c==42?0:1;}'
assert_run 0 'struct B{long a,b,c;};struct B make(){struct B x={10,12,20};return x;}int main(){return make().c==20?0:1;}'
assert_run 0 'struct B{long a,b,c;};struct B make(){struct B x={10,12,20};return x;}long sum(struct B x){return x.a+x.b+x.c;}int main(){return sum(make())==42?0:1;}'

# Hidden sret consumes the first GP register. Six user integer parameters prove
# the sixth moves to the caller stack while SSE arguments still use XMM registers.
assert_run 0 'struct B{long a,b,c;};struct B make(long a,long b,long c,long d,long e,long f){struct B x={a+b,c+d,e+f};return x;}int main(){struct B x=make(1,2,3,4,5,27);return x.a+x.b+x.c==42?0:1;}'
assert_run 0 'struct M{double a;long b;double c;};struct M make(double a,long b,double c){struct M x={a,b,c};return x;}int main(){struct M x=make(10.0,12,20.0);return x.a+x.b+x.c==42.0?0:1;}'

# MEMORY arguments consume no GP/SSE registers; later scalar parameters still
# use the register pools until those pools themselves are exhausted.
assert_run 0 'struct B{long a,b,c;};long f(long a,struct B x,long b,long c,long d,long e,long q,long z){return a+x.a+x.b+x.c+b+c+d+e+q+z;}int main(){struct B x={2,3,4};return f(1,x,5,6,7,8,1,5)==42?0:1;}'

# Indirect calls share the same hidden-sret and MEMORY-argument protocol.
assert_run 0 'struct B{long a,b,c;};struct B make(long a,long b,long c){struct B x={a,b,c};return x;}long sum(struct B x){return x.a+x.b+x.c;}int main(){struct B (*mk)(long,long,long)=make;long (*sm)(struct B)=sum;return sm(mk(10,12,20))==42?0:1;}'

# A named MEMORY parameter occupies stack slots before unnamed arguments. va_start
# must skip it while retaining the GP cursor for register-passed varargs.

# MEMORY-returning variadic functions start gp_offset after the hidden sret pointer
# and the named scalar argument.

# Minicc caller -> host GCC callee verifies stack-passed records, hidden sret,
# register shifting, mixed large records, and variadic MEMORY actuals.
cat > tmp-memory-host.c <<'EOF'
#include <stdarg.h>
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long host_sum(struct Big x){return x.a+x.b+x.c;}
struct Big host_make(long a,long b,long c,long d,long e,long f){struct Big x={a+b,c+d,e+f};return x;}
long host_after(long a,struct Big x,long b,long c,long d,long e,long q,long z){return a+x.a+x.b+x.c+b+c+d+e+q+z;}
struct Mix host_mix(double a,long b,double c){struct Mix x={a,b,c};return x;}
long host_var(int tag,...){va_list ap;va_start(ap,tag);struct Big x=va_arg(ap,struct Big);va_end(ap);return tag+x.a+x.b+x.c;}
EOF
cc -c -o tmp-memory-host.o tmp-memory-host.c
cat > tmp-memory-mini-caller.c <<'EOF'
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long host_sum(struct Big);
struct Big host_make(long,long,long,long,long,long);
long host_after(long,struct Big,long,long,long,long,long,long);
struct Mix host_mix(double,long,double);
long host_var(int,...);
int main(void){
  struct Big x={10,12,20}; if(host_sum(x)!=42) return 1;
  struct Big y=host_make(1,2,3,4,5,27); if(y.a+y.b+y.c!=42) return 2;
  struct Big z={2,3,4}; if(host_after(1,z,5,6,7,8,1,5)!=42) return 3;
  struct Mix m=host_mix(10.0,12,20.0); if(m.a+m.b+m.c!=42.0) return 4;
  if(host_var(0,x)!=42) return 5;
  return 0;
}
EOF
./minicc tmp-memory-mini-caller.c > tmp-memory-mini-caller.s
cc -o tmp-memory-mini-caller tmp-memory-mini-caller.s tmp-memory-host.o
./tmp-memory-mini-caller
printf '%s\n' 'OK(MEMORY record ABI): minicc caller interoperates with host GCC'

# Host GCC caller -> minicc callee checks incoming stack objects, hidden return
# destinations, GP shifting, mixed fields, and named-MEMORY variadic cursor state.
cat > tmp-memory-mini-callee.c <<'EOF'
#include <stdarg.h>
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long mini_sum(struct Big x){return x.a+x.b+x.c;}
struct Big mini_make(long a,long b,long c,long d,long e,long f){struct Big x={a+b,c+d,e+f};return x;}
long mini_after(long a,struct Big x,long b,long c,long d,long e,long q,long z){return a+x.a+x.b+x.c+b+c+d+e+q+z;}
struct Mix mini_mix(double a,long b,double c){struct Mix x={a,b,c};return x;}
long mini_named_var(struct Big fixed,int tag,...){
  va_list ap;va_start(ap,tag);
  long a=va_arg(ap,long),b=va_arg(ap,long),c=va_arg(ap,long);
  long d=va_arg(ap,long),e=va_arg(ap,long),f=va_arg(ap,long);
  va_end(ap);
  return fixed.a+fixed.b+fixed.c+tag+a+b+c+d+e+f;
}
struct Big mini_ret_var(int tag,...){
  va_list ap;va_start(ap,tag);
  long a=va_arg(ap,long),b=va_arg(ap,long),c=va_arg(ap,long);
  va_end(ap);
  struct Big x={a,b,c};return x;
}
EOF
./minicc tmp-memory-mini-callee.c > tmp-memory-mini-callee.s
cat > tmp-memory-host-main.c <<'EOF'
#include <stdarg.h>
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long mini_sum(struct Big);
struct Big mini_make(long,long,long,long,long,long);
long mini_after(long,struct Big,long,long,long,long,long,long);
struct Mix mini_mix(double,long,double);
long mini_named_var(struct Big,int,...);
struct Big mini_ret_var(int,...);
int main(void){
  struct Big x={10,12,20}; if(mini_sum(x)!=42) return 1;
  struct Big y=mini_make(1,2,3,4,5,27); if(y.a+y.b+y.c!=42) return 2;
  struct Big z={2,3,4}; if(mini_after(1,z,5,6,7,8,1,5)!=42) return 3;
  struct Mix m=mini_mix(10.0,12,20.0); if(m.a+m.b+m.c!=42.0) return 4;
  struct Big fixed={1,2,3}; if(mini_named_var(fixed,0,4L,5L,6L,7L,8L,6L)!=42) return 5;
  struct Big r=mini_ret_var(0,10L,12L,20L); if(r.a+r.b+r.c!=42) return 6;
  return 0;
}
EOF
cc -o tmp-memory-host-main tmp-memory-host-main.c tmp-memory-mini-callee.s
./tmp-memory-host-main
printf '%s\n' 'OK(MEMORY record ABI): host GCC caller interoperates with minicc callee'

rm -f tmp-memory-record.c tmp-memory-record.s tmp-memory-record \
      tmp-memory-host.c tmp-memory-host.o \
      tmp-memory-mini-caller.c tmp-memory-mini-caller.s tmp-memory-mini-caller \
      tmp-memory-mini-callee.c tmp-memory-mini-callee.s \
      tmp-memory-host-main.c tmp-memory-host-main

echo 'All SysV MEMORY record ABI tests passed!'
