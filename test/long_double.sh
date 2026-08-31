#!/bin/bash
set -euo pipefail

CC_MINI="${MINICC:-./minicc}"

compile_run() {
  name="$1"
  src="$2"
  printf '%s\n' "$src" > "tmp-ld-${name}.c"
  "$CC_MINI" "tmp-ld-${name}.c" > "tmp-ld-${name}.s"
  gcc -o "tmp-ld-${name}" "tmp-ld-${name}.s"
  "./tmp-ld-${name}"
  echo "OK(long double): $name"
}

expect_fail() {
  name="$1"
  src="$2"
  printf '%s\n' "$src" > "tmp-ld-bad-${name}.c"
  if "$CC_MINI" -fsyntax-only "tmp-ld-bad-${name}.c" >"tmp-ld-bad-${name}.out" 2>"tmp-ld-bad-${name}.err"; then
    echo "FAIL(long double): expected rejection for $name"
    exit 1
  fi
  echo "OK(long double reject): $name"
}

compile_run layout 'int main(void) { return !(sizeof(long double)==16 && _Alignof(long double)==16); }'
compile_run literal 'int main(void) { long double x=1.25L; return !(x==1.25L); }'
compile_run hex_literal 'int main(void) { long double x=0x1.8p+2L; return !(x==6.0L); }'
compile_run precision 'int main(void) { long double a=9007199254740993.0L; long double b=9007199254740992.0L; return !(a>b && a-b==1.0L); }'
compile_run arithmetic 'int main(void) { long double x=9.0L; x=(x+3.0L)*2.0L/4.0L-1.0L; return !((int)x==5); }'
compile_run mixed 'int main(void) { double d=2.5; float f=1.25f; long double x=d+f+0.25L; return !(x==4.0L); }'
compile_run casts 'int main(void) { long double x=(long double)7 + (long double)0.75; int y=(int)x; double d=(double)x; float f=(float)x; return !(y==7 && d>7.74 && d<7.76 && f>7.74f && f<7.76f); }'
compile_run truth 'int main(void) { long double z=0.0L, x=-3.0L; return !(!z && x && (x<0.0L)); }'
compile_run unary 'int main(void) { long double x=2.0L; long double old=x++; ++x; x-=1.0L; x*=2.0L; x/=2.0L; return !(old==2.0L && x==3.0L && -x==-3.0L); }'
compile_run array 'int main(void) { long double a[3]; a[0]=1.0L; a[1]=2.0L; a[2]=3.0L; long double *p=a; return !(p[2]-p[0]==2.0L && (p+3)-p==3); }'
compile_run record_storage 'struct S { int a; long double x; int b; }; int main(void) { struct S s={3, 4.5L, 7}; s.x+=0.5L; return !(s.a==3 && s.x==5.0L && s.b==7 && _Alignof(struct S)==16); }'
compile_run static_scalar 'long double g=1.25L+2.5L; int main(void) { static long double s=8.0L/2.0L; return !(g==3.75L && s==4.0L); }'
compile_run static_record 'struct S { int a; long double x; }; static struct S s={.a=9,.x=6.25L}; int main(void) { return !(s.a==9 && s.x==6.25L); }'
compile_run generic 'int main(void) { long double x=1.0L; return _Generic(x, long double: 0, double: 1, default: 2); }'
compile_run local_call 'long double add(long double a,long double b){ return a+b; } long double twice(long double x){ return x*2.0L; } int main(void){ return !(twice(add(1.25L,2.5L))==7.5L); }'
compile_run indirect_call 'long double add(long double a,long double b){return a+b;} int main(void){ long double (*fp)(long double,long double)=add; return !(fp(4.0L,1.5L)==5.5L); }'
compile_run mixed_call 'int check(int a,double d,long double x,int b,long double y){return a==1 && d==2.0 && x==3.0L && b==4 && y==5.0L;} int main(void){return !check(1,2.0,3.0L,4,5.0L);}'
compile_run float_header '#include <float.h>\nint main(void) { return !(LDBL_MANT_DIG==64 && LDBL_DIG>=18 && LDBL_MAX>1.0e4000L && LDBL_MIN<1.0e-4000L); }'

