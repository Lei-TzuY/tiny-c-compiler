#include "minicc.h"

// codegen.c

static int depth;
static char *argreg64[] = {"%rdi", "%rsi", "%rdx", "%rcx", "%r8",  "%r9"};
static char *argreg32[] = {"%edi", "%esi", "%edx", "%ecx", "%r8d", "%r9d"};
static char *argreg16[] = {"%di",  "%si",  "%dx",  "%cx",  "%r8w", "%r9w"};
static char *argreg8[]  = {"%dil", "%sil", "%dl",  "%cl",  "%r8b", "%r9b"};
static char *current_fn;
static Function *current_fn_obj;
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
    if (ty->kind == TY_LDOUBLE) {
        printf("  sub $16, %%rsp\n");
        printf("  fstpt (%%rsp)\n");
        depth += 2;
        return;
    }
    printf("  sub $8, %%rsp\n");
    if (ty->kind == TY_FLOAT)
        printf("  movss %%xmm0, (%%rsp)\n");
    else
        printf("  movsd %%xmm0, (%%rsp)\n");
    depth++;
}

static void popf(Type *ty, char *reg) {
    if (ty->kind == TY_LDOUBLE) {
        printf("  fldt (%%rsp)\n");
        printf("  add $16, %%rsp\n");
        depth -= 2;
        return;
    }
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
    else if (ty->kind == TY_LDOUBLE)
        printf("  fldt (%%rax)\n");
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
    } else if (ty->kind == TY_LDOUBLE) {
        // Assignment expressions retain their value in ST(0): duplicate it
        // before the popping 80-bit store.
        printf("  fld %%st(0)\n");
        printf("  fstpt (%%rdi)\n");
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

static uint64_t bitfield_mask(int width) {
    return width == 64 ? UINT64_MAX : ((UINT64_C(1) << width) - 1);
}

// RAX holds the address of the declared allocation unit. Load it as raw
// unsigned bits, extract the field, then sign-extend from the field width when
// the declared base type is signed. _Bool remains the canonical 0/1 value.
static void load_bitfield(Member *member) {
    Type *ty = member->ty;
    if (ty->size == 1)
        printf("  movzbq (%%rax), %%rax\n");
    else if (ty->size == 2)
        printf("  movzwq (%%rax), %%rax\n");
    else if (ty->size == 4)
        printf("  mov (%%rax), %%eax\n");
    else if (ty->size == 8)
        printf("  mov (%%rax), %%rax\n");
    else
        error("unsupported bit-field allocation unit");

    if (member->bit_offset)
        printf("  shr $%d, %%rax\n", member->bit_offset);
    if (member->bit_width < 64) {
        uint64_t mask = bitfield_mask(member->bit_width);
        printf("  movabs $0x%016" PRIx64 ", %%rdx\n", mask);
        printf("  and %%rdx, %%rax\n");
    }

    if (!ty->is_unsigned && ty->kind != TY_BOOL && member->bit_width < 64) {
        int shift = 64 - member->bit_width;
        printf("  shl $%d, %%rax\n", shift);
        printf("  sar $%d, %%rax\n", shift);
    }
}

// The address is on the expression stack and RAX holds the value to assign.
// Merge only the selected bits into the allocation unit so neighboring fields
// and ordinary bytes sharing that unit remain unchanged. Leave RAX as the
// converted/truncated value of the assignment expression.
static void store_bitfield(Member *member) {
    Type *ty = member->ty;
    if (ty->kind == TY_BOOL) {
        printf("  cmp $0, %%rax\n");
        printf("  setne %%al\n");
        printf("  movzb %%al, %%rax\n");
    }
    uint64_t mask = bitfield_mask(member->bit_width);
    if (member->bit_width < 64) {
        printf("  movabs $0x%016" PRIx64 ", %%r10\n", mask);
        printf("  and %%r10, %%rax\n");
    }

    pop("%rdi");
    printf("  mov %%rax, %%rsi\n");

    if (ty->size == 1)
        printf("  movzbq (%%rdi), %%rdx\n");
    else if (ty->size == 2)
        printf("  movzwq (%%rdi), %%rdx\n");
    else if (ty->size == 4)
        printf("  mov (%%rdi), %%edx\n");
    else if (ty->size == 8)
        printf("  mov (%%rdi), %%rdx\n");
    else
        error("unsupported bit-field allocation unit");

    uint64_t shifted = mask << member->bit_offset;
    uint64_t clear = ~shifted;
    printf("  movabs $0x%016" PRIx64 ", %%r11\n", clear);
    printf("  and %%r11, %%rdx\n");
    if (member->bit_offset)
        printf("  shl $%d, %%rsi\n", member->bit_offset);
    printf("  or %%rsi, %%rdx\n");

    if (ty->size == 1)
        printf("  mov %%dl, (%%rdi)\n");
    else if (ty->size == 2)
        printf("  mov %%dx, (%%rdi)\n");
    else if (ty->size == 4)
        printf("  mov %%edx, (%%rdi)\n");
    else
        printf("  mov %%rdx, (%%rdi)\n");

    if (!ty->is_unsigned && ty->kind != TY_BOOL && member->bit_width < 64) {
        int shift = 64 - member->bit_width;
        printf("  shl $%d, %%rax\n", shift);
        printf("  sar $%d, %%rax\n", shift);
    }
}

static void load_lvalue(Node *node) {
    if (node->kind == ND_MEMBER && node->member && node->member->is_bitfield)
        load_bitfield(node->member);
    else
        load(node->ty);
}

static void store_lvalue(Node *node) {
    if (node->kind == ND_MEMBER && node->member && node->member->is_bitfield)
        store_bitfield(node->member);
    else
        store(node->ty);
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
    if (ty->kind == TY_LDOUBLE) {
        printf("  fldz\n");
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

    // Long double is represented in x87 ST(0); float/double remain in XMM0.
    if (to->kind == TY_LDOUBLE && from->kind != TY_LDOUBLE) {
        if (from->kind == TY_FLOAT) {
            printf("  sub $16, %%rsp\n");
            printf("  movss %%xmm0, (%%rsp)\n");
            printf("  flds (%%rsp)\n");
            printf("  add $16, %%rsp\n");
            return;
        }
        if (from->kind == TY_DOUBLE) {
            printf("  sub $16, %%rsp\n");
            printf("  movsd %%xmm0, (%%rsp)\n");
            printf("  fldl (%%rsp)\n");
            printf("  add $16, %%rsp\n");
            return;
        }
        if (is_integer(from)) {
            printf("  sub $16, %%rsp\n");
            printf("  mov %%rax, (%%rsp)\n");
            printf("  fildq (%%rsp)\n");
            // Signed integer conversion is direct. For uint64_t values with the
            // high bit set, add 2^64 to the signed interpretation.
            if (from->size == 8 && from->is_unsigned) {
                int c = count();
                printf("  test %%rax, %%rax\n");
                printf("  jns .L.u64_to_ld_end.%d\n", c);
                long double two64 = 18446744073709551616.0L;
                unsigned char raw[16] = {0};
                memcpy(raw, &two64, 10);
                printf("  sub $16, %%rsp\n");
                for (int i = 0; i < 16; i++)
                    printf("  movb $%u, %d(%%rsp)\n", raw[i], i);
                printf("  fldt (%%rsp)\n");
                printf("  add $16, %%rsp\n");
                printf("  faddp %%st, %%st(1)\n");
                printf(".L.u64_to_ld_end.%d:\n", c);
            }
            printf("  add $16, %%rsp\n");
            return;
        }
    }

    if (from->kind == TY_LDOUBLE && to->kind != TY_LDOUBLE) {
        if (to->kind == TY_FLOAT || to->kind == TY_DOUBLE) {
            printf("  sub $16, %%rsp\n");
            if (to->kind == TY_FLOAT) {
                printf("  fstps (%%rsp)\n");
                printf("  movss (%%rsp), %%xmm0\n");
            } else {
                printf("  fstpl (%%rsp)\n");
                printf("  movsd (%%rsp), %%xmm0\n");
            }
            printf("  add $16, %%rsp\n");
            return;
        }
        if (is_integer(to)) {
            printf("  sub $16, %%rsp\n");
            printf("  fisttpq (%%rsp)\n");
            printf("  mov (%%rsp), %%rax\n");
            printf("  add $16, %%rsp\n");
            normalize(to);
            return;
        }
    }

    if (is_integer(from) && is_flonum(to)) {
        // SSE2 only provides signed 64-bit integer-to-float conversion.  For
        // unsigned long values with the high bit set, halve the value while
        // preserving the dropped low bit, convert the now-signed-positive
        // integer, then double the floating result.  This is the standard
        // exact-rounding reduction used for the full uint64_t domain.
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
        // cvtt{s,d}2si also targets signed 64-bit integers.  Values in the
        // upper half of uint64_t are converted after subtracting 2^63, then
        // the high bit is restored in the integer result.  C leaves negative,
        // NaN, and out-of-range floating conversions undefined, so only the
        // representable unsigned range needs a defined lowering here.
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

static void gen_addr(Node *node) {
    if (node->kind == ND_COMPOUND_LITERAL) {
        if (node->lhs)
            gen_expr(node->lhs);
        if (!node->var)
            error("compound literal missing backing object");
        if (node->var->is_local)
            printf("  lea %d(%%rbp), %%rax\n", node->var->offset);
        else
            printf("  lea %s(%%rip), %%rax\n", node->var->name);
        return;
    }
    if (node->kind == ND_VAR) {
        if (node->var->is_local && node->var->is_vla)
            printf("  mov %d(%%rbp), %%rax\n", node->var->offset);
        else if (node->var->is_local)
            printf("  lea %d(%%rbp), %%rax\n", node->var->offset);
        else if (node->var->is_thread_local) {
            // Linux x86-64 local-exec TLS: obtain the thread pointer from FS
            // and add the linker's per-symbol TPOFF relocation. This works for
            // executable-local definitions and external TLS symbols resolved at
            // final link time.
            printf("  mov %%fs:0, %%rax\n");
            printf("  lea %s@tpoff(%%rax), %%rax\n", node->var->name);
        }
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
        // Aggregate values are represented by address throughout this backend.
        // gen_expr therefore works for both ordinary record lvalues and
        // materialized record-returning calls such as make().field.
        gen_expr(node->lhs);
        printf("  add $%d, %%rax\n", node->member->offset);
        return;
    }

    error("not an lvalue");
}

static void gen_inc_dec(Node *node, bool increment, bool return_old) {
    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        if (return_old) {
            printf("  sub $16, %%rsp\n");
            printf("  fld %%st(0)\n");
            printf("  fstpt (%%rsp)\n");
            depth += 2;
        }
        printf("  fld1\n");
        printf(increment ? "  faddp %%st, %%st(1)\n"
                         : "  fsubrp %%st, %%st(1)\n");
        store(node->ty);
        if (return_old) {
            printf("  fstp %%st(0)\n");
            printf("  fldt (%%rsp)\n");
            printf("  add $16, %%rsp\n");
            depth -= 2;
        }
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
        if (increment)
            printf("  add %%rdi, %%rax\n");
        else
            printf("  sub %%rdi, %%rax\n");
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

static void gen_compound_assign(Node *node) {
    if (node->ty->kind == TY_LDOUBLE) {
        gen_addr(node->lhs);
        push();
        load(node->ty);
        pushf(node->ty);
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, node->ty);
        printf("  fldt (%%rsp)\n");
        printf("  add $16, %%rsp\n");
        depth -= 2;
        // Arrange ST0=rhs, ST1=old so the same pop operations as ordinary
        // binary arithmetic compute old op rhs.
        printf("  fxch %%st(1)\n");
        if (node->kind == ND_ADD_EQ) printf("  faddp %%st, %%st(1)\n");
        else if (node->kind == ND_MUL_EQ) printf("  fmulp %%st, %%st(1)\n");
        else if (node->kind == ND_SUB_EQ) printf("  fsubrp %%st, %%st(1)\n");
        else if (node->kind == ND_DIV_EQ) printf("  fdivrp %%st, %%st(1)\n");
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
        operation_ty = get_common_type_for_nodes(node->lhs, node->rhs);
    else if (node->kind == ND_SHR_EQ)
        // Integer promotion of the left operand.  Using int as the second
        // operand is a compact way to request exactly that promotion here.
        operation_ty = integer_promotion_for_node(node->lhs);

    gen_addr(node->lhs);
    push();
    load_lvalue(node->lhs);
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

    store_lvalue(node->lhs);
    normalize(node->ty);
}

typedef struct {
    int slots;
    int gp;
    int fp;
    bool memory;
    SysVAbiClass classes[2];
} RecordAbi;

// Parser and backend share the same ABI frontier. Small records use the shared
// per-eightbyte classifier; complete records larger than 16 bytes are MEMORY
// class and therefore occupy rounded stack slots instead of GP/SSE registers.
static RecordAbi require_record_abi(Type *ty) {
    RecordAbi abi = {};
    if (sysv_record_is_memory(ty)) {
        abi.memory = true;
        abi.slots = (ty->size + 7) / 8;
        return abi;
    }

    abi.slots = sysv_classify_record(ty, abi.classes);
    if (!abi.slots)
        error("unsupported by-value record ABI");
    for (int i = 0; i < abi.slots; i++) {
        if (abi.classes[i] == SYSV_ABI_INTEGER)
            abi.gp++;
        else if (abi.classes[i] == SYSV_ABI_SSE)
            abi.fp++;
        else
            error("invalid SysV record class");
    }
    return abi;
}

// Spill an aggregate expression value from the address in RAX. Zeroing the
// rounded eightbyte area keeps partial final slots deterministic and avoids
// reading bytes beyond the C object merely to fill an ABI stack slot/register.
static void push_record_value(Type *ty) {
    RecordAbi abi = require_record_abi(ty);
    printf("  sub $%d, %%rsp\n", abi.slots * 8);
    depth += abi.slots;
    for (int i = 0; i < abi.slots; i++)
        printf("  movq $0, %d(%%rsp)\n", i * 8);

    int i = 0;
    for (; i + 8 <= ty->size; i += 8) {
        printf("  mov %d(%%rax), %%r10\n", i);
        printf("  mov %%r10, %d(%%rsp)\n", i);
    }
    if (i + 4 <= ty->size) {
        printf("  mov %d(%%rax), %%r10d\n", i);
        printf("  mov %%r10d, %d(%%rsp)\n", i);
        i += 4;
    }
    if (i + 2 <= ty->size) {
        printf("  mov %d(%%rax), %%r10w\n", i);
        printf("  mov %%r10w, %d(%%rsp)\n", i);
        i += 2;
    }
    if (i < ty->size) {
        printf("  mov %d(%%rax), %%r10b\n", i);
        printf("  mov %%r10b, %d(%%rsp)\n", i);
    }
}

static void store_register_bytes_to_local(const char *reg64, int dst, int bytes) {
    if (bytes == 8) {
        printf("  mov %s, %d(%%rbp)\n", reg64, dst);
        return;
    }

    printf("  mov %s, %%r10\n", reg64);
    for (int i = 0; i < bytes; i++) {
        printf("  mov %%r10b, %d(%%rbp)\n", dst + i);
        if (i + 1 < bytes)
            printf("  shr $8, %%r10\n");
    }
}

static void store_sse_bytes_to_local(int xmm, int dst, int bytes) {
    printf("  movq %%xmm%d, %%r10\n", xmm);
    store_register_bytes_to_local("%r10", dst, bytes);
}

static void copy_stack_record_to_local(Type *ty, int src, int dst) {
    int i = 0;
    for (; i + 8 <= ty->size; i += 8) {
        printf("  mov %d(%%rbp), %%r10\n", src + i);
        printf("  mov %%r10, %d(%%rbp)\n", dst + i);
    }
    if (i + 4 <= ty->size) {
        printf("  mov %d(%%rbp), %%r10d\n", src + i);
        printf("  mov %%r10d, %d(%%rbp)\n", dst + i);
        i += 4;
    }
    if (i + 2 <= ty->size) {
        printf("  mov %d(%%rbp), %%r10w\n", src + i);
        printf("  mov %%r10w, %d(%%rbp)\n", dst + i);
        i += 2;
    }
    if (i < ty->size) {
        printf("  mov %d(%%rbp), %%r10b\n", src + i);
        printf("  mov %%r10b, %d(%%rbp)\n", dst + i);
    }
}

static void save_record_parameter(Obj *var, int *gp, int *fp, int *stack_arg) {
    RecordAbi abi = require_record_abi(var->ty);
    if (abi.memory) {
        int src = 16 + *stack_arg * 8;
        copy_stack_record_to_local(var->ty, src, var->offset);
        *stack_arg += abi.slots;
        return;
    }

    if (*gp + abi.gp <= 6 && *fp + abi.fp <= 8) {
        int g = *gp;
        int f = *fp;
        for (int i = 0; i < abi.slots; i++) {
            int bytes = var->ty->size - i * 8;
            if (bytes > 8)
                bytes = 8;
            if (abi.classes[i] == SYSV_ABI_INTEGER)
                store_register_bytes_to_local(argreg64[g++], var->offset + i * 8, bytes);
            else
                store_sse_bytes_to_local(f++, var->offset + i * 8, bytes);
        }
        *gp += abi.gp;
        *fp += abi.fp;
        return;
    }

    // A small aggregate also reverts entirely to memory if either required
    // register class is short; do not consume the other class partially.
    int src = 16 + *stack_arg * 8;
    copy_stack_record_to_local(var->ty, src, var->offset);
    *stack_arg += abi.slots;
}

// Load exactly `bytes` little-endian bytes from the record address in R10 into
// one GP register. Partial eightbytes are built bytewise so no read crosses the
// source object's bounds.
static void load_record_bytes_to_reg(int offset, int bytes,
                                     const char *dst64, const char *dst32) {
    if (bytes == 8) {
        printf("  mov %d(%%r10), %s\n", offset, dst64);
        return;
    }

    printf("  xor %s, %s\n", dst32, dst32);
    for (int i = bytes - 1; i >= 0; i--) {
        if (i != bytes - 1)
            printf("  shl $8, %s\n", dst64);
        printf("  movzbq %d(%%r10), %%rcx\n", offset + i);
        printf("  or %%rcx, %s\n", dst64);
    }
}

static void emit_memory_record_return(Type *ty) {
    if (!current_fn_obj || !current_fn_obj->sret_offset)
        error("missing hidden record return pointer");

    // Source aggregate address arrives in RAX. The incoming hidden destination
    // was saved in the frame because arbitrary expressions/calls may clobber RDI.
    printf("  mov %%rax, %%r10\n");
    printf("  mov %d(%%rbp), %%r11\n", current_fn_obj->sret_offset);

    int i = 0;
    for (; i + 8 <= ty->size; i += 8) {
        printf("  mov %d(%%r10), %%rcx\n", i);
        printf("  mov %%rcx, %d(%%r11)\n", i);
    }
    if (i + 4 <= ty->size) {
        printf("  mov %d(%%r10), %%ecx\n", i);
        printf("  mov %%ecx, %d(%%r11)\n", i);
        i += 4;
    }
    if (i + 2 <= ty->size) {
        printf("  mov %d(%%r10), %%cx\n", i);
        printf("  mov %%cx, %d(%%r11)\n", i);
        i += 2;
    }
    if (i < ty->size) {
        printf("  mov %d(%%r10), %%cl\n", i);
        printf("  mov %%cl, %d(%%r11)\n", i);
    }

    // SysV requires MEMORY-returning functions to also return the destination
    // address in RAX.
    printf("  mov %%r11, %%rax\n");
}

static void emit_record_return(Type *ty) {
    RecordAbi abi = require_record_abi(ty);
    if (abi.memory) {
        emit_memory_record_return(ty);
        return;
    }

    static const char *gp64[] = {"%rax", "%rdx"};
    static const char *gp32[] = {"%eax", "%edx"};
    int g = 0;
    int f = 0;

    printf("  mov %%rax, %%r10\n");
    for (int i = 0; i < abi.slots; i++) {
        int bytes = ty->size - i * 8;
        if (bytes > 8)
            bytes = 8;
        if (abi.classes[i] == SYSV_ABI_INTEGER) {
            load_record_bytes_to_reg(i * 8, bytes, gp64[g], gp32[g]);
            g++;
        } else {
            load_record_bytes_to_reg(i * 8, bytes, "%r11", "%r11d");
            printf("  movq %%r11, %%xmm%d\n", f++);
        }
    }
}

static void materialize_record_call(Node *node) {
    RecordAbi abi = require_record_abi(node->ty);
    if (!node->ret_buffer)
        error("missing record call return buffer");

    if (abi.memory) {
        // The callee wrote directly into this hidden destination.
        printf("  lea %d(%%rbp), %%rax\n", node->ret_buffer->offset);
        return;
    }

    static const char *gp64[] = {"%rax", "%rdx"};
    int g = 0;
    int f = 0;
    for (int i = 0; i < abi.slots; i++) {
        int bytes = node->ty->size - i * 8;
        if (bytes > 8)
            bytes = 8;
        if (abi.classes[i] == SYSV_ABI_INTEGER)
            store_register_bytes_to_local(gp64[g++], node->ret_buffer->offset + i * 8, bytes);
        else
            store_sse_bytes_to_local(f++, node->ret_buffer->offset + i * 8, bytes);
    }
    printf("  lea %d(%%rbp), %%rax\n", node->ret_buffer->offset);
}

// Generate a function call (direct or indirect via function pointer). Small
// records draw independently from GP/SSE pools; MEMORY records always use the
// stack. A MEMORY return reserves RDI for the hidden caller-owned destination.
static void gen_funcall(Node *node) {
    bool indirect = (node->funcname == NULL);
    bool memory_return = node->ty && node->ty->kind == TY_STRUCT &&
                         sysv_record_is_memory(node->ty);

    if (indirect) {
        gen_expr(node->lhs);
        push(); // function address remains above the argument spills
    }

    Node *args[32];
    bool fp_arg[32];
    bool ld_arg[32];
    bool record_arg[32];
    bool stack_arg[32];
    int abi_slot[32];
    int record_gp_base[32];
    int record_fp_base[32];
    SysVAbiClass record_classes[32][2];
    int stack_slot[32];
    int spill_before[32];
    int spill_slots[32];
    int nargs = 0;
    int gp_count = memory_return ? 1 : 0;
    int fp_count = 0;
    int stack_count = 0;
    int total_spill_slots = 0;

    for (Node *arg = node->args; arg; arg = arg->next) {
        if (nargs >= 32)
            error("too many arguments");
        add_type(arg);
        args[nargs] = arg;
        record_arg[nargs] = arg->ty && arg->ty->kind == TY_STRUCT;
        ld_arg[nargs] = !record_arg[nargs] && arg->ty && arg->ty->kind == TY_LDOUBLE;
        fp_arg[nargs] = !record_arg[nargs] && !ld_arg[nargs] && is_flonum(arg->ty);
        stack_arg[nargs] = false;
        spill_before[nargs] = total_spill_slots;

        if (record_arg[nargs]) {
            RecordAbi abi = require_record_abi(arg->ty);
            spill_slots[nargs] = abi.slots;
            if (abi.memory) {
                stack_arg[nargs] = true;
                stack_slot[nargs] = stack_count;
                stack_count += abi.slots;
            } else {
                for (int j = 0; j < abi.slots; j++)
                    record_classes[nargs][j] = abi.classes[j];

                if (gp_count + abi.gp <= 6 && fp_count + abi.fp <= 8) {
                    record_gp_base[nargs] = gp_count;
                    record_fp_base[nargs] = fp_count;
                    gp_count += abi.gp;
                    fp_count += abi.fp;
                } else {
                    stack_arg[nargs] = true;
                    stack_slot[nargs] = stack_count;
                    stack_count += abi.slots;
                }
            }
        } else if (ld_arg[nargs]) {
            spill_slots[nargs] = 2;
            if (stack_count & 1)
                stack_count++;
            stack_arg[nargs] = true;
            stack_slot[nargs] = stack_count;
            stack_count += 2;
        } else if (fp_arg[nargs]) {
            spill_slots[nargs] = 1;
            if (fp_count < 8)
                abi_slot[nargs] = fp_count++;
            else {
                stack_arg[nargs] = true;
                stack_slot[nargs] = stack_count++;
            }
        } else {
            spill_slots[nargs] = 1;
            if (gp_count < 6)
                abi_slot[nargs] = gp_count++;
            else {
                stack_arg[nargs] = true;
                stack_slot[nargs] = stack_count++;
            }
        }

        gen_expr(arg);
        if (record_arg[nargs])
            push_record_value(arg->ty);
        else if (fp_arg[nargs] || ld_arg[nargs])
            pushf(arg->ty);
        else
            push();

        total_spill_slots += spill_slots[nargs];
        nargs++;
    }

    printf("  mov %%rsp, %%r11\n");

    for (int i = 0; i < nargs; i++) {
        if (stack_arg[i])
            continue;
        int src = (total_spill_slots - spill_before[i] - spill_slots[i]) * 8;
        if (record_arg[i]) {
            int g = record_gp_base[i];
            int f = record_fp_base[i];
            for (int j = 0; j < spill_slots[i]; j++) {
                if (record_classes[i][j] == SYSV_ABI_INTEGER)
                    printf("  mov %d(%%r11), %s\n", src + j * 8, argreg64[g++]);
                else
                    printf("  movq %d(%%r11), %%xmm%d\n", src + j * 8, f++);
            }
        } else if (fp_arg[i]) {
            if (args[i]->ty->kind == TY_FLOAT)
                printf("  movss %d(%%r11), %%xmm%d\n", src, abi_slot[i]);
            else
                printf("  movsd %d(%%r11), %%xmm%d\n", src, abi_slot[i]);
        } else {
            printf("  mov %d(%%r11), %s\n", src, argreg64[abi_slot[i]]);
        }
    }

    if (indirect)
        printf("  mov %d(%%r11), %%r10\n", total_spill_slots * 8);

    // Keep alignment padding above the stack argument area, preserving the
    // first stack-passed argument at 0(%rsp) immediately before call.
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
            int src = (total_spill_slots - spill_before[i] - spill_slots[i]) * 8;
            int dst = stack_slot[i] * 8;
            for (int j = 0; j < spill_slots[i]; j++) {
                printf("  mov %d(%%r11), %%rax\n", src + j * 8);
                printf("  mov %%rax, %d(%%rsp)\n", dst + j * 8);
            }
        }
    }

    if (memory_return) {
        if (!node->ret_buffer)
            error("missing MEMORY record return buffer");
        printf("  lea %d(%%rbp), %%rdi\n", node->ret_buffer->offset);
    }

    // For variadic calls AL counts every XMM register used by named/unnamed
    // scalar or small-record arguments. MEMORY records contribute no XMM regs.
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

    int spill_count = total_spill_slots + (indirect ? 1 : 0);
    if (spill_count) {
        printf("  add $%d, %%rsp\n", spill_count * 8);
        depth -= spill_count;
    }

    // SysV places scalar integer return values in the low part of RAX. For
    // types narrower than 64 bits the remaining bits are not a C value and
    // must be interpreted according to the declared return type at the call
    // site. Canonicalize signed/unsigned bool/char/short/int exactly as loads
    // and casts do before any enclosing expression consumes the result.
    if (node->ty && node->ty->kind != TY_STRUCT)
        normalize(node->ty);

    if (node->ty && node->ty->kind == TY_STRUCT)
        materialize_record_call(node);
}

// Copy one low eightbyte from the variadic register-save area into a
// record result local. Only bytes belonging to the C object are stored.
static void copy_va_register_slot_to_local(const char *index_reg,
                                           int dst, int bytes) {
    printf("  mov (%%rdx,%s), %%r10\n", index_reg);
    store_register_bytes_to_local("%r10", dst, bytes);
}

static void copy_va_stack_record_to_local(Type *ty, int dst) {
    int slots = (ty->size + 7) / 8;
    for (int i = 0; i < slots; i++) {
        int bytes = ty->size - i * 8;
        if (bytes > 8)
            bytes = 8;
        printf("  mov %d(%%rdx), %%r10\n", i * 8);
        store_register_bytes_to_local("%r10", dst + i * 8, bytes);
    }
}

// Aggregate va_arg mirrors the ordinary SysV classifier. Small records consume
// independent GP/SSE save slots only when every required class is available;
// otherwise the whole value comes from overflow_arg_area. MEMORY records always
// come from overflow_arg_area and do not consume either register cursor.
static void gen_record_va_arg(Node *node) {
    RecordAbi abi = require_record_abi(node->ty);
    if (!node->ret_buffer)
        error("missing record va_arg materialization buffer");

    gen_expr(node->lhs);
    printf("  mov %%rax, %%rdi\n");
    int c = count();

    if (!abi.memory) {
        if (abi.gp) {
            printf("  mov 0(%%rdi), %%eax\n");
            printf("  cmp $%d, %%eax\n", 48 - abi.gp * 8);
            printf("  ja .L.va_record_stack.%d\n", c);
        }
        if (abi.fp) {
            printf("  mov 4(%%rdi), %%eax\n");
            printf("  cmp $%d, %%eax\n", 176 - abi.fp * 16);
            printf("  ja .L.va_record_stack.%d\n", c);
        }

        printf("  mov 0(%%rdi), %%esi\n");
        printf("  mov 4(%%rdi), %%ecx\n");
        printf("  mov 16(%%rdi), %%rdx\n");
        for (int i = 0; i < abi.slots; i++) {
            int bytes = node->ty->size - i * 8;
            if (bytes > 8)
                bytes = 8;
            if (abi.classes[i] == SYSV_ABI_INTEGER) {
                copy_va_register_slot_to_local("%rsi", node->ret_buffer->offset + i * 8, bytes);
                printf("  add $8, %%esi\n");
            } else if (abi.classes[i] == SYSV_ABI_SSE) {
                copy_va_register_slot_to_local("%rcx", node->ret_buffer->offset + i * 8, bytes);
                printf("  add $16, %%ecx\n");
            } else {
                error("invalid SysV record class in va_arg");
            }
        }
        if (abi.gp)
            printf("  mov %%esi, 0(%%rdi)\n");
        if (abi.fp)
            printf("  mov %%ecx, 4(%%rdi)\n");
        printf("  lea %d(%%rbp), %%rax\n", node->ret_buffer->offset);
        printf("  jmp .L.va_record_end.%d\n", c);
    }

    printf(".L.va_record_stack.%d:\n", c);
    printf("  mov 8(%%rdi), %%rdx\n");
    if (node->ty->align > 8) {
        printf("  add $%d, %%rdx\n", node->ty->align - 1);
        printf("  and $-%d, %%rdx\n", node->ty->align);
    }
    copy_va_stack_record_to_local(node->ty, node->ret_buffer->offset);
    printf("  add $%d, %%rdx\n", abi.slots * 8);
    printf("  mov %%rdx, 8(%%rdi)\n");
    printf("  lea %d(%%rbp), %%rax\n", node->ret_buffer->offset);
    printf(".L.va_record_end.%d:\n", c);
}

static void gen_expr(Node *node) {
    if (node->kind == ND_NUM) {
        if (node->ty && node->ty->kind == TY_LDOUBLE) {
            unsigned char raw[16] = {0};
            memcpy(raw, &node->ldval, 10);
            printf("  sub $16, %%rsp\n");
            for (int i = 0; i < 16; i++)
                printf("  movb $%u, %d(%%rsp)\n", raw[i], i);
            printf("  fldt (%%rsp)\n");
            printf("  add $16, %%rsp\n");
            return;
        }
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

    if (node->kind == ND_VAR || node->kind == ND_COMPOUND_LITERAL) {
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
            load_lvalue(node);
        return;
    }

    if (node->kind == ND_VA_START) {
        if (!current_fn_obj || !current_fn_obj->is_variadic)
            error("va_start outside variadic function");
        gen_expr(node->lhs); // RAX = &va_list
        printf("  movl $%d, 0(%%rax)\n", current_fn_obj->va_gp_offset);
        printf("  movl $%d, 4(%%rax)\n", current_fn_obj->va_fp_offset);
        printf("  lea %d(%%rbp), %%rdx\n", current_fn_obj->va_stack_offset);
        printf("  mov %%rdx, 8(%%rax)\n");
        printf("  lea %d(%%rbp), %%rdx\n", current_fn_obj->va_offset);
        printf("  mov %%rdx, 16(%%rax)\n");
        return;
    }

    if (node->kind == ND_VA_ARG) {
        if (node->ty->kind == TY_STRUCT) {
            gen_record_va_arg(node);
            return;
        }

        gen_expr(node->lhs); // RAX = &va_list
        printf("  mov %%rax, %%rdi\n");
        int c = count();

        if (node->ty->kind == TY_LDOUBLE) {
            printf("  mov 8(%%rdi), %%rdx\n");
            printf("  add $15, %%rdx\n");
            printf("  and $-16, %%rdx\n");
            printf("  fldt (%%rdx)\n");
            printf("  add $16, %%rdx\n");
            printf("  mov %%rdx, 8(%%rdi)\n");
            return;
        }

        if (node->ty->kind == TY_DOUBLE) {
            printf("  mov 4(%%rdi), %%eax\n");
            printf("  cmp $176, %%eax\n");
            printf("  jae .L.va_fp_stack.%d\n", c);
            printf("  mov 16(%%rdi), %%rdx\n");
            printf("  movsd (%%rdx,%%rax), %%xmm0\n");
            printf("  add $16, %%eax\n");
            printf("  mov %%eax, 4(%%rdi)\n");
            printf("  jmp .L.va_end.%d\n", c);
            printf(".L.va_fp_stack.%d:\n", c);
            printf("  mov 8(%%rdi), %%rdx\n");
            printf("  movsd (%%rdx), %%xmm0\n");
            printf("  add $8, %%rdx\n");
            printf("  mov %%rdx, 8(%%rdi)\n");
            printf(".L.va_end.%d:\n", c);
            return;
        }

        printf("  mov 0(%%rdi), %%eax\n");
        printf("  cmp $48, %%eax\n");
        printf("  jae .L.va_gp_stack.%d\n", c);
        printf("  mov 16(%%rdi), %%rdx\n");
        printf("  mov %%eax, %%ecx\n");
        printf("  add $8, %%ecx\n");
        printf("  mov %%ecx, 0(%%rdi)\n");
        printf("  mov (%%rdx,%%rax), %%rax\n");
        printf("  jmp .L.va_gp_end.%d\n", c);
        printf(".L.va_gp_stack.%d:\n", c);
        printf("  mov 8(%%rdi), %%rdx\n");
        printf("  mov (%%rdx), %%rax\n");
        printf("  add $8, %%rdx\n");
        printf("  mov %%rdx, 8(%%rdi)\n");
        printf(".L.va_gp_end.%d:\n", c);
        if (is_integer(node->ty))
            normalize(node->ty);
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
        store_lvalue(node->lhs);
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

    if (node->kind == ND_POS) {
        gen_expr(node->lhs);
        if (is_integer(node->ty))
            normalize(node->ty);
        return;
    }

    if (node->kind == ND_NEG) {
        gen_expr(node->lhs);
        if (node->ty->kind == TY_LDOUBLE) {
            printf("  fchs\n");
        } else if (node->ty->kind == TY_FLOAT) {
            printf("  mov $0x80000000, %%eax\n");
            printf("  movd %%eax, %%xmm1\n");
            printf("  xorps %%xmm1, %%xmm0\n");
        } else if (node->ty->kind == TY_DOUBLE) {
            printf("  movabs $0x8000000000000000, %%rax\n");
            printf("  movq %%rax, %%xmm1\n");
            printf("  xorpd %%xmm1, %%xmm0\n");
        } else {
            printf("  neg %%rax\n");
            if (is_integer(node->ty))
                normalize(node->ty);
        }
        return;
    }

    if (node->kind == ND_BITNOT) {
        gen_expr(node->lhs);
        printf("  not %%rax\n");
        normalize(node->ty);
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
        common = get_common_type_for_nodes(node->lhs, node->rhs);

    if (common && common->kind == TY_LDOUBLE) {
        gen_expr(node->rhs);
        cast_value(node->rhs->ty, common);
        pushf(common);
        gen_expr(node->lhs);
        cast_value(node->lhs->ty, common);
        printf("  fldt (%%rsp)\n");
        printf("  add $16, %%rsp\n");
        depth -= 2;

        if (comparison) {
            // ST0=rhs, ST1=lhs. Compare lhs against rhs and consume both.
            printf("  fxch %%st(1)\n");
            printf("  fucomip %%st(1), %%st\n");
            printf("  fstp %%st(0)\n");
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

        if (node->kind == ND_ADD) printf("  faddp %%st, %%st(1)\n");
        else if (node->kind == ND_MUL) printf("  fmulp %%st, %%st(1)\n");
        else if (node->kind == ND_SUB) printf("  fsubrp %%st, %%st(1)\n");
        else if (node->kind == ND_DIV) printf("  fdivrp %%st, %%st(1)\n");
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
    if (node->kind == ND_VLA_SAVE) {
        printf("  mov %%rsp, %d(%%rbp)\n", node->var->offset);
        return;
    }

    if (node->kind == ND_VLA_ALLOC) {
        if (!node->var || !node->var->vla_size)
            error("invalid VLA allocation metadata");
        // The backend supports object alignments through 16 bytes. Rounding
        // each dynamic allocation to 16 also keeps SysV call alignment stable.
        printf("  mov %d(%%rbp), %%rax\n", node->var->vla_size->offset);
        printf("  add $15, %%rax\n");
        printf("  and $-16, %%rax\n");
        printf("  sub %%rax, %%rsp\n");
        printf("  mov %%rsp, %d(%%rbp)\n", node->var->offset);
        return;
    }

    if (node->kind == ND_VLA_RESTORE) {
        printf("  mov %d(%%rbp), %%rsp\n", node->var->offset);
        return;
    }

    if (node->kind == ND_RETURN) {
        if (node->lhs) {
            gen_expr(node->lhs);
            if (current_return_ty && current_return_ty->kind == TY_STRUCT)
                emit_record_return(current_return_ty);
            else
                cast_value(node->lhs->ty, current_return_ty);
        }
        printf("  jmp .L.return.%s\n", current_fn);
        return;
    }

    if (node->kind == ND_BREAK) {
        if (!brk_label) error("break outside loop");
        if (node->var)
            printf("  mov %d(%%rbp), %%rsp\n", node->var->offset);
        printf("  jmp %s\n", brk_label);
        return;
    }

    if (node->kind == ND_CONTINUE) {
        if (!cnt_label) error("continue outside loop");
        if (node->var)
            printf("  mov %d(%%rbp), %%rsp\n", node->var->offset);
        printf("  jmp %s\n", cnt_label);
        return;
    }

    if (node->kind == ND_GOTO) {
        if (node->var)
            printf("  mov %d(%%rbp), %%rsp\n", node->var->offset);
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
        if (node->var)
            printf("  mov %d(%%rbp), %%rsp\n", node->var->offset);

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

// File-scope and block-static objects must begin at an address satisfying their
// declared type alignment. GAS data directives do not implicitly realign the
// location counter, so a one-byte object emitted immediately before a long,
// pointer, double or record would otherwise leave the later symbol misaligned.
static void emit_data_alignment(Obj *var) {
    int align = var->align > 0 ? var->align
                               : (var->ty && var->ty->align > 0 ? var->ty->align : 1);
    if (align > 1)
        printf("  .balign %d\n", align);
}

static void emit_object_section(Obj *var, bool initialized) {
    if (var->is_thread_local) {
        if (initialized)
            printf("  .section .tdata,\"awT\",@progbits\n");
        else
            printf("  .section .tbss,\"awT\",@nobits\n");
        return;
    }
    printf("  .data\n");
}

static void assign_lvar_offsets(Program *prog) {
    for (Function *fn = prog->fns; fn; fn = fn->next) {
        int offset = 0;

        if (fn->is_variadic) {
            // SysV AMD64 register_save_area: 6 GP slots followed by 8 16-byte
            // SSE slots. RBP is 16-byte aligned here, so -176 is aligned too.
            offset = 176;
            fn->va_offset = -offset;
        }

        if (fn->return_ty && sysv_record_is_memory(fn->return_ty)) {
            offset += 8;
            offset = align_up_cg(offset, 8);
            fn->sret_offset = -offset;
        }

        for (Obj *var = fn->locals; var; var = var->next) {
            int align = var->is_vla ? 8
                                    : (var->align > 0 ? var->align
                                       : (var->ty->align > 0 ? var->ty->align : 1));
            int size = var->is_vla ? 8 : var->ty->size;
            offset += size;
            offset = align_up_cg(offset, align);
            var->offset = -offset;
        }

        if (fn->is_variadic) {
            int gp = fn->return_ty && sysv_record_is_memory(fn->return_ty) ? 1 : 0;
            int fp = 0;
            int stack_arg = 0;
            for (Obj *p = fn->params; p; p = p->param_next) {
                if (p->ty->kind == TY_STRUCT) {
                    RecordAbi abi = require_record_abi(p->ty);
                    if (abi.memory) {
                        stack_arg += abi.slots;
                    } else if (gp + abi.gp <= 6 && fp + abi.fp <= 8) {
                        gp += abi.gp;
                        fp += abi.fp;
                    } else {
                        stack_arg += abi.slots;
                    }
                } else if (p->ty->kind == TY_LDOUBLE) {
                    if (stack_arg & 1)
                        stack_arg++;
                    stack_arg += 2;
                } else if (is_flonum(p->ty)) {
                    if (fp < 8)
                        fp++;
                    else
                        stack_arg++;
                } else {
                    if (gp < 6)
                        gp++;
                    else
                        stack_arg++;
                }
            }
            fn->va_gp_offset = gp * 8;
            fn->va_fp_offset = 48 + fp * 16;
            fn->va_stack_offset = 16 + stack_arg * 8;
        }

        fn->stack_size = align_up_cg(offset, 16);
    }
}

static void emit_data(Program *prog) {
    for (Obj *var = prog->globals; var; var = var->next) {
        if (var->is_function) continue; // function symbols don't need storage
        if (var->is_extern) continue;   // extern declarations don't allocate

        if (var->init_image) {
            emit_object_section(var, true);
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            emit_data_alignment(var);
            printf("%s:\n", var->name);

            for (int off = 0; off < var->init_image_size;) {
                Relocation *found = NULL;
                for (Relocation *rel = var->init_relocs; rel; rel = rel->next) {
                    if (rel->offset == off) {
                        found = rel;
                        break;
                    }
                }

                if (found) {
                    if (found->addend > 0)
                        printf("  .quad %s+%" PRId64 "\n", found->label, found->addend);
                    else if (found->addend < 0)
                        printf("  .quad %s%" PRId64 "\n", found->label, found->addend);
                    else
                        printf("  .quad %s\n", found->label);
                    off += 8;
                    continue;
                }

                printf("  .byte %u\n", (unsigned char)var->init_image[off]);
                off++;
            }
            if (var->init_image_size < var->ty->size)
                printf("  .zero %d\n", var->ty->size - var->init_image_size);
        } else if (var->init_data) {
            if (var->is_string_literal)
                printf("  .section .rodata\n");
            else {
                emit_object_section(var, true);
                if (!var->is_static)
                    printf("  .globl %s\n", var->name);
            }
            emit_data_alignment(var);
            printf("%s:\n", var->name);
            for (int i = 0; i < var->ty->array_len; i++)
                printf("  .byte %d\n", (unsigned char)var->init_data[i]);
        } else if (var->init_vals) {
            emit_object_section(var, true);
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            emit_data_alignment(var);
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
        } else if (var->has_init_reloc) {
            emit_object_section(var, true);
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            emit_data_alignment(var);
            printf("%s:\n", var->name);
            if (var->init_reloc_addend > 0)
                printf("  .quad %s+%" PRId64 "\n", var->init_reloc_label,
                       var->init_reloc_addend);
            else if (var->init_reloc_addend < 0)
                printf("  .quad %s%" PRId64 "\n", var->init_reloc_label,
                       var->init_reloc_addend);
            else
                printf("  .quad %s\n", var->init_reloc_label);
        } else if (var->has_init_val) {
            emit_object_section(var, true);
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            emit_data_alignment(var);
            printf("%s:\n", var->name);
            if (var->ty->kind == TY_FLOAT) {
                union { float f; uint32_t u; } u = { (float)var->finit_val };
                printf("  .long %" PRIu32 "\n", u.u);
            } else if (var->ty->kind == TY_DOUBLE) {
                union { double d; uint64_t u; } u = { var->finit_val };
                printf("  .quad %" PRIu64 "\n", u.u);
            } else if (var->ty->kind == TY_LDOUBLE) {
                unsigned char raw[16] = {0};
                memcpy(raw, &var->ldinit_val, 10);
                for (int i = 0; i < 16; i++)
                    printf("  .byte %u\n", raw[i]);
            } else if (var->ty->size == 1)
                printf("  .byte %" PRId64 "\n", var->init_val);
            else if (var->ty->size == 2)
                printf("  .short %" PRId64 "\n", var->init_val);
            else if (var->ty->size == 4)
                printf("  .long %" PRId64 "\n", var->init_val);
            else
                printf("  .quad %" PRId64 "\n", var->init_val);
        } else {
            emit_object_section(var, false);
            if (!var->is_static)
                printf("  .globl %s\n", var->name);
            emit_data_alignment(var);
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
        current_fn_obj = fn;
        current_return_ty = fn->return_ty;
        if (fn->return_ty && fn->return_ty->kind == TY_STRUCT)
            require_record_abi(fn->return_ty);

        // Prologue
        printf("  push %%rbp\n");
        printf("  mov %%rsp, %%rbp\n");
        printf("  sub $%d, %%rsp\n", fn->stack_size);

        if (fn->return_ty && sysv_record_is_memory(fn->return_ty))
            printf("  mov %%rdi, %d(%%rbp)\n", fn->sret_offset);

        if (fn->is_variadic) {
            printf("  mov %%rdi, %d(%%rbp)\n", fn->va_offset + 0);
            printf("  mov %%rsi, %d(%%rbp)\n", fn->va_offset + 8);
            printf("  mov %%rdx, %d(%%rbp)\n", fn->va_offset + 16);
            printf("  mov %%rcx, %d(%%rbp)\n", fn->va_offset + 24);
            printf("  mov %%r8,  %d(%%rbp)\n", fn->va_offset + 32);
            printf("  mov %%r9,  %d(%%rbp)\n", fn->va_offset + 40);
            for (int i = 0; i < 8; i++)
                printf("  movaps %%xmm%d, %d(%%rbp)\n", i, fn->va_offset + 48 + i * 16);
        }

        // Save named parameters to ordinary local slots. GP and SSE register
        // numbers advance independently, with a shared source-order stack area.
        int gp = fn->return_ty && sysv_record_is_memory(fn->return_ty) ? 1 : 0;
        int fp = 0;
        int stack_arg = 0;
        for (Obj *var = fn->params; var; var = var->param_next) {
            if (var->ty->kind == TY_STRUCT) {
                save_record_parameter(var, &gp, &fp, &stack_arg);
                continue;
            }
            if (var->ty->kind == TY_LDOUBLE) {
                if (stack_arg & 1)
                    stack_arg++;
                int src = 16 + stack_arg * 8;
                printf("  mov %d(%%rbp), %%rax\n", src);
                printf("  mov %%rax, %d(%%rbp)\n", var->offset);
                printf("  mov %d(%%rbp), %%rax\n", src + 8);
                printf("  mov %%rax, %d(%%rbp)\n", var->offset + 8);
                stack_arg += 2;
                continue;
            }
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

    // GNU/ELF linkers treat an input object without this marker as potentially
    // requiring an executable stack. Generated C code never needs one, so emit
    // the conventional empty note section explicitly.
    printf("  .section .note.GNU-stack,\"\",@progbits\n");
}
