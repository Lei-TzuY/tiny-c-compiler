#include "minicc.h"

// codegen.c

static int depth;
static char *argreg64[] = {"%rdi", "%rsi", "%rdx", "%rcx", "%r8",  "%r9"};
static char *argreg32[] = {"%edi", "%esi", "%edx", "%ecx", "%r8d", "%r9d"};
static char *argreg16[] = {"%di",  "%si",  "%dx",  "%cx",  "%r8w", "%r9w"};
static char *argreg8[]  = {"%dil", "%sil", "%dl",  "%cl",  "%r8b", "%r9b"};
static char *current_fn;
static Type *current_return_ty;
static char *brk_label;
static char *cnt_label;

static void gen_expr(Node *node);
static int count(void);

static void push(void) {
    printf("  push %%rax\n");
    depth++;
}

static void pop(char *arg) {
    printf("  pop %s\n", arg);
    depth--;
}

static void pushf(Type *ty) {
    printf("  sub $8, %%rsp\n");
    if (ty->kind == TY_FLOAT)
        printf("  movss %%xmm0, (%%rsp)\n");
    else
        printf("  movsd %%xmm0, (%%rsp)\n");
    depth++;
}

static void popf(Type *ty, char *reg) {
    if (ty->kind == TY_FLOAT)
        printf("  movss (%%rsp), %s\n", reg);
    else
        printf("  movsd (%%rsp), %s\n", reg);
    printf("  add $8, %%rsp\n");
    depth--;
}

static void load(Type *ty) {
    if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT || ty->kind == TY_FUNC)
        return; // arrays/structs/functions decay to address

    if (ty->kind == TY_FLOAT)
        printf("  movss (%%rax), %%xmm0\n");
    else if (ty->kind == TY_DOUBLE)
        printf("  movsd (%%rax), %%xmm0\n");
    else if (ty->kind == TY_BOOL)
        printf("  movzbq (%%rax), %%rax\n");
    else if (ty->kind == TY_CHAR) {
        if (ty->is_unsigned)
            printf("  movzbq (%%rax), %%rax\n");
        else
            printf("  movsbq (%%rax), %%rax\n");
    } else if (ty->kind == TY_SHORT) {
        if (ty->is_unsigned)
            printf("  movzwq (%%rax), %%rax\n");
        else
            printf("  movswq (%%rax), %%rax\n");
    } else if (ty->kind == TY_INT) {
        if (ty->is_unsigned)
            printf("  mov (%%rax), %%eax\n");
        else
            printf("  movslq (%%rax), %%rax\n");
    } else
        printf("  mov (%%rax), %%rax\n");
}

static void store(Type *ty) {
    pop("%rdi");
    if (ty->kind == TY_FLOAT) {
        printf("  movss %%xmm0, (%%rdi)\n");
    } else if (ty->kind == TY_DOUBLE) {
        printf("  movsd %%xmm0, (%%rdi)\n");
    } else if (ty->kind == TY_BOOL) {
        // _Bool: any non-zero value becomes 1
        printf("  cmp $0, %%rax\n");
        printf("  setne %%al\n");
        printf("  movzb %%al, %%rax\n");
        printf("  mov %%al, (%%rdi)\n");
    } else if (ty->kind == TY_CHAR) {
        printf("  mov %%al, (%%rdi)\n");
    } else if (ty->kind == TY_SHORT) {
        printf("  mov %%ax, (%%rdi)\n");
    } else if (ty->kind == TY_INT) {
        printf("  mov %%eax, (%%rdi)\n");
    } else if (ty->kind == TY_STRUCT) {
        int i = 0;
        for (; i + 8 <= ty->size; i += 8) {
            printf("  mov %d(%%rax), %%rsi\n", i);
            printf("  mov %%rsi, %d(%%rdi)\n", i);
        }
        for (; i + 4 <= ty->size; i += 4) {
            printf("  mov %d(%%rax), %%esi\n", i);
            printf("  mov %%esi, %d(%%rdi)\n", i);
        }
        for (; i < ty->size; i++) {
            printf("  movzb %d(%%rax), %%rsi\n", i);
            printf("  mov %%sil, %d(%%rdi)\n", i);
        }
    } else {
        printf("  mov %%rax, (%%rdi)\n");
    }
}

static void normalize(Type *ty) {
    if (ty->kind == TY_BOOL) {
        printf("  cmp $0, %%rax\n");
        printf("  setne %%al\n");
        printf("  movzb %%al, %%rax\n");
    } else if (ty->kind == TY_CHAR) {
        if (ty->is_unsigned)
            printf("  movzbq %%al, %%rax\n");
        else
            printf("  movsbq %%al, %%rax\n");
    } else if (ty->kind == TY_SHORT) {
        if (ty->is_unsigned)
            printf("  movzwq %%ax, %%rax\n");
        else
            printf("  movswq %%ax, %%rax\n");
    } else if (ty->kind == TY_INT) {
        if (ty->is_unsigned)
            printf("  mov %%eax, %%eax\n");
        else
            printf("  movslq %%eax, %%rax\n");
    }
}

