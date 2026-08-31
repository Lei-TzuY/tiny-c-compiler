from pathlib import Path


def rw(path):
    return Path(path).read_text()


def wr(path, text):
    Path(path).write_text(text)


def rep(text, old, new, count=1):
    actual = text.count(old)
    if actual < count:
        raise SystemExit(f"expected at least {count} occurrences, got {actual}: {old[:100]!r}")
    return text.replace(old, new, count)

# minicc.h
p = 'minicc.h'
s = rw(p)
s = rep(s, '    double fval;    // If kind is TK_NUM (floating point), its value\n',
        '    double fval;    // If kind is TK_NUM (float/double), its value\n    long double ldval; // If kind is TK_NUM (long double), its extended value\n')
s = rep(s, '    TY_FLOAT,\n    TY_DOUBLE,\n', '    TY_FLOAT,\n    TY_DOUBLE,\n    TY_LDOUBLE,\n')
s = rep(s, 'extern Type *ty_float;\nextern Type *ty_double;\n',
        'extern Type *ty_float;\nextern Type *ty_double;\nextern Type *ty_ldouble;\n')
s = rep(s, '    double fval;   // Used if kind == ND_NUM (float)\n',
        '    double fval;   // Used if kind == ND_NUM (float/double)\n    long double ldval; // Used if kind == ND_NUM (long double)\n')
s = rep(s, '    double finit_val;    // for initialized double/float global scalars\n',
        '    double finit_val;    // for initialized float/double global scalars\n    long double ldinit_val; // for initialized long double global scalars\n')
wr(p, s)

# type.c
p = 'type.c'
s = rw(p)
s = rep(s, 'Type *ty_float  = &(Type){TY_FLOAT,  4, 4, false};\nType *ty_double = &(Type){TY_DOUBLE, 8, 8, false};\n',
        'Type *ty_float   = &(Type){TY_FLOAT,   4, 4, false};\nType *ty_double  = &(Type){TY_DOUBLE,  8, 8, false};\n// SysV x86-64 stores the 80-bit x87 extended value in a 16-byte object.\nType *ty_ldouble = &(Type){TY_LDOUBLE, 16, 16, false};\n')
s = rep(s, '    return ty->kind == TY_FLOAT || ty->kind == TY_DOUBLE;\n',
        '    return ty->kind == TY_FLOAT || ty->kind == TY_DOUBLE ||\n           ty->kind == TY_LDOUBLE;\n')
s = rep(s, '    else if (is_flonum(ty))\n        cls = SYSV_ABI_SSE;\n',
        '    else if (ty->kind == TY_LDOUBLE)\n        // Scalar long double uses the SysV X87/X87UP classes, which are not\n        // represented by the record INTEGER/SSE classifier. Small records\n        // containing one are rejected by the record ABI firewall.\n        return false;\n    else if (is_flonum(ty))\n        cls = SYSV_ABI_SSE;\n')
s = rep(s, '    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)\n        return ty_double;\n',
        '    if (ty1->kind == TY_LDOUBLE || ty2->kind == TY_LDOUBLE)\n        return ty_ldouble;\n    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)\n        return ty_double;\n')
s = rep(s, '    case TY_FLOAT:\n    case TY_DOUBLE:\n        return true;\n',
        '    case TY_FLOAT:\n    case TY_DOUBLE:\n    case TY_LDOUBLE:\n        return true;\n')
wr(p, s)

# tokenize.c
p = 'tokenize.c'
s = rw(p)
s = rep(s, 'static bool read_floating_literal(char *start, char **rest, double *value,\n                                  Type **literal_ty) {',
        'static bool read_floating_literal(char *start, char **rest, long double *value,\n                                  Type **literal_ty) {')
s = rep(s, '    } else if (*p == \'l\' || *p == \'L\') {\n        // The language frontend intentionally does not expose long double yet:\n        // the x86-64 backend has no x87 80-bit storage/call ABI lowering.\n        error_at(start, "long double floating constants are not supported");\n    }\n',
        '    } else if (*p == \'l\' || *p == \'L\') {\n        ty = ty_ldouble;\n        p++;\n    }\n')
