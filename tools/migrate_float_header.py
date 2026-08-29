from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()
marker = '    if (!strcmp(name, "limits.h")) {'
block = r'''    if (!strcmp(name, "float.h")) {
        return "#ifndef __MINICC_FLOAT_H\n"
               "#define __MINICC_FLOAT_H 1\n"
               "#define FLT_RADIX 2\n"
               "#define FLT_MANT_DIG 24\n"
               "#define DBL_MANT_DIG 53\n"
               "#define FLT_DIG 6\n"
               "#define DBL_DIG 15\n"
               "#define FLT_MIN_EXP (-125)\n"
               "#define DBL_MIN_EXP (-1021)\n"
               "#define FLT_MIN_10_EXP (-37)\n"
               "#define DBL_MIN_10_EXP (-307)\n"
               "#define FLT_MAX_EXP 128\n"
               "#define DBL_MAX_EXP 1024\n"
               "#define FLT_MAX_10_EXP 38\n"
               "#define DBL_MAX_10_EXP 308\n"
               "#define DECIMAL_DIG 17\n"
               "#define FLT_DECIMAL_DIG 9\n"
               "#define DBL_DECIMAL_DIG 17\n"
               "#define FLT_EVAL_METHOD 0\n"
               "#define FLT_ROUNDS 1\n"
               "#define FLT_HAS_SUBNORM 1\n"
               "#define DBL_HAS_SUBNORM 1\n"
               "#define FLT_MAX 0x1.fffffep+127F\n"
               "#define DBL_MAX 0x1.fffffffffffffp+1023\n"
               "#define FLT_EPSILON 0x1p-23F\n"
               "#define DBL_EPSILON 0x1p-52\n"
               "#define FLT_MIN 0x1p-126F\n"
               "#define DBL_MIN 0x1p-1022\n"
               "#define FLT_TRUE_MIN 0x1p-149F\n"
               "#define DBL_TRUE_MIN 0x1p-1074\n"
               "#endif\n";
    }
'''
if '    if (!strcmp(name, "float.h")) {' not in text:
    pos = text.index(marker)
    text = text[:pos] + block + text[pos:]
    pp.write_text(text)

makefile = Path("Makefile")
mk = makefile.read_text()
needle = "\tbash ./test/floating_literals.sh\n"
entry = "\tbash ./test/float_header.sh\n"
if entry not in mk:
    if needle not in mk:
        raise SystemExit("floating literal test entry not found")
    makefile.write_text(mk.replace(needle, needle + entry, 1))

Path("test/float_header.sh").write_text(r'''#!/bin/bash
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

# The target is deliberately a float/double subset. Do not expose LDBL_*
# macros until 80-bit storage and SysV x87 lowering exist.
assert_run 0 '#include <float.h>
#ifdef LDBL_MANT_DIG
#error long double must remain firewalled
#endif
#ifdef LDBL_MAX
#error long double constants must remain firewalled
#endif
int main(void){return 0;}'

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
''')
