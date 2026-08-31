#!/bin/bash
set -eu
MINICC=${MINICC:-./minicc}
cleanup(){ rm -f tmp-ldabi-*.c tmp-ldabi-*.s tmp-ldabi-*.o tmp-ldabi-*; }
trap cleanup EXIT

# host caller -> minicc callee, including stack alignment between GP arguments.
cat > tmp-ldabi-mini.c <<'EOF'
long double mix(int a,long double x,int b){return x+(long double)(a+b);}
long double via(long double (*fn)(int,long double,int),int a,long double x,int b){return fn(a,x,b);}
long double variadic(int tag,...){__builtin_va_list ap;__builtin_va_start(ap);long double x=__builtin_va_arg(ap,long double);return x+(long double)tag;}
EOF
"$MINICC" tmp-ldabi-mini.c > tmp-ldabi-mini.s
cc -c -o tmp-ldabi-mini.o tmp-ldabi-mini.s
cat > tmp-ldabi-host.c <<'EOF'
long double mix(int,long double,int);
long double via(long double (*)(int,long double,int),int,long double,int);
long double variadic(int,...);
static long double hostfn(int a,long double x,int b){return x-(long double)a+(long double)b;}
int main(void){if(mix(2,3.5L,4)!=9.5L)return 1;if(via(hostfn,2,9.0L,5)!=12.0L)return 2;if(variadic(3,4.25L)!=7.25L)return 3;return 0;}
EOF
cc -c -o tmp-ldabi-host.o tmp-ldabi-host.c
cc -o tmp-ldabi-a tmp-ldabi-host.o tmp-ldabi-mini.o
./tmp-ldabi-a

# minicc caller -> host callee, direct, indirect, and variadic va_arg.
cat > tmp-ldabi-host2.c <<'EOF'
#include <stdarg.h>
long double host_mix(int a,long double x,int b){return x+(long double)(a*2-b);}
long double host_variadic(int tag,...){va_list ap;va_start(ap,tag);long double x=va_arg(ap,long double);va_end(ap);return x-(long double)tag;}
EOF
cc -c -o tmp-ldabi-host2.o tmp-ldabi-host2.c
cat > tmp-ldabi-main.c <<'EOF'
long double host_mix(int,long double,int); long double host_variadic(int,...);
int main(void){long double (*fp)(int,long double,int)=host_mix;if(host_mix(4,5.5L,3)!=10.5L)return 1;if(fp(2,9.0L,1)!=12.0L)return 2;if(host_variadic(3,8.25L)!=5.25L)return 3;return 0;}
EOF
"$MINICC" tmp-ldabi-main.c > tmp-ldabi-main.s
cc -c -o tmp-ldabi-main.o tmp-ldabi-main.s
cc -o tmp-ldabi-b tmp-ldabi-main.o tmp-ldabi-host2.o
./tmp-ldabi-b

echo 'All SysV long double ABI tests passed!'