static void value_to_bool(Type *ty) {
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

    // Most same-kind conversions are representation-preserving, but signed
    // and unsigned integer types of the same rank still require the target
    // width/sign interpretation (notably int <-> unsigned int).
    if (from->kind == to->kind &&
        (!is_integer(from) || from->is_unsigned == to->is_unsigned))
        return;

    if (to->kind == TY_VOID)
        return;

    if (to->kind == TY_BOOL) {
        value_to_bool(from);
        return;
    }

    if (is_integer(from) && is_flonum(to)) {
        if (to->kind == TY_FLOAT)
            printf("  cvtsi2ss %%rax, %%xmm0\n");
        else
            printf("  cvtsi2sd %%rax, %%xmm0\n");
        return;
    }

    if (is_flonum(from) && is_integer(to)) {
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

static void gen_addr(Node *node) {
    if (node->kind == ND_VAR) {
        if (node->var->is_local)
            printf("  lea %d(%%rbp), %%rax\n", node->var->offset);
        else if (node->var->is_function && !node->var->is_static)
            // A default-visible function may be interposed, so materialize its
            // address through the GOT. This is valid in PIE code and also works
            // for functions defined in the current translation unit.
            printf("  mov %s@GOTPCREL(%%rip), %%rax\n", node->var->name);
        else
            printf("  lea %s(%%rip), %%rax\n", node->var->name);
        return;
    }
    if (node->kind == ND_DEREF) {
        gen_expr(node->lhs);
        return;
    }
    if (node->kind == ND_MEMBER) {
        gen_addr(node->lhs);
        printf("  add $%d, %%rax\n", node->member->offset);
        return;
    }

    error("not an lvalue");
}

static void gen_inc_dec(Node *node, bool increment, bool return_old) {
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

    int step;
    if (node->ty->kind == TY_PTR)
        step = node->ty->base->size;
    else
        step = 1;

    gen_addr(node->lhs);
    push();
    load(node->ty);
    if (return_old)
        printf("  mov %%rax, %%rsi\n");

    if (increment)
        printf("  add $%d, %%rax\n", step);
    else
        printf("  sub $%d, %%rax\n", step);

    store(node->ty);
    normalize(node->ty);
    if (return_old)
        printf("  mov %%rsi, %%rax\n");
}

static void gen_compound_assign(Node *node) {
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
            else if (node->kind == ND_SUB_EQ) {
                printf("  subss %%xmm0, %%xmm1\n");
                printf("  movaps %%xmm1, %%xmm0\n");
            } else if (node->kind == ND_DIV_EQ) {
                printf("  divss %%xmm0, %%xmm1\n");
                printf("  movaps %%xmm1, %%xmm0\n");
            } else {
                error("invalid floating compound assignment");
            }
        } else {
            if (node->kind == ND_ADD_EQ) printf("  addsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_MUL_EQ) printf("  mulsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_SUB_EQ) {
                printf("  subsd %%xmm0, %%xmm1\n");
                printf("  movapd %%xmm1, %%xmm0\n");
            } else if (node->kind == ND_DIV_EQ) {
                printf("  divsd %%xmm0, %%xmm1\n");
                printf("  movapd %%xmm1, %%xmm0\n");
            } else {
                error("invalid floating compound assignment");
            }
        }
        store(node->ty);
        return;
    }

    Type *operation_ty = NULL;
    if (node->kind == ND_DIV_EQ || node->kind == ND_MOD_EQ)
        operation_ty = get_common_type(node->lhs->ty, node->rhs->ty);
    else if (node->kind == ND_SHR_EQ)
        // Integer promotion of the left operand.  Using int as the second
        // operand is a compact way to request exactly that promotion here.
        operation_ty = get_common_type(node->lhs->ty, ty_int);

    gen_addr(node->lhs);
    push();
    load(node->ty);
    if (operation_ty)
        cast_value(node->lhs->ty, operation_ty);
    push();
    gen_expr(node->rhs);
    if (operation_ty &&
        (node->kind == ND_DIV_EQ || node->kind == ND_MOD_EQ))
        cast_value(node->rhs->ty, operation_ty);
    printf("  mov %%rax, %%rsi\n");
    pop("%rax");

    switch (node->kind) {
    case ND_ADD_EQ: printf("  add %%rsi, %%rax\n"); break;
    case ND_SUB_EQ: printf("  sub %%rsi, %%rax\n"); break;
    case ND_MUL_EQ: printf("  imul %%rsi, %%rax\n"); break;
    case ND_DIV_EQ:
        if (operation_ty && operation_ty->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rsi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rsi\n");
        }
        break;
    case ND_MOD_EQ:
        if (operation_ty && operation_ty->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rsi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rsi\n");
        }
        printf("  mov %%rdx, %%rax\n");
        break;
    case ND_AND_EQ: printf("  and %%rsi, %%rax\n"); break;
    case ND_OR_EQ:  printf("  or %%rsi, %%rax\n"); break;
    case ND_XOR_EQ: printf("  xor %%rsi, %%rax\n"); break;
    case ND_SHL_EQ:
        printf("  mov %%rsi, %%rcx\n");
        printf("  shl %%cl, %%rax\n");
        break;
    case ND_SHR_EQ:
        printf("  mov %%rsi, %%rcx\n");
        if (operation_ty && operation_ty->is_unsigned)
            printf("  shr %%cl, %%rax\n");
        else
            printf("  sar %%cl, %%rax\n");
        break;
    default: error("invalid compound assignment");
    }

    store(node->ty);
    normalize(node->ty);
}

