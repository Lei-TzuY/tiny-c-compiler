from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1))


# Public ABI metadata: <=16-byte records are register-classified, while larger
# complete records use the SysV MEMORY class.
replace_once(
    "minicc.h",
    "int sysv_classify_record(Type *ty, SysVAbiClass classes[2]);\n",
    "int sysv_classify_record(Type *ty, SysVAbiClass classes[2]);\n"
    "bool sysv_record_is_memory(Type *ty);\n",
)
replace_once(
    "minicc.h",
    "    int stack_size;\n    bool is_static;\n",
    "    int stack_size;\n"
    "    int sret_offset;    // saved hidden SysV MEMORY-return pointer, relative to RBP\n"
    "    bool is_static;\n",
)

# Extend the shared classifier with an explicit MEMORY predicate.  The existing
# per-eightbyte classifier remains the authority for <=16-byte INTEGER/SSE data.
p = Path("type.c")
text = p.read_text()
start = text.index("// SysV AMD64 classifies records up to two eightbytes independently.")
end = text.index("Type *qualify_type(Type *ty, bool is_const, bool is_volatile) {", start)
new_type_block = r'''// SysV AMD64 classifies records up to two eightbytes independently.  This
// compiler's scalar type system needs only INTEGER and SSE classes: integers and
// pointers contribute INTEGER, float/double contribute SSE, and overlapping
// union/subobject contributions merge with INTEGER taking precedence over SSE.
// Complete records larger than two eightbytes are MEMORY-class.
static SysVAbiClass merge_sysv_class(SysVAbiClass a, SysVAbiClass b) {
    if (a == SYSV_ABI_NONE)
        return b;
    if (b == SYSV_ABI_NONE)
        return a;
    if (a == SYSV_ABI_INTEGER || b == SYSV_ABI_INTEGER)
        return SYSV_ABI_INTEGER;
    return SYSV_ABI_SSE;
}

static bool classify_sysv_type(Type *ty, int offset, SysVAbiClass classes[2]) {
    if (!ty || ty->size <= 0)
        return false;

    if (ty->kind == TY_ARRAY) {
        if (ty->array_len <= 0 || !ty->base)
            return false;
        for (int i = 0; i < ty->array_len; i++)
            if (!classify_sysv_type(ty->base, offset + i * ty->base->size, classes))
                return false;
        return true;
    }

    if (ty->kind == TY_STRUCT) {
        if (ty->is_incomplete || !ty->members)
            return false;
        for (Member *m = ty->members; m; m = m->next)
            if (!classify_sysv_type(m->ty, offset + m->offset, classes))
                return false;
        return true;
    }

    SysVAbiClass cls;
    if (is_integer(ty) || ty->kind == TY_PTR)
        cls = SYSV_ABI_INTEGER;
    else if (is_flonum(ty))
        cls = SYSV_ABI_SSE;
    else
        return false;

    int first = offset / 8;
    int last = (offset + ty->size - 1) / 8;
    if (first < 0 || last >= 2)
        return false;
    for (int i = first; i <= last; i++)
        classes[i] = merge_sysv_class(classes[i], cls);
    return true;
}

int sysv_classify_record(Type *ty, SysVAbiClass classes[2]) {
    classes[0] = SYSV_ABI_NONE;
    classes[1] = SYSV_ABI_NONE;

    if (!ty || ty->kind != TY_STRUCT || ty->is_incomplete ||
        ty->size <= 0 || ty->size > 16)
        return 0;
    if (!classify_sysv_type(ty, 0, classes))
        return 0;

    int slots = (ty->size + 7) / 8;
    for (int i = 0; i < slots; i++)
        if (classes[i] == SYSV_ABI_NONE)
            return 0;
    return slots;
}

bool sysv_record_is_memory(Type *ty) {
    return ty && ty->kind == TY_STRUCT && !ty->is_incomplete && ty->size > 16;
}

'''
p.write_text(text[:start] + new_type_block + text[end:])

