from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)

# --- minicc.h: record-returning calls need stable hidden local storage. ---
p = Path("minicc.h")
s = p.read_text()
old = '''    Obj *var;      // Variable reference\n    Type *ty;      // Type of this node\n    Member *member; // Used if kind == ND_MEMBER\n'''
new = '''    Obj *var;      // Variable reference\n    Type *ty;      // Type of this node\n    Member *member; // Used if kind == ND_MEMBER\n    Obj *ret_buffer; // Hidden local materialization for by-value record calls\n'''
s = replace_once(s, old, new, "Node ret_buffer")
p.write_text(s)

# --- parse.c: allocate hidden locals for known record-valued calls. ---
p = Path("parse.c")
s = p.read_text()
anchor = '''static Obj *create_lvar(char *name) {\n    Obj *var = calloc(1, sizeof(Obj));\n    var->name = name;\n    var->is_local = true;\n    var->next = locals;\n    locals = var;\n\n    VarScope *vs = calloc(1, sizeof(VarScope));\n    vs->name = name;\n    vs->var = var;\n    vs->next = current_scope->vars;\n    current_scope->vars = vs;\n\n    return var;\n}\n'''
replacement = anchor + '''\n// A SysV register-returned record still needs addressable storage because the\n// rest of this compiler represents aggregate expression values by address.\n// Allocate an anonymous ordinary local while parsing a function body so the\n// backend can materialize RAX/RDX there immediately after the call.\nstatic void prepare_record_call_result(Node *node) {\n    if (!current_return_ty || !node || !node->ty || node->ty->kind != TY_STRUCT)\n        return;\n\n    Obj *buf = create_lvar(new_unique_name());\n    buf->ty = node->ty;\n    node->ret_buffer = buf;\n}\n'''
s = replace_once(s, anchor, replacement, "hidden record return helper")

old = '''    tok = skip(tok, "(");\n    node->args = parse_call_arguments(&tok, tok, fty);\n    *rest = tok;\n    return node;\n}\n\nstatic Node *postfix'''
new = '''    tok = skip(tok, "(");\n    node->args = parse_call_arguments(&tok, tok, fty);\n    prepare_record_call_result(node);\n    *rest = tok;\n    return node;\n}\n\nstatic Node *postfix'''
s = replace_once(s, old, new, "indirect record call buffer")

old = '''                tok = skip(tok->next, "(");\n                node->args = parse_call_arguments(&tok, tok, fty);\n                *rest = tok;\n                return node;\n'''
new = '''                tok = skip(tok->next, "(");\n                node->args = parse_call_arguments(&tok, tok, fty);\n                prepare_record_call_result(node);\n                *rest = tok;\n                return node;\n'''
s = replace_once(s, old, new, "direct record call buffer")
p.write_text(s)

# --- codegen.c: SysV AMD64 INTEGER-class records up to two eightbytes. ---
p = Path("codegen.c")
s = p.read_text()

old = '''    if (node->kind == ND_MEMBER) {\n        gen_addr(node->lhs);\n        printf("  add $%d, %%rax\\n", node->member->offset);\n        return;\n    }\n'''
new = '''    if (node->kind == ND_MEMBER) {\n        // Aggregate values are represented by address throughout this backend.\n        // gen_expr therefore works for both ordinary record lvalues and\n        // materialized record-returning calls such as make().field.\n        gen_expr(node->lhs);\n        printf("  add $%d, %%rax\\n", node->member->offset);\n        return;\n    }\n'''
s = replace_once(s, old, new, "member address from aggregate value")