s = rep(s, '    double fval = strtod(start, &converted);\n',
        '    long double fval = strtold(start, &converted);\n')
s = rep(s, '            double fval;\n            Type *float_ty;\n',
        '            long double fval;\n            Type *float_ty;\n')
s = rep(s, '                cur->is_float = true;\n                cur->fval = fval;\n                cur->ty = float_ty;\n',
        '                cur->is_float = true;\n                cur->ldval = fval;\n                cur->fval = (double)fval;\n                cur->ty = float_ty;\n')
wr(p, s)

# parse.c
p = 'parse.c'
s = rw(p)
s = rep(s, '        if (state->n_long == 1)\n            error_at(state->first->loc, "long double is not supported by this target");\n        return;\n',
        '        return;\n')
s = rep(s, '    validate_type_specifier_set(&specs, saw_signed, saw_unsigned, tok);\n',
        '    validate_type_specifier_set(&specs, saw_signed, saw_unsigned, tok);\n    if (specs.n_double == 1 && specs.n_long == 1)\n        ty = ty_ldouble;\n')
s = rep(s, 'typedef struct {\n    Type *ty;\n    bool is_fp;\n    int64_t ival;\n    double fval;\n} ConstNumber;\n',
        'typedef struct {\n    Type *ty;\n    bool is_fp;\n    int64_t ival;\n    long double fval;\n} ConstNumber;\n')
s = s.replace('static double const_number_as_double(ConstNumber v) {',
              'static long double const_number_as_long_double(ConstNumber v) {')
s = s.replace('        return (double)(uint64_t)val;\n    return (double)val;\n',
              '        return (long double)(uint64_t)val;\n    return (long double)val;\n')
s = s.replace('        double x = const_number_as_double(v);\n',
              '        long double x = const_number_as_long_double(v);\n')
s = s.replace('        out.fval = ty->kind == TY_FLOAT ? (double)(float)x : x;\n',
              '        out.fval = ty->kind == TY_FLOAT ? (long double)(float)x\n                  : ty->kind == TY_DOUBLE ? (long double)(double)x : x;\n')
s = s.replace('    double x = v.fval;\n', '    long double x = v.fval;\n')
s = s.replace('        if (!(x >= 0.0) || x >= 18446744073709551616.0)\n',
              '        if (!(x >= 0.0L) || x >= 18446744073709551616.0L)\n')
s = s.replace('    if (x < (double)INT64_MIN || x >= 9223372036854775808.0)\n',
              '    if (x < (long double)INT64_MIN || x >= 9223372036854775808.0L)\n')
s = rep(s, '        return (ConstNumber){.ty = node->ty, .is_fp = true,\n                             .fval = node->ty->kind == TY_FLOAT\n                                         ? (double)(float)node->fval\n                                         : node->fval};\n',
        '        return (ConstNumber){.ty = node->ty, .is_fp = true,\n                             .fval = node->ty->kind == TY_FLOAT\n                                         ? (long double)(float)node->fval\n                                     : node->ty->kind == TY_DOUBLE\n                                         ? (long double)node->fval\n                                         : node->ldval};\n')
s = rep(s, '        v.fval = node->ty->kind == TY_FLOAT ? (double)(float)-v.fval : -v.fval;\n',
        '        v.fval = node->ty->kind == TY_FLOAT ? (long double)(float)-v.fval\n                 : node->ty->kind == TY_DOUBLE ? (long double)(double)-v.fval\n                                                : -v.fval;\n')
s = s.replace('        double a = const_number_as_double(eval_const_number(node->lhs));\n        double b = const_number_as_double(eval_const_number(node->rhs));\n        double r = node->kind == ND_ADD ? a + b\n',
              '        long double a = const_number_as_long_double(eval_const_number(node->lhs));\n        long double b = const_number_as_long_double(eval_const_number(node->rhs));\n        long double r = node->kind == ND_ADD ? a + b\n')
s = s.replace('            r = (double)(float)r;\n', '            r = (long double)(float)r;\n        else if (node->ty->kind == TY_DOUBLE)\n            r = (long double)(double)r;\n')
s = s.replace('            double a = const_number_as_double(lhs);\n            double b = const_number_as_double(rhs);\n',
              '            long double a = const_number_as_long_double(lhs);\n            long double b = const_number_as_long_double(rhs);\n')