# Semantic ABI gate now admits both register-classified and MEMORY-class records.
replace_once(
    "parse.c",
    "static bool supported_record_abi(Type *ty) {\n"
    "    SysVAbiClass classes[2];\n"
    "    return ty && ty->kind == TY_STRUCT && sysv_classify_record(ty, classes) > 0;\n"
    "}\n",
    "static bool supported_record_abi(Type *ty) {\n"
    "    SysVAbiClass classes[2];\n"
    "    return ty && ty->kind == TY_STRUCT &&\n"
    "           (sysv_record_is_memory(ty) || sysv_classify_record(ty, classes) > 0);\n"
    "}\n",
)
replace_once(
    "parse.c",
    "// Aggregate expressions are represented by an address in the backend. Small\n"
    "// records returned in INTEGER/SSE registers are therefore materialized into an\n"
    "// anonymous local immediately after the call, preserving ordinary record\n"
    "// expression behavior such as make().field and return-to-argument chaining.\n",
    "// Aggregate expressions are represented by an address in the backend. Every\n"
    "// by-value record call therefore owns an anonymous local result object: small\n"
    "// records are materialized from return registers, while MEMORY-class callees\n"
    "// receive that object's address directly as their hidden sret destination.\n",
)
replace_once(
    "parse.c",
    "// Keep the record-ABI firewall shape-aware: all naturally laid-out records up\n"
    "// to 16 bytes whose eightbytes classify as INTEGER/SSE are now lowered exactly.\n"
    "// Prototypes may still describe larger MEMORY-class records when never crossed.\n",
    "// Keep the record-ABI gate shape-aware: <=16-byte records use per-eightbyte\n"
    "// INTEGER/SSE lowering and larger complete records use the SysV MEMORY class.\n"
    "// Prototypes remain representable even before an ABI boundary is crossed.\n",
)

# Replace the record ABI/code-call lowering as one coherent block so register
# allocation, stack copies, sret, and materialization cannot drift independently.
p = Path("codegen.c")
text = p.read_text()
start = text.index("typedef struct {\n    int slots;\n    int gp;\n    int fp;\n    SysVAbiClass classes[2];\n} RecordAbi;")
end = text.index("static void gen_expr(Node *node) {", start)
new_codegen_block = r'''typedef struct {
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
        fp_arg[nargs] = !record_arg[nargs] && is_flonum(arg->ty);
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
        else if (fp_arg[nargs])
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

    if (node->ty && node->ty->kind == TY_STRUCT)
        materialize_record_call(node);
}

'''
p.write_text(text[:start] + new_codegen_block + text[end:])

# Frame layout and callee entry: MEMORY return consumes RDI, and named MEMORY
# parameters consume only positive stack slots.
p = Path("codegen.c")
text = p.read_text()
old = '''        if (fn->is_variadic) {
            // SysV AMD64 register_save_area: 6 GP slots followed by 8 16-byte
            // SSE slots. RBP is 16-byte aligned here, so -176 is aligned too.
            offset = 176;
            fn->va_offset = -offset;
        }

        for (Obj *var = fn->locals; var; var = var->next) {
'''
new = '''        if (fn->is_variadic) {
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
'''
if old not in text:
    raise SystemExit("assign_lvar_offsets prefix anchor missing")
text = text.replace(old, new, 1)
old = '''        if (fn->is_variadic) {
            int gp = 0;
            int fp = 0;
            int stack_arg = 0;
            for (Obj *p = fn->params; p; p = p->param_next) {
                if (p->ty->kind == TY_STRUCT) {
                    RecordAbi abi = require_record_abi(p->ty);
                    if (gp + abi.gp <= 6 && fp + abi.fp <= 8) {
                        gp += abi.gp;
                        fp += abi.fp;
                    } else {
                        stack_arg += abi.slots;
                    }
'''
new = '''        if (fn->is_variadic) {
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
'''
if old not in text:
    raise SystemExit("variadic layout anchor missing")