marker = '''// Generate a function call (direct or indirect via function pointer).\n'''
idx = s.index(marker)
helpers = r'''// This focused SysV subset supports by-value records whose complete object
// representation fits in one or two INTEGER-class eightbytes.  Integer and
// pointer leaves (including nested arrays/records) are sufficient for that
// classification.  Floating/SSE and >16-byte MEMORY-class records are rejected
// rather than silently passing their address as the old scalar path did.
static bool integer_record_component(Type *ty) {
    if (!ty)
        return false;
    if (is_integer(ty) || ty->kind == TY_PTR)
        return true;
    if (ty->kind == TY_ARRAY)
        return ty->array_len > 0 && integer_record_component(ty->base);
    if (ty->kind == TY_STRUCT) {
        if (ty->is_incomplete || !ty->members)
            return false;
        for (Member *m = ty->members; m; m = m->next)
            if (!integer_record_component(m->ty))
                return false;
        return true;
    }
    return false;
}

static int integer_record_abi_slots(Type *ty) {
    if (!ty || ty->kind != TY_STRUCT || ty->is_incomplete ||
        ty->size <= 0 || ty->size > 16 || !integer_record_component(ty))
        return 0;
    return (ty->size + 7) / 8;
}

static int require_integer_record_abi(Type *ty) {
    int slots = integer_record_abi_slots(ty);
    if (!slots)
        error("unsupported by-value record ABI: expected <=16-byte INTEGER-class record");
    return slots;
}

// Spill an aggregate expression value from the address in RAX.  Zeroing the
// rounded eightbyte area keeps partial final slots deterministic and avoids
// reading bytes beyond the C object merely to fill an ABI register.
static void push_record_value(Type *ty) {
    int slots = require_integer_record_abi(ty);
    printf("  sub $%d, %%rsp\n", slots * 8);
    depth += slots;
    for (int i = 0; i < slots; i++)
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

static void save_integer_record_parameter(Obj *var, int *gp, int *stack_arg) {
    int slots = require_integer_record_abi(var->ty);
    if (*gp + slots <= 6) {
        int remaining = var->ty->size;
        for (int i = 0; i < slots; i++) {
            int bytes = remaining > 8 ? 8 : remaining;
            store_register_bytes_to_local(argreg64[*gp + i],
                                          var->offset + i * 8, bytes);
            remaining -= bytes;
        }
        *gp += slots;
        return;
    }

    int src = 16 + *stack_arg * 8;
    copy_stack_record_to_local(var->ty, src, var->offset);
    *stack_arg += slots;
}

// Load exactly `bytes` little-endian bytes from the record address in R10 into
// one SysV result register.  Partial eightbytes are built bytewise so no read
// crosses the source object's bounds.
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

static void emit_integer_record_return(Type *ty) {
    int slots = require_integer_record_abi(ty);
    printf("  mov %%rax, %%r10\n");
    int first = ty->size > 8 ? 8 : ty->size;
    load_record_bytes_to_reg(0, first, "%rax", "%eax");
    if (slots == 2)
        load_record_bytes_to_reg(8, ty->size - 8, "%rdx", "%edx");
}

static void materialize_integer_record_call(Node *node) {
    int slots = require_integer_record_abi(node->ty);
    if (!node->ret_buffer)
        error("missing record call return buffer");

    int first = node->ty->size > 8 ? 8 : node->ty->size;
    store_register_bytes_to_local("%rax", node->ret_buffer->offset, first);
    if (slots == 2)
        store_register_bytes_to_local("%rdx", node->ret_buffer->offset + 8,
                                      node->ty->size - 8);
    printf("  lea %d(%%rbp), %%rax\n", node->ret_buffer->offset);
}

'''
s = s[:idx] + helpers + s[idx:]

