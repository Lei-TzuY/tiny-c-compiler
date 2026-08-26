from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}\n--- pattern ---\n{old}")
    p.write_text(text.replace(old, new, 1))


# Tokenizer: preserve the f/F suffix as a real float type.
replace_once(
    "tokenize.c",
    '''            if (*end == 'f' || *end == 'F') {
                is_flonum = true;
                end++;
            }

            if (is_flonum) {
                p = end;
                cur = cur->next = new_token(TK_NUM, q, p);
                cur->line_no = line;
                cur->is_float = true;
                cur->fval = fval;
                cur->ty = ty_double;
                continue;
            }
''',
    '''            bool is_float_suffix = false;
            if (*end == 'f' || *end == 'F') {
                is_flonum = true;
                is_float_suffix = true;
                end++;
            }

            if (is_flonum) {
                p = end;
                cur = cur->next = new_token(TK_NUM, q, p);
                cur->line_no = line;
                cur->is_float = true;
                cur->fval = fval;
                cur->ty = is_float_suffix ? ty_float : ty_double;
                continue;
            }
''')

# Parser: accept floating arithmetic without weakening integer-only operators.
replace_once(
    "parse.c",
    '''    if (is_integer(lhs->ty) && is_integer(rhs->ty))
        return new_binary(ND_ADD, lhs, rhs);
''',
    '''    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_ADD, lhs, rhs);
''')
replace_once(
    "parse.c",
    '''    if (is_integer(lhs->ty) && is_integer(rhs->ty))
        return new_binary(ND_SUB, lhs, rhs);
''',
    '''    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_SUB, lhs, rhs);
''')
replace_once(
    "parse.c",
    '''    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
        if (is_integer(lhs->ty) && is_integer(rhs->ty))
            return new_binary(kind, lhs, rhs);

        if (lhs->ty->kind == TY_PTR && is_integer(rhs->ty)) {
            rhs = new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size));
            return new_binary(kind, lhs, rhs);
        }

        error("invalid operands");
    }

    if (is_integer(lhs->ty) && is_integer(rhs->ty))
        return new_binary(kind, lhs, rhs);

    error("invalid operands");
''',
    '''    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
        if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
            return new_binary(kind, lhs, rhs);

        if (lhs->ty->kind == TY_PTR && is_integer(rhs->ty)) {
            rhs = new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size));
            return new_binary(kind, lhs, rhs);
        }

        error("invalid operands");
    }

    if ((kind == ND_MUL_EQ || kind == ND_DIV_EQ) &&
        is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(kind, lhs, rhs);

    if (is_integer(lhs->ty) && is_integer(rhs->ty))
        return new_binary(kind, lhs, rhs);

    error("invalid operands");
''')
replace_once(
    "parse.c",
    '''    if (!is_integer(expr->ty) && expr->ty->kind != TY_PTR)
        error("invalid operand");
''',
    '''    if (!is_numeric(expr->ty) && expr->ty->kind != TY_PTR)
        error("invalid operand");
''')

# Constant floating scalar initializers for static locals and globals.
replace_once(
    "parse.c",
    '''static int64_t parse_const_int(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM)
        error_at(tok->loc, "expected integer constant");
    int64_t val = tok->val;
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}
''',
    '''static int64_t parse_const_int(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM || tok->is_float)
        error_at(tok->loc, "expected integer constant");
    int64_t val = tok->val;
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}

static double parse_const_double(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM)
        error_at(tok->loc, "expected numeric constant");
    double val = tok->is_float ? tok->fval : (double)tok->val;
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}
''')
replace_once(
    "parse.c",
    '''            } else {
                var->init_val = parse_const_int(&tok, tok);
                var->has_init_val = true;
            }
            continue;
''',
    '''            } else {
                if (is_flonum(ty))
                    var->finit_val = parse_const_double(&tok, tok);
                else
                    var->init_val = parse_const_int(&tok, tok);
                var->has_init_val = true;
            }
            continue;
''')
replace_once(
    "parse.c",
    '''                    } else {
                        var->init_val = parse_const_int(&tok, tok);
                        var->has_init_val = true;
                    }
''',
    '''                    } else {
                        if (is_flonum(ty))
                            var->finit_val = parse_const_double(&tok, tok);
                        else
                            var->init_val = parse_const_int(&tok, tok);
                        var->has_init_val = true;
                    }
''')