text = text.replace(old, new, 1)
old = '''        current_return_ty = fn->return_ty;
        if (fn->return_ty && fn->return_ty->kind == TY_STRUCT)
            require_record_abi(fn->return_ty);

        // Prologue
        printf("  push %%rbp\\n");
        printf("  mov %%rsp, %%rbp\\n");
        printf("  sub $%d, %%rsp\\n", fn->stack_size);

        if (fn->is_variadic) {
'''
new = '''        current_return_ty = fn->return_ty;
        if (fn->return_ty && fn->return_ty->kind == TY_STRUCT)
            require_record_abi(fn->return_ty);

        // Prologue
        printf("  push %%rbp\\n");
        printf("  mov %%rsp, %%rbp\\n");
        printf("  sub $%d, %%rsp\\n", fn->stack_size);

        if (fn->return_ty && sysv_record_is_memory(fn->return_ty))
            printf("  mov %%rdi, %d(%%rbp)\\n", fn->sret_offset);

        if (fn->is_variadic) {
'''
if old not in text:
    raise SystemExit("prologue sret anchor missing")
text = text.replace(old, new, 1)
old = '''        int gp = 0;
        int fp = 0;
        int stack_arg = 0;
'''
new = '''        int gp = fn->return_ty && sysv_record_is_memory(fn->return_ty) ? 1 : 0;
        int fp = 0;
        int stack_arg = 0;
'''
# This occurrence is the callee parameter-save counters after the variadic block;
# the earlier one was already rewritten above and no longer matches exactly.
if old not in text:
    raise SystemExit("callee gp counter anchor missing")
text = text.replace(old, new, 1)
p.write_text(text)

# Wire the focused MEMORY-class ABI regression suite.
replace_once(
    "Makefile",
    "\tbash ./test/sysv_sse_record_abi.sh\n",
    "\tbash ./test/sysv_sse_record_abi.sh\n\tbash ./test/sysv_memory_record_abi.sh\n",
)

# Advance old frontier tests: the previously rejected >16-byte cases are now
# positive ABI coverage; truly incomplete records are still rejected elsewhere.
p = Path("test/record_abi_firewall.sh")
text = p.read_text()
text = text.replace(
'''# Only true MEMORY-class record boundaries remain rejected in this scalar subset.
assert_fail 'struct Big{long a;long b;long c;};long f(struct Big x){return x.a;}int main(){return 0;}'
assert_fail 'struct Big{double a;double b;double c;};struct Big f(void){struct Big x={1.0,2.0,3.0};return x;}int main(){return 0;}'

# Unsupported prototypes remain representable if never crossed.
assert_run 0 'struct Big{double a;double b;double c;};struct Big ext(struct Big);int main(){return 0;}'
''',
'''# MEMORY-class records now cross real ABI boundaries too.
assert_run 7 'struct Big{long a;long b;long c;};long f(struct Big x){return x.a;}int main(){struct Big x={7,8,9};return f(x);}'
assert_run 0 'struct Big{double a;double b;double c;};struct Big f(void){struct Big x={1.0,2.0,3.0};return x;}int main(){struct Big x=f();return x.a+x.b+x.c==6.0?0:1;}'

# Large-record prototypes remain representable whether or not crossed.
assert_run 0 'struct Big{double a;double b;double c;};struct Big ext(struct Big);int main(){return 0;}'
''')
text = text.replace(
'''# Actual aggregate type still protects MEMORY-class unprototyped/variadic paths.
assert_fail 'struct Big{double a;double b;double c;};int f();int main(){struct Big x={1.0,2.0,3.0};return f(x);}'
assert_fail 'struct Big{double a;double b;double c;};int f(int,...);int main(){struct Big x={1.0,2.0,3.0};return f(1,x);}'
''',
'''# MEMORY-class actuals also work through unprototyped/variadic calls.
assert_run 0 'struct Big{double a;double b;double c;};int f(){return 0;}int main(){struct Big x={1.0,2.0,3.0};return f(x);}'
assert_run 0 'struct Big{double a;double b;double c;};int f(int n,...){return n;}int main(){struct Big x={1.0,2.0,3.0};return f(0,x);}'
''')
p.write_text(text)

