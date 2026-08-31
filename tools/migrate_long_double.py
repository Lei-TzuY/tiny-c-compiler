#!/usr/bin/env python3
from pathlib import Path
import re


def read(path):
    return Path(path).read_text()


def write(path, text):
    Path(path).write_text(text)


def rep(text, old, new, label, count=1):
    n = text.count(old)
    if n != count:
        raise SystemExit(f"{label}: expected {count} matches, got {n}")
    return text.replace(old, new)


def replace_between(text, start, end, new, label):
    i = text.find(start)
    if i < 0:
        raise SystemExit(f"{label}: start not found")
    j = text.find(end, i)
    if j < 0:
        raise SystemExit(f"{label}: end not found")
    return text[:i] + new + text[j:]

# ---- minicc.h ----
h = read("minicc.h")
h = rep(h, "    double fval;    // If kind is TK_NUM (floating point), its value\n",
        "    long double fval; // If kind is TK_NUM (floating point), its value\n",
        "token fval")
h = rep(h, "    TY_FLOAT,\n    TY_DOUBLE,\n", "    TY_FLOAT,\n    TY_DOUBLE,\n    TY_LDOUBLE,\n", "type kind")
h = rep(h, "extern Type *ty_float;\nextern Type *ty_double;\n",
        "extern Type *ty_float;\nextern Type *ty_double;\nextern Type *ty_ldouble;\n", "type extern")
h = rep(h, "    double fval;   // Used if kind == ND_NUM (float)\n",
        "    long double fval; // Used if kind == ND_NUM (floating)\n", "node fval")
h = rep(h, "    double finit_val;    // for initialized double/float global scalars\n",
        "    long double finit_val; // initialized floating scalar\n", "object finit")
write("minicc.h", h)

# ---- type.c ----
t = read("type.c")
t = rep(t, "Type *ty_float  = &(Type){TY_FLOAT,  4, 4, false};\nType *ty_double = &(Type){TY_DOUBLE, 8, 8, false};\n",
        "Type *ty_float   = &(Type){TY_FLOAT,   4,  4, false};\n"
        "Type *ty_double  = &(Type){TY_DOUBLE,  8,  8, false};\n"
        "Type *ty_ldouble = &(Type){TY_LDOUBLE, 16, 16, false};\n", "floating types")
t = rep(t, "    return ty->kind == TY_FLOAT || ty->kind == TY_DOUBLE;\n",
        "    return ty->kind == TY_FLOAT || ty->kind == TY_DOUBLE ||\n"
        "           ty->kind == TY_LDOUBLE;\n", "is_flonum")
t = rep(t, "    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)\n        return ty_double;\n",
        "    if (ty1->kind == TY_LDOUBLE || ty2->kind == TY_LDOUBLE)\n"
        "        return ty_ldouble;\n"
        "    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)\n        return ty_double;\n", "common long double")
t = rep(t, "    case TY_FLOAT:\n    case TY_DOUBLE:\n        return true;\n",
        "    case TY_FLOAT:\n    case TY_DOUBLE:\n    case TY_LDOUBLE:\n        return true;\n", "equality compatibility")
t = rep(t, "    SysVAbiClass cls;\n    if (is_integer(ty) || ty->kind == TY_PTR)\n",
        "    // SysV x87/X87UP aggregate classes are post-processed to MEMORY.\n"
        "    // Keep the small-record INTEGER/SSE classifier deliberately free\n"
        "    // of long-double values; sysv_record_is_memory() handles them.\n"
        "    if (ty->kind == TY_LDOUBLE)\n        return false;\n\n"
        "    SysVAbiClass cls;\n    if (is_integer(ty) || ty->kind == TY_PTR)\n", "record x87 classifier")
old = "bool sysv_record_is_memory(Type *ty) {\n    return ty && ty->kind == TY_STRUCT && !ty->is_incomplete && ty->size > 16;\n}\n"
new = r'''static bool type_contains_long_double(Type *ty) {
    if (!ty)
        return false;
    if (ty->kind == TY_LDOUBLE)
        return true;
    if (ty->kind == TY_ARRAY)
        return type_contains_long_double(ty->base);
    if (ty->kind == TY_STRUCT) {
        for (Member *m = ty->members; m; m = m->next)
            if (!m->is_bitfield && type_contains_long_double(m->ty))
                return true;
    }
    return false;
}

bool sysv_record_is_memory(Type *ty) {
    return ty && ty->kind == TY_STRUCT && !ty->is_incomplete &&
           (ty->size > 16 || type_contains_long_double(ty));
}
'''
t = rep(t, old, new, "record memory x87")
write("type.c", t)

# ---- tokenize.c ----
tok = read("tokenize.c")
tok = rep(tok,
          "static bool read_floating_literal(char *start, char **rest, double *value,\n                                  Type **literal_ty) {\n",
          "static bool read_floating_literal(char *start, char **rest, long double *value,\n                                  Type **literal_ty) {\n",
          "floating reader signature")
tok = rep(tok,
          "    } else if (*p == 'l' || *p == 'L') {\n"
          "        // The language frontend intentionally does not expose long double yet:\n"
          "        // the x86-64 backend has no x87 80-bit storage/call ABI lowering.\n"
          "        error_at(start, \"long double floating constants are not supported\");\n"
          "    }\n",
          "    } else if (*p == 'l' || *p == 'L') {\n"
          "        ty = ty_ldouble;\n"
          "        p++;\n"
          "    }\n",
          "long double suffix")
tok = rep(tok,
          "    double fval = strtod(start, &converted);\n"
          "    if (converted != body_end)\n"
          "        error_at(start, \"invalid floating constant\");\n\n"
          "    *rest = p;\n"
          "    *value = fval;\n",
          "    long double fval = strtold(start, &converted);\n"
          "    if (converted != body_end)\n"
          "        error_at(start, \"invalid floating constant\");\n"
          "    if (ty == ty_float)\n"
          "        fval = (long double)(float)fval;\n"
          "    else if (ty == ty_double)\n"
          "        fval = (long double)(double)fval;\n\n"
          "    *rest = p;\n"
          "    *value = fval;\n",
          "strtold conversion")
tok = rep(tok, "            double fval;\n            Type *float_ty;\n",
          "            long double fval;\n            Type *float_ty;\n", "tokenizer fval local")
write("tokenize.c", tok)

# ---- parse.c ----
p = read("parse.c")
p = rep(p,
        "        if (state->n_long == 1)\n            error_at(state->first->loc, \"long double is not supported by this target\");\n        return;\n",
        "        return;\n", "accept long double type specifier")
p = rep(p,
        "    validate_type_specifier_set(&specs, saw_signed, saw_unsigned, tok);\n"
        "    if (is_restrict && !is_restrict_qualifiable_type(ty))\n",
        "    validate_type_specifier_set(&specs, saw_signed, saw_unsigned, tok);\n"
        "    if (specs.n_double == 1 && specs.n_long == 1)\n"
        "        ty = ty_ldouble;\n"
        "    if (is_restrict && !is_restrict_qualifiable_type(ty))\n",
        "select long double type")