# Codegen stack helpers for scalar SSE values.
replace_once(
    "codegen.c",
    '''static void pop(char *arg) {
    printf("  pop %s\\n", arg);
    depth--;
}

static void load(Type *ty) {
''',
    '''static void pop(char *arg) {
    printf("  pop %s\\n", arg);
    depth--;
}

static void pushf(Type *ty) {
    printf("  sub $8, %%rsp\\n");
    if (ty->kind == TY_FLOAT)
        printf("  movss %%xmm0, (%%rsp)\\n");
    else
        printf("  movsd %%xmm0, (%%rsp)\\n");
    depth++;
}

static void popf(Type *ty, char *reg) {
    if (ty->kind == TY_FLOAT)
        printf("  movss (%%rsp), %s\\n", reg);
    else
        printf("  movsd (%%rsp), %s\\n", reg);
    printf("  add $8, %%rsp\\n");
    depth--;
}

static void load(Type *ty) {
''')

replace_once(
    "codegen.c",
    '''    if (ty->kind == TY_BOOL)
        printf("  movzbq (%%rax), %%rax\\n");
''',
    '''    if (ty->kind == TY_FLOAT)
        printf("  movss (%%rax), %%xmm0\\n");
    else if (ty->kind == TY_DOUBLE)
        printf("  movsd (%%rax), %%xmm0\\n");
    else if (ty->kind == TY_BOOL)
        printf("  movzbq (%%rax), %%rax\\n");
''')

replace_once(
    "codegen.c",
    '''static void store(Type *ty) {
    pop("%rdi");
    if (ty->kind == TY_BOOL) {
''',
    '''static void store(Type *ty) {
    pop("%rdi");
    if (ty->kind == TY_FLOAT) {
        printf("  movss %%xmm0, (%%rdi)\\n");
    } else if (ty->kind == TY_DOUBLE) {
        printf("  movsd %%xmm0, (%%rdi)\\n");
    } else if (ty->kind == TY_BOOL) {
''')

# Truth conversion and scalar casts.
replace_once(
    "codegen.c",
    '''static void gen_addr(Node *node) {
''',
    '''static void value_to_bool(Type *ty) {
    if (is_flonum(ty)) {
        if (ty->kind == TY_FLOAT) {
            printf("  xorps %%xmm1, %%xmm1\\n");
            printf("  ucomiss %%xmm1, %%xmm0\\n");
        } else {
            printf("  xorpd %%xmm1, %%xmm1\\n");
            printf("  ucomisd %%xmm1, %%xmm0\\n");
        }
        printf("  setne %%al\\n");
        printf("  setp %%dl\\n");
        printf("  or %%dl, %%al\\n");
        printf("  movzb %%al, %%rax\\n");
        return;
    }
    printf("  cmp $0, %%rax\\n");
    printf("  setne %%al\\n");
    printf("  movzb %%al, %%rax\\n");
}

static void cast_value(Type *from, Type *to) {
    if (!from || !to || from == to || from->kind == to->kind)
        return;

    if (to->kind == TY_VOID)
        return;

    if (to->kind == TY_BOOL) {
        value_to_bool(from);
        return;
    }

    if (is_integer(from) && is_flonum(to)) {
        if (to->kind == TY_FLOAT)
            printf("  cvtsi2ss %%rax, %%xmm0\\n");
        else
            printf("  cvtsi2sd %%rax, %%xmm0\\n");
        return;
    }

    if (is_flonum(from) && is_integer(to)) {
        if (from->kind == TY_FLOAT)
            printf("  cvttss2si %%xmm0, %%rax\\n");
        else
            printf("  cvttsd2si %%xmm0, %%rax\\n");
        normalize(to);
        return;
    }

    if (from->kind == TY_FLOAT && to->kind == TY_DOUBLE) {
        printf("  cvtss2sd %%xmm0, %%xmm0\\n");
        return;
    }
    if (from->kind == TY_DOUBLE && to->kind == TY_FLOAT) {
        printf("  cvtsd2ss %%xmm0, %%xmm0\\n");
        return;
    }

    if (is_integer(from) && is_integer(to))
        normalize(to);
}

static void gen_addr(Node *node) {
''')