p = Path("test/sysv_record_abi.sh")
text = p.read_text()
text = text.replace(
'''# Records larger than two eightbytes remain MEMORY-class and are diagnosed
# instead of silently treating an aggregate address as one scalar value.
assert_fail 'struct B{long a;long b;long c;};long f(struct B x){return x.a;}int main(){struct B x={1,2,3};return f(x);}'
assert_fail 'struct B{long a;long b;long c;};struct B make(){struct B x={1,2,3};return x;}int main(){return 0;}'
''',
'''# Larger records use the SysV MEMORY class; the dedicated suite exercises the
# full sret/stack protocol while these cases guard the former rejection frontier.
assert_run 0 'struct B{long a;long b;long c;};long f(struct B x){return x.a+x.b+x.c;}int main(){struct B x={10,12,20};return f(x)==42?0:1;}'
assert_run 0 'struct B{long a;long b;long c;};struct B make(){struct B x={10,12,20};return x;}int main(){struct B x=make();return x.a+x.b+x.c==42?0:1;}'
''')
p.write_text(text)

memory_test = r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-memory-record.c
  ./minicc tmp-memory-record.c > tmp-memory-record.s
  cc -o tmp-memory-record tmp-memory-record.s
  set +e
  ./tmp-memory-record
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "MEMORY record ABI failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(MEMORY record ABI): $actual"
}

# >16-byte records are passed as rounded stack objects and copied into callee
# locals, preserving ordinary by-value semantics.
assert_run 0 'struct B{long a,b,c;};long sum(struct B b){return b.a+b.b+b.c;}int main(){struct B b={10,12,20};return sum(b)==42?0:1;}'
assert_run 0 'struct M{double a;long b;double c;};double sum(struct M m){return m.a+m.b+m.c;}int main(){struct M m={10.0,12,20.0};return sum(m)==42.0?0:1;}'
assert_run 0 'union U{long v[3];double d[3];};long sum(union U u){return u.v[0]+u.v[1]+u.v[2];}int main(){union U u;u.v[0]=10;u.v[1]=12;u.v[2]=20;return sum(u)==42?0:1;}'

# MEMORY returns use a hidden RDI destination and remain address-valued after the
# call, so member access, assignment, and return-to-argument chaining work.
assert_run 0 'struct B{long a,b,c;};struct B make(long a,long b,long c){struct B x={a,b,c};return x;}int main(){struct B x=make(10,12,20);return x.a+x.b+x.c==42?0:1;}'
assert_run 0 'struct B{long a,b,c;};struct B make(){struct B x={10,12,20};return x;}int main(){return make().c==20?0:1;}'
assert_run 0 'struct B{long a,b,c;};struct B make(){struct B x={10,12,20};return x;}long sum(struct B x){return x.a+x.b+x.c;}int main(){return sum(make())==42?0:1;}'

# Hidden sret consumes the first GP register. Six user integer parameters prove
# the sixth moves to the caller stack while SSE arguments still use XMM registers.
assert_run 0 'struct B{long a,b,c;};struct B make(long a,long b,long c,long d,long e,long f){struct B x={a+b,c+d,e+f};return x;}int main(){struct B x=make(1,2,3,4,5,27);return x.a+x.b+x.c==42?0:1;}'
assert_run 0 'struct M{double a;long b;double c;};struct M make(double a,long b,double c){struct M x={a,b,c};return x;}int main(){struct M x=make(10.0,12,20.0);return x.a+x.b+x.c==42.0?0:1;}'

# MEMORY arguments consume no GP/SSE registers; later scalar parameters still
# use the register pools until those pools themselves are exhausted.
assert_run 0 'struct B{long a,b,c;};long f(long a,struct B x,long b,long c,long d,long e,long q,long z){return a+x.a+x.b+x.c+b+c+d+e+q+z;}int main(){struct B x={2,3,4};return f(1,x,5,6,7,8,1,5)==42?0:1;}'