start = s.index('static void gen_funcall(Node *node) {')
end = s.index('\nstatic void gen_expr(Node *node) {', start)
new_func = r'''static void gen_funcall(Node *node) {
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
    int stack_slot[32];
    int spill_before[32];
    int spill_slots[32];
    int nargs = 0;
    int gp_count = 0;
    int fp_count = 0;
    int stack_count = 0;
    int total_spill_slots = 0;

    // Preserve left-to-right evaluation while spilling each complete argument
    // value. Records occupy one or two eightbyte spill slots instead of the old
    // accidental single pointer-sized slot.
    for (Node *arg = node->args; arg; arg = arg->next) {
        if (nargs >= 32)
            error("too many arguments");
        add_type(arg);
        args[nargs] = arg;
        record_arg[nargs] = arg->ty && arg->ty->kind == TY_STRUCT;
        fp_arg[nargs] = !record_arg[nargs] && is_flonum(arg->ty);
        stack_arg[nargs] = false;
        spill_before[nargs] = total_spill_slots;
        spill_slots[nargs] = record_arg[nargs]
                                 ? require_integer_record_abi(arg->ty)
                                 : 1;

        if (record_arg[nargs]) {
            int slots = spill_slots[nargs];
            if (gp_count + slots <= 6) {
                abi_slot[nargs] = gp_count;
                gp_count += slots;
            } else {
                stack_arg[nargs] = true;
                stack_slot[nargs] = stack_count;
                stack_count += slots;
            }
        } else if (fp_arg[nargs]) {
            if (fp_count < 8)
                abi_slot[nargs] = fp_count++;
            else {
                stack_arg[nargs] = true;
                stack_slot[nargs] = stack_count++;
            }
        } else {
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

    // R11 points at the lowest-address argument spill. Variable-width record
    // spills use the cumulative slot counts to recover each source address.
    printf("  mov %%rsp, %%r11\n");

    for (int i = 0; i < nargs; i++) {
        if (stack_arg[i])
            continue;
        int src = (total_spill_slots - spill_before[i] - spill_slots[i]) * 8;
        if (record_arg[i]) {
            for (int j = 0; j < spill_slots[i]; j++)
                printf("  mov %d(%%r11), %s\n", src + j * 8,
                       argreg64[abi_slot[i] + j]);
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
            int src = (total_spill_slots - spill_before[i] - spill_slots[i]) * 8;
            int dst = stack_slot[i] * 8;
            for (int j = 0; j < spill_slots[i]; j++) {
                printf("  mov %d(%%r11), %%rax\n", src + j * 8);
                printf("  mov %%rax, %d(%%rsp)\n", dst + j * 8);
            }
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

    int spill_count = total_spill_slots + (indirect ? 1 : 0);
    if (spill_count) {
        printf("  add $%d, %%rsp\n", spill_count * 8);
        depth -= spill_count;
    }

    if (node->ty && node->ty->kind == TY_STRUCT)
        materialize_integer_record_call(node);
}
'''
s = s[:start] + new_func + s[end:]

old = '''    if (node->kind == ND_RETURN) {\n        if (node->lhs) {\n            gen_expr(node->lhs);\n            cast_value(node->lhs->ty, current_return_ty);\n        }\n        printf("  jmp .L.return.%s\\n", current_fn);\n        return;\n    }\n'''
new = '''    if (node->kind == ND_RETURN) {\n        if (node->lhs) {\n            gen_expr(node->lhs);\n            if (current_return_ty && current_return_ty->kind == TY_STRUCT)\n                emit_integer_record_return(current_return_ty);\n            else\n                cast_value(node->lhs->ty, current_return_ty);\n        }\n        printf("  jmp .L.return.%s\\n", current_fn);\n        return;\n    }\n'''
s = replace_once(s, old, new, "record return lowering")

old = '''            for (Obj *p = fn->params; p; p = p->param_next) {\n                if (is_flonum(p->ty)) {\n                    if (fp < 8)\n                        fp++;\n                    else\n                        stack_arg++;\n                } else {\n                    if (gp < 6)\n                        gp++;\n                    else\n                        stack_arg++;\n                }\n            }\n'''
new = '''            for (Obj *p = fn->params; p; p = p->param_next) {\n                if (p->ty->kind == TY_STRUCT) {\n                    int slots = require_integer_record_abi(p->ty);\n                    if (gp + slots <= 6)\n                        gp += slots;\n                    else\n                        stack_arg += slots;\n                } else if (is_flonum(p->ty)) {\n                    if (fp < 8)\n                        fp++;\n                    else\n                        stack_arg++;\n                } else {\n                    if (gp < 6)\n                        gp++;\n                    else\n                        stack_arg++;\n                }\n            }\n'''
s = replace_once(s, old, new, "variadic named record classification")

old = '''        current_fn_obj = fn;\n        current_return_ty = fn->return_ty;\n\n        // Prologue\n'''
new = '''        current_fn_obj = fn;\n        current_return_ty = fn->return_ty;\n        if (fn->return_ty && fn->return_ty->kind == TY_STRUCT)\n            require_integer_record_abi(fn->return_ty);\n\n        // Prologue\n'''
s = replace_once(s, old, new, "validate record return ABI")

old = '''        for (Obj *var = fn->params; var; var = var->param_next) {\n            if (is_flonum(var->ty)) {\n'''
new = '''        for (Obj *var = fn->params; var; var = var->param_next) {\n            if (var->ty->kind == TY_STRUCT) {\n                save_integer_record_parameter(var, &gp, &stack_arg);\n                continue;\n            }\n            if (is_flonum(var->ty)) {\n'''
s = replace_once(s, old, new, "save record parameters")