p = rep(p, "    double fval;\n} ConstNumber;\n",
        "    long double fval;\n} ConstNumber;\n", "ConstNumber storage")
p = rep(p, "static double const_number_as_double(ConstNumber v) {\n",
        "static long double const_number_as_floating(ConstNumber v) {\n", "const helper name")
p = p.replace("const_number_as_double(", "const_number_as_floating(")
p = rep(p, "        return (double)(uint64_t)val;\n    return (double)val;\n",
        "        return (long double)(uint64_t)val;\n    return (long double)val;\n", "const integer to fp")
p = rep(p,
        "        double x = const_number_as_floating(v);\n"
        "        out.is_fp = true;\n"
        "        out.fval = ty->kind == TY_FLOAT ? (double)(float)x : x;\n",
        "        long double x = const_number_as_floating(v);\n"
        "        out.is_fp = true;\n"
        "        if (ty->kind == TY_FLOAT)\n"
        "            out.fval = (long double)(float)x;\n"
        "        else if (ty->kind == TY_DOUBLE)\n"
        "            out.fval = (long double)(double)x;\n"
        "        else\n"
        "            out.fval = x;\n", "constant cast to floating")
p = rep(p, "    double x = v.fval;\n", "    long double x = v.fval;\n", "constant fp to integer")
p = p.replace("18446744073709551616.0)", "18446744073709551616.0L)")
p = p.replace("(double)INT64_MIN", "(long double)INT64_MIN")
p = p.replace("9223372036854775808.0)", "9223372036854775808.0L)")
p = rep(p,
        "                             .fval = node->ty->kind == TY_FLOAT\n"
        "                                         ? (double)(float)node->fval\n"
        "                                         : node->fval};\n",
        "                             .fval = node->ty->kind == TY_FLOAT\n"
        "                                         ? (long double)(float)node->fval\n"
        "                                         : node->ty->kind == TY_DOUBLE\n"
        "                                               ? (long double)(double)node->fval\n"
        "                                               : node->fval};\n", "constant literal precision")
p = rep(p,
        "        v.fval = node->ty->kind == TY_FLOAT ? (double)(float)-v.fval : -v.fval;\n",
        "        v.fval = node->ty->kind == TY_FLOAT ? (long double)(float)-v.fval\n"
        "                 : node->ty->kind == TY_DOUBLE ? (long double)(double)-v.fval\n"
        "                 : -v.fval;\n", "constant neg precision")
p = rep(p,
        "        double a = const_number_as_floating(eval_const_number(node->lhs));\n"
        "        double b = const_number_as_floating(eval_const_number(node->rhs));\n"
        "        double r = node->kind == ND_ADD ? a + b\n",
        "        long double a = const_number_as_floating(eval_const_number(node->lhs));\n"
        "        long double b = const_number_as_floating(eval_const_number(node->rhs));\n"
        "        long double r = node->kind == ND_ADD ? a + b\n", "constant arithmetic precision")
p = rep(p, "            r = (double)(float)r;\n",
        "            r = (long double)(float)r;\n"
        "        else if (node->ty->kind == TY_DOUBLE)\n"
        "            r = (long double)(double)r;\n", "constant result precision")
p = rep(p,
        "static double parse_const_double(Token **rest, Token *tok) {\n"
        "    Node *node = assign(&tok, tok);\n"
        "    add_type(node);\n"
        "    if (!is_numeric(node->ty))\n"
        "        error(\"static floating initializer requires an arithmetic constant expression\");\n\n"
        "    ConstNumber value = const_number_cast(eval_const_number(node), ty_double);\n"
        "    *rest = tok;\n"
        "    return value.fval;\n"
        "}\n",
        "static long double parse_const_floating(Token **rest, Token *tok, Type *target) {\n"
        "    Node *node = assign(&tok, tok);\n"
        "    add_type(node);\n"
        "    if (!is_numeric(node->ty))\n"
        "        error(\"static floating initializer requires an arithmetic constant expression\");\n\n"
        "    ConstNumber value = const_number_cast(eval_const_number(node), target);\n"
        "    *rest = tok;\n"
        "    return value.fval;\n"
        "}\n", "parse static floating")
p = rep(p, "        var->finit_val = parse_const_double(rest, tok);\n",
        "        var->finit_val = parse_const_floating(rest, tok, ty);\n", "scalar static fp")
p = rep(p,
        "    if (is_flonum(ty)) {\n"
        "        double val = parse_const_double(rest, tok);\n"
        "        if (ty->kind == TY_FLOAT) {\n"
        "            float f = (float)val;\n"
        "            memcpy(var->init_image + offset, &f, sizeof(f));\n"
        "        } else {\n"
        "            memcpy(var->init_image + offset, &val, sizeof(val));\n"
        "        }\n"
        "        return;\n"
        "    }\n",
        "    if (is_flonum(ty)) {\n"
        "        long double val = parse_const_floating(rest, tok, ty);\n"
        "        if (ty->kind == TY_FLOAT) {\n"
        "            float f = (float)val;\n"
        "            memcpy(var->init_image + offset, &f, sizeof(f));\n"
        "        } else if (ty->kind == TY_DOUBLE) {\n"
        "            double d = (double)val;\n"
        "            memcpy(var->init_image + offset, &d, sizeof(d));\n"
        "        } else {\n"
        "            unsigned char raw[16] = {0};\n"
        "            memcpy(raw, &val, sizeof(val));\n"
        "            memcpy(var->init_image + offset, raw, 16);\n"
        "        }\n"
        "        return;\n"
        "    }\n", "static aggregate floating")
p = rep(p, "    case TY_FLOAT:\n    case TY_DOUBLE:\n        return true;\n",
        "    case TY_FLOAT:\n    case TY_DOUBLE:\n    case TY_LDOUBLE:\n        return true;\n", "parse type compatibility")
p = rep(p,
        "        bool fp = ty->kind == TY_DOUBLE;\n"
        "        bool record = ty->kind == TY_STRUCT && supported_record_abi(ty);\n"
        "        if (!gp && !fp && !record)\n",
        "        bool fp = ty->kind == TY_DOUBLE;\n"
        "        bool ld = ty->kind == TY_LDOUBLE;\n"
        "        bool record = ty->kind == TY_STRUCT && supported_record_abi(ty);\n"
        "        if (!gp && !fp && !ld && !record)\n", "va_arg long double parser")
write("parse.c", p)