s = rep(s, 'static double parse_const_double(Token **rest, Token *tok) {\n    Node *node = assign(&tok, tok);\n    add_type(node);\n    if (!is_numeric(node->ty))\n        error("static floating initializer requires an arithmetic constant expression");\n\n    ConstNumber value = const_number_cast(eval_const_number(node), ty_double);\n    *rest = tok;\n    return value.fval;\n}\n',
        'static long double parse_const_flonum(Token **rest, Token *tok, Type *target) {\n    Node *node = assign(&tok, tok);\n    add_type(node);\n    if (!is_numeric(node->ty))\n        error("static floating initializer requires an arithmetic constant expression");\n\n    ConstNumber value = const_number_cast(eval_const_number(node), target);\n    *rest = tok;\n    return value.fval;\n}\n')
s = rep(s, '    if (is_flonum(ty)) {\n        var->finit_val = parse_const_double(rest, tok);\n        var->has_init_val = true;\n        return;\n    }\n',
        '    if (is_flonum(ty)) {\n        long double value = parse_const_flonum(rest, tok, ty);\n        if (ty->kind == TY_LDOUBLE)\n            var->ldinit_val = value;\n        else\n            var->finit_val = (double)value;\n        var->has_init_val = true;\n        return;\n    }\n')
s = rep(s, '    if (is_flonum(ty)) {\n        double val = parse_const_double(rest, tok);\n        if (ty->kind == TY_FLOAT) {\n            float f = (float)val;\n            memcpy(var->init_image + offset, &f, sizeof(f));\n        } else {\n            memcpy(var->init_image + offset, &val, sizeof(val));\n        }\n        return;\n    }\n',
        '    if (is_flonum(ty)) {\n        long double val = parse_const_flonum(rest, tok, ty);\n        if (ty->kind == TY_FLOAT) {\n            float f = (float)val;\n            memcpy(var->init_image + offset, &f, sizeof(f));\n        } else if (ty->kind == TY_DOUBLE) {\n            double d = (double)val;\n            memcpy(var->init_image + offset, &d, sizeof(d));\n        } else {\n            // x86-64 long double has a 10-byte x87 payload in a 16-byte object.\n            // Keep padding deterministic in static images.\n            memset(var->init_image + offset, 0, 16);\n            memcpy(var->init_image + offset, &val, 10);\n        }\n        return;\n    }\n')
s = rep(s, '        if (tok->is_float)\n            node->fval = tok->fval;\n',
        '        if (tok->is_float) {\n            node->fval = tok->fval;\n            node->ldval = tok->ldval;\n        }\n')
wr(p, s)

# preprocess_v2.c: expose x86-64 long-double limits through the builtin float.h.
p = 'preprocess_v2.c'
s = rw(p)
needle = '"#define DBL_TRUE_MIN 4.94065645841246544177e-324\\n"\n'
if needle in s:
    s = s.replace(needle, needle +
        '               "#define LDBL_MANT_DIG 64\\n"\n'
        '               "#define LDBL_DIG 18\\n"\n'
        '               "#define LDBL_MIN_EXP (-16381)\\n"\n'
        '               "#define LDBL_MIN_10_EXP (-4931)\\n"\n'
        '               "#define LDBL_MAX_EXP 16384\\n"\n'
        '               "#define LDBL_MAX_10_EXP 4932\\n"\n'
        '               "#define LDBL_MAX 1.18973149535723176502e+4932L\\n"\n'
        '               "#define LDBL_EPSILON 1.08420217248550443401e-19L\\n"\n'
        '               "#define LDBL_MIN 3.36210314311209350626e-4932L\\n"\n')
wr(p, s)