# ++/-- for floating scalars.
replace_once(
    "codegen.c",
    '''static void gen_inc_dec(Node *node, bool increment, bool return_old) {
    int step;
    if (node->ty->kind == TY_PTR)
        step = node->ty->base->size;
    else
        step = 1;

    gen_addr(node->lhs);
''',
    '''static void gen_inc_dec(Node *node, bool increment, bool return_old) {
    if (is_flonum(node->ty)) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        if (return_old)
            printf("  movaps %%xmm0, %%xmm2\\n");
        if (node->ty->kind == TY_FLOAT) {
            printf("  mov $1065353216, %%eax\\n");
            printf("  movd %%eax, %%xmm1\\n");
            printf(increment ? "  addss %%xmm1, %%xmm0\\n" : "  subss %%xmm1, %%xmm0\\n");
        } else {
            printf("  mov $4607182418800017408, %%rax\\n");
            printf("  movq %%rax, %%xmm1\\n");
            printf(increment ? "  addsd %%xmm1, %%xmm0\\n" : "  subsd %%xmm1, %%xmm0\\n");
        }
        store(node->ty);
        if (return_old)
            printf("  movaps %%xmm2, %%xmm0\\n");
        return;
    }

    int step;
    if (node->ty->kind == TY_PTR)
        step = node->ty->base->size;
    else
        step = 1;

    gen_addr(node->lhs);
''')

# Compound floating assignments.
replace_once(
    "codegen.c",
    '''static void gen_compound_assign(Node *node) {
    gen_addr(node->lhs);
''',
    '''static void gen_compound_assign(Node *node) {
    if (is_flonum(node->ty)) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        pushf(node->ty);
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, node->ty);
        popf(node->ty, "%xmm1");

        if (node->ty->kind == TY_FLOAT) {
            if (node->kind == ND_ADD_EQ) printf("  addss %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_MUL_EQ) printf("  mulss %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_SUB_EQ) {
                printf("  subss %%xmm0, %%xmm1\\n");
                printf("  movaps %%xmm1, %%xmm0\\n");
            } else if (node->kind == ND_DIV_EQ) {
                printf("  divss %%xmm0, %%xmm1\\n");
                printf("  movaps %%xmm1, %%xmm0\\n");
            } else {
                error("invalid floating compound assignment");
            }
        } else {
            if (node->kind == ND_ADD_EQ) printf("  addsd %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_MUL_EQ) printf("  mulsd %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_SUB_EQ) {
                printf("  subsd %%xmm0, %%xmm1\\n");
                printf("  movapd %%xmm1, %%xmm0\\n");
            } else if (node->kind == ND_DIV_EQ) {
                printf("  divsd %%xmm0, %%xmm1\\n");
                printf("  movapd %%xmm1, %%xmm0\\n");
            } else {
                error("invalid floating compound assignment");
            }
        }
        store(node->ty);
        return;
    }

    gen_addr(node->lhs);
''')

# Literal emission respects float vs double width.
replace_once(
    "codegen.c",
    '''        if (node->ty && is_flonum(node->ty)) {
            union { double d; uint64_t u; } u = { node->fval };
            printf("  mov $%" PRIu64 ", %%rax\\n", u.u);
            printf("  movq %%rax, %%xmm0\\n");
            return;
        }
''',
    '''        if (node->ty && node->ty->kind == TY_FLOAT) {
            union { float f; uint32_t u; } u = { (float)node->fval };
            printf("  mov $%" PRIu32 ", %%eax\\n", u.u);
            printf("  movd %%eax, %%xmm0\\n");
            return;
        }
        if (node->ty && node->ty->kind == TY_DOUBLE) {
            union { double d; uint64_t u; } u = { node->fval };
            printf("  mov $%" PRIu64 ", %%rax\\n", u.u);
            printf("  movq %%rax, %%xmm0\\n");
            return;
        }
''')

# Assignment performs the implicit scalar conversion before storing.
replace_once(
    "codegen.c",
    '''    if (node->kind == ND_ASSIGN) {
        gen_addr(node->lhs);
        push();
        gen_expr(node->rhs);
        store(node->ty);
        normalize(node->ty);
        return;
    }
''',
    '''    if (node->kind == ND_ASSIGN) {
        gen_addr(node->lhs);
        push();
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, node->ty);
        store(node->ty);
        normalize(node->ty);
        return;
    }
''')