p.write_text(s)

# --- Focused host-ABI and rejection regressions. ---
test = r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-record-abi.c
  ./minicc tmp-record-abi.c > tmp-record-abi.s
  cc -o tmp-record-abi tmp-record-abi.s
  set +e
  ./tmp-record-abi
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "record ABI failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(record ABI): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-record-abi-bad.c
  if ./minicc tmp-record-abi-bad.c > tmp-record-abi-bad.s 2>/dev/null; then
    echo 'record ABI unexpectedly accepted unsupported by-value shape'
    echo "$input"
    exit 1
  fi
  echo 'OK(record ABI): rejected unsupported by-value shape'
}

# One- and two-eightbyte INTEGER-class records pass and return by value.
assert_run 0 'struct S{int x;int y;};int sum(struct S s){return s.x+s.y;}int main(){struct S s={20,22};return sum(s)==42?0:1;}'
assert_run 0 'struct P{long a;long b;};long sum(struct P p){return p.a+p.b;}int main(){struct P p={19,23};return sum(p)==42?0:1;}'
assert_run 0 'struct P{long a;long b;};struct P make(long a,long b){struct P p={a,b};return p;}int main(){struct P p=make(17,25);return p.a+p.b==42?0:1;}'
assert_run 0 'struct T{int a;int b;int c;};struct T make(){struct T t={10,20,12};return t;}int main(){struct T t=make();return t.a+t.b+t.c==42?0:1;}'

# Returned aggregate values remain addressable internally for member reads and
# can feed another by-value call without accidentally passing the temp address.
assert_run 0 'struct P{long a;long b;};struct P make(){struct P p={1,41};return p;}int main(){return make().b==41?0:1;}'
assert_run 0 'struct P{long a;long b;};struct P make(){struct P p={20,22};return p;}long sum(struct P p){return p.a+p.b;}int main(){return sum(make())==42?0:1;}'

# Integer-class recursion covers nested records, integer arrays, pointers and
# integer-only unions without introducing an SSE-class special case.
assert_run 0 'struct I{int a;int b;};struct O{struct I i;long z;};long f(struct O o){return o.i.a+o.i.b+o.z;}int main(){struct O o={{10,12},20};return f(o)==42?0:1;}'
assert_run 0 'union U{long x;unsigned char b[8];};long f(union U u){return u.x;}int main(){union U u={.x=42};return f(u)==42?0:1;}'
assert_run 0 'struct P{int *p;long x;};long f(struct P s){return *s.p+s.x;}int main(){int x=20;struct P s={&x,22};return f(s)==42?0:1;}'

# Function pointers use the same direct/indirect record ABI path.
assert_run 0 'struct P{long a;long b;};long sum(struct P p){return p.a+p.b;}int main(){long (*fp)(struct P)=sum;struct P p={20,22};return fp(p)==42?0:1;}'
assert_run 0 'struct P{long a;long b;};struct P make(long a,long b){struct P p={a,b};return p;}int main(){struct P (*fp)(long,long)=make;struct P p=fp(21,21);return p.a+p.b==42?0:1;}'

# If a two-eightbyte record cannot fit the remaining GP registers, SysV reverts
# the whole aggregate to the stack; a later scalar may still consume the final
# GP register.
assert_run 0 'struct P{long a;long b;};long f(long a,long b,long c,long d,long e,struct P p,long z){return a+b+c+d+e+p.a+p.b+z;}int main(){struct P p={6,7};return f(1,2,3,4,5,p,14)==42?0:1;}'