# codegen.c
p = 'codegen.c'
s = rw(p)
# Extended temporary stack spill support.
s = rep(s, 'static void pushf(Type *ty) {\n    printf("  sub $8, %%rsp\\n");\n    if (ty->kind == TY_FLOAT)\n        printf("  movss %%xmm0, (%%rsp)\\n");\n    else\n        printf("  movsd %%xmm0, (%%rsp)\\n");\n    depth++;\n}\n',
'''static void pushf(Type *ty) {
    if (ty->kind == TY_LDOUBLE) {
        printf("  sub $16, %%rsp\\n");
        printf("  fstpt (%%rsp)\\n");
        depth += 2;
        return;
    }
    printf("  sub $8, %%rsp\\n");
    if (ty->kind == TY_FLOAT)
        printf("  movss %%xmm0, (%%rsp)\\n");
    else
        printf("  movsd %%xmm0, (%%rsp)\\n");
    depth++;
}
''')
s = rep(s, 'static void popf(Type *ty, char *reg) {\n    if (ty->kind == TY_FLOAT)\n',
        'static void popf(Type *ty, char *reg) {\n    if (ty->kind == TY_LDOUBLE) {\n        printf("  fldt (%%rsp)\\n");\n        printf("  add $16, %%rsp\\n");\n        depth -= 2;\n        return;\n    }\n    if (ty->kind == TY_FLOAT)\n')
s = rep(s, '    if (ty->kind == TY_FLOAT)\n        printf("  movss (%%rax), %%xmm0\\n");\n    else if (ty->kind == TY_DOUBLE)\n        printf("  movsd (%%rax), %%xmm0\\n");\n',
        '    if (ty->kind == TY_FLOAT)\n        printf("  movss (%%rax), %%xmm0\\n");\n    else if (ty->kind == TY_DOUBLE)\n        printf("  movsd (%%rax), %%xmm0\\n");\n    else if (ty->kind == TY_LDOUBLE)\n        printf("  fldt (%%rax)\\n");\n')
s = rep(s, '    } else if (ty->kind == TY_DOUBLE) {\n        printf("  movsd %%xmm0, (%%rdi)\\n");\n    } else if (ty->kind == TY_BOOL) {\n',
        '    } else if (ty->kind == TY_DOUBLE) {\n        printf("  movsd %%xmm0, (%%rdi)\\n");\n    } else if (ty->kind == TY_LDOUBLE) {\n        // Assignment expressions retain their value in ST(0): duplicate it\n        // before the popping 80-bit store.\n        printf("  fld %%st(0)\\n");\n        printf("  fstpt (%%rdi)\\n");\n    } else if (ty->kind == TY_BOOL) {\n')
