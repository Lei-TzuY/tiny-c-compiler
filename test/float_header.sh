#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-float-h.c
  "$MINICC" tmp-float-h.c > tmp-float-h.s
  cc -o tmp-float-h tmp-float-h.s
  set +e
  ./tmp-float-h >/dev/null 2>&1
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(float.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

cleanup() {
  rm -f tmp-float-h.c tmp-float-h.s tmp-float-h
}
trap cleanup EXIT

# Repeated inclusion and the integer-valued C11 characteristics must be usable
# by the preprocessor as well as normal expressions.
assert_run 0 '#include <float.h>
#include <float.h>
#if FLT_RADIX != 2
#error bad FLT_RADIX
#endif
#if FLT_MANT_DIG != 24 || DBL_MANT_DIG != 53
#error bad mantissa widths
#endif
#if FLT_DIG != 6 || DBL_DIG != 15
#error bad decimal precision
#endif
#if FLT_MIN_EXP != -125 || DBL_MIN_EXP != -1021
#error bad minimum exponents
#endif
#if FLT_MAX_EXP != 128 || DBL_MAX_EXP != 1024
#error bad maximum exponents
#endif
#if FLT_EVAL_METHOD != 0 || FLT_ROUNDS != 1
#error bad evaluation model
#endif
#if FLT_HAS_SUBNORM != 1 || DBL_HAS_SUBNORM != 1
#error bad subnormal model
#endif
int main(void){return !(DECIMAL_DIG==17&&FLT_DECIMAL_DIG==9&&DBL_DECIMAL_DIG==17);}'

# x86-64 SysV long double uses 80-bit extended precision in 16-byte storage.
assert_run 0 '#include <float.h>
#if LDBL_MANT_DIG != 64 || LDBL_DIG != 18
#error bad long-double precision
#endif
#if LDBL_MIN_EXP != -16381 || LDBL_MAX_EXP != 16384
#error bad long-double exponent range
#endif
#if LDBL_DECIMAL_DIG != 21 || LDBL_HAS_SUBNORM != 1
#error bad long-double model
#endif
int main(void){
  if(_Generic(LDBL_MAX,long double:1,default:0)!=1)return 1;
  if(_Generic(LDBL_EPSILON,long double:1,default:0)!=1)return 2;
  if(_Generic(LDBL_MIN,long double:1,default:0)!=1)return 3;
  if(_Generic(LDBL_TRUE_MIN,long double:1,default:0)!=1)return 4;
  if(!(1.0L+LDBL_EPSILON>1.0L))return 5;
  return 0;
}'

# Macro constants must retain the correct language types.
assert_run 0 '#include <float.h>
int main(void){
  if(_Generic(FLT_MAX,float:1,default:0)!=1)return 1;
  if(_Generic(FLT_EPSILON,float:1,default:0)!=1)return 2;
  if(_Generic(FLT_MIN,float:1,default:0)!=1)return 3;
  if(_Generic(FLT_TRUE_MIN,float:1,default:0)!=1)return 4;
  if(_Generic(DBL_MAX,double:1,default:0)!=1)return 5;
  if(_Generic(DBL_EPSILON,double:1,default:0)!=1)return 6;
  if(_Generic(DBL_MIN,double:1,default:0)!=1)return 7;
  if(_Generic(DBL_TRUE_MIN,double:1,default:0)!=1)return 8;
  return 0;
}'

# Epsilon values describe the next representable value around 1 for the
# compiler's SSE float/double execution model.
assert_run 0 '#include <float.h>
int main(void){
  float f=1.0f;
  if(!(f+FLT_EPSILON>f))return 1;
  if(f+FLT_EPSILON/2.0f!=f)return 2;
  double d=1.0;
  if(!(d+DBL_EPSILON>d))return 3;
  if(d+DBL_EPSILON/2.0!=d)return 4;
  return 0;
}'

# Normal minima, true minima, and maxima must survive tokenization, static
# initialization, and runtime comparison without being collapsed to zero.
assert_run 0 '#include <float.h>
float fmin=FLT_MIN;
float ftrue=FLT_TRUE_MIN;
float fmax=FLT_MAX;
double dmin=DBL_MIN;
double dtrue=DBL_TRUE_MIN;
double dmax=DBL_MAX;
int main(void){
  if(!(fmin>0.0f&&ftrue>0.0f&&ftrue<fmin&&fmax>fmin))return 1;
  if(!(dmin>0.0&&dtrue>0.0&&dtrue<dmin&&dmax>dmin))return 2;
  return 0;
}'

# The true-minimum values must be exactly at the subnormal floor for each
# implemented binary format.
assert_run 0 '#include <float.h>
int main(void){
  if(FLT_TRUE_MIN/2.0f!=0.0f)return 1;
  if(DBL_TRUE_MIN/2.0!=0.0)return 2;
  if(FLT_MIN/2.0f==0.0f)return 3;
  if(DBL_MIN/2.0==0.0)return 4;
  return 0;
}'

echo 'All supported-model <float.h> tests passed!'