// Generate a function call (direct or indirect via function pointer).
// Integer/pointer arguments use rdi..r9 and float/double arguments independently
// use xmm0..xmm7. Once a register class is exhausted, later arguments of that
// class are copied to a contiguous caller stack-argument area in source order.
static void gen_funcall(Node *node) {
    bool indirect = (node->funcname == NULL);

    if (indirect) {
        gen_expr(node->lhs);
        push(); // function address remains above the argument spills
    }

    Node *args[32];
    bool fp_arg[32];
    bool stack_arg[32];
    int abi_slot[32];
    int stack_slot[32];
    int nargs = 0;
    int gp_count = 0;
    int fp_count = 0;
    int stack_count = 0;

    // Preserve the compiler's existing left-to-right argument evaluation by
    // spilling every computed value first. Each spill occupies one 8-byte slot.
    for (Node *arg = node->args; arg; arg = arg->next) {
        if (nargs >= 32)
            error("too many arguments");
        add_type(arg);
        args[nargs] = arg;
        fp_arg[nargs] = is_flonum(arg->ty);
        stack_arg[nargs] = false;

        gen_expr(arg);
        if (fp_arg[nargs]) {
            if (fp_count < 8)
                abi_slot[nargs] = fp_count++;
            else {
                stack_arg[nargs] = true;
                stack_slot[nargs] = stack_count++;
            }
            pushf(arg->ty);
        } else {
            if (gp_count < 6)
                abi_slot[nargs] = gp_count++;
            else {
                stack_arg[nargs] = true;
                stack_slot[nargs] = stack_count++;
            }
            push();
        }
        nargs++;
    }

    // r11 points at the last argument spill. Argument i lives at
    // (nargs-1-i)*8(r11), independent of whether it will use a register or stack.
    printf("  mov %%rsp, %%r11\n");

    for (int i = 0; i < nargs; i++) {
        if (stack_arg[i])
            continue;
        int src = (nargs - 1 - i) * 8;
        if (fp_arg[i]) {
            if (args[i]->ty->kind == TY_FLOAT)
                printf("  movss %d(%%r11), %%xmm%d\n", src, abi_slot[i]);
            else
                printf("  movsd %d(%%r11), %%xmm%d\n", src, abi_slot[i]);
        } else {
            printf("  mov %d(%%r11), %s\n", src, argreg64[abi_slot[i]]);
        }
    }

    if (indirect)
        printf("  mov %d(%%r11), %%r10\n", nargs * 8);

    // Keep alignment padding above the final stack arguments so the first
    // stack-passed argument remains at 0(%rsp) immediately before `call`.
    int pad = (depth + stack_count) & 1;
    if (pad) {
        printf("  sub $8, %%rsp\n");
        depth++;
    }

    if (stack_count) {
        printf("  sub $%d, %%rsp\n", stack_count * 8);
        depth += stack_count;

        for (int i = 0; i < nargs; i++) {
            if (!stack_arg[i])
                continue;
            int src = (nargs - 1 - i) * 8;
            int dst = stack_slot[i] * 8;
            // Raw 8-byte copy preserves both integer and SSE-class spill bits;
            // float callees consume only the low 4 bytes from their stack slot.
            printf("  mov %d(%%r11), %%rax\n", src);
            printf("  mov %%rax, %d(%%rsp)\n", dst);
        }
    }

    // SysV variadic calls use AL for the number of XMM registers actually used.
    printf("  mov $%d, %%eax\n", fp_count);
    if (indirect)
        printf("  call *%%r10\n");
    else
        printf("  call %s\n", node->funcname);

    if (stack_count) {
        printf("  add $%d, %%rsp\n", stack_count * 8);
        depth -= stack_count;
    }
    if (pad) {
        printf("  add $8, %%rsp\n");
        depth--;
    }

    int spill_slots = nargs + (indirect ? 1 : 0);
    if (spill_slots) {
        printf("  add $%d, %%rsp\n", spill_slots * 8);
        depth -= spill_slots;
    }
}

