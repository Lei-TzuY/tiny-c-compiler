from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing replacement marker in {path}: {old[:80]!r}")
    if s.count(old) != 1:
        raise SystemExit(f"replacement marker not unique in {path}: {old[:80]!r}")
    p.write_text(s.replace(old, new, 1))


# Shared ABI class API.
replace_once(
    "minicc.h",
    "bool is_numeric(Type *ty);\nint sysv_integer_record_slots(Type *ty);\n",
    "bool is_numeric(Type *ty);\n\n"
    "typedef enum {\n"
    "    SYSV_ABI_NONE,\n"
    "    SYSV_ABI_INTEGER,\n"
    "    SYSV_ABI_SSE,\n"
    "} SysVAbiClass;\n\n"
    "int sysv_classify_record(Type *ty, SysVAbiClass classes[2]);\n",
)

# Replace the conservative INTEGER-only classifier with an actual per-eightbyte
# INTEGER/SSE merge classifier for the scalar type system supported by minicc.
p = Path("type.c")
s = p.read_text()
start = s.index("// Conservative SysV AMD64 aggregate subset shared by semantic ABI checks and")
end = s.index("Type *qualify_type(Type *ty, bool is_const, bool is_volatile) {", start)
classifier = r'''// SysV AMD64 classifies records up to two eightbytes independently.  This
// compiler's scalar type system needs only INTEGER and SSE classes: integers and
// pointers contribute INTEGER, float/double contribute SSE, and overlapping
// union/subobject contributions merge with INTEGER taking precedence over SSE.
// Larger records remain MEMORY-class and stay behind the ABI firewall.
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

'''
p.write_text(s[:start] + classifier + s[end:])

# Parser-side ABI firewall and hidden result materialization use the same shared
# classifier as codegen.
replace_once(
    "parse.c",
    '''// Aggregate expressions are represented by an address in the backend. A small
// record returned in RAX/RDX is therefore materialized into an anonymous local
// immediately after the call, preserving ordinary record-expression behavior.
static void prepare_record_call_result(Node *node) {
    if (!current_return_ty || !node || !node->ty ||
        !sysv_integer_record_slots(node->ty))
        return;

    Obj *buf = create_lvar(new_unique_name());
    buf->ty = node->ty;
    node->ret_buffer = buf;
}
''',
    '''static bool supported_record_abi(Type *ty) {
    SysVAbiClass classes[2];
    return ty && ty->kind == TY_STRUCT && sysv_classify_record(ty, classes) > 0;
}

// Aggregate expressions are represented by an address in the backend. Small
// records returned in INTEGER/SSE registers are therefore materialized into an
// anonymous local immediately after the call, preserving ordinary record
// expression behavior such as make().field and return-to-argument chaining.
static void prepare_record_call_result(Node *node) {
    if (!current_return_ty || !node || !supported_record_abi(node->ty))
        return;

    Obj *buf = create_lvar(new_unique_name());
    buf->ty = node->ty;
    node->ret_buffer = buf;
}
''',
)

