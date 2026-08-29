#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-thread-local.c
  "$MINICC" tmp-thread-local.c > tmp-thread-local.s
  cc -pthread -o tmp-thread-local tmp-thread-local.s
  set +e
  ./tmp-thread-local
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(_Thread_local): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-thread-local-bad.c
  if "$MINICC" tmp-thread-local-bad.c > /dev/null 2>tmp-thread-local.err; then
    echo 'FAIL(_Thread_local): expected rejection'
    echo "$input"
    exit 1
  fi
}

# File-scope TLS is real storage with per-thread lifetime and ordinary value/address access.
assert_run 7 '_Thread_local int x=7;int main(void){return x;}'
assert_run 0 '_Thread_local int x;int main(void){return x;}'
assert_run 0 '_Thread_local int a[2]={3,4};int main(void){return a[0]!=3||a[1]!=4;}'
assert_run 0 '_Thread_local char s[]="abc";int main(void){return sizeof(s)!=4||s[2]!=99||s[3]!=0;}'
assert_run 0 '_Alignas(16) _Thread_local char x;int main(void){return (unsigned long)&x%16;}'
assert_run 0 'static _Thread_local int x=5;int main(void){return x!=5;}'
assert_run 0 '_Thread_local static int x=6;int main(void){return x!=6;}'
assert_run 0 'extern _Thread_local int x;_Thread_local int x=9;int main(void){return x!=9;}'
assert_run 0 'extern _Thread_local int x=10;int main(void){return x!=10;}'
assert_run 0 'static _Thread_local int x=11;extern _Thread_local int x;int main(void){return x!=11;}'

# Block-scope TLS must carry static or extern. Static-local TLS keeps its value
# for the lifetime of the current thread; extern binds the canonical TLS object.
assert_run 0 'int f(void){static _Thread_local int x=2;return ++x;}int main(void){return f()!=3||f()!=4;}'
assert_run 0 '_Thread_local int x=12;int f(void){extern _Thread_local int x;return x;}int main(void){return f()!=12;}'

# A worker starts with the TLS initializer independently from main, and writes
# do not leak back to the main thread.
assert_run 0 'int pthread_create(unsigned long*,void*,void*(*)(void*),void*);int pthread_join(unsigned long,void**);_Thread_local int x=1;void *worker(void *p){if(x!=1)return (void*)1;x=7;return (void*)(long)x;}int main(void){unsigned long t;void *r=0;x=3;if(pthread_create(&t,0,worker,0))return 2;if(pthread_join(t,&r))return 3;return x==3&&(long)r==7?0:4;}'

# Block-scope static TLS must also be instantiated independently for every
# thread. The main thread advances its own instance to 12, the worker must
# still observe a fresh 10 initializer, and the main instance must resume at 13.
assert_run 0 'int pthread_create(unsigned long*,void*,void*(*)(void*),void*);int pthread_join(unsigned long,void**);int next(void){static _Thread_local int x=10;return ++x;}void *worker(void *p){return (void*)(long)(next()!=11||next()!=12);}int main(void){unsigned long t;void *r=0;if(next()!=11||next()!=12)return 1;if(pthread_create(&t,0,worker,0))return 2;if(pthread_join(t,&r))return 3;if((long)r)return 4;return next()==13?0:5;}'

# Cross-object ELF TLS interoperability: consume a host-defined TLS symbol.
cat > tmp-host-tls-def.c <<'EOF'
_Thread_local int host_tls = 21;
EOF
cc -std=c11 -c tmp-host-tls-def.c -o tmp-host-tls-def.o
printf '%s\n' 'extern _Thread_local int host_tls;int main(void){return host_tls==21?0:1;}' > tmp-thread-local.c
"$MINICC" tmp-thread-local.c > tmp-thread-local.s
cc -o tmp-thread-local tmp-thread-local.s tmp-host-tls-def.o
./tmp-thread-local