static void gen_expr(Node *node) {
    if (node->kind == ND_NUM) {
        if (node->ty && node->ty->kind == TY_FLOAT) {
            union { float f; uint32_t u; } u = { (float)node->fval };
            printf("  mov $%" PRIu32 ", %%eax\n", u.u);
            printf("  movd %%eax, %%xmm0\n");
            return;
        }
        if (node->ty && node->ty->kind == TY_DOUBLE) {
            union { double d; uint64_t u; } u = { node->fval };
            printf("  mov $%" PRIu64 ", %%rax\n", u.u);
            printf("  movq %%rax, %%xmm0\n");
            return;
        }
        printf("  mov $%" PRId64 ", %%rax\n", node->val);
        return;
    }

    if (node->kind == ND_VAR) {
        gen_addr(node);
        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_STRUCT &&
            node->ty->kind != TY_FUNC)
            load(node->ty);
        return;
    }

    if (node->kind == ND_ADDR) {
        gen_addr(node->lhs);
        return;
    }

    if (node->kind == ND_DEREF) {
        gen_expr(node->lhs);
        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_STRUCT &&
            node->ty->kind != TY_FUNC)
            load(node->ty);
        return;
    }

    if (node->kind == ND_MEMBER) {
        gen_addr(node);
        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_STRUCT)
            load(node->ty);
        return;
    }

    if (node->kind == ND_FUNCALL) {
        gen_funcall(node);
        return;
    }

    if (node->kind == ND_ASSIGN) {
        gen_addr(node->lhs);
        push();
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, node->ty);
        store(node->ty);
        normalize(node->ty);
        return;
    }

    if (node->kind == ND_ADD_EQ || node->kind == ND_SUB_EQ ||
        node->kind == ND_MUL_EQ || node->kind == ND_DIV_EQ ||
        node->kind == ND_MOD_EQ || node->kind == ND_AND_EQ ||
        node->kind == ND_OR_EQ  || node->kind == ND_XOR_EQ ||
        node->kind == ND_SHL_EQ || node->kind == ND_SHR_EQ) {
        gen_compound_assign(node);
        return;
    }

    if (node->kind == ND_PRE_INC || node->kind == ND_PRE_DEC ||
        node->kind == ND_POST_INC || node->kind == ND_POST_DEC) {
        bool increment = node->kind == ND_PRE_INC || node->kind == ND_POST_INC;
        bool return_old = node->kind == ND_POST_INC || node->kind == ND_POST_DEC;
        gen_inc_dec(node, increment, return_old);
        return;
    }

    if (node->kind == ND_NEG) {
        gen_expr(node->lhs);
        printf("  neg %%rax\n");
        return;
    }

    if (node->kind == ND_BITNOT) {
        gen_expr(node->lhs);
        printf("  not %%rax\n");
        return;
    }

    if (node->kind == ND_CAST) {
        gen_expr(node->lhs);
        cast_value(node->lhs->ty, node->ty);
        return;
    }

    if (node->kind == ND_TERNARY) {
        int c = count();
        gen_expr(node->cond);
        value_to_bool(node->cond->ty);
        printf("  cmp $0, %%rax\n");
        printf("  je .L.else.%d\n", c);
        gen_expr(node->then);
        cast_value(node->then->ty, node->ty);
        printf("  jmp .L.end.%d\n", c);
        printf(".L.else.%d:\n", c);
        gen_expr(node->els);
        cast_value(node->els->ty, node->ty);
        printf(".L.end.%d:\n", c);
        return;
    }

    if (node->kind == ND_NOT) {
        gen_expr(node->lhs);
        value_to_bool(node->lhs->ty);
        printf("  xor $1, %%rax\n");
        return;
    }

    if (node->kind == ND_LOGAND) {
        int c = count();
        gen_expr(node->lhs);
        value_to_bool(node->lhs->ty);
        printf("  cmp $0, %%rax\n");
        printf("  je  .L.false.%d\n", c);
        gen_expr(node->rhs);
        value_to_bool(node->rhs->ty);
        printf("  cmp $0, %%rax\n");
        printf("  je  .L.false.%d\n", c);
        printf("  mov $1, %%rax\n");
        printf("  jmp .L.end.%d\n", c);
        printf(".L.false.%d:\n", c);
        printf("  mov $0, %%rax\n");
        printf(".L.end.%d:\n", c);
        return;
    }

    if (node->kind == ND_LOGOR) {
        int c = count();
        gen_expr(node->lhs);
        value_to_bool(node->lhs->ty);
        printf("  cmp $0, %%rax\n");
        printf("  jne .L.true.%d\n", c);
        gen_expr(node->rhs);
        value_to_bool(node->rhs->ty);
        printf("  cmp $0, %%rax\n");
        printf("  jne .L.true.%d\n", c);
        printf("  mov $0, %%rax\n");
        printf("  jmp .L.end.%d\n", c);
        printf(".L.true.%d:\n", c);
        printf("  mov $1, %%rax\n");
        printf(".L.end.%d:\n", c);
        return;
    }

    if (node->kind == ND_COMMA) {
        gen_expr(node->lhs);
        gen_expr(node->rhs);
        return;
    }

    bool arithmetic = node->kind == ND_ADD || node->kind == ND_SUB ||
                      node->kind == ND_MUL || node->kind == ND_DIV ||
                      node->kind == ND_MOD || node->kind == ND_BITAND ||
                      node->kind == ND_BITOR || node->kind == ND_BITXOR;
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
                printf("  ucomiss %%xmm1, %%xmm0\n");
            else
                printf("  ucomisd %%xmm1, %%xmm0\n");

            if (node->kind == ND_EQ) {
                printf("  sete %%al\n");
                printf("  setnp %%dl\n");
                printf("  and %%dl, %%al\n");
            } else if (node->kind == ND_NE) {
                printf("  setne %%al\n");
                printf("  setp %%dl\n");
                printf("  or %%dl, %%al\n");
            } else if (node->kind == ND_LT) {
                printf("  setb %%al\n");
                printf("  setnp %%dl\n");
                printf("  and %%dl, %%al\n");
            } else {
                printf("  setbe %%al\n");
                printf("  setnp %%dl\n");
                printf("  and %%dl, %%al\n");
            }
            printf("  movzb %%al, %%rax\n");
            return;
        }

        if (common->kind == TY_FLOAT) {
            if (node->kind == ND_ADD) printf("  addss %%xmm1, %%xmm0\n");
            else if (node->kind == ND_MUL) printf("  mulss %%xmm1, %%xmm0\n");
            else if (node->kind == ND_SUB) {
                printf("  subss %%xmm1, %%xmm0\n");
            } else if (node->kind == ND_DIV) {
                printf("  divss %%xmm1, %%xmm0\n");
            }
        } else {
            if (node->kind == ND_ADD) printf("  addsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_MUL) printf("  mulsd %%xmm1, %%xmm0\n");
            else if (node->kind == ND_SUB) {
                printf("  subsd %%xmm1, %%xmm0\n");
            } else if (node->kind == ND_DIV) {
                printf("  divsd %%xmm1, %%xmm0\n");
            }
        }
        return;
    }

    gen_expr(node->rhs);
    if (common && is_integer(common))
        cast_value(node->rhs->ty, common);
    push();
    gen_expr(node->lhs);
    if (common && is_integer(common))
        cast_value(node->lhs->ty, common);
    pop("%rdi");

    switch (node->kind) {
    case ND_ADD:
        printf("  add %%rdi, %%rax\n");
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_SUB:
        printf("  sub %%rdi, %%rax\n");
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_MUL:
        printf("  imul %%rdi, %%rax\n");
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_DIV:
        if (common && common->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rdi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rdi\n");
        }
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_MOD:
        if (common && common->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rdi\n");
            printf("  mov %%rdx, %%rax\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rdi\n");
            printf("  mov %%rdx, %%rax\n");
        }
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_BITAND:
        printf("  and %%rdi, %%rax\n");
        if (common) normalize(common);
        return;
    case ND_BITOR:
        printf("  or %%rdi, %%rax\n");
        if (common) normalize(common);
        return;
    case ND_BITXOR:
        printf("  xor %%rdi, %%rax\n");
        if (common) normalize(common);
        return;
    case ND_SHL:
        printf("  mov %%rdi, %%rcx\n");
        printf("  shl %%cl, %%rax\n");
        normalize(node->ty);
        return;
    case ND_SHR:
        printf("  mov %%rdi, %%rcx\n");
        if (node->ty && node->ty->is_unsigned)
            printf("  shr %%cl, %%rax\n");
        else
            printf("  sar %%cl, %%rax\n");
        normalize(node->ty);
        return;
    case ND_EQ: case ND_NE: case ND_LT: case ND_LE:
        printf("  cmp %%rdi, %%rax\n");
        if (node->kind == ND_EQ) printf("  sete %%al\n");
        else if (node->kind == ND_NE) printf("  setne %%al\n");
        else if ((common && common->is_unsigned) ||
                 (!common && node->lhs->ty && node->lhs->ty->kind == TY_PTR)) {
            if (node->kind == ND_LT) printf("  setb %%al\n");
            else if (node->kind == ND_LE) printf("  setbe %%al\n");
        } else {
            if (node->kind == ND_LT) printf("  setl %%al\n");
            else if (node->kind == ND_LE) printf("  setle %%al\n");
        }
        printf("  movzb %%al, %%rax\n");
        return;
    default:
        error("invalid expression");
    }
}