p = Path("parse.c")
s = p.read_text()
start = s.index("// Keep PR #49's ABI firewall, but open the INTEGER-only subset")
end = s.index("// Parse a call's comma-separated argument list after the opening parenthesis.", start)
abi_check = r'''// Keep the record-ABI firewall shape-aware: all naturally laid-out records up
// to 16 bytes whose eightbytes classify as INTEGER/SSE are now lowered exactly.
// Prototypes may still describe larger MEMORY-class records when never crossed.
static void check_supported_function_abi(Type *fty, Token *at) {
    if (!fty || fty->kind != TY_FUNC)
        return;

    if (fty->return_ty && fty->return_ty->kind == TY_STRUCT &&
        !supported_record_abi(fty->return_ty))
        error_at(at->loc, "unsupported record return ABI for x86-64 backend");

    if (!fty->has_prototype)
        return;
    for (Obj *param = fty->params; param; param = param->param_next)
        if (param->ty && param->ty->kind == TY_STRUCT &&
            !supported_record_abi(param->ty))
            error_at(at->loc, "unsupported record parameter ABI for x86-64 backend");
}

'''
p.write_text(s[:start] + abi_check + s[end:])
replace_once(
    "parse.c",
    '''        // Unprototyped calls and variadic tails have no declared parameter to
        // inspect, so classify an aggregate from its actual type. Supported
        // INTEGER-class records use the same caller lowering as fixed params.
        if (arg->ty && arg->ty->kind == TY_STRUCT &&
            !sysv_integer_record_slots(arg->ty))
            error_at(arg_tok->loc, "unsupported record argument ABI for x86-64 backend");
''',
    '''        // Unprototyped calls and variadic tails have no declared parameter to
        // inspect, so classify aggregate actuals directly before codegen.
        if (arg->ty && arg->ty->kind == TY_STRUCT &&
            !supported_record_abi(arg->ty))
            error_at(arg_tok->loc, "unsupported record argument ABI for x86-64 backend");
''',
)

