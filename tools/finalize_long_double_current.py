#!/usr/bin/env python3
from pathlib import Path


def replace(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected one match, got {n}")
    p.write_text(s.replace(old, new))


# Floating literals: L/l is now a supported standard suffix.
old = '''# Long-double literals are standard C but deliberately firewalled until the
# backend has 80-bit storage and SysV x87 argument/return lowering.
assert_reject 'int main(){return (int)1.0L;}'
assert_reject 'int main(){return (int).5l;}'
assert_reject 'int main(){return (int)0x1p2L;}'
'''
new = '''# L/l selects x86-64 long double (80-bit extended precision in 16-byte storage).
assert_run 16 'int main(){return sizeof(1.0L);}'
assert_run 1  'int main(){return _Generic(.5l,long double:1,default:0);}'
assert_run 4  'int main(){return (int)0x1p2L;}'
assert_reject 'int main(){return (int)1.0LL;}'
assert_reject 'int main(){return (int)0x1p2LF;}'
'''
replace('test/floating_literals.sh', old, new, 'floating literal long-double block')

# float.h: turn the old firewall into positive x87-format validation.
old = '''# The target is deliberately a float/double subset. Do not expose LDBL_*
# macros until 80-bit storage and SysV x87 lowering exist.
assert_run 0 '#include <float.h>
#ifdef LDBL_MANT_DIG
#error long double must remain firewalled
#endif
#ifdef LDBL_MAX
#error long double constants must remain firewalled
#endif
int main(void){return 0;}'
'''
new = '''# x86-64 SysV long double uses 80-bit extended precision in 16-byte storage.
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
'''
replace('test/float_header.sh', old, new, 'float.h long-double firewall')

# Fix a literal backslash-n imported from the historical focused regression.
p = Path('test/long_double.sh')
s = p.read_text()
needle = "run 0 '#include <float.h>\\nint main(void){if(LDBL_MANT_DIG!=64||LDBL_DIG!=18||DECIMAL_DIG!=21)return 1; if(_Generic(LDBL_EPSILON,long double:1,default:0)!=1)return 2; if(!(1.0L+LDBL_EPSILON>1.0L))return 3; return 0;}'"
repl = "run 0 '#include <float.h>\nint main(void){if(LDBL_MANT_DIG!=64||LDBL_DIG!=18||DECIMAL_DIG!=21)return 1; if(_Generic(LDBL_EPSILON,long double:1,default:0)!=1)return 2; if(!(1.0L+LDBL_EPSILON>1.0L))return 3; return 0;}'"
if needle not in s:
    raise SystemExit('long_double.sh float.h source anchor not found')
s = s.replace(needle, repl)
s += '''\nrun 0 '#include <math.h>
int main(void){long double x=sqrtl(81.0L);if(x!=9.0L)return 1;if(fabsl(-3.5L)!=3.5L)return 2;if(powl(2.0L,5.0L)!=32.0L)return 3;if(!isfinite(x)||isnan(x)||isinf(x))return 4;if(!signbit(copysignl(0.0L,-1.0L)))return 5;if(fpclassify(1.0L)!=FP_NORMAL)return 6;return 0;}'
'''
p.write_text(s)

# Extend the current math.h surface while retaining all recent header additions.
p = Path('preprocess_v2.c')
s = p.read_text()
anchor = '               "#define HUGE_VALF (1.0f / 0.0f)\\n"\n'
if s.count(anchor) != 1:
    raise SystemExit('HUGE_VALF anchor mismatch')
s = s.replace(anchor, anchor + '               "#define HUGE_VALL (1.0L / 0.0L)\\n"\n', 1)

anchor = '               "union __minicc_math_f_bits { float f; unsigned int u; };\\n"\n'
if s.count(anchor) != 1:
    raise SystemExit('math long-double union anchor mismatch')
s = s.replace(anchor, anchor + '               "union __minicc_math_l_bits { long double x; unsigned long u[2]; };\\n"\n', 1)

anchor = '               "static inline int __minicc_isfinite(double x) { return !__minicc_isnan(x) && !__minicc_isinf(x); }\\n"\n'
extra = ('               "static inline int __minicc_isnanl(long double x) { return x != x; }\\n"\n'
         '               "static inline int __minicc_isinfl(long double x) { return !__minicc_isnanl(x) && x != 0.0L && x + x == x; }\\n"\n'
         '               "static inline int __minicc_isfinitel(long double x) { return !__minicc_isnanl(x) && !__minicc_isinfl(x); }\\n"\n')
if s.count(anchor) != 1:
    raise SystemExit('math predicate anchor mismatch')
s = s.replace(anchor, anchor + extra, 1)

anchor = '               "static inline int __minicc_signbit(double x) { union __minicc_math_d_bits v; v.d=x; return (int)(v.u >> 63); }\\n"\n'
if s.count(anchor) != 1:
    raise SystemExit('math signbit anchor mismatch')
s = s.replace(anchor, anchor + '               "static inline int __minicc_signbitl(long double x) { union __minicc_math_l_bits v; v.x=x; return (int)((v.u[1] >> 15) & 1UL); }\\n"\n', 1)

anchor = '               "static inline int __minicc_fpclassifyf(float x) { union __minicc_math_f_bits v; unsigned int e, f; v.f=x; e=(v.u >> 23) & 0xffU; f=v.u & 0x7fffffU; if (e==0xffU) return f ? FP_NAN : FP_INFINITE; if (!e) return f ? FP_SUBNORMAL : FP_ZERO; return FP_NORMAL; }\\n"\n'
if s.count(anchor) != 1:
    raise SystemExit('math fpclassify anchor mismatch')
s = s.replace(anchor, anchor + '               "static inline int __minicc_fpclassifyl(long double x) { union __minicc_math_l_bits v; unsigned long e, f; v.x=x; e=v.u[1] & 0x7fffUL; f=v.u[0]; if (e==0x7fffUL) return (f & 0x7fffffffffffffffUL) ? FP_NAN : FP_INFINITE; if (!e) return f ? FP_SUBNORMAL : FP_ZERO; return FP_NORMAL; }\\n"\n', 1)

anchor = '               "static inline int __minicc_isunordered(double x,double y){return __minicc_isnan(x)||__minicc_isnan(y);}\\n"\n'
ordered = ('               "static inline int __minicc_isgreaterl(long double x,long double y){return !__minicc_isnanl(x)&&!__minicc_isnanl(y)&&x>y;}\\n"\n'
           '               "static inline int __minicc_isgreaterequall(long double x,long double y){return !__minicc_isnanl(x)&&!__minicc_isnanl(y)&&x>=y;}\\n"\n'
           '               "static inline int __minicc_islessl(long double x,long double y){return !__minicc_isnanl(x)&&!__minicc_isnanl(y)&&x<y;}\\n"\n'
           '               "static inline int __minicc_islessequall(long double x,long double y){return !__minicc_isnanl(x)&&!__minicc_isnanl(y)&&x<=y;}\\n"\n'
           '               "static inline int __minicc_islessgreaterl(long double x,long double y){return !__minicc_isnanl(x)&&!__minicc_isnanl(y)&&(x<y||x>y);}\\n"\n'
           '               "static inline int __minicc_isunorderedl(long double x,long double y){return __minicc_isnanl(x)||__minicc_isnanl(y);}\\n"\n')
if s.count(anchor) != 1:
    raise SystemExit('math ordered comparison anchor mismatch')
s = s.replace(anchor, anchor + ordered, 1)

old = '''               "#define fpclassify(x) _Generic((x), float: __minicc_fpclassifyf, default: __minicc_fpclassify)((x))\\n"
               "#define isfinite(x) __minicc_isfinite((double)(x))\\n"
               "#define isinf(x) __minicc_isinf((double)(x))\\n"
               "#define isnan(x) __minicc_isnan((double)(x))\\n"
               "#define isnormal(x) (fpclassify(x) == FP_NORMAL)\\n"
               "#define signbit(x) __minicc_signbit((double)(x))\\n"
               "#define isgreater(x,y) __minicc_isgreater((double)(x),(double)(y))\\n"
               "#define isgreaterequal(x,y) __minicc_isgreaterequal((double)(x),(double)(y))\\n"
               "#define isless(x,y) __minicc_isless((double)(x),(double)(y))\\n"
               "#define islessequal(x,y) __minicc_islessequal((double)(x),(double)(y))\\n"
               "#define islessgreater(x,y) __minicc_islessgreater((double)(x),(double)(y))\\n"
               "#define isunordered(x,y) __minicc_isunordered((double)(x),(double)(y))\\n"
'''
new = '''               "#define fpclassify(x) _Generic((x), float: __minicc_fpclassifyf, long double: __minicc_fpclassifyl, default: __minicc_fpclassify)((x))\\n"
               "#define isfinite(x) _Generic((x), long double: __minicc_isfinitel, default: __minicc_isfinite)((x))\\n"
               "#define isinf(x) _Generic((x), long double: __minicc_isinfl, default: __minicc_isinf)((x))\\n"
               "#define isnan(x) _Generic((x), long double: __minicc_isnanl, default: __minicc_isnan)((x))\\n"
               "#define isnormal(x) (fpclassify(x) == FP_NORMAL)\\n"
               "#define signbit(x) _Generic((x), long double: __minicc_signbitl, default: __minicc_signbit)((x))\\n"
               "#define isgreater(x,y) _Generic(((x)+(y)), long double: __minicc_isgreaterl, default: __minicc_isgreater)((x),(y))\\n"
               "#define isgreaterequal(x,y) _Generic(((x)+(y)), long double: __minicc_isgreaterequall, default: __minicc_isgreaterequal)((x),(y))\\n"
               "#define isless(x,y) _Generic(((x)+(y)), long double: __minicc_islessl, default: __minicc_isless)((x),(y))\\n"
               "#define islessequal(x,y) _Generic(((x)+(y)), long double: __minicc_islessequall, default: __minicc_islessequal)((x),(y))\\n"
               "#define islessgreater(x,y) _Generic(((x)+(y)), long double: __minicc_islessgreaterl, default: __minicc_islessgreater)((x),(y))\\n"
               "#define isunordered(x,y) _Generic(((x)+(y)), long double: __minicc_isunorderedl, default: __minicc_isunordered)((x),(y))\\n"
'''
if s.count(old) != 1:
    raise SystemExit(f'math macro block count={s.count(old)}')
s = s.replace(old, new, 1)

anchor = '               "double fdim(double,double); float fdimf(float,float); double fmax(double,double); float fmaxf(float,float); double fmin(double,double); float fminf(float,float); double fabs(double); float fabsf(float); double fma(double,double,double); float fmaf(float,float,float);\\n"\n'
extra = (
'               "long double acosl(long double); long double asinl(long double); long double atanl(long double); long double atan2l(long double,long double);\\n"\n'
'               "long double cosl(long double); long double sinl(long double); long double tanl(long double); long double acoshl(long double); long double asinhl(long double); long double atanhl(long double);\\n"\n'
'               "long double coshl(long double); long double sinhl(long double); long double tanhl(long double); long double expl(long double); long double exp2l(long double); long double expm1l(long double);\\n"\n'
'               "long double frexpl(long double,int *); long double ldexpl(long double,int); long double logl(long double); long double log10l(long double); long double log1pl(long double); long double log2l(long double);\\n"\n'
'               "long double modfl(long double,long double *); long double scalbnl(long double,int); long double scalblnl(long double,long); int ilogbl(long double); long double logbl(long double);\\n"\n'
'               "long double cbrtl(long double); long double hypotl(long double,long double); long double powl(long double,long double); long double sqrtl(long double);\\n"\n'
'               "long double erfl(long double); long double erfcl(long double); long double lgammal(long double); long double tgammal(long double);\\n"\n'
'               "long double ceill(long double); long double floorl(long double); long double nearbyintl(long double); long double rintl(long double); long double roundl(long double); long double truncl(long double);\\n"\n'
'               "long lrintl(long double); long lroundl(long double); long long llrintl(long double); long long llroundl(long double);\\n"\n'
'               "long double fmodl(long double,long double); long double remainderl(long double,long double); long double remquol(long double,long double,int *);\\n"\n'
'               "long double copysignl(long double,long double); long double nanl(const char *); long double nextafterl(long double,long double);\\n"\n'
'               "long double fdiml(long double,long double); long double fmaxl(long double,long double); long double fminl(long double,long double); long double fabsl(long double); long double fmal(long double,long double,long double);\\n"\n')
if s.count(anchor) != 1:
    raise SystemExit('math prototype anchor mismatch')
s = s.replace(anchor, anchor + extra, 1)
p.write_text(s)

# README: remove stale firewalls and describe the x87 ABI/header surface.
p = Path('README.md')
s = p.read_text()
s = s.replace('validated C type-specifier sets (including required explicit type specifiers, order-independent signed/unsigned integer forms, and explicit rejection of unsupported `long double`)',
              'validated C type-specifier sets (including required explicit type specifiers, order-independent signed/unsigned integer forms, and x86-64 SysV `long double`)')
s = s.replace('scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and function arguments/returns using the SysV AMD64 register/stack convention.',
              'scalar `float`/`double` plus x87 `long double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and function arguments/returns using the SysV AMD64 register/stack/x87 conventions.')
s = s.replace('Full-range `unsigned long` conversions to and from `float`/`double` are lowered without signed-64 truncation.',
              'Full-range `unsigned long` conversions to and from floating types are lowered without signed-64 truncation; `long double` values use 80-bit extended precision in 16-byte storage and ST(0) returns, while arguments use the ABI memory class.')
s = s.replace('Built-in `<math.h>` exposes a C99 float/double libm surface, floating classification/comparison macros, and common mathematical constants for Linux x86-64 programs linked with `-lm`. Long-double (`*l`) entry points remain deferred until the x87 scalar/ABI layer is implemented.',
              'Built-in `<math.h>` exposes C99 float/double/long-double libm declarations, floating classification/comparison macros that preserve `long double` precision, and common mathematical constants for Linux x86-64 programs linked with `-lm`.')
p.write_text(s)
print('finalized long double current-main integration')