# Indirect calls share the same hidden-sret and MEMORY-argument protocol.
assert_run 0 'struct B{long a,b,c;};struct B make(long a,long b,long c){struct B x={a,b,c};return x;}long sum(struct B x){return x.a+x.b+x.c;}int main(){struct B (*mk)(long,long,long)=make;long (*sm)(struct B)=sum;return sm(mk(10,12,20))==42?0:1;}'

# A named MEMORY parameter occupies stack slots before unnamed arguments. va_start
# must skip it while retaining the GP cursor for register-passed varargs.
assert_run 0 'include-placeholder'

# MEMORY-returning variadic functions start gp_offset after the hidden sret pointer
# and the named scalar argument.
assert_run 0 'include-placeholder-2'

# Minicc caller -> host GCC callee verifies stack-passed records, hidden sret,
# register shifting, mixed large records, and variadic MEMORY actuals.
cat > tmp-memory-host.c <<'EOF'
#include <stdarg.h>
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long host_sum(struct Big x){return x.a+x.b+x.c;}
struct Big host_make(long a,long b,long c,long d,long e,long f){struct Big x={a+b,c+d,e+f};return x;}
long host_after(long a,struct Big x,long b,long c,long d,long e,long q,long z){return a+x.a+x.b+x.c+b+c+d+e+q+z;}
struct Mix host_mix(double a,long b,double c){struct Mix x={a,b,c};return x;}
long host_var(int tag,...){va_list ap;va_start(ap,tag);struct Big x=va_arg(ap,struct Big);va_end(ap);return tag+x.a+x.b+x.c;}
EOF
cc -c -o tmp-memory-host.o tmp-memory-host.c
cat > tmp-memory-mini-caller.c <<'EOF'
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long host_sum(struct Big);
struct Big host_make(long,long,long,long,long,long);
long host_after(long,struct Big,long,long,long,long,long,long);
struct Mix host_mix(double,long,double);
long host_var(int,...);
int main(void){
  struct Big x={10,12,20}; if(host_sum(x)!=42) return 1;
  struct Big y=host_make(1,2,3,4,5,27); if(y.a+y.b+y.c!=42) return 2;
  struct Big z={2,3,4}; if(host_after(1,z,5,6,7,8,1,5)!=42) return 3;
  struct Mix m=host_mix(10.0,12,20.0); if(m.a+m.b+m.c!=42.0) return 4;
  if(host_var(0,x)!=42) return 5;
  return 0;
}
EOF
./minicc tmp-memory-mini-caller.c > tmp-memory-mini-caller.s
cc -o tmp-memory-mini-caller tmp-memory-mini-caller.s tmp-memory-host.o
./tmp-memory-mini-caller
printf '%s\n' 'OK(MEMORY record ABI): minicc caller interoperates with host GCC'