# ---- codegen.c ----
c = read("codegen.c")
# Add x87 helpers after popf.
anchor = '''static void popf(Type *ty, char *reg) {
    if (ty->kind == TY_FLOAT)
        printf("  movss (%%rsp), %s\\n", reg);
    else
        printf("  movsd (%%rsp), %s\\n", reg);
    printf("  add $8, %%rsp\\n");
    depth--;
}
'''
insert = anchor + r'''
static void pushld(void) {
    printf("  sub $16, %%rsp\n");
    printf("  fstpt (%%rsp)\n");
    depth += 2;
}

static void popld(void) {
    printf("  fldt (%%rsp)\n");
    printf("  add $16, %%rsp\n");
    depth -= 2;
}

// The compiler itself runs on the same x86-64 SysV target. Materialize the
// host long-double representation byte-for-byte and load only the 80-bit x87
// payload; the six ABI padding bytes stay deterministic zeroes.
static void emit_long_double_constant(long double value) {
    unsigned char raw[16] = {0};
    uint64_t lo = 0, hi = 0;
    if (sizeof(long double) != 16)
        error("host long double representation is incompatible with x86-64 target");
    memcpy(raw, &value, sizeof(value));
    memcpy(&lo, raw, 8);
    memcpy(&hi, raw + 8, 8);
    printf("  sub $16, %%rsp\n");
    printf("  movabs $0x%016" PRIx64 ", %%rax\n", lo);
    printf("  mov %%rax, (%%rsp)\n");
    printf("  movabs $0x%016" PRIx64 ", %%rax\n", hi);
    printf("  mov %%rax, 8(%%rsp)\n");
    printf("  fldt (%%rsp)\n");
    printf("  add $16, %%rsp\n");
}
'''
c = rep(c, anchor, insert, "x87 helpers")
# load/store long double
c = rep(c,
        "    if (ty->kind == TY_FLOAT)\n        printf(\"  movss (%%rax), %%xmm0\\n\");\n"
        "    else if (ty->kind == TY_DOUBLE)\n        printf(\"  movsd (%%rax), %%xmm0\\n\");\n",
        "    if (ty->kind == TY_FLOAT)\n        printf(\"  movss (%%rax), %%xmm0\\n\");\n"
        "    else if (ty->kind == TY_DOUBLE)\n        printf(\"  movsd (%%rax), %%xmm0\\n\");\n"
        "    else if (ty->kind == TY_LDOUBLE)\n        printf(\"  fldt (%%rax)\\n\");\n", "load long double")
c = rep(c,
        "    } else if (ty->kind == TY_DOUBLE) {\n"
        "        printf(\"  movsd %%xmm0, (%%rdi)\\n\");\n"
        "    } else if (ty->kind == TY_BOOL) {\n",
        "    } else if (ty->kind == TY_DOUBLE) {\n"
        "        printf(\"  movsd %%xmm0, (%%rdi)\\n\");\n"
        "    } else if (ty->kind == TY_LDOUBLE) {\n"
        "        // Assignment expressions retain their value in ST(0).\n"
        "        printf(\"  fld %%st(0)\\n\");\n"
        "        printf(\"  fstpt (%%rdi)\\n\");\n"
        "    } else if (ty->kind == TY_BOOL) {\n", "store long double")