# Minicc caller -> host GCC callee verifies the external SysV boundary.
cat > tmp-record-host.c <<'EOF'
struct Pair { long a; long b; };
long host_sum(struct Pair p) { return p.a + p.b; }
struct Pair host_make(long a, long b) { struct Pair p = {a, b}; return p; }
long host_stack(long a,long b,long c,long d,long e,struct Pair p,long z) {
  return a+b+c+d+e+p.a+p.b+z;
}
EOF
cc -c -o tmp-record-host.o tmp-record-host.c
cat > tmp-record-mini-caller.c <<'EOF'
struct Pair { long a; long b; };
long host_sum(struct Pair p);
struct Pair host_make(long a, long b);
long host_stack(long,long,long,long,long,struct Pair,long);
int main(){
  struct Pair p={20,22};
  if(host_sum(p)!=42) return 1;
  struct Pair q=host_make(19,23);
  if(q.a+q.b!=42) return 2;
  struct Pair r={6,7};
  if(host_stack(1,2,3,4,5,r,14)!=42) return 3;
  return 0;
}
EOF
./minicc tmp-record-mini-caller.c > tmp-record-mini-caller.s
cc -o tmp-record-mini-caller tmp-record-mini-caller.s tmp-record-host.o
./tmp-record-mini-caller
printf '%s\n' 'OK(record ABI): minicc caller interoperates with host GCC'

# Host GCC caller -> minicc callee verifies incoming records and RAX/RDX returns.
cat > tmp-record-mini-callee.c <<'EOF'
struct Pair { long a; long b; };
long mini_sum(struct Pair p){return p.a+p.b;}
struct Pair mini_make(long a,long b){struct Pair p={a,b};return p;}
long mini_stack(long a,long b,long c,long d,long e,struct Pair p,long z){
  return a+b+c+d+e+p.a+p.b+z;
}
EOF
./minicc tmp-record-mini-callee.c > tmp-record-mini-callee.s
cat > tmp-record-host-main.c <<'EOF'
struct Pair { long a; long b; };
long mini_sum(struct Pair);
struct Pair mini_make(long,long);
long mini_stack(long,long,long,long,long,struct Pair,long);
int main(void){
  struct Pair p={18,24};
  if(mini_sum(p)!=42) return 1;
  struct Pair q=mini_make(17,25);
  if(q.a+q.b!=42) return 2;
  struct Pair r={6,7};
  if(mini_stack(1,2,3,4,5,r,14)!=42) return 3;
  return 0;
}
EOF
cc -o tmp-record-host-main tmp-record-host-main.c tmp-record-mini-callee.s
./tmp-record-host-main
printf '%s\n' 'OK(record ABI): host GCC caller interoperates with minicc callee'

# Unsupported ABI classes now diagnose instead of silently treating a record
# address as one integer argument/result.
assert_fail 'struct F{double x;};int f(struct F x){return 0;}int main(){struct F x={1.0};return f(x);}'
assert_fail 'struct M{double x;long y;};long f(struct M x){return x.y;}int main(){struct M x={1.0,2};return f(x);}'
assert_fail 'struct B{long a;long b;long c;};long f(struct B x){return x.a;}int main(){struct B x={1,2,3};return f(x);}'
assert_fail 'struct F{double x;};struct F make(){struct F x={1.0};return x;}int main(){return 0;}'
assert_fail 'struct B{long a;long b;long c;};struct B make(){struct B x={1,2,3};return x;}int main(){return 0;}'

echo 'All SysV integer-record ABI tests passed!'
'''
Path("test/sysv_record_abi.sh").write_text(test)

# Makefile test entry.
p = Path("Makefile")
s = p.read_text()
old = '\tbash ./test/float_abi.sh\n'
new = old + '\tbash ./test/sysv_record_abi.sh\n'
s = replace_once(s, old, new, "Makefile record ABI test")
p.write_text(s)

# README: document the exact supported ABI frontier instead of implying every
# aggregate shape is already implemented.
p = Path("README.md")
s = p.read_text()
old = '- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required.\n'
new = '- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required. SysV AMD64 by-value calls/returns support records up to 16 bytes whose leaves classify entirely as INTEGER (integers, pointers, arrays/nested records of those); larger or floating/SSE-class records are diagnosed rather than miscompiled.\n'
s = replace_once(s, old, new, "README record ABI frontier")

note = '- Character-array string initialization is supported recursively inside automatic/static aggregates, including struct/union members, multidimensional character arrays, and designated subobjects, with C-compatible NUL truncation and zero-fill.\n'
addition = note + '\n- Small INTEGER-class records use the SysV AMD64 by-value ABI across direct/indirect calls and returns, including whole-record stack fallback when the remaining GP registers cannot hold every eightbyte and interoperability with host-compiled C.\n'
s = replace_once(s, note, addition, "README record ABI note")
p.write_text(s)