# Cast expressions share the same conversion machinery.
replace_once(
    "codegen.c",
    '''    if (node->kind == ND_CAST) {
        gen_expr(node->lhs);
        if (node->ty->kind == TY_BOOL) {
            printf("  cmp $0, %%rax\\n");
            printf("  setne %%al\\n");
            printf("  movzb %%al, %%rax\\n");
        } else if (node->ty->kind == TY_CHAR)
            printf("  movsbq %%al, %%rax\\n");
        else if (node->ty->kind == TY_SHORT)
            printf("  movswq %%ax, %%rax\\n");
        else if (node->ty->kind == TY_INT)
            printf("  movslq %%eax, %%rax\\n");
        return;
    }
''',
    '''    if (node->kind == ND_CAST) {
        gen_expr(node->lhs);
        cast_value(node->lhs->ty, node->ty);
        return;
    }
''')

# Conditions and logical operators accept floating scalar truth values.
replace_once(
    "codegen.c",
    '''        gen_expr(node->cond);
        printf("  cmp $0, %%rax\\n");
        printf("  je .L.else.%d\\n", c);
''',
    '''        gen_expr(node->cond);
        value_to_bool(node->cond->ty);
        printf("  cmp $0, %%rax\\n");
        printf("  je .L.else.%d\\n", c);
''')
replace_once(
    "codegen.c",
    '''    if (node->kind == ND_NOT) {
        gen_expr(node->lhs);
        printf("  cmp $0, %%rax\\n");
        printf("  sete %%al\\n");
        printf("  movzb %%al, %%rax\\n");
        return;
    }
''',
    '''    if (node->kind == ND_NOT) {
        gen_expr(node->lhs);
        value_to_bool(node->lhs->ty);
        printf("  xor $1, %%rax\\n");
        return;
    }
''')
replace_once(
    "codegen.c",
    '''        gen_expr(node->lhs);
        printf("  cmp $0, %%rax\\n");
        printf("  je  .L.false.%d\\n", c);
        gen_expr(node->rhs);
        printf("  cmp $0, %%rax\\n");
''',
    '''        gen_expr(node->lhs);
        value_to_bool(node->lhs->ty);
        printf("  cmp $0, %%rax\\n");
        printf("  je  .L.false.%d\\n", c);
        gen_expr(node->rhs);
        value_to_bool(node->rhs->ty);
        printf("  cmp $0, %%rax\\n");
''')
replace_once(
    "codegen.c",
    '''        gen_expr(node->lhs);
        printf("  cmp $0, %%rax\\n");
        printf("  jne .L.true.%d\\n", c);
        gen_expr(node->rhs);
        printf("  cmp $0, %%rax\\n");
''',
    '''        gen_expr(node->lhs);
        value_to_bool(node->lhs->ty);
        printf("  cmp $0, %%rax\\n");
        printf("  jne .L.true.%d\\n", c);
        gen_expr(node->rhs);
        value_to_bool(node->rhs->ty);
        printf("  cmp $0, %%rax\\n");
''')

# Floating arithmetic/comparison path before the integer register path.
replace_once(
    "codegen.c",
    '''    gen_expr(node->rhs);
    push();
    gen_expr(node->lhs);
    pop("%rdi");

    switch (node->kind) {
''',
    '''    bool arithmetic = node->kind == ND_ADD || node->kind == ND_SUB ||
                      node->kind == ND_MUL || node->kind == ND_DIV;
    bool comparison = node->kind == ND_EQ || node->kind == ND_NE ||
                      node->kind == ND_LT || node->kind == ND_LE;
    Type *common = NULL;
    if ((arithmetic || comparison) && node->lhs->ty && node->rhs->ty &&
        is_numeric(node->lhs->ty) && is_numeric(node->rhs->ty))
        common = get_common_type(node->lhs->ty, node->rhs->ty);

    if (common && is_flonum(common)) {
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, common);
        pushf(common);
        gen_expr(node->lhs);
        cast_value(node->lhs->ty, common);
        popf(common, "%xmm1");

        if (comparison) {
            if (common->kind == TY_FLOAT)
                printf("  ucomiss %%xmm1, %%xmm0\\n");
            else
                printf("  ucomisd %%xmm1, %%xmm0\\n");

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

        if (common->kind == TY_FLOAT) {
            if (node->kind == ND_ADD) printf("  addss %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_MUL) printf("  mulss %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_SUB) {
                printf("  subss %%xmm1, %%xmm0\\n");
            } else if (node->kind == ND_DIV) {
                printf("  divss %%xmm1, %%xmm0\\n");
            }
        } else {
            if (node->kind == ND_ADD) printf("  addsd %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_MUL) printf("  mulsd %%xmm1, %%xmm0\\n");
            else if (node->kind == ND_SUB) {
                printf("  subsd %%xmm1, %%xmm0\\n");
            } else if (node->kind == ND_DIV) {
                printf("  divsd %%xmm1, %%xmm0\\n");
            }
        }
        return;
    }

    gen_expr(node->rhs);
    push();
    gen_expr(node->lhs);
    pop("%rdi");

    switch (node->kind) {
''')