# Replace value_to_bool and cast_value entirely.
start = "static void value_to_bool(Type *ty) {\n"
end = "static void gen_addr(Node *node) {\n"
new = r'''static void value_to_bool(Type *ty) {
    if (ty->kind == TY_LDOUBLE) {
        printf("  fldz\n");
        printf("  fxch %%st(1)\n");
        printf("  fucomip %%st(1), %%st\n");
        printf("  fstp %%st(0)\n");
        printf("  setne %%al\n");
        printf("  setp %%dl\n");
        printf("  or %%dl, %%al\n");
        printf("  movzb %%al, %%rax\n");
        return;
    }
    if (is_flonum(ty)) {
        if (ty->kind == TY_FLOAT) {
            printf("  xorps %%xmm1, %%xmm1\n");
            printf("  ucomiss %%xmm1, %%xmm0\n");
        } else {
            printf("  xorpd %%xmm1, %%xmm1\n");
            printf("  ucomisd %%xmm1, %%xmm0\n");
        }
        printf("  setne %%al\n");
        printf("  setp %%dl\n");
        printf("  or %%dl, %%al\n");
        printf("  movzb %%al, %%rax\n");
        return;
    }
    printf("  cmp $0, %%rax\n");
    printf("  setne %%al\n");
    printf("  movzb %%al, %%rax\n");
}

static void cast_value(Type *from, Type *to) {
    if (!from || !to || from == to)
        return;
    if (from->kind == to->kind &&
        (!is_integer(from) || from->is_unsigned == to->is_unsigned))
        return;
    if (to->kind == TY_VOID)
        return;
    if (to->kind == TY_BOOL) {
        value_to_bool(from);
        return;
    }

    if (is_integer(from) && to->kind == TY_LDOUBLE) {
        if (from->size == 8 && from->is_unsigned) {
            int c = count();
            printf("  test %%rax, %%rax\n");
            printf("  js .L.u64_to_ld.%d\n", c);
            printf("  sub $8, %%rsp\n");
            printf("  mov %%rax, (%%rsp)\n");
            printf("  fildq (%%rsp)\n");
            printf("  add $8, %%rsp\n");
            printf("  jmp .L.u64_to_ld_end.%d\n", c);
            printf(".L.u64_to_ld.%d:\n", c);
            printf("  mov %%rax, %%rdx\n");
            printf("  and $1, %%eax\n");
            printf("  shr $1, %%rdx\n");
            printf("  or %%rax, %%rdx\n");
            printf("  sub $8, %%rsp\n");
            printf("  mov %%rdx, (%%rsp)\n");
            printf("  fildq (%%rsp)\n");
            printf("  add $8, %%rsp\n");
            printf("  fadd %%st(0), %%st(0)\n");
            printf(".L.u64_to_ld_end.%d:\n", c);
            return;
        }
        printf("  sub $8, %%rsp\n");
        printf("  mov %%rax, (%%rsp)\n");
        printf("  fildq (%%rsp)\n");
        printf("  add $8, %%rsp\n");
        return;
    }

    if (from->kind == TY_LDOUBLE && is_integer(to)) {
        if (to->size == 8 && to->is_unsigned) {
            int c = count();
            emit_long_double_constant(0x1p63L);
            printf("  fxch %%st(1)\n");
            printf("  fucomi %%st(1), %%st\n");
            printf("  jb .L.ld_to_u64_low.%d\n", c);
            printf("  fsub %%st(1), %%st\n");
            printf("  fstp %%st(1)\n");
            printf("  sub $8, %%rsp\n");
            printf("  fisttpq (%%rsp)\n");
            printf("  mov (%%rsp), %%rax\n");
            printf("  add $8, %%rsp\n");
            printf("  movabs $0x8000000000000000, %%rdx\n");
            printf("  or %%rdx, %%rax\n");
            printf("  jmp .L.ld_to_u64_end.%d\n", c);
            printf(".L.ld_to_u64_low.%d:\n", c);
            printf("  fstp %%st(1)\n");
            printf("  sub $8, %%rsp\n");
            printf("  fisttpq (%%rsp)\n");
            printf("  mov (%%rsp), %%rax\n");
            printf("  add $8, %%rsp\n");
            printf(".L.ld_to_u64_end.%d:\n", c);
            return;
        }
        printf("  sub $8, %%rsp\n");
        printf("  fisttpq (%%rsp)\n");
        printf("  mov (%%rsp), %%rax\n");
        printf("  add $8, %%rsp\n");
        normalize(to);
        return;
    }

    if ((from->kind == TY_FLOAT || from->kind == TY_DOUBLE) &&
        to->kind == TY_LDOUBLE) {
        printf("  sub $8, %%rsp\n");
        if (from->kind == TY_FLOAT) {
            printf("  movss %%xmm0, (%%rsp)\n");
            printf("  flds (%%rsp)\n");
        } else {
            printf("  movsd %%xmm0, (%%rsp)\n");
            printf("  fldl (%%rsp)\n");
        }
        printf("  add $8, %%rsp\n");
        return;
    }

    if (from->kind == TY_LDOUBLE && (to->kind == TY_FLOAT || to->kind == TY_DOUBLE)) {
        printf("  sub $8, %%rsp\n");
        if (to->kind == TY_FLOAT) {
            printf("  fstps (%%rsp)\n");
            printf("  movss (%%rsp), %%xmm0\n");
        } else {
            printf("  fstpl (%%rsp)\n");
            printf("  movsd (%%rsp), %%xmm0\n");
        }
        printf("  add $8, %%rsp\n");
        return;
    }

    if (is_integer(from) && is_flonum(to)) {
        if (from->size == 8 && from->is_unsigned) {
            int c = count();
            printf("  test %%rax, %%rax\n");
            printf("  js .L.u64_to_fp.%d\n", c);
            if (to->kind == TY_FLOAT)
                printf("  cvtsi2ss %%rax, %%xmm0\n");
            else
                printf("  cvtsi2sd %%rax, %%xmm0\n");
            printf("  jmp .L.u64_to_fp_end.%d\n", c);
            printf(".L.u64_to_fp.%d:\n", c);
            printf("  mov %%rax, %%rdx\n");
            printf("  and $1, %%eax\n");
            printf("  shr $1, %%rdx\n");
            printf("  or %%rax, %%rdx\n");
            if (to->kind == TY_FLOAT) {
                printf("  cvtsi2ss %%rdx, %%xmm0\n");
                printf("  addss %%xmm0, %%xmm0\n");
            } else {
                printf("  cvtsi2sd %%rdx, %%xmm0\n");
                printf("  addsd %%xmm0, %%xmm0\n");
            }
            printf(".L.u64_to_fp_end.%d:\n", c);
            return;
        }
        if (to->kind == TY_FLOAT)
            printf("  cvtsi2ss %%rax, %%xmm0\n");
        else
            printf("  cvtsi2sd %%rax, %%xmm0\n");
        return;
    }

    if (is_flonum(from) && is_integer(to)) {
        if (to->size == 8 && to->is_unsigned) {
            int c = count();
            if (from->kind == TY_FLOAT) {
                printf("  mov $0x5f000000, %%edx\n");
                printf("  movd %%edx, %%xmm1\n");
                printf("  ucomiss %%xmm1, %%xmm0\n");
                printf("  jb .L.fp_to_u64_low.%d\n", c);
                printf("  subss %%xmm1, %%xmm0\n");
                printf("  cvttss2si %%xmm0, %%rax\n");
            } else {
                printf("  movabs $0x43e0000000000000, %%rdx\n");
                printf("  movq %%rdx, %%xmm1\n");
                printf("  ucomisd %%xmm1, %%xmm0\n");
                printf("  jb .L.fp_to_u64_low.%d\n", c);
                printf("  subsd %%xmm1, %%xmm0\n");
                printf("  cvttsd2si %%xmm0, %%rax\n");
            }
            printf("  movabs $0x8000000000000000, %%rdx\n");
            printf("  or %%rdx, %%rax\n");
            printf("  jmp .L.fp_to_u64_end.%d\n", c);
            printf(".L.fp_to_u64_low.%d:\n", c);
            if (from->kind == TY_FLOAT)
                printf("  cvttss2si %%xmm0, %%rax\n");
            else
                printf("  cvttsd2si %%xmm0, %%rax\n");
            printf(".L.fp_to_u64_end.%d:\n", c);
            return;
        }
        if (from->kind == TY_FLOAT)
            printf("  cvttss2si %%xmm0, %%rax\n");
        else
            printf("  cvttsd2si %%xmm0, %%rax\n");
        normalize(to);
        return;
    }

    if (from->kind == TY_FLOAT && to->kind == TY_DOUBLE) {
        printf("  cvtss2sd %%xmm0, %%xmm0\n");
        return;
    }
    if (from->kind == TY_DOUBLE && to->kind == TY_FLOAT) {
        printf("  cvtsd2ss %%xmm0, %%xmm0\n");
        return;
    }
    if (is_integer(from) && is_integer(to))
        normalize(to);
}

'''
c = replace_between(c, start, end, new, "value/cast x87")
# Replace increment/decrement and compound assignment.
c = replace_between(c, "static void gen_inc_dec(Node *node, bool increment, bool return_old) {\n",
                    "static void gen_compound_assign(Node *node) {\n", r'''static void gen_inc_dec(Node *node, bool increment, bool return_old) {
    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        if (return_old) {
            printf("  fld %%st(0)\n");
            pushld();
        }
        emit_long_double_constant(1.0L);
        if (increment)
            printf("  faddp %%st, %%st(1)\n");
        else
            printf("  fsubp %%st, %%st(1)\n");
        int addr_off = return_old ? 16 : 0;
        printf("  mov %d(%%rsp), %%rdi\n", addr_off);
        printf("  fld %%st(0)\n");
        printf("  fstpt (%%rdi)\n");
        if (return_old) {
            printf("  fstp %%st(0)\n");
            popld();
        }
        printf("  add $8, %%rsp\n");
        depth--;
        return;
    }

    if (is_flonum(node->ty)) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        if (return_old)
            printf("  movaps %%xmm0, %%xmm2\n");
        if (node->ty->kind == TY_FLOAT) {
            printf("  mov $1065353216, %%eax\n");
            printf("  movd %%eax, %%xmm1\n");
            printf(increment ? "  addss %%xmm1, %%xmm0\n" : "  subss %%xmm1, %%xmm0\n");
        } else {
            printf("  mov $4607182418800017408, %%rax\n");
            printf("  movq %%rax, %%xmm1\n");
            printf(increment ? "  addsd %%xmm1, %%xmm0\n" : "  subsd %%xmm1, %%xmm0\n");
        }
        store(node->ty);
        if (return_old)
            printf("  movaps %%xmm2, %%xmm0\n");
        return;
    }

    int step = 1;
    if (node->ty->kind == TY_PTR && !node->rhs)
        step = node->ty->base->size;
    gen_addr(node->lhs);
    push();
    load_lvalue(node->lhs);
    bool bitfield = node->lhs->kind == ND_MEMBER && node->lhs->member &&
                    node->lhs->member->is_bitfield;
    if (return_old)
        printf(bitfield ? "  mov %%rax, %%r8\n" : "  mov %%rax, %%rsi\n");
    if (node->rhs) {
        push();
        gen_expr(node->rhs);
        printf("  mov %%rax, %%rdi\n");
        pop("%rax");
        printf(increment ? "  add %%rdi, %%rax\n" : "  sub %%rdi, %%rax\n");
    } else if (increment) {
        printf("  add $%d, %%rax\n", step);
    } else {
        printf("  sub $%d, %%rax\n", step);
    }
    store_lvalue(node->lhs);
    normalize(node->ty);
    if (return_old)
        printf(bitfield ? "  mov %%r8, %%rax\n" : "  mov %%rsi, %%rax\n");
}

''', "long double incdec")
c = replace_between(c, "static void gen_compound_assign(Node *node) {\n",
                    "typedef struct {\n    int slots;\n", r'''static void gen_compound_assign(Node *node) {
    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        pushld();
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, node->ty);
        popld(); // ST0=old lhs, ST1=rhs
        printf("  fxch %%st(1)\n"); // ST0=rhs, ST1=old lhs
        if (node->kind == ND_ADD_EQ) printf("  faddp %%st, %%st(1)\n");
        else if (node->kind == ND_MUL_EQ) printf("  fmulp %%st, %%st(1)\n");
        else if (node->kind == ND_SUB_EQ) printf("  fsubp %%st, %%st(1)\n");
        else if (node->kind == ND_DIV_EQ) printf("  fdivp %%st, %%st(1)\n");
        else error("invalid long double compound assignment");
        store(node->ty);
        return;
    }

    if (is_flonum(node->ty)) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        pushf(node->ty);
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, node->ty);
        popf(node->ty, "%xmm1");
        if (node->ty->kind == TY_FLOAT) {
            if (node->kind == ND_ADD_EQ) printf("  addss %%xmm1, %%xmm0\n");
            else if (node->kind == ND_MUL_EQ) printf("  mulss %%xmm1, %%xmm0\n");
            else if (node->kind == ND_SUB_EQ) { printf("  subss %%xmm0, %%xmm1\n"); printf("  movaps %%xmm1, %%xmm0\n"); }
            else if (node->kind == ND_DIV_EQ) { printf("  divss %%xmm0, %%xmm1\n"); printf("  movaps %%xmm1, %%xmm0\n"); }
            else error("invalid floating compound assignment");
        } else {
            if (node->kind == ND_ADD_EQ) printf("  addsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_MUL_EQ) printf("  mulsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_SUB_EQ) { printf("  subsd %%xmm0, %%xmm1\n"); printf("  movapd %%xmm1, %%xmm0\n"); }
            else if (node->kind == ND_DIV_EQ) { printf("  divsd %%xmm0, %%xmm1\n"); printf("  movapd %%xmm1, %%xmm0\n"); }
            else error("invalid floating compound assignment");
        }
        store(node->ty);
        return;
    }

    Type *operation_ty = NULL;
    if (node->kind == ND_DIV_EQ || node->kind == ND_MOD_EQ)
        operation_ty = get_common_type_for_nodes(node->lhs, node->rhs);
    else if (node->kind == ND_SHR_EQ)
        operation_ty = integer_promotion_for_node(node->lhs);
    gen_addr(node->lhs);
    push();
    load_lvalue(node->lhs);
    if (operation_ty) cast_value(node->lhs->ty, operation_ty);
    push();
    gen_expr(node->rhs);
    if (operation_ty && (node->kind == ND_DIV_EQ || node->kind == ND_MOD_EQ))
        cast_value(node->rhs->ty, operation_ty);
    printf("  mov %%rax, %%rsi\n");
    pop("%rax");
    switch (node->kind) {
    case ND_ADD_EQ: printf("  add %%rsi, %%rax\n"); break;
    case ND_SUB_EQ: printf("  sub %%rsi, %%rax\n"); break;
    case ND_MUL_EQ: printf("  imul %%rsi, %%rax\n"); break;
    case ND_DIV_EQ:
        if (operation_ty && operation_ty->is_unsigned) { printf("  mov $0, %%rdx\n"); printf("  div %%rsi\n"); }
        else { printf("  cqo\n"); printf("  idiv %%rsi\n"); }
        break;
    case ND_MOD_EQ:
        if (operation_ty && operation_ty->is_unsigned) { printf("  mov $0, %%rdx\n"); printf("  div %%rsi\n"); }
        else { printf("  cqo\n"); printf("  idiv %%rsi\n"); }
        printf("  mov %%rdx, %%rax\n"); break;
    case ND_AND_EQ: printf("  and %%rsi, %%rax\n"); break;
    case ND_OR_EQ: printf("  or %%rsi, %%rax\n"); break;
    case ND_XOR_EQ: printf("  xor %%rsi, %%rax\n"); break;
    case ND_SHL_EQ: printf("  mov %%rsi, %%rcx\n"); printf("  shl %%cl, %%rax\n"); break;
    case ND_SHR_EQ:
        printf("  mov %%rsi, %%rcx\n");
        printf(operation_ty && operation_ty->is_unsigned ? "  shr %%cl, %%rax\n" : "  sar %%cl, %%rax\n");
        break;
    default: error("invalid compound assignment");
    }
    store_lvalue(node->lhs);
    normalize(node->ty);
}

''', "long double compound")
# Replace gen_funcall wholesale.
c = replace_between(c, "static void gen_funcall(Node *node) {\n",
                    "// Copy one low eightbyte from the variadic register-save area", r'''static void gen_funcall(Node *node) {
    bool indirect = (node->funcname == NULL);
    bool memory_return = node->ty && node->ty->kind == TY_STRUCT &&
                         sysv_record_is_memory(node->ty);
    if (indirect) { gen_expr(node->lhs); push(); }

    Node *args[32];
    bool fp_arg[32], ld_arg[32], record_arg[32], stack_arg[32];
    int abi_slot[32], record_gp_base[32], record_fp_base[32];
    SysVAbiClass record_classes[32][2];
    int stack_slot[32], spill_before[32], spill_slots[32];
    int nargs=0, gp_count=memory_return?1:0, fp_count=0, stack_count=0, total_spill_slots=0;

    for (Node *arg=node->args; arg; arg=arg->next) {
        if (nargs>=32) error("too many arguments");
        add_type(arg);
        args[nargs]=arg;
        record_arg[nargs]=arg->ty && arg->ty->kind==TY_STRUCT;
        ld_arg[nargs]=!record_arg[nargs] && arg->ty && arg->ty->kind==TY_LDOUBLE;
        fp_arg[nargs]=!record_arg[nargs] && !ld_arg[nargs] && is_flonum(arg->ty);
        stack_arg[nargs]=false;
        spill_before[nargs]=total_spill_slots;

        if (record_arg[nargs]) {
            RecordAbi abi=require_record_abi(arg->ty);
            spill_slots[nargs]=abi.slots;
            if (abi.memory) {
                if (arg->ty->align>8 && (stack_count&1)) stack_count++;
                stack_arg[nargs]=true; stack_slot[nargs]=stack_count; stack_count+=abi.slots;
            } else {
                for(int j=0;j<abi.slots;j++) record_classes[nargs][j]=abi.classes[j];
                if(gp_count+abi.gp<=6 && fp_count+abi.fp<=8) {
                    record_gp_base[nargs]=gp_count; record_fp_base[nargs]=fp_count;
                    gp_count+=abi.gp; fp_count+=abi.fp;
                } else {
                    if (arg->ty->align>8 && (stack_count&1)) stack_count++;
                    stack_arg[nargs]=true; stack_slot[nargs]=stack_count; stack_count+=abi.slots;
                }
            }
        } else if (ld_arg[nargs]) {
            spill_slots[nargs]=2;
            if (stack_count&1) stack_count++;
            stack_arg[nargs]=true; stack_slot[nargs]=stack_count; stack_count+=2;
        } else if (fp_arg[nargs]) {
            spill_slots[nargs]=1;
            if(fp_count<8) abi_slot[nargs]=fp_count++;
            else { stack_arg[nargs]=true; stack_slot[nargs]=stack_count++; }
        } else {
            spill_slots[nargs]=1;
            if(gp_count<6) abi_slot[nargs]=gp_count++;
            else { stack_arg[nargs]=true; stack_slot[nargs]=stack_count++; }
        }

        gen_expr(arg);
        if(record_arg[nargs]) push_record_value(arg->ty);
        else if(ld_arg[nargs]) pushld();
        else if(fp_arg[nargs]) pushf(arg->ty);
        else push();
        total_spill_slots += spill_slots[nargs];
        nargs++;
    }

    printf("  mov %%rsp, %%r11\n");
    for(int i=0;i<nargs;i++) {
        if(stack_arg[i]) continue;
        int src=(total_spill_slots-spill_before[i]-spill_slots[i])*8;
        if(record_arg[i]) {
            int g=record_gp_base[i], f=record_fp_base[i];
            for(int j=0;j<spill_slots[i];j++) {
                if(record_classes[i][j]==SYSV_ABI_INTEGER) printf("  mov %d(%%r11), %s\n",src+j*8,argreg64[g++]);
                else printf("  movq %d(%%r11), %%xmm%d\n",src+j*8,f++);
            }
        } else if(fp_arg[i]) {
            printf(args[i]->ty->kind==TY_FLOAT ? "  movss %d(%%r11), %%xmm%d\n" : "  movsd %d(%%r11), %%xmm%d\n",src,abi_slot[i]);
        } else {
            printf("  mov %d(%%r11), %s\n",src,argreg64[abi_slot[i]]);
        }
    }
    if(indirect) printf("  mov %d(%%r11), %%r10\n",total_spill_slots*8);

    int pad=(depth+stack_count)&1;
    if(pad){ printf("  sub $8, %%rsp\n"); depth++; }
    if(stack_count){
        printf("  sub $%d, %%rsp\n",stack_count*8); depth+=stack_count;
        for(int i=0;i<nargs;i++) if(stack_arg[i]) {
            int src=(total_spill_slots-spill_before[i]-spill_slots[i])*8;
            int dst=stack_slot[i]*8;
            for(int j=0;j<spill_slots[i];j++) {
                printf("  mov %d(%%r11), %%rax\n",src+j*8);
                printf("  mov %%rax, %d(%%rsp)\n",dst+j*8);
            }
        }
    }
    if(memory_return){
        if(!node->ret_buffer) error("missing MEMORY record return buffer");
        printf("  lea %d(%%rbp), %%rdi\n",node->ret_buffer->offset);
    }
    printf("  mov $%d, %%eax\n",fp_count);
    if(indirect) printf("  call *%%r10\n"); else printf("  call %s\n",node->funcname);
    if(stack_count){ printf("  add $%d, %%rsp\n",stack_count*8); depth-=stack_count; }
    if(pad){ printf("  add $8, %%rsp\n"); depth--; }
    int spill_count=total_spill_slots+(indirect?1:0);
    if(spill_count){ printf("  add $%d, %%rsp\n",spill_count*8); depth-=spill_count; }
    if(node->ty && node->ty->kind!=TY_STRUCT && node->ty->kind!=TY_LDOUBLE) normalize(node->ty);
    if(node->ty && node->ty->kind==TY_STRUCT) materialize_record_call(node);
}

''', "long double function calls")
# ND_NUM long double
c = rep(c,
        "        if (node->ty && node->ty->kind == TY_DOUBLE) {\n"
        "            union { double d; uint64_t u; } u = { node->fval };\n"
        "            printf(\"  mov $%\" PRIu64 \", %%rax\\n\", u.u);\n"
        "            printf(\"  movq %%rax, %%xmm0\\n\");\n"
        "            return;\n"
        "        }\n",
        "        if (node->ty && node->ty->kind == TY_DOUBLE) {\n"
        "            union { double d; uint64_t u; } u = { (double)node->fval };\n"
        "            printf(\"  mov $%\" PRIu64 \", %%rax\\n\", u.u);\n"
        "            printf(\"  movq %%rax, %%xmm0\\n\");\n"
        "            return;\n"
        "        }\n"
        "        if (node->ty && node->ty->kind == TY_LDOUBLE) {\n"
        "            emit_long_double_constant(node->fval);\n"
        "            return;\n"
        "        }\n", "long double literal codegen")