static int count(void) {
    static int i = 1;
    return i++;
}

static void emit_switch_dispatch(Node *node, Node **default_case) {
    if (!node)
        return;

    // A nested switch owns its own case/default labels.
    if (node->kind == ND_SWITCH)
        return;

    if (node->kind == ND_CASE) {
        printf("  movabs $%" PRId64 ", %%rdi\n", node->val);
        printf("  cmp %%rdi, %%rax\n");
        printf("  je %s\n", node->unique_label);
        emit_switch_dispatch(node->lhs, default_case);
        return;
    }

    if (node->kind == ND_DEFAULT) {
        *default_case = node;
        emit_switch_dispatch(node->lhs, default_case);
        return;
    }

    if (node->kind == ND_BLOCK) {
        for (Node *n = node->body; n; n = n->next)
            emit_switch_dispatch(n, default_case);
        return;
    }

    if (node->kind == ND_IF) {
        emit_switch_dispatch(node->then, default_case);
        emit_switch_dispatch(node->els, default_case);
        return;
    }

    if (node->kind == ND_WHILE || node->kind == ND_DO || node->kind == ND_FOR) {
        emit_switch_dispatch(node->then, default_case);
        return;
    }

    if (node->kind == ND_LABEL) {
        emit_switch_dispatch(node->lhs, default_case);
        return;
    }
}

