#!/bin/bash
set -eu
MINICC=${MINICC:-./minicc}
run() {
  expected=$1; src=$2
  printf '%s\n' "$src" > tmp-ld.c
  "$MINICC" tmp-ld.c > tmp-ld.s
  cc -o tmp-ld tmp-ld.s
  set +e; ./tmp-ld >/dev/null 2>&1; actual=$?; set -e
  if [ "$actual" != "$expected" ]; then echo "FAIL(long double): expected $expected got $actual"; echo "$src"; exit 1; fi
}
trap 'rm -f tmp-ld.c tmp-ld.s tmp-ld' EXIT
run 0 'int main(void){return !(sizeof(long double)==16&&_Alignof(long double)==16);}'
run 0 'int main(void){return _Generic(1.0L,long double:0,default:1);}'
run 0 'int main(void){long double x=1.0L+0x1p-60L; double d=(double)x; if(x==1.0L)return 1; if(d!=1.0)return 2; return 0;}'
run 0 'int main(void){long double a=7.5L,b=2.5L; if(a+b!=10.0L)return 1; if(a-b!=5.0L)return 2; if(a*b!=18.75L)return 3; if(a/b!=3.0L)return 4; return 0;}'
run 0 'int main(void){long double x=2.0L; x+=3.0L; if(x!=5.0L)return 1; x*=2.0L; if(x!=10.0L)return 2; x-=4.0L; if(x!=6.0L)return 3; x/=3.0L; return x!=2.0L;}'
run 0 'int main(void){long double x=2.0L; long double a=x++; if(a!=2.0L||x!=3.0L)return 1; long double b=--x; return b!=2.0L||x!=2.0L;}'
run 0 'int main(void){long double x=-3.5L; if(!(x<0.0L))return 1; if(-x!=3.5L)return 2; if(!x)return 3; return (int)3.75L!=3;}'
run 0 'int main(void){unsigned long x=18446744073709551615UL; long double y=(long double)x; unsigned long z=(unsigned long)y; return z!=x;}'
run 0 'struct S{char c; long double x; char z;}; int main(void){struct S s={1,2.5L,3}; if(_Alignof(struct S)!=16)return 1; if(sizeof(struct S)!=48)return 2; return s.x!=2.5L;}'
run 0 'static long double x=1.0L+0x1p-60L; static struct S{int n; long double x;} s={7,3.25L}; int main(void){if(x==1.0L)return 1; return s.n!=7||s.x!=3.25L;}'
run 0 '#include <float.h>
int main(void){if(LDBL_MANT_DIG!=64||LDBL_DIG!=18||DECIMAL_DIG!=21)return 1; if(_Generic(LDBL_EPSILON,long double:1,default:0)!=1)return 2; if(!(1.0L+LDBL_EPSILON>1.0L))return 3; return 0;}'
echo 'All long double scalar tests passed!'

run 0 '#include <math.h>
int main(void){long double x=sqrtl(81.0L);if(x!=9.0L)return 1;if(fabsl(-3.5L)!=3.5L)return 2;if(powl(2.0L,5.0L)!=32.0L)return 3;if(!isfinite(x)||isnan(x)||isinf(x))return 4;if(!signbit(copysignl(0.0L,-1.0L)))return 5;if(fpclassify(1.0L)!=FP_NORMAL)return 6;return 0;}'