# Remove the old bit-pattern floating compare special-case.
replace_once(
    "codegen.c",
    '''    case ND_EQ: case ND_NE: case ND_LT: case ND_LE:
        if (node->lhs->ty && is_flonum(node->lhs->ty)) {
            printf("  movq %%rax, %%xmm0\\n");
            printf("  movq %%rdi, %%xmm1\\n");
            printf("  ucomisd %%xmm1, %%xmm0\\n");
            if (node->kind == ND_EQ) printf("  sete %%al\\n");
            else if (node->kind == ND_NE) printf("  setne %%al\\n");
            else if (node->kind == ND_LT) printf("  setb %%al\\n");
            else if (node->kind == ND_LE) printf("  setbe %%al\\n");
            printf("  movzb %%al, %%rax\\n");
            return;
        }
        printf("  cmp %%rdi, %%rax\\n");
''',
    '''    case ND_EQ: case ND_NE: case ND_LT: case ND_LE:
        printf("  cmp %%rdi, %%rax\\n");
''')

# Statement conditions use the same scalar truth conversion.
for old, new in [
    ('''        gen_expr(node->cond);\n        printf("  cmp $0, %%rax\\n");\n        printf("  je  .L.else.%d\\n", c);\n''',
     '''        gen_expr(node->cond);\n        value_to_bool(node->cond->ty);\n        printf("  cmp $0, %%rax\\n");\n        printf("  je  .L.else.%d\\n", c);\n'''),
    ('''        gen_expr(node->cond);\n        printf("  cmp $0, %%rax\\n");\n        printf("  je  .L.end.%d\\n", c);\n''',
     '''        gen_expr(node->cond);\n        value_to_bool(node->cond->ty);\n        printf("  cmp $0, %%rax\\n");\n        printf("  je  .L.end.%d\\n", c);\n'''),
    ('''        gen_expr(node->cond);\n        printf("  cmp $0, %%rax\\n");\n        printf("  jne .L.begin.%d\\n", c);\n''',
     '''        gen_expr(node->cond);\n        value_to_bool(node->cond->ty);\n        printf("  cmp $0, %%rax\\n");\n        printf("  jne .L.begin.%d\\n", c);\n'''),
]:
    # Some patterns occur more than once (while/for). Replace all exact matches.
    p = Path("codegen.c")
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"codegen.c: missing condition pattern\n{old}")
    p.write_text(text.replace(old, new))

# Global scalar floating-point initializers are emitted by bit pattern.
replace_once(
    "codegen.c",
    '''        } else if (var->has_init_val) {
            printf("  .data\\n");
            if (!var->is_static)
                printf("  .globl %s\\n", var->name);
            printf("%s:\\n", var->name);
            if (var->ty->size == 1)
                printf("  .byte %" PRId64 "\\n", var->init_val);
            else if (var->ty->size == 2)
                printf("  .short %" PRId64 "\\n", var->init_val);
            else if (var->ty->size == 4)
                printf("  .long %" PRId64 "\\n", var->init_val);
            else
                printf("  .quad %" PRId64 "\\n", var->init_val);
''',
    '''        } else if (var->has_init_val) {
            printf("  .data\\n");
            if (!var->is_static)
                printf("  .globl %s\\n", var->name);
            printf("%s:\\n", var->name);
            if (var->ty->kind == TY_FLOAT) {
                union { float f; uint32_t u; } u = { (float)var->finit_val };
                printf("  .long %" PRIu32 "\\n", u.u);
            } else if (var->ty->kind == TY_DOUBLE) {
                union { double d; uint64_t u; } u = { var->finit_val };
                printf("  .quad %" PRIu64 "\\n", u.u);
            } else if (var->ty->size == 1)
                printf("  .byte %" PRId64 "\\n", var->init_val);
            else if (var->ty->size == 2)
                printf("  .short %" PRId64 "\\n", var->init_val);
            else if (var->ty->size == 4)
                printf("  .long %" PRId64 "\\n", var->init_val);
            else
                printf("  .quad %" PRId64 "\\n", var->init_val);
''')