static void gen_stmt(Node *node) {
    if (node->kind == ND_RETURN) {
        if (node->lhs) {
            gen_expr(node->lhs);
            cast_value(node->lhs->ty, current_return_ty);
        }
        printf("  jmp .L.return.%s\n", current_fn);
        return;
    }

    if (node->kind == ND_BREAK) {
        if (!brk_label) error("break outside loop");
        printf("  jmp %s\n", brk_label);
        return;
    }

    if (node->kind == ND_CONTINUE) {
        if (!cnt_label) error("continue outside loop");
        printf("  jmp %s\n", cnt_label);
        return;
    }

    if (node->kind == ND_GOTO) {
        printf("  jmp %s\n", node->unique_label);
        return;
    }

    if (node->kind == ND_LABEL) {
        printf("%s:\n", node->unique_label);
        gen_stmt(node->lhs);
        return;
    }

    if (node->kind == ND_CASE || node->kind == ND_DEFAULT) {
        printf("%s:\n", node->unique_label);
        if (node->lhs)
            gen_stmt(node->lhs);
        return;
    }

    if (node->kind == ND_EXPR_STMT) {
        if (node->lhs) gen_expr(node->lhs);
        return;
    }

    if (node->kind == ND_BLOCK) {
        for (Node *n = node->body; n; n = n->next)
            gen_stmt(n);
        return;
    }

    if (node->kind == ND_IF) {
        int c = count();
        gen_expr(node->cond);
        value_to_bool(node->cond->ty);
        printf("  cmp $0, %%rax\n");
        printf("  je  .L.else.%d\n", c);
        gen_stmt(node->then);
        printf("  jmp .L.end.%d\n", c);
        printf(".L.else.%d:\n", c);
        if (node->els) gen_stmt(node->els);
        printf(".L.end.%d:\n", c);
        return;
    }

    if (node->kind == ND_WHILE) {
        int c = count();
        char brk_buf[32], cnt_buf[32];
        sprintf(brk_buf, ".L.end.%d", c);
        sprintf(cnt_buf, ".L.begin.%d", c);
        char *old_brk = brk_label, *old_cnt = cnt_label;
        brk_label = brk_buf; cnt_label = cnt_buf;

        printf(".L.begin.%d:\n", c);
        gen_expr(node->cond);
        value_to_bool(node->cond->ty);
        printf("  cmp $0, %%rax\n");
        printf("  je  .L.end.%d\n", c);
        gen_stmt(node->then);
        printf("  jmp .L.begin.%d\n", c);
        printf(".L.end.%d:\n", c);

        brk_label = old_brk; cnt_label = old_cnt;
        return;
    }

    if (node->kind == ND_DO) {
        int c = count();
        char brk_buf[32], cnt_buf[32];
        sprintf(brk_buf, ".L.end.%d", c);
        sprintf(cnt_buf, ".L.continue.%d", c);
        char *old_brk = brk_label, *old_cnt = cnt_label;
        brk_label = brk_buf; cnt_label = cnt_buf;

        printf(".L.begin.%d:\n", c);
        gen_stmt(node->then);
        printf(".L.continue.%d:\n", c);
        gen_expr(node->cond);
        value_to_bool(node->cond->ty);
        printf("  cmp $0, %%rax\n");
        printf("  jne .L.begin.%d\n", c);
        printf(".L.end.%d:\n", c);

        brk_label = old_brk; cnt_label = old_cnt;
        return;
    }

    if (node->kind == ND_FOR) {
        int c = count();
        char brk_buf[32], cnt_buf[32];
        sprintf(brk_buf, ".L.end.%d", c);
        sprintf(cnt_buf, ".L.continue.%d", c);
        char *old_brk = brk_label, *old_cnt = cnt_label;
        brk_label = brk_buf; cnt_label = cnt_buf;

        if (node->init) gen_stmt(node->init);
        printf(".L.begin.%d:\n", c);
        if (node->cond) {
            gen_expr(node->cond);
            value_to_bool(node->cond->ty);
            printf("  cmp $0, %%rax\n");
            printf("  je  .L.end.%d\n", c);
        }
        gen_stmt(node->then);
        printf(".L.continue.%d:\n", c);
        if (node->inc) gen_expr(node->inc);
        printf("  jmp .L.begin.%d\n", c);
        printf(".L.end.%d:\n", c);

        brk_label = old_brk; cnt_label = old_cnt;
        return;
    }

    if (node->kind == ND_SWITCH) {
        int c = count();
        gen_expr(node->cond);
        cast_value(node->cond->ty, node->ty);

        Node *default_case = NULL;
        emit_switch_dispatch(node->then, &default_case);
        if (default_case)
            printf("  jmp %s\n", default_case->unique_label);
        else
            printf("  jmp .L.end.%d\n", c);

        char brk_buf[32];
        sprintf(brk_buf, ".L.end.%d", c);
        char *old_brk = brk_label;
        brk_label = brk_buf;

        gen_stmt(node->then);

        printf(".L.end.%d:\n", c);
        brk_label = old_brk;
        return;
    }

    error("invalid statement");
}