# Truth conversion.
s = rep(s, 'static void value_to_bool(Type *ty) {\n    if (is_flonum(ty)) {\n',
'''static void value_to_bool(Type *ty) {
    if (ty->kind == TY_LDOUBLE) {
        printf("  fldz\\n");
        printf("  fucomip %%st(1), %%st\\n");
        printf("  fstp %%st(0)\\n");
        printf("  setne %%al\\n");
        printf("  setp %%dl\\n");
        printf("  or %%dl, %%al\\n");
        printf("  movzb %%al, %%rax\\n");
        return;
    }
    if (is_flonum(ty)) {
''')
# Cast long-double branches before generic float/integer cases.
marker = '    if (to->kind == TY_BOOL) {\n        value_to_bool(from);\n        return;\n    }\n\n'
insert = '''    if (to->kind == TY_BOOL) {
        value_to_bool(from);
        return;
    }

    // Long double is represented in x87 ST(0); float/double remain in XMM0.
    if (to->kind == TY_LDOUBLE && from->kind != TY_LDOUBLE) {
        if (from->kind == TY_FLOAT) {
            printf("  sub $16, %%rsp\\n");
            printf("  movss %%xmm0, (%%rsp)\\n");
            printf("  flds (%%rsp)\\n");
            printf("  add $16, %%rsp\\n");
            return;
        }
        if (from->kind == TY_DOUBLE) {
            printf("  sub $16, %%rsp\\n");
            printf("  movsd %%xmm0, (%%rsp)\\n");
            printf("  fldl (%%rsp)\\n");
            printf("  add $16, %%rsp\\n");
            return;
        }
        if (is_integer(from)) {
            printf("  sub $16, %%rsp\\n");
            printf("  mov %%rax, (%%rsp)\\n");
            printf("  fildq (%%rsp)\\n");
            // Signed integer conversion is direct. For uint64_t values with the
            // high bit set, add 2^64 to the signed interpretation.
            if (from->size == 8 && from->is_unsigned) {
                int c = count();
                printf("  test %%rax, %%rax\\n");
                printf("  jns .L.u64_to_ld_end.%d\\n", c);
                long double two64 = 18446744073709551616.0L;
                unsigned char raw[16] = {0};
                memcpy(raw, &two64, 10);
                printf("  sub $16, %%rsp\\n");
                for (int i = 0; i < 16; i++)
                    printf("  movb $%u, %d(%%rsp)\\n", raw[i], i);
                printf("  fldt (%%rsp)\\n");
                printf("  add $16, %%rsp\\n");
                printf("  faddp %%st, %%st(1)\\n");
                printf(".L.u64_to_ld_end.%d:\\n", c);
            }
            printf("  add $16, %%rsp\\n");
            return;
        }
    }

    if (from->kind == TY_LDOUBLE && to->kind != TY_LDOUBLE) {
        if (to->kind == TY_FLOAT || to->kind == TY_DOUBLE) {
            printf("  sub $16, %%rsp\\n");
            if (to->kind == TY_FLOAT) {
                printf("  fstps (%%rsp)\\n");
                printf("  movss (%%rsp), %%xmm0\\n");
            } else {
                printf("  fstpl (%%rsp)\\n");
                printf("  movsd (%%rsp), %%xmm0\\n");
            }
            printf("  add $16, %%rsp\\n");
            return;
        }
        if (is_integer(to)) {
            printf("  sub $16, %%rsp\\n");
            printf("  fisttpq (%%rsp)\\n");
            printf("  mov (%%rsp), %%rax\\n");
            printf("  add $16, %%rsp\\n");
            normalize(to);
            return;
        }
    }

'''
s = rep(s, marker, insert)
# Floating inc/dec: add dedicated LD path before generic flonum.
s = rep(s, 'static void gen_inc_dec(Node *node, bool increment, bool return_old) {\n    if (is_flonum(node->ty)) {\n',
'''static void gen_inc_dec(Node *node, bool increment, bool return_old) {
    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        if (return_old) {
            printf("  sub $16, %%rsp\\n");
            printf("  fld %%st(0)\\n");
            printf("  fstpt (%%rsp)\\n");
            depth += 2;
        }
        printf("  fld1\\n");
        printf(increment ? "  faddp %%st, %%st(1)\\n"
                         : "  fsubrp %%st, %%st(1)\\n");
        store(node->ty);
        if (return_old) {
            printf("  fstp %%st(0)\\n");
            printf("  fldt (%%rsp)\\n");
            printf("  add $16, %%rsp\\n");
            depth -= 2;
        }
        return;
    }
    if (is_flonum(node->ty)) {
''')
# Floating compound dedicated branch.
s = rep(s, 'static void gen_compound_assign(Node *node) {\n    if (is_flonum(node->ty)) {\n',
'''static void gen_compound_assign(Node *node) {
    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        pushf(node->ty);
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, node->ty);
        printf("  fldt (%%rsp)\\n");
        printf("  add $16, %%rsp\\n");
        depth -= 2;
        // Arrange ST0=rhs, ST1=old so the same pop operations as ordinary
        // binary arithmetic compute old op rhs.
        printf("  fxch %%st(1)\\n");
        if (node->kind == ND_ADD_EQ) printf("  faddp %%st, %%st(1)\\n");
        else if (node->kind == ND_MUL_EQ) printf("  fmulp %%st, %%st(1)\\n");
        else if (node->kind == ND_SUB_EQ) printf("  fsubrp %%st, %%st(1)\\n");
        else if (node->kind == ND_DIV_EQ) printf("  fdivrp %%st, %%st(1)\\n");
        else error("invalid long double compound assignment");
        store(node->ty);
        return;
    }
    if (is_flonum(node->ty)) {
''')
# Function-call classification arrays and handling.
s = rep(s, '    bool fp_arg[32];\n    bool record_arg[32];\n',
        '    bool fp_arg[32];\n    bool ld_arg[32];\n    bool record_arg[32];\n')
