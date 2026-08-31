from pathlib import Path
p=Path('preprocess_v2.c')
s=p.read_text()
old='''               "#define DBL_MANT_DIG 53\\n"
               "#define FLT_DIG 6\\n"
               "#define DBL_DIG 15\\n"
'''
new='''               "#define DBL_MANT_DIG 53\\n"
               "#define LDBL_MANT_DIG 64\\n"
               "#define FLT_DIG 6\\n"
               "#define DBL_DIG 15\\n"
               "#define LDBL_DIG 18\\n"
'''
if s.count(old)!=1: raise SystemExit(f'float mant/dig anchor count={s.count(old)}')
s=s.replace(old,new)
old='''               "#define DBL_MIN_EXP (-1021)\\n"
               "#define FLT_MIN_10_EXP (-37)\\n"
               "#define DBL_MIN_10_EXP (-307)\\n"
               "#define FLT_MAX_EXP 128\\n"
               "#define DBL_MAX_EXP 1024\\n"
               "#define FLT_MAX_10_EXP 38\\n"
               "#define DBL_MAX_10_EXP 308\\n"
'''
new='''               "#define DBL_MIN_EXP (-1021)\\n"
               "#define LDBL_MIN_EXP (-16381)\\n"
               "#define FLT_MIN_10_EXP (-37)\\n"
               "#define DBL_MIN_10_EXP (-307)\\n"
               "#define LDBL_MIN_10_EXP (-4931)\\n"
               "#define FLT_MAX_EXP 128\\n"
               "#define DBL_MAX_EXP 1024\\n"
               "#define LDBL_MAX_EXP 16384\\n"
               "#define FLT_MAX_10_EXP 38\\n"
               "#define DBL_MAX_10_EXP 308\\n"
               "#define LDBL_MAX_10_EXP 4932\\n"
'''
if s.count(old)!=1: raise SystemExit(f'float exponent anchor count={s.count(old)}')
s=s.replace(old,new)
old='''               "#define DBL_DECIMAL_DIG 17\\n"
               "#define FLT_EVAL_METHOD 0\\n"
'''
new='''               "#define DBL_DECIMAL_DIG 17\\n"
               "#define LDBL_DECIMAL_DIG 21\\n"
               "#define FLT_EVAL_METHOD 0\\n"
'''
if s.count(old)!=1: raise SystemExit(f'float decimal anchor count={s.count(old)}')
s=s.replace(old,new)
old='''               "#define DBL_HAS_SUBNORM 1\\n"
               "#define FLT_MAX 0x1.fffffep+127F\\n"
               "#define DBL_MAX 0x1.fffffffffffffp+1023\\n"
               "#define FLT_EPSILON 0x1p-23F\\n"
               "#define DBL_EPSILON 0x1p-52\\n"
               "#define FLT_MIN 0x1p-126F\\n"
               "#define DBL_MIN 0x1p-1022\\n"
               "#define FLT_TRUE_MIN 0x1p-149F\\n"
               "#define DBL_TRUE_MIN 0x1p-1074\\n"
'''
new='''               "#define DBL_HAS_SUBNORM 1\\n"
               "#define LDBL_HAS_SUBNORM 1\\n"
               "#define FLT_MAX 0x1.fffffep+127F\\n"
               "#define DBL_MAX 0x1.fffffffffffffp+1023\\n"
               "#define LDBL_MAX 0xf.fffffffffffffffp+16380L\\n"
               "#define FLT_EPSILON 0x1p-23F\\n"
               "#define DBL_EPSILON 0x1p-52\\n"
               "#define LDBL_EPSILON 0x1p-63L\\n"
               "#define FLT_MIN 0x1p-126F\\n"
               "#define DBL_MIN 0x1p-1022\\n"
               "#define LDBL_MIN 0x1p-16382L\\n"
               "#define FLT_TRUE_MIN 0x1p-149F\\n"
               "#define DBL_TRUE_MIN 0x1p-1074\\n"
               "#define LDBL_TRUE_MIN 0x1p-16445L\\n"
'''
if s.count(old)!=1: raise SystemExit(f'float value anchor count={s.count(old)}')
s=s.replace(old,new)
p.write_text(s)