static int align_up_cg(int n, int a) { return (n + a - 1) / a * a; }

static void assign_lvar_offsets(Program *prog) {
    for (Function *fn = prog->fns; fn; fn = fn->next) {
        int offset = 0;
        if (fn->is_variadic) {
            offset += 48;
            fn->va_offset = -offset;

            int p_idx = 0;
            for (Obj *p = fn->params; p; p = p->param_next) {
                p->offset = fn->va_offset + p_idx * 8;
                p_idx++;
            }
        }
        for (Obj *var = fn->locals; var; var = var->next) {
            if (fn->is_variadic) {
                bool is_param = false;
                for (Obj *p = fn->params; p; p = p->param_next) {
                    if (p == var) { is_param = true; break; }
                }
                if (is_param) continue;
            }
            int align = var->ty->align > 0 ? var->ty->align : 1;
            offset += var->ty->size;
            offset = align_up_cg(offset, align);
            var->offset = -offset;
        }
        fn->stack_size = align_up_cg(offset, 16);
    }
}

static void emit_data(Program *prog) {
    for (Obj *var = prog->globals; var; var = var->next) {
        if (var->is_function) continue; // function symbols don't need storage
        if (var->is_extern) continue;   // extern declarations don't allocate

        if (var->init_data) {
            printf("  .section .rodata\n");
            printf("%s:\n", var->name);
            for (int i = 0; i < var->ty->array_len; i++)
                printf("  .byte %d\n", var->init_data[i]);
        } else if (var->init_vals) {
            printf("  .data\n");
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            printf("%s:\n", var->name);
            int elem_size = var->ty->base ? var->ty->base->size : 4;
            for (int i = 0; i < var->init_vals_count; i++) {
                if (elem_size == 1)
                    printf("  .byte %" PRId64 "\n", var->init_vals[i]);
                else if (elem_size == 2)
                    printf("  .short %" PRId64 "\n", var->init_vals[i]);
                else if (elem_size == 4)
                    printf("  .long %" PRId64 "\n", var->init_vals[i]);
                else
                    printf("  .quad %" PRId64 "\n", var->init_vals[i]);
            }
            int emitted = var->init_vals_count * elem_size;
            if (emitted < var->ty->size)
                printf("  .zero %d\n", var->ty->size - emitted);
        } else if (var->has_init_val) {
            printf("  .data\n");
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            printf("%s:\n", var->name);
            if (var->ty->kind == TY_FLOAT) {
                union { float f; uint32_t u; } u = { (float)var->finit_val };
                printf("  .long %" PRIu32 "\n", u.u);
            } else if (var->ty->kind == TY_DOUBLE) {
                union { double d; uint64_t u; } u = { var->finit_val };
                printf("  .quad %" PRIu64 "\n", u.u);
            } else if (var->ty->size == 1)
                printf("  .byte %" PRId64 "\n", var->init_val);
            else if (var->ty->size == 2)
                printf("  .short %" PRId64 "\n", var->init_val);
            else if (var->ty->size == 4)
                printf("  .long %" PRId64 "\n", var->init_val);
            else
                printf("  .quad %" PRId64 "\n", var->init_val);
        } else {
            printf("  .data\n");
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            printf("%s:\n", var->name);
            printf("  .zero %d\n", var->ty->size);
        }
    }
}