# va_arg long double before double
c = rep(c,
        "        if (node->ty->kind == TY_DOUBLE) {\n",
        "        if (node->ty->kind == TY_LDOUBLE) {\n"
        "            printf(\"  mov 8(%%rdi), %%rdx\\n\");\n"
        "            printf(\"  add $15, %%rdx\\n\");\n"
        "            printf(\"  and $-16, %%rdx\\n\");\n"
        "            printf(\"  fldt (%%rdx)\\n\");\n"
        "            printf(\"  add $16, %%rdx\\n\");\n"
        "            printf(\"  mov %%rdx, 8(%%rdi)\\n\");\n"
        "            return;\n"
        "        }\n\n"
        "        if (node->ty->kind == TY_DOUBLE) {\n", "long double va_arg")
# neg long double
c = rep(c,
        "        } else if (node->ty->kind == TY_DOUBLE) {\n"
        "            printf(\"  movabs $0x8000000000000000, %%rax\\n\");\n"
        "            printf(\"  movq %%rax, %%xmm1\\n\");\n"
        "            printf(\"  xorpd %%xmm1, %%xmm0\\n\");\n"
        "        } else {\n",
        "        } else if (node->ty->kind == TY_DOUBLE) {\n"
        "            printf(\"  movabs $0x8000000000000000, %%rax\\n\");\n"
        "            printf(\"  movq %%rax, %%xmm1\\n\");\n"
        "            printf(\"  xorpd %%xmm1, %%xmm0\\n\");\n"
        "        } else if (node->ty->kind == TY_LDOUBLE) {\n"
        "            printf(\"  fchs\\n\");\n"
        "        } else {\n", "long double neg")