# Focused regression suite. It deliberately keeps function-call ABI out of scope.
Path("test/float.sh").write_text(r'''#!/bin/bash
set -e

assert_float() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-float.c
  "${MINICC:-./minicc}" tmp-float.c > tmp-float.s
  gcc -o tmp-float tmp-float.s
  set +e
  ./tmp-float
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(float): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(float): $actual"
}

assert_float 4 'int main() { return sizeof(float); }'
assert_float 8 'int main() { return sizeof(double); }'
assert_float 3 'int main() { float x=1.5f; return (int)(x*2.0f); }'
assert_float 4 'int main() { double x=1.5; return (int)(x+2.5); }'
assert_float 5 'int main() { double x=8.0; return (int)(x-3.0); }'
assert_float 4 'int main() { double x=9.0; return (int)(x/2.0); }'
assert_float 4 'int main() { int x=2; return (int)(x+2.75); }'
assert_float 1 'int main() { return 1.5 < 2.0; }'
assert_float 1 'int main() { return 2.0 >= 2.0; }'
assert_float 1 'int main() { float x=1.25f; return x==1.25f; }'
assert_float 9 'int main() { double x=0.5; if (x) return 9; return 1; }'
assert_float 7 'int main() { double x=0.0; if (x) return 1; return 7; }'
assert_float 1 'int main() { return !0.0; }'
assert_float 1 'int main() { return 0.0 || 2.0; }'
assert_float 1 'int main() { return 1.0 && 2.0; }'
assert_float 7 'int main() { double x=3.5; return (int)(x*2); }'
assert_float 3 'int main() { double x=1.0; x+=2.5; return (int)x; }'
assert_float 6 'int main() { float x=2.0f; x*=3.0f; return (int)x; }'
assert_float 3 'int main() { double x=2.0; ++x; return (int)x; }'
assert_float 2 'int main() { double x=2.0; return (int)x++; }'
assert_float 3 'int main() { return (int)(double)3; }'
assert_float 3 'int main() { return (int)(float)3; }'
assert_float 3 'int main() { return (int)(float)3.75; }'
assert_float 5 'double g=2.5; int main() { return (int)(g*2); }'
assert_float 6 'float g=3.0f; int main() { return (int)(g*2.0f); }'
assert_float 8 'int main() { static double x=4.0; return (int)(x*2); }'
assert_float 4 'int main() { return (int)(-1.5 + 5.5); }'

echo "All floating-point core tests passed!"
''')

# Wire the suite into make test.
replace_once(
    "Makefile",
    '''test: minicc
\t./test/test.sh
\tbash ./test/preprocessor.sh
\tbash ./test/preprocessor_advanced.sh
''',
    '''test: minicc
\t./test/test.sh
\tbash ./test/preprocessor.sh
\tbash ./test/preprocessor_advanced.sh
\tbash ./test/float.sh
''')

# Document the intentionally scoped support.
replace_once(
    "README.md",
    '''- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `void`, pointers, arrays, `struct`, `union`, `enum`, `typedef`, `unsigned`
''',
    '''- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, `enum`, `typedef`, `unsigned`
''')
replace_once(
    "README.md",
    '''- **Target**: x86-64 AT&T syntax assembly, Linux System V ABI
''',
    '''- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, and scalar global/static initializers. Floating-point function arguments/returns are not yet supported.
- **Target**: x86-64 AT&T syntax assembly, Linux System V ABI
''')

print("float core migration applied")