void codegen(Program *prog) {
    assign_lvar_offsets(prog);
    emit_data(prog);

    printf("  .text\n");
    for (Function *fn = prog->fns; fn; fn = fn->next) {
        if (!fn->is_static)
            printf("  .globl %s\n", fn->name);
        printf("%s:\n", fn->name);
        current_fn = fn->name;
        current_return_ty = fn->return_ty;

        // Prologue
        printf("  push %%rbp\n");
        printf("  mov %%rsp, %%rbp\n");
        printf("  sub $%d, %%rsp\n", fn->stack_size);

        if (fn->is_variadic) {
            printf("  mov %%rdi, %d(%%rbp)\n", fn->va_offset + 0);
            printf("  mov %%rsi, %d(%%rbp)\n", fn->va_offset + 8);
            printf("  mov %%rdx, %d(%%rbp)\n", fn->va_offset + 16);
            printf("  mov %%rcx, %d(%%rbp)\n", fn->va_offset + 24);
            printf("  mov %%r8,  %d(%%rbp)\n", fn->va_offset + 32);
            printf("  mov %%r9,  %d(%%rbp)\n", fn->va_offset + 40);
        } else {
            // Save register arguments to locals and copy overflow arguments from
            // the caller stack. GPR/SSE register numbers advance independently,
            // while stack-passed arguments share one source-order slot sequence.
            int gp = 0;
            int fp = 0;
            int stack_arg = 0;
            for (Obj *var = fn->params; var; var = var->param_next) {
                if (is_flonum(var->ty)) {
                    if (fp < 8) {
                        if (var->ty->kind == TY_FLOAT)
                            printf("  movss %%xmm%d, %d(%%rbp)\n", fp, var->offset);
                        else
                            printf("  movsd %%xmm%d, %d(%%rbp)\n", fp, var->offset);
                        fp++;
                    } else {
                        int src = 16 + stack_arg++ * 8;
                        if (var->ty->kind == TY_FLOAT) {
                            printf("  movss %d(%%rbp), %%xmm15\n", src);
                            printf("  movss %%xmm15, %d(%%rbp)\n", var->offset);
                        } else {
                            printf("  movsd %d(%%rbp), %%xmm15\n", src);
                            printf("  movsd %%xmm15, %d(%%rbp)\n", var->offset);
                        }
                    }
                    continue;
                }

                if (gp < 6) {
                    if (var->ty->kind == TY_BOOL || var->ty->kind == TY_CHAR)
                        printf("  mov %s, %d(%%rbp)\n", argreg8[gp++], var->offset);
                    else if (var->ty->kind == TY_SHORT)
                        printf("  mov %s, %d(%%rbp)\n", argreg16[gp++], var->offset);
                    else if (var->ty->kind == TY_INT)
                        printf("  mov %s, %d(%%rbp)\n", argreg32[gp++], var->offset);
                    else
                        printf("  mov %s, %d(%%rbp)\n", argreg64[gp++], var->offset);
                    continue;
                }

                int src = 16 + stack_arg++ * 8;
                if (var->ty->kind == TY_BOOL || var->ty->kind == TY_CHAR) {
                    printf("  mov %d(%%rbp), %%al\n", src);
                    printf("  mov %%al, %d(%%rbp)\n", var->offset);
                } else if (var->ty->kind == TY_SHORT) {
                    printf("  mov %d(%%rbp), %%ax\n", src);
                    printf("  mov %%ax, %d(%%rbp)\n", var->offset);
                } else if (var->ty->kind == TY_INT) {
                    printf("  mov %d(%%rbp), %%eax\n", src);
                    printf("  mov %%eax, %d(%%rbp)\n", var->offset);
                } else {
                    printf("  mov %d(%%rbp), %%rax\n", src);
                    printf("  mov %%rax, %d(%%rbp)\n", var->offset);
                }
            }
        }

        for (Node *n = fn->body; n; n = n->next) {
            add_type(n);
            gen_stmt(n);
            assert(depth == 0);
        }

        // Epilogue
        printf(".L.return.%s:\n", fn->name);
        printf("  mov %%rbp, %%rsp\n");
        printf("  pop %%rbp\n");
        printf("  ret\n");
    }
}