# floating common block replace using a marker.
float_start = "    if (common && is_flonum(common)) {\n"
float_end = "    gen_expr(node->rhs);\n    if (common && is_integer(common))\n"
i = c.find(float_start)
j = c.find(float_end, i)
if i < 0 or j < 0: raise SystemExit("floating binary block not found")
block = r'''    if (common && common->kind == TY_LDOUBLE) {
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, common);
        pushld();
        gen_expr(node->lhs);
        cast_value(node->lhs->ty, common);
        popld(); // ST0=rhs, ST1=lhs
        if (comparison) {
            printf("  fxch %%st(1)\n");
            printf("  fucomip %%st(1), %%st\n");
            printf("  fstp %%st(0)\n");
            if (node->kind == ND_EQ) { printf("  sete %%al\n"); printf("  setnp %%dl\n"); printf("  and %%dl, %%al\n"); }
            else if (node->kind == ND_NE) { printf("  setne %%al\n"); printf("  setp %%dl\n"); printf("  or %%dl, %%al\n"); }
            else if (node->kind == ND_LT) { printf("  setb %%al\n"); printf("  setnp %%dl\n"); printf("  and %%dl, %%al\n"); }
            else { printf("  setbe %%al\n"); printf("  setnp %%dl\n"); printf("  and %%dl, %%al\n"); }
            printf("  movzb %%al, %%rax\n");
            return;
        }
        if (node->kind == ND_ADD) printf("  faddp %%st, %%st(1)\n");
        else if (node->kind == ND_SUB) printf("  fsubp %%st, %%st(1)\n");
        else if (node->kind == ND_MUL) printf("  fmulp %%st, %%st(1)\n");
        else if (node->kind == ND_DIV) printf("  fdivp %%st, %%st(1)\n");
        else error("invalid long double arithmetic");
        return;
    }

    if (common && is_flonum(common)) {
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, common);
        pushf(common);
        gen_expr(node->lhs);
        cast_value(node->lhs->ty, common);
        popf(common, "%xmm1");
        if (comparison) {
            if (common->kind == TY_FLOAT) printf("  ucomiss %%xmm1, %%xmm0\n");
            else printf("  ucomisd %%xmm1, %%xmm0\n");
            if (node->kind == ND_EQ) { printf("  sete %%al\n"); printf("  setnp %%dl\n"); printf("  and %%dl, %%al\n"); }
            else if (node->kind == ND_NE) { printf("  setne %%al\n"); printf("  setp %%dl\n"); printf("  or %%dl, %%al\n"); }
            else if (node->kind == ND_LT) { printf("  setb %%al\n"); printf("  setnp %%dl\n"); printf("  and %%dl, %%al\n"); }
            else { printf("  setbe %%al\n"); printf("  setnp %%dl\n"); printf("  and %%dl, %%al\n"); }
            printf("  movzb %%al, %%rax\n");
            return;
        }
        if (common->kind == TY_FLOAT) {
            if (node->kind == ND_ADD) printf("  addss %%xmm1, %%xmm0\n");
            else if (node->kind == ND_MUL) printf("  mulss %%xmm1, %%xmm0\n");
            else if (node->kind == ND_SUB) printf("  subss %%xmm1, %%xmm0\n");
            else if (node->kind == ND_DIV) printf("  divss %%xmm1, %%xmm0\n");
        } else {
            if (node->kind == ND_ADD) printf("  addsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_MUL) printf("  mulsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_SUB) printf("  subsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_DIV) printf("  divsd %%xmm1, %%xmm0\n");
        }
        return;
    }

'''
c = c[:i] + block + c[j:]
# static scalar emission
c = rep(c,
        "            if (var->ty->kind == TY_FLOAT) {\n"
        "                union { float f; uint32_t u; } u = { (float)var->finit_val };\n"
        "                printf(\"  .long %\" PRIu32 \\"\\n\", u.u);\n"
        "            } else if (var->ty->kind == TY_DOUBLE) {\n"
        "                union { double d; uint64_t u; } u = { var->finit_val };\n"
        "                printf(\"  .quad %\" PRIu64 \\"\\n\", u.u);\n"
        "            } else if (var->ty->size == 1)\n",
        "            if (var->ty->kind == TY_FLOAT) {\n"
        "                union { float f; uint32_t u; } u = { (float)var->finit_val };\n"
        "                printf(\"  .long %\" PRIu32 \\"\\n\", u.u);\n"
        "            } else if (var->ty->kind == TY_DOUBLE) {\n"
        "                union { double d; uint64_t u; } u = { (double)var->finit_val };\n"
        "                printf(\"  .quad %\" PRIu64 \\"\\n\", u.u);\n"
        "            } else if (var->ty->kind == TY_LDOUBLE) {\n"
        "                unsigned char raw[16] = {0};\n"
        "                long double ld = var->finit_val;\n"
        "                memcpy(raw, &ld, sizeof(ld));\n"
        "                for (int i = 0; i < 16; i++)\n"
        "                    printf(\"  .byte %u\\n\", raw[i]);\n"
        "            } else if (var->ty->size == 1)\n", "static long double emission")