s = rep(s, '        record_arg[nargs] = arg->ty && arg->ty->kind == TY_STRUCT;\n        fp_arg[nargs] = !record_arg[nargs] && is_flonum(arg->ty);\n',
        '        record_arg[nargs] = arg->ty && arg->ty->kind == TY_STRUCT;\n        ld_arg[nargs] = !record_arg[nargs] && arg->ty && arg->ty->kind == TY_LDOUBLE;\n        fp_arg[nargs] = !record_arg[nargs] && !ld_arg[nargs] && is_flonum(arg->ty);\n')
s = rep(s, '        } else if (fp_arg[nargs]) {\n            spill_slots[nargs] = 1;\n',
        '        } else if (ld_arg[nargs]) {\n            spill_slots[nargs] = 2;\n            if (stack_count & 1)\n                stack_count++;\n            stack_arg[nargs] = true;\n            stack_slot[nargs] = stack_count;\n            stack_count += 2;\n        } else if (fp_arg[nargs]) {\n            spill_slots[nargs] = 1;\n')
s = rep(s, '        if (record_arg[nargs])\n            push_record_value(arg->ty);\n        else if (fp_arg[nargs])\n            pushf(arg->ty);\n        else\n',
        '        if (record_arg[nargs])\n            push_record_value(arg->ty);\n        else if (fp_arg[nargs] || ld_arg[nargs])\n            pushf(arg->ty);\n        else\n')
# Long double va_arg before double.
s = rep(s, '        if (node->ty->kind == TY_DOUBLE) {\n            printf("  mov 4(%%rdi), %%eax\\n");\n',
        '        if (node->ty->kind == TY_LDOUBLE) {\n            printf("  mov 8(%%rdi), %%rdx\\n");\n            printf("  add $15, %%rdx\\n");\n            printf("  and $-16, %%rdx\\n");\n            printf("  fldt (%%rdx)\\n");\n            printf("  add $16, %%rdx\\n");\n            printf("  mov %%rdx, 8(%%rdi)\\n");\n            return;\n        }\n\n        if (node->ty->kind == TY_DOUBLE) {\n            printf("  mov 4(%%rdi), %%eax\\n");\n')
# Literal emission.
s = rep(s, '    if (node->kind == ND_NUM) {\n        if (node->ty && node->ty->kind == TY_FLOAT) {\n',
'''    if (node->kind == ND_NUM) {
        if (node->ty && node->ty->kind == TY_LDOUBLE) {
            unsigned char raw[16] = {0};
            memcpy(raw, &node->ldval, 10);
            printf("  sub $16, %%rsp\\n");
            for (int i = 0; i < 16; i++)
                printf("  movb $%u, %d(%%rsp)\\n", raw[i], i);
            printf("  fldt (%%rsp)\\n");
            printf("  add $16, %%rsp\\n");
            return;
        }
        if (node->ty && node->ty->kind == TY_FLOAT) {
''')
# Negation.
s = rep(s, '        if (node->ty->kind == TY_FLOAT) {\n            printf("  mov $0x80000000, %%eax\\n");\n',
        '        if (node->ty->kind == TY_LDOUBLE) {\n            printf("  fchs\\n");\n        } else if (node->ty->kind == TY_FLOAT) {\n            printf("  mov $0x80000000, %%eax\\n");\n')