# And expose a minicc-defined TLS symbol to host C.
printf '%s\n' '_Thread_local int minicc_tls=22;' > tmp-thread-local.c
"$MINICC" tmp-thread-local.c > tmp-thread-local.s
cc -c tmp-thread-local.s -o tmp-thread-local.o
cat > tmp-host-tls-use.c <<'EOF'
extern _Thread_local int minicc_tls;
int main(void){ return minicc_tls == 22 ? 0 : 1; }
EOF
cc -std=c11 -o tmp-host-tls-use tmp-host-tls-use.c tmp-thread-local.o
./tmp-host-tls-use

# The emitted object must carry true ELF TLS symbols and both initialized and
# zero-initialized TLS sections rather than ordinary .data storage.
printf '%s\n' '_Thread_local int tls_init=4;_Thread_local int tls_zero;int main(void){return tls_init+tls_zero-4;}' > tmp-thread-local.c
"$MINICC" tmp-thread-local.c > tmp-thread-local.s
cc -c tmp-thread-local.s -o tmp-thread-local.o
readelf -sW tmp-thread-local.o | grep -Eq 'TLS[[:space:]]+GLOBAL.*tls_init'
readelf -sW tmp-thread-local.o | grep -Eq 'TLS[[:space:]]+GLOBAL.*tls_zero'
readelf -SW tmp-thread-local.o | grep -q '\.tdata'
readelf -SW tmp-thread-local.o | grep -q '\.tbss'

# Internal-linkage TLS must remain a local ELF symbol rather than being
# exported just because it uses TLS storage.
printf '%s\n' '_Thread_local int global_tls;static _Thread_local int hidden_tls=3;int read_hidden(void){return hidden_tls;}' > tmp-thread-local.c
"$MINICC" tmp-thread-local.c > tmp-thread-local.s
cc -c tmp-thread-local.s -o tmp-thread-local.o
readelf -sW tmp-thread-local.o | grep -Eq 'TLS[[:space:]]+GLOBAL.*global_tls'
readelf -sW tmp-thread-local.o | grep -Eq 'TLS[[:space:]]+LOCAL.*hidden_tls'

# C11 storage-class and declaration constraints.
assert_reject '_Thread_local int f(void);int main(void){return 0;}'
assert_reject 'int f(_Thread_local int x){return x;}int main(void){return 0;}'
assert_reject 'struct S{_Thread_local int x;};int main(void){return 0;}'
assert_reject 'typedef _Thread_local int T;int main(void){return 0;}'
assert_reject 'int main(void){_Thread_local int x;return 0;}'
assert_reject 'int main(void){auto _Thread_local int x;return 0;}'
assert_reject 'int main(void){register _Thread_local int x;return 0;}'
assert_reject 'auto _Thread_local int x;int main(void){return 0;}'
assert_reject 'register _Thread_local int x;int main(void){return 0;}'
assert_reject '_Thread_local _Thread_local int x;int main(void){return 0;}'
assert_reject '_Thread_local static extern int x;int main(void){return 0;}'
assert_reject '_Thread_local int;int main(void){return 0;}'

# Every declaration of one object must agree on thread storage duration.
assert_reject '_Thread_local int x;extern int x;int main(void){return 0;}'
assert_reject 'int x;extern _Thread_local int x;int main(void){return 0;}'
assert_reject 'extern _Thread_local int x;extern int x;int main(void){return 0;}'
assert_reject '_Thread_local int x;int f(void){extern int x;return x;}int main(void){return 0;}'
assert_reject 'int x;int f(void){extern _Thread_local int x;return x;}int main(void){return 0;}'

# TLS addresses are runtime values and therefore cannot appear in static
# address-constant initializers.
assert_reject '_Thread_local int x;int *p=&x;int main(void){return 0;}'
assert_reject '_Thread_local int x;_Thread_local int *p=&x;int main(void){return 0;}'

rm -f tmp-thread-local.c tmp-thread-local.s tmp-thread-local tmp-thread-local.o \
      tmp-thread-local-bad.c tmp-thread-local.err tmp-host-tls-def.c \
      tmp-host-tls-def.o tmp-host-tls-use.c tmp-host-tls-use

echo 'All _Thread_local tests passed!'