# host GCC caller -> minicc callee
cat > tmp-ld-callee.c <<'EOF'
long double minicc_ld(long double a, long double b) { return a * b + 0.5L; }
EOF
"$CC_MINI" tmp-ld-callee.c > tmp-ld-callee.s
gcc -c tmp-ld-callee.s -o tmp-ld-callee.o
cat > tmp-ld-host-caller.c <<'EOF'
extern long double minicc_ld(long double, long double);
int main(void) {
    long double x = minicc_ld(1.5L, 4.0L);
    return x == 6.5L ? 0 : 1;
}
EOF
gcc -std=c11 -c tmp-ld-host-caller.c -o tmp-ld-host-caller.o
gcc -o tmp-ld-host-to-mini tmp-ld-host-caller.o tmp-ld-callee.o
./tmp-ld-host-to-mini
echo 'OK(long double): host GCC caller -> minicc callee'

# minicc caller -> host GCC callee
cat > tmp-ld-host-callee.c <<'EOF'
long double host_ld(long double a, int n, long double b) {
    return a + (long double)n + b;
}
EOF
gcc -std=c11 -c tmp-ld-host-callee.c -o tmp-ld-host-callee.o
cat > tmp-ld-mini-caller.c <<'EOF'
long double host_ld(long double, int, long double);
int main(void) { return !(host_ld(1.25L, 3, 2.5L) == 6.75L); }
EOF
"$CC_MINI" tmp-ld-mini-caller.c > tmp-ld-mini-caller.s
gcc -c tmp-ld-mini-caller.s -o tmp-ld-mini-caller.o
gcc -o tmp-ld-mini-to-host tmp-ld-mini-caller.o tmp-ld-host-callee.o
./tmp-ld-mini-to-host
echo 'OK(long double): minicc caller -> host GCC callee'

# host variadic caller -> minicc va_arg(long double)
cat > tmp-ld-va-mini.c <<'EOF'
#include <stdarg.h>
int mini_va(int marker, ...) {
    va_list ap;
    va_start(ap, marker);
    long double x = va_arg(ap, long double);
    int n = va_arg(ap, int);
    long double y = va_arg(ap, long double);
    return marker==7 && x==1.25L && n==9 && y==3.5L;
}
EOF
"$CC_MINI" tmp-ld-va-mini.c > tmp-ld-va-mini.s
gcc -c tmp-ld-va-mini.s -o tmp-ld-va-mini.o
cat > tmp-ld-va-host.c <<'EOF'
int mini_va(int, ...);
int main(void) { return mini_va(7, 1.25L, 9, 3.5L) ? 0 : 1; }
EOF
gcc -std=c11 -c tmp-ld-va-host.c -o tmp-ld-va-host.o
gcc -o tmp-ld-va-host-to-mini tmp-ld-va-host.o tmp-ld-va-mini.o
./tmp-ld-va-host-to-mini
echo 'OK(long double): host variadic caller -> minicc va_arg'

# minicc variadic caller -> host va_arg(long double)
cat > tmp-ld-va-host-callee.c <<'EOF'
#include <stdarg.h>
int host_va(int marker, ...) {
    va_list ap;
    va_start(ap, marker);
    long double x = va_arg(ap, long double);
    int n = va_arg(ap, int);
    long double y = va_arg(ap, long double);
    va_end(ap);
    return marker==5 && x==2.25L && n==11 && y==4.75L;
}
EOF
gcc -std=c11 -c tmp-ld-va-host-callee.c -o tmp-ld-va-host-callee.o
cat > tmp-ld-va-mini-caller.c <<'EOF'
int host_va(int, ...);
int main(void) { return host_va(5, 2.25L, 11, 4.75L) ? 0 : 1; }
EOF
"$CC_MINI" tmp-ld-va-mini-caller.c > tmp-ld-va-mini-caller.s
gcc -c tmp-ld-va-mini-caller.s -o tmp-ld-va-mini-caller.o
gcc -o tmp-ld-va-mini-to-host tmp-ld-va-mini-caller.o tmp-ld-va-host-callee.o
./tmp-ld-va-mini-to-host
echo 'OK(long double): minicc variadic caller -> host va_arg'

expect_fail unsigned_type 'unsigned long double x; int main(void){return 0;}'
expect_fail long_long_double 'long long double x; int main(void){return 0;}'
expect_fail bitfield 'struct S { long double x:3; }; int main(void){return 0;}'
expect_fail small_record_abi 'struct S { long double x; }; struct S id(struct S x){return x;} int main(void){return 0;}'

echo 'All long double tests passed!'