# Specialized binary LD path at start of flonum common branch.
s = rep(s, '    if (common && is_flonum(common)) {\n        gen_expr(node->rhs);\n',
'''    if (common && common->kind == TY_LDOUBLE) {
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, common);
        pushf(common);
        gen_expr(node->lhs);
        cast_value(node->lhs->ty, common);
        printf("  fldt (%%rsp)\\n");
        printf("  add $16, %%rsp\\n");
        depth -= 2;

        if (comparison) {
            // ST0=rhs, ST1=lhs. Compare lhs against rhs and consume both.
            printf("  fxch %%st(1)\\n");
            printf("  fucomip %%st(1), %%st\\n");
            printf("  fstp %%st(0)\\n");
            if (node->kind == ND_EQ) {
                printf("  sete %%al\\n");
                printf("  setnp %%dl\\n");
                printf("  and %%dl, %%al\\n");
            } else if (node->kind == ND_NE) {
                printf("  setne %%al\\n");
                printf("  setp %%dl\\n");
                printf("  or %%dl, %%al\\n");
            } else if (node->kind == ND_LT) {
                printf("  setb %%al\\n");
                printf("  setnp %%dl\\n");
                printf("  and %%dl, %%al\\n");
            } else {
                printf("  setbe %%al\\n");
                printf("  setnp %%dl\\n");
                printf("  and %%dl, %%al\\n");
            }
            printf("  movzb %%al, %%rax\\n");
            return;
        }

        if (node->kind == ND_ADD) printf("  faddp %%st, %%st(1)\\n");
        else if (node->kind == ND_MUL) printf("  fmulp %%st, %%st(1)\\n");
        else if (node->kind == ND_SUB) printf("  fsubrp %%st, %%st(1)\\n");
        else if (node->kind == ND_DIV) printf("  fdivrp %%st, %%st(1)\\n");
        else error("invalid long double arithmetic");
        return;
    }

    if (common && is_flonum(common)) {
        gen_expr(node->rhs);
''')
# Variadic named stack cursor: insert LD before is_flonum.
s = rep(s, '                } else if (is_flonum(p->ty)) {\n                    if (fp < 8)\n',
        '                } else if (p->ty->kind == TY_LDOUBLE) {\n                    if (stack_arg & 1)\n                        stack_arg++;\n                    stack_arg += 2;\n                } else if (is_flonum(p->ty)) {\n                    if (fp < 8)\n')
# Static scalar emission long double.
s = rep(s, '            } else if (var->ty->kind == TY_DOUBLE) {\n                union { double d; uint64_t u; } u = { var->finit_val };\n                printf("  .quad %" PRIu64 "\\n", u.u);\n            } else if (var->ty->size == 1)\n',
        '            } else if (var->ty->kind == TY_DOUBLE) {\n                union { double d; uint64_t u; } u = { var->finit_val };\n                printf("  .quad %" PRIu64 "\\n", u.u);\n            } else if (var->ty->kind == TY_LDOUBLE) {\n                unsigned char raw[16] = {0};\n                memcpy(raw, &var->ldinit_val, 10);\n                for (int i = 0; i < 16; i++)\n                    printf("  .byte %u\\n", raw[i]);\n            } else if (var->ty->size == 1)\n')
# Callee named long-double parameters before is_flonum.
s = rep(s, '            if (is_flonum(var->ty)) {\n                if (fp < 8) {\n',
        '            if (var->ty->kind == TY_LDOUBLE) {\n                if (stack_arg & 1)\n                    stack_arg++;\n                int src = 16 + stack_arg * 8;\n                printf("  mov %d(%%rbp), %%rax\\n", src);\n                printf("  mov %%rax, %d(%%rbp)\\n", var->offset);\n                printf("  mov %d(%%rbp), %%rax\\n", src + 8);\n                printf("  mov %%rax, %d(%%rbp)\\n", var->offset + 8);\n                stack_arg += 2;\n                continue;\n            }\n            if (is_flonum(var->ty)) {\n                if (fp < 8) {\n')
wr(p, s)

# Makefile
p = 'Makefile'
s = rw(p)
s = rep(s, '\tbash ./test/float.sh\n', '\tbash ./test/float.sh\n\tbash ./test/long_double.sh\n')
wr(p, s)

# README targeted wording.
p = 'README.md'
s = rw(p)
s = s.replace('`float` (4B), `double` (8B), `void`',
              '`float` (4B), `double` (8B), x86-64 `long double` (16B object / 80-bit x87 precision), `void`')
s = s.replace('Floating constants are grammar-validated C99 decimal/hex spellings: decimal exponents require digits, hexadecimal floats require a `p`/`P` binary exponent, and `f`/`F` selects `float`; `l`/`L` long-double constants are diagnosed until the backend implements the x87 long-double ABI.',
              'Floating constants are grammar-validated C99 decimal/hex spellings: decimal exponents require digits, hexadecimal floats require a `p`/`P` binary exponent, `f`/`F` selects `float`, and `l`/`L` selects the x86-64 80-bit `long double` type.')
wr(p, s)

print('long double migration applied')