# Replace record ABI lowering + caller argument assignment as one coherent unit.
p = Path("codegen.c")
s = p.read_text()
start = s.index("// The parser and backend share one conservative SysV classification predicate,")
end = s.index("static void gen_expr(Node *node) {", start)
codegen_block = r'''typedef struct {
    int slots;
    int gp;
    int fp;
    SysVAbiClass classes[2];
} RecordAbi;

// Parser and backend share sysv_classify_record(), so every accepted record
// arrives here with the same per-eightbyte INTEGER/SSE shape used for lowering.
static RecordAbi require_record_abi(Type *ty) {
    RecordAbi abi = {};
    abi.slots = sysv_classify_record(ty, abi.classes);
    if (!abi.slots)
        error("unsupported by-value record ABI: expected <=16-byte INTEGER/SSE record");
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
// reading bytes beyond the C object merely to fill an ABI register.
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

    // SysV reverts the entire aggregate to memory if either register class is
    // short; do not consume the still-available registers of the other class.
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

static void emit_record_return(Type *ty) {
    RecordAbi abi = require_record_abi(ty);
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
    static const char *gp64[] = {"%rax", "%rdx"};
    int g = 0;
    int f = 0;

    if (!node->ret_buffer)
        error("missing record call return buffer");

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

// Generate a function call (direct or indirect via function pointer). Scalar and
// aggregate INTEGER/SSE classes draw independently from rdi..r9 and xmm0..xmm7.
// If any class needed by a record is exhausted, the whole record is stack-passed.
static void gen_funcall(Node *node) {
    bool indirect = (node->funcname == NULL);

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
    int gp_count = 0;
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

    // For variadic calls AL counts every XMM register used, including SSE
    // eightbytes contributed by aggregate arguments.
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
p.write_text(s[:start] + codegen_block + s[end:])

replace_once(
    "codegen.c",
    "                emit_integer_record_return(current_return_ty);\n",
    "                emit_record_return(current_return_ty);\n",
)
replace_once(
    "codegen.c",
    '''                if (p->ty->kind == TY_STRUCT) {
                    int slots = require_integer_record_abi(p->ty);
                    if (gp + slots <= 6)
                        gp += slots;
                    else
                        stack_arg += slots;
                } else if (is_flonum(p->ty)) {
''',
    '''                if (p->ty->kind == TY_STRUCT) {
                    RecordAbi abi = require_record_abi(p->ty);
                    if (gp + abi.gp <= 6 && fp + abi.fp <= 8) {
                        gp += abi.gp;
                        fp += abi.fp;
                    } else {
                        stack_arg += abi.slots;
                    }
                } else if (is_flonum(p->ty)) {
''',
)
replace_once(
    "codegen.c",
    "            require_integer_record_abi(fn->return_ty);\n",
    "            require_record_abi(fn->return_ty);\n",
)
replace_once(
    "codegen.c",
    "                save_integer_record_parameter(var, &gp, &stack_arg);\n",
    "                save_record_parameter(var, &gp, &fp, &stack_arg);\n",
)

# Existing INTEGER-focused tests should now leave only true MEMORY-class rejects.
p = Path("test/sysv_record_abi.sh")
s = p.read_text()
old = '''# Unsupported ABI classes now diagnose instead of silently treating a record
# address as one integer argument/result.
assert_fail 'struct F{double x;};int f(struct F x){return 0;}int main(){struct F x={1.0};return f(x);}'
assert_fail 'struct M{double x;long y;};long f(struct M x){return x.y;}int main(){struct M x={1.0,2};return f(x);}'
assert_fail 'struct B{long a;long b;long c;};long f(struct B x){return x.a;}int main(){struct B x={1,2,3};return f(x);}'
assert_fail 'struct F{double x;};struct F make(){struct F x={1.0};return x;}int main(){return 0;}'
assert_fail 'struct B{long a;long b;long c;};struct B make(){struct B x={1,2,3};return x;}int main(){return 0;}'
'''
new = '''# Records larger than two eightbytes remain MEMORY-class and are diagnosed
# instead of silently treating an aggregate address as one scalar value.
assert_fail 'struct B{long a;long b;long c;};long f(struct B x){return x.a;}int main(){struct B x={1,2,3};return f(x);}'
assert_fail 'struct B{long a;long b;long c;};struct B make(){struct B x={1,2,3};return x;}int main(){return 0;}'
'''
if old not in s:
    raise SystemExit("sysv_record_abi rejection block changed")
p.write_text(s.replace(old, new, 1).replace("All SysV integer-record ABI tests passed!", "All SysV base record ABI tests passed!"))

# Firewall frontier advances from SSE rejection to MEMORY-only rejection.
p = Path("test/record_abi_firewall.sh")
s = p.read_text()
old = '''# Unsupported classes remain safely diagnosed at actual ABI boundaries.
assert_fail 'struct F{double x;};int f(struct F x){return 0;}int main(){return 0;}'
assert_fail 'struct M{double x;long y;};long f(struct M x){return x.y;}int main(){return 0;}'
assert_fail 'struct Big{long a;long b;long c;};long f(struct Big x){return x.a;}int main(){return 0;}'
assert_fail 'struct F{double x;};struct F f(void){struct F x={1.0};return x;}int main(){return 0;}'
assert_fail 'struct Big{long a;long b;long c;};struct Big f(void){struct Big x={1,2,3};return x;}int main(){return 0;}'

# Unsupported prototypes remain representable if never crossed.
assert_run 0 'struct F{double x;};struct F ext(struct F);int main(){return 0;}'

# Actual aggregate type still protects unprototyped/variadic paths.
assert_fail 'struct F{double x;};int f();int main(){struct F x={1.0};return f(x);}'
assert_fail 'struct F{double x;};int f(int,...);int main(){struct F x={1.0};return f(1,x);}'
'''
new = '''# SSE-only and mixed INTEGER/SSE records up to 16 bytes now cross real ABI
# boundaries instead of being conservatively rejected.
assert_run 0 'struct F{double x;};double f(struct F x){return x.x;}int main(){struct F x={42.0};return f(x)==42.0?0:1;}'
assert_run 0 'struct M{double x;long y;};double f(struct M x){return x.x+x.y;}int main(){struct M x={20.0,22};return f(x)==42.0?0:1;}'
assert_run 0 'struct F{double x;};struct F f(void){struct F x={42.0};return x;}int main(){return f().x==42.0?0:1;}'

# Only true MEMORY-class record boundaries remain rejected in this scalar subset.
assert_fail 'struct Big{long a;long b;long c;};long f(struct Big x){return x.a;}int main(){return 0;}'
assert_fail 'struct Big{double a;double b;double c;};struct Big f(void){struct Big x={1.0,2.0,3.0};return x;}int main(){return 0;}'

# Unsupported prototypes remain representable if never crossed.
assert_run 0 'struct Big{double a;double b;double c;};struct Big ext(struct Big);int main(){return 0;}'

# Supported aggregate actuals work through unprototyped/variadic paths too.
assert_run 0 'struct F{double x;};int f(){return 0;}int main(){struct F x={1.0};return f(x);}'
assert_run 0 'struct F{double x;};int f(int n,...){return n;}int main(){struct F x={1.0};return f(0,x);}'

# Actual aggregate type still protects MEMORY-class unprototyped/variadic paths.
assert_fail 'struct Big{double a;double b;double c;};int f();int main(){struct Big x={1.0,2.0,3.0};return f(x);}'
assert_fail 'struct Big{double a;double b;double c;};int f(int,...);int main(){struct Big x={1.0,2.0,3.0};return f(1,x);}'
'''
if old not in s:
    raise SystemExit("record firewall block changed")
p.write_text(s.replace(old, new, 1))

# PR #52's conservative union rejects become exact merge-positive cases.
p = Path("test/sysv_mixed_union_abi.sh")
s = p.read_text()
old = '''# Pure SSE records, and mixed unions without a full-width INTEGER covering
# member, remain deliberately outside the current conservative classifier.
assert_fail 'union U{double d;};int f(union U u){return 0;}int main(){return 0;}'
assert_fail 'union U{int i;double d;};int f(union U u){return u.i;}int main(){return 0;}'
'''
new = '''# The full classifier also handles pure SSE unions and exact INTEGER-over-SSE
# merging when a narrower integer member overlaps a wider floating member.
assert_run 0 'union U{double d;};double f(union U u){return u.d;}int main(){union U u;u.d=42.0;return f(u)==42.0?0:1;}'
assert_run 0 'union U{int i;double d;};int f(union U u){return u.i;}int main(){union U u;u.i=42;return f(u)==42?0:1;}'
'''
if old not in s:
    raise SystemExit("mixed union conservative block changed")
p.write_text(s.replace(old, new, 1))

# New focused SSE/mixed record ABI suite.
Path("test/sysv_sse_record_abi.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-sse-record.c
  ./minicc tmp-sse-record.c > tmp-sse-record.s
  cc -o tmp-sse-record tmp-sse-record.s
  set +e
  ./tmp-sse-record
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "SSE record ABI failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(SSE record ABI): $actual"
}

# Pure SSE records use XMM registers for one or two eightbytes and for returns.
assert_run 0 'struct F{double x;};double get(struct F s){return s.x;}int main(){struct F s={42.0};return get(s)==42.0?0:1;}'
assert_run 0 'struct F{double x;};struct F make(double x){struct F s={x};return s;}int main(){return make(42.0).x==42.0?0:1;}'
assert_run 0 'struct D{double a;double b;};double sum(struct D s){return s.a+s.b;}int main(){struct D s={20.0,22.0};return sum(s)==42.0?0:1;}'
assert_run 0 'struct D{double a;double b;};struct D make(){struct D s={19.0,23.0};return s;}int main(){struct D s=make();return s.a+s.b==42.0?0:1;}'
assert_run 0 'struct F2{float a;float b;};float sum(struct F2 s){return s.a+s.b;}int main(){struct F2 s={20.0f,22.0f};return sum(s)==42.0f?0:1;}'
assert_run 0 'struct A{double v[2];};double sum(struct A a){return a.v[0]+a.v[1];}int main(){struct A a={{20.0,22.0}};return sum(a)==42.0?0:1;}'

# Mixed records draw from GP and SSE pools independently; order of eightbytes
# controls the return register class, not a single aggregate-wide class.
assert_run 0 'struct M{double d;long i;};double sum(struct M m){return m.d+m.i;}int main(){struct M m={20.0,22};return sum(m)==42.0?0:1;}'
assert_run 0 'struct M{double d;long i;};struct M make(){struct M m={20.0,22};return m;}int main(){struct M m=make();return m.d+m.i==42.0?0:1;}'
assert_run 0 'struct R{long i;double d;};struct R make(){struct R r={22,20.0};return r;}int main(){struct R r=make();return r.i+r.d==42.0?0:1;}'

# INTEGER dominates SSE when both contribute to the same eightbyte.
assert_run 0 'struct P{float f;int i;};int get(struct P p){return p.i;}int main(){struct P p={1.0f,42};return get(p)==42?0:1;}'
assert_run 0 'union U{int i;double d;};int get(union U u){return u.i;}int main(){union U u;u.i=42;return get(u)==42?0:1;}'

# If the whole aggregate cannot fit in either required register class, SysV
# stack-passes it without consuming the other still-available class.
assert_run 0 'struct D{double a;double b;};double f(double a,double b,double c,double d,double e,double q,double g,struct D p,double z){return a+b+c+d+e+q+g+p.a+p.b+z;}int main(){struct D p={10.0,11.0};return f(1,1,1,1,1,1,1,p,14)==42.0?0:1;}'
assert_run 0 'struct M{double d;long i;};double f(long a,long b,long c,long d,long e,long q,struct M m,double z){return a+b+c+d+e+q+m.d+m.i+z;}int main(){struct M m={10.0,12};return f(1,1,1,1,1,1,m,14.0)==42.0?0:1;}'
assert_run 0 'struct M{double d;long i;};double f(double a,double b,double c,double d,double e,double q,double g,double h,struct M m,long z){return a+b+c+d+e+q+g+h+m.d+m.i+z;}int main(){struct M m={10.0,11};return f(1,1,1,1,1,1,1,1,m,13)==42.0?0:1;}'

# Minicc caller -> host GCC callee, including SSE exhaustion and a variadic
# aggregate whose XMM use must be reflected in AL.
cat > tmp-sse-record-host.c <<'EOF'
#include <stdarg.h>
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double host_d(struct D x){return x.a+x.b;}
struct M host_m(double d,long i){struct M x={d,i};return x;}
int host_p(struct P x){return x.i;}
double host_stack(double a,double b,double c,double d,double e,double f,double g,struct D p,double z){return a+b+c+d+e+f+g+p.a+p.b+z;}
double host_var(int tag,...){va_list ap;va_start(ap,tag);struct D x=va_arg(ap,struct D);va_end(ap);return x.a+x.b;}
EOF
cc -c -o tmp-sse-record-host.o tmp-sse-record-host.c
cat > tmp-sse-record-mini-caller.c <<'EOF'
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double host_d(struct D);
struct M host_m(double,long);
int host_p(struct P);
double host_stack(double,double,double,double,double,double,double,struct D,double);
double host_var(int,...);
int main(void){
  struct D d={20.0,22.0}; if(host_d(d)!=42.0) return 1;
  struct M m=host_m(20.0,22); if(m.d+m.i!=42.0) return 2;
  struct P p={1.0f,42}; if(host_p(p)!=42) return 3;
  struct D s={10.0,11.0}; if(host_stack(1,1,1,1,1,1,1,s,14)!=42.0) return 4;
  if(host_var(0,d)!=42.0) return 5;
  return 0;
}
EOF
./minicc tmp-sse-record-mini-caller.c > tmp-sse-record-mini-caller.s
cc -o tmp-sse-record-mini-caller tmp-sse-record-mini-caller.s tmp-sse-record-host.o
./tmp-sse-record-mini-caller
printf '%s\n' 'OK(SSE record ABI): minicc caller interoperates with host GCC'

# Host GCC caller -> minicc callee verifies incoming SSE/mixed values, mixed
# return registers, whole-record stack fallback, and named-record va_start state.
cat > tmp-sse-record-mini-callee.c <<'EOF'
#include <stdarg.h>
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double mini_d(struct D x){return x.a+x.b;}
struct M mini_m(double d,long i){struct M x={d,i};return x;}
int mini_p(struct P x){return x.i;}
double mini_stack(double a,double b,double c,double d,double e,double f,double g,struct D p,double z){return a+b+c+d+e+f+g+p.a+p.b+z;}
double mini_named_var(struct D fixed,int tag,...){va_list ap;va_start(ap,tag);double z=va_arg(ap,double);va_end(ap);return fixed.a+fixed.b+z;}
EOF
./minicc tmp-sse-record-mini-callee.c > tmp-sse-record-mini-callee.s
cat > tmp-sse-record-host-main.c <<'EOF'
struct D { double a,b; };
struct M { double d; long i; };
struct P { float f; int i; };
double mini_d(struct D);
struct M mini_m(double,long);
int mini_p(struct P);
double mini_stack(double,double,double,double,double,double,double,struct D,double);
double mini_named_var(struct D,int,...);
int main(void){
  struct D d={20.0,22.0}; if(mini_d(d)!=42.0) return 1;
  struct M m=mini_m(20.0,22); if(m.d+m.i!=42.0) return 2;
  struct P p={1.0f,42}; if(mini_p(p)!=42) return 3;
  struct D s={10.0,11.0}; if(mini_stack(1,1,1,1,1,1,1,s,14)!=42.0) return 4;
  struct D fixed={10.0,12.0}; if(mini_named_var(fixed,0,20.0)!=42.0) return 5;
  return 0;
}
EOF
cc -o tmp-sse-record-host-main tmp-sse-record-host-main.c tmp-sse-record-mini-callee.s
./tmp-sse-record-host-main
printf '%s\n' 'OK(SSE record ABI): host GCC caller interoperates with minicc callee'

rm -f tmp-sse-record.c tmp-sse-record.s tmp-sse-record \
      tmp-sse-record-host.c tmp-sse-record-host.o \
      tmp-sse-record-mini-caller.c tmp-sse-record-mini-caller.s tmp-sse-record-mini-caller \
      tmp-sse-record-mini-callee.c tmp-sse-record-mini-callee.s \
      tmp-sse-record-host-main.c tmp-sse-record-host-main

echo 'All SysV SSE/mixed record ABI tests passed!'
''')

replace_once(
    "Makefile",
    "\tbash ./test/sysv_record_abi.sh\n\tbash ./test/sysv_mixed_union_abi.sh\n",
    "\tbash ./test/sysv_record_abi.sh\n\tbash ./test/sysv_sse_record_abi.sh\n\tbash ./test/sysv_mixed_union_abi.sh\n",
)

# Documentation moves the ABI frontier from INTEGER-only to full scalar
# INTEGER/SSE classification for <=16-byte records.
p = Path("README.md")
s = p.read_text()
s = s.replace(
    "SysV AMD64 by-value calls/returns support records up to 16 bytes whose leaves classify entirely as INTEGER (integers, pointers, arrays/nested records of those); larger or floating/SSE-class records remain diagnosed at actual ABI boundaries, while record pointers are fully supported.",
    "SysV AMD64 by-value calls/returns support naturally laid-out records up to 16 bytes with per-eightbyte INTEGER/SSE classification, including floating members, mixed integer/floating records, nested arrays/records, and INTEGER-dominant union merges; larger MEMORY-class records remain diagnosed at actual ABI boundaries, while record pointers are fully supported.",
)
s = s.replace(
    "- Small INTEGER-class records use the SysV AMD64 by-value ABI across direct/indirect calls and returns, including whole-record stack fallback when remaining GP registers cannot hold every eightbyte and interoperability with host-compiled C.\n",
    "- Small records use SysV AMD64 per-eightbyte INTEGER/SSE classification across direct/indirect calls and returns. GP/XMM pools are tracked independently; if either class cannot fit an aggregate, the whole record falls back to the stack without consuming the other class, and bidirectional host-GCC interoperability is regression-tested.\n",
)
p.write_text(s)

# No stale INTEGER-only classifier hooks may remain in permanent compiler code.
for path in ["minicc.h", "type.c", "parse.c", "codegen.c"]:
    text = Path(path).read_text()
    if "sysv_integer_record_slots" in text or "require_integer_record_abi" in text:
        raise SystemExit(f"stale INTEGER-only ABI helper in {path}")