# named parameter stack handling: inject before generic flonum
c = rep(c,
        "            if (is_flonum(var->ty)) {\n",
        "            if (var->ty->kind == TY_LDOUBLE) {\n"
        "                if (stack_arg & 1) stack_arg++;\n"
        "                int src = 16 + stack_arg * 8;\n"
        "                printf(\"  mov %d(%%rbp), %%rax\\n\", src);\n"
        "                printf(\"  mov %%rax, %d(%%rbp)\\n\", var->offset);\n"
        "                printf(\"  mov %d(%%rbp), %%rax\\n\", src + 8);\n"
        "                printf(\"  mov %%rax, %d(%%rbp)\\n\", var->offset + 8);\n"
        "                stack_arg += 2;\n"
        "                continue;\n"
        "            }\n"
        "            if (is_flonum(var->ty)) {\n", "callee long double param")
# variadic named-arg cursor calculation: one occurrence before prologue loop
c = rep(c,
        "                } else if (is_flonum(p->ty)) {\n"
        "                    if (fp < 8)\n"
        "                        fp++;\n"
        "                    else\n"
        "                        stack_arg++;\n",
        "                } else if (p->ty->kind == TY_LDOUBLE) {\n"
        "                    if (stack_arg & 1) stack_arg++;\n"
        "                    stack_arg += 2;\n"
        "                } else if (is_flonum(p->ty)) {\n"
        "                    if (fp < 8)\n"
        "                        fp++;\n"
        "                    else\n"
        "                        stack_arg++;\n", "va named long double")