# Host GCC caller -> minicc callee checks incoming stack objects, hidden return
# destinations, GP shifting, mixed fields, and named-MEMORY variadic cursor state.
cat > tmp-memory-mini-callee.c <<'EOF'
#include <stdarg.h>
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long mini_sum(struct Big x){return x.a+x.b+x.c;}
struct Big mini_make(long a,long b,long c,long d,long e,long f){struct Big x={a+b,c+d,e+f};return x;}
long mini_after(long a,struct Big x,long b,long c,long d,long e,long q,long z){return a+x.a+x.b+x.c+b+c+d+e+q+z;}
struct Mix mini_mix(double a,long b,double c){struct Mix x={a,b,c};return x;}
long mini_named_var(struct Big fixed,int tag,...){
  va_list ap;va_start(ap,tag);
  long a=va_arg(ap,long),b=va_arg(ap,long),c=va_arg(ap,long);
  long d=va_arg(ap,long),e=va_arg(ap,long),f=va_arg(ap,long);
  va_end(ap);
  return fixed.a+fixed.b+fixed.c+tag+a+b+c+d+e+f;
}
struct Big mini_ret_var(int tag,...){
  va_list ap;va_start(ap,tag);
  long a=va_arg(ap,long),b=va_arg(ap,long),c=va_arg(ap,long);
  va_end(ap);
  struct Big x={a,b,c};return x;
}
EOF
./minicc tmp-memory-mini-callee.c > tmp-memory-mini-callee.s
cat > tmp-memory-host-main.c <<'EOF'
#include <stdarg.h>
struct Big { long a,b,c; };
struct Mix { double a; long b; double c; };
long mini_sum(struct Big);
struct Big mini_make(long,long,long,long,long,long);
long mini_after(long,struct Big,long,long,long,long,long,long);
struct Mix mini_mix(double,long,double);
long mini_named_var(struct Big,int,...);
struct Big mini_ret_var(int,...);
int main(void){
  struct Big x={10,12,20}; if(mini_sum(x)!=42) return 1;
  struct Big y=mini_make(1,2,3,4,5,27); if(y.a+y.b+y.c!=42) return 2;
  struct Big z={2,3,4}; if(mini_after(1,z,5,6,7,8,1,5)!=42) return 3;
  struct Mix m=mini_mix(10.0,12,20.0); if(m.a+m.b+m.c!=42.0) return 4;
  struct Big fixed={1,2,3}; if(mini_named_var(fixed,0,4L,5L,6L,7L,8L,6L)!=42) return 5;
  struct Big r=mini_ret_var(0,10L,12L,20L); if(r.a+r.b+r.c!=42) return 6;
  return 0;
}
EOF
cc -o tmp-memory-host-main tmp-memory-host-main.c tmp-memory-mini-callee.s
./tmp-memory-host-main
printf '%s\n' 'OK(MEMORY record ABI): host GCC caller interoperates with minicc callee'

rm -f tmp-memory-record.c tmp-memory-record.s tmp-memory-record \
      tmp-memory-host.c tmp-memory-host.o \
      tmp-memory-mini-caller.c tmp-memory-mini-caller.s tmp-memory-mini-caller \
      tmp-memory-mini-callee.c tmp-memory-mini-callee.s \
      tmp-memory-host-main.c tmp-memory-host-main

echo 'All SysV MEMORY record ABI tests passed!'
'''
# Replace two placeholders with real source strings containing #include; embedding
# them directly in single-quoted shell arguments would be unwieldy, so keep the
# self-contained variadic edge cases in the host-interoperability block below.
memory_test = memory_test.replace("assert_run 0 'include-placeholder'\n", "")
memory_test = memory_test.replace("assert_run 0 'include-placeholder-2'\n", "")
Path("test/sysv_memory_record_abi.sh").write_text(memory_test)

# Documentation: the supported scalar type system now covers both register and
# MEMORY aggregate classes.
p = Path("README.md")
text = p.read_text()
text = text.replace(
"SysV AMD64 by-value calls/returns support records up to 16 bytes via per-eightbyte INTEGER/SSE classification, including mixed GP/XMM records, INTEGER-dominant overlap, whole-record stack fallback when either register class is exhausted, and host-C interoperability; larger MEMORY-class records remain diagnosed at actual ABI boundaries, while record pointers are fully supported.",
"SysV AMD64 by-value calls/returns support <=16-byte records via per-eightbyte INTEGER/SSE classification and >16-byte records via the MEMORY class. Small aggregates support mixed GP/XMM registers and whole-record stack fallback; large arguments are stack-copied and large returns use the hidden sret pointer convention, with host-C interoperability across both paths. Record pointers remain fully supported."
)
text = text.replace(
"- Small INTEGER/SSE-class records use the SysV AMD64 by-value ABI across direct/indirect calls and returns, including mixed GP/XMM classification, whole-record stack fallback when either register pool cannot hold the complete aggregate, variadic XMM accounting, and interoperability with host-compiled C.\n",
"- Record values use the SysV AMD64 by-value ABI across direct/indirect calls and returns: <=16-byte aggregates use INTEGER/SSE register classification with whole-record fallback, while >16-byte MEMORY aggregates are copied through stack argument areas and hidden sret destinations. Variadic register/stack cursors and host-C interoperability cover both paths.\n"
)
p.write_text(text)