# save record parameter stack alignment
c = rep(c,
        "    if (abi.memory) {\n"
        "        int src = 16 + *stack_arg * 8;\n",
        "    if (abi.memory) {\n"
        "        if (var->ty->align > 8 && (*stack_arg & 1)) (*stack_arg)++;\n"
        "        int src = 16 + *stack_arg * 8;\n", "memory record stack alignment")
c = rep(c,
        "    int src = 16 + *stack_arg * 8;\n"
        "    copy_stack_record_to_local(var->ty, src, var->offset);\n"
        "    *stack_arg += abi.slots;\n}\n",
        "    if (var->ty->align > 8 && (*stack_arg & 1)) (*stack_arg)++;\n"
        "    int src = 16 + *stack_arg * 8;\n"
        "    copy_stack_record_to_local(var->ty, src, var->offset);\n"
        "    *stack_arg += abi.slots;\n}\n", "fallback record stack alignment")
write("codegen.c", c)

# ---- builtin headers ----
pp = read("preprocess_v2.c")
pp = rep(pp,
         "               \"typedef struct { long long __ll; double __d; } max_align_t;\\n\"\n",
         "               \"typedef struct { long double __ld; long long __ll; } max_align_t;\\n\"\n",
         "max_align_t long double")
pp = rep(pp,
         "               \"#define DBL_MANT_DIG 53\\n\"\n",
         "               \"#define DBL_MANT_DIG 53\\n\"\n"
         "               \"#define LDBL_MANT_DIG 64\\n\"\n", "LDBL mant")
pp = rep(pp, "               \"#define DBL_DIG 15\\n\"\n",
         "               \"#define DBL_DIG 15\\n\"\n"
         "               \"#define LDBL_DIG 18\\n\"\n", "LDBL dig")
pp = rep(pp, "               \"#define DBL_MIN_EXP (-1021)\\n\"\n",
         "               \"#define DBL_MIN_EXP (-1021)\\n\"\n"
         "               \"#define LDBL_MIN_EXP (-16381)\\n\"\n", "LDBL min exp")
pp = rep(pp, "               \"#define DBL_MIN_10_EXP (-307)\\n\"\n",
         "               \"#define DBL_MIN_10_EXP (-307)\\n\"\n"
         "               \"#define LDBL_MIN_10_EXP (-4931)\\n\"\n", "LDBL min 10")
pp = rep(pp, "               \"#define DBL_MAX_EXP 1024\\n\"\n",
         "               \"#define DBL_MAX_EXP 1024\\n\"\n"
         "               \"#define LDBL_MAX_EXP 16384\\n\"\n", "LDBL max exp")
pp = rep(pp, "               \"#define DBL_MAX_10_EXP 308\\n\"\n",
         "               \"#define DBL_MAX_10_EXP 308\\n\"\n"
         "               \"#define LDBL_MAX_10_EXP 4932\\n\"\n", "LDBL max10")
pp = rep(pp, "               \"#define DECIMAL_DIG 17\\n\"\n",
         "               \"#define DECIMAL_DIG 21\\n\"\n", "decimal dig")
pp = rep(pp, "               \"#define DBL_DECIMAL_DIG 17\\n\"\n",
         "               \"#define DBL_DECIMAL_DIG 17\\n\"\n"
         "               \"#define LDBL_DECIMAL_DIG 21\\n\"\n", "LDBL decimal dig")
pp = rep(pp, "               \"#define DBL_HAS_SUBNORM 1\\n\"\n",
         "               \"#define DBL_HAS_SUBNORM 1\\n\"\n"
         "               \"#define LDBL_HAS_SUBNORM 1\\n\"\n", "LDBL subnorm")
pp = rep(pp, "               \"#define DBL_MAX 0x1.fffffffffffffp+1023\\n\"\n",
         "               \"#define DBL_MAX 0x1.fffffffffffffp+1023\\n\"\n"
         "               \"#define LDBL_MAX 0xf.fffffffffffffffp+16380L\\n\"\n", "LDBL max")
pp = rep(pp, "               \"#define DBL_EPSILON 0x1p-52\\n\"\n",
         "               \"#define DBL_EPSILON 0x1p-52\\n\"\n"
         "               \"#define LDBL_EPSILON 0x1p-63L\\n\"\n", "LDBL epsilon")
pp = rep(pp, "               \"#define DBL_MIN 0x1p-1022\\n\"\n",
         "               \"#define DBL_MIN 0x1p-1022\\n\"\n"
         "               \"#define LDBL_MIN 0x1p-16382L\\n\"\n", "LDBL min")
pp = rep(pp, "               \"#define DBL_TRUE_MIN 0x1p-1074\\n\"\n",
         "               \"#define DBL_TRUE_MIN 0x1p-1074\\n\"\n"
         "               \"#define LDBL_TRUE_MIN 0x1p-16445L\\n\"\n", "LDBL true min")
write("preprocess_v2.c", pp)

# ---- Makefile / README ----
m = read("Makefile")
m = rep(m, "\tbash ./test/float_abi.sh\n", "\tbash ./test/float_abi.sh\n\tbash ./test/long_double.sh\n\tbash ./test/long_double_abi.sh\n", "Makefile long double")
write("Makefile", m)

r = read("README.md")
r = rep(r, "`float` (4B), `double` (8B), `void`", "`float` (4B), `double` (8B), x86-64 `long double` (80-bit extended precision in 16B storage), `void`", "README types")
r = rep(r, "Floating constants are grammar-validated C99 decimal/hex spellings: decimal exponents require digits, hexadecimal floats require a `p`/`P` binary exponent, and `f`/`F` selects `float`; `l`/`L` long-double constants are diagnosed until the backend implements the x87 long-double ABI.",
        "Floating constants are grammar-validated C99 decimal/hex spellings: decimal exponents require digits, hexadecimal floats require a `p`/`P` binary exponent, `f`/`F` selects `float`, and `l`/`L` selects the x87-backed `long double` type.", "README literal")
write("README.md", r)

# ---- tests ----
Path("test/long_double.sh").write_text(r'''#!/bin/bash
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
run 0 '#include <float.h>\nint main(void){if(LDBL_MANT_DIG!=64||LDBL_DIG!=18||DECIMAL_DIG!=21)return 1; if(_Generic(LDBL_EPSILON,long double:1,default:0)!=1)return 2; if(!(1.0L+LDBL_EPSILON>1.0L))return 3; return 0;}'
echo 'All long double scalar tests passed!'
''')
Path("test/long_double_abi.sh").write_text(r'''#!/bin/bash
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
''')

print("long double migration applied")
