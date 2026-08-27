from pathlib import Path

p = Path("codegen.c")
s = p.read_text()

old_call = r'''// Generate a function call (direct or indirect via function pointer).
// Integer/pointer arguments use rdi..r9; float/double arguments independently
// use xmm0..xmm7 as required by the System V AMD64 ABI.
static void gen_funcall(Node *node) {
    bool indirect = (node->funcname == NULL);

    if (indirect) {
        gen_expr(node->lhs);
        push(); // save function address below argument spills
    }

    Node *args[32];
    bool fp_arg[32];
    int abi_slot[32];
    int nargs = 0;
    int gp_count = 0;
    int fp_count = 0;

    for (Node *arg = node->args; arg; arg = arg->next) {
        if (nargs >= 32)
            error("too many arguments");
        add_type(arg);
        args[nargs] = arg;

        gen_expr(arg);
        if (is_flonum(arg->ty)) {
            if (fp_count >= 8)
                error("too many floating-point register arguments");
            fp_arg[nargs] = true;
            abi_slot[nargs] = fp_count++;
            pushf(arg->ty);
        } else {
            if (gp_count >= 6)
                error("too many integer register arguments");
            fp_arg[nargs] = false;
            abi_slot[nargs] = gp_count++;
            push();
        }
        nargs++;
    }

    for (int i = nargs - 1; i >= 0; i--) {
        if (fp_arg[i]) {
            char reg[16];
            sprintf(reg, "%%xmm%d", abi_slot[i]);
            popf(args[i]->ty, reg);
        } else {
            pop(argreg64[abi_slot[i]]);
        }
    }

    int c = count();

    if (indirect)
        pop("%r10");

    printf("  mov %%rsp, %%rax\n");
    printf("  and $15, %%rax\n");
    printf("  jnz .L.call.%d\n", c);
    // For variadic callees, SysV requires AL to contain the number of vector
    // registers used. Non-variadic callees ignore it.
    printf("  mov $%d, %%eax\n", fp_count);
    if (indirect)
        printf("  call *%%r10\n");
    else
        printf("  call %s\n", node->funcname);
    printf("  jmp .L.end.%d\n", c);
    printf(".L.call.%d:\n", c);
    printf("  sub $8, %%rsp\n");
    printf("  mov $%d, %%eax\n", fp_count);
    if (indirect)
        printf("  call *%%r10\n");
    else
        printf("  call %s\n", node->funcname);
    printf("  add $8, %%rsp\n");
    printf(".L.end.%d:\n", c);
}
'''

new_call = r'''// Generate a function call (direct or indirect via function pointer).
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
'''

if old_call not in s:
    raise SystemExit("gen_funcall block not found")
s = s.replace(old_call, new_call, 1)

old_prologue = r'''        } else {
            // Save passed-by-register arguments to the stack. Integer and SSE
            // register numbers advance independently under SysV AMD64.
            int gp = 0;
            int fp = 0;
            for (Obj *var = fn->params; var; var = var->param_next) {
                if (is_flonum(var->ty)) {
                    if (fp >= 8)
                        error("too many floating-point parameters");
                    if (var->ty->kind == TY_FLOAT)
                        printf("  movss %%xmm%d, %d(%%rbp)\n", fp, var->offset);
                    else
                        printf("  movsd %%xmm%d, %d(%%rbp)\n", fp, var->offset);
                    fp++;
                    continue;
                }

                if (gp >= 6)
                    error("too many integer parameters");
                if (var->ty->kind == TY_BOOL || var->ty->kind == TY_CHAR)
                    printf("  mov %s, %d(%%rbp)\n", argreg8[gp++], var->offset);
                else if (var->ty->kind == TY_SHORT)
                    printf("  mov %s, %d(%%rbp)\n", argreg16[gp++], var->offset);
                else if (var->ty->kind == TY_INT)
                    printf("  mov %s, %d(%%rbp)\n", argreg32[gp++], var->offset);
                else
                    printf("  mov %s, %d(%%rbp)\n", argreg64[gp++], var->offset);
            }
        }
'''

new_prologue = r'''        } else {
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
'''

if old_prologue not in s:
    raise SystemExit("non-variadic parameter prologue block not found")
s = s.replace(old_prologue, new_prologue, 1)
p.write_text(s)

make = Path("Makefile")
m = make.read_text()
needle = '\tbash ./test/enum_constexpr_tags.sh\n'
if needle not in m:
    raise SystemExit("enum constexpr test line not found")
if '\tbash ./test/abi_stack_args.sh\n' not in m:
    m = m.replace(needle, needle + '\tbash ./test/abi_stack_args.sh\n', 1)
make.write_text(m)

Path("test/abi_stack_args.sh").write_text(r'''#!/bin/bash
set -e

assert_abi() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-abi-stack.c
  "${MINICC:-./minicc}" tmp-abi-stack.c > tmp-abi-stack.s
  gcc -o tmp-abi-stack tmp-abi-stack.s
  set +e
  ./tmp-abi-stack
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stack ABI): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(stack ABI): $actual"
}

assert_abi 28 'int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;} int main(){return sum7(1,2,3,4,5,6,7);}'
assert_abi 55 'int sum10(int a,int b,int c,int d,int e,int f,int g,int h,int i,int j){return a+b+c+d+e+f+g+h+i+j;} int main(){return sum10(1,2,3,4,5,6,7,8,9,10);}'
assert_abi 45 'double sum9(double a,double b,double c,double d,double e,double f,double g,double h,double i){return a+b+c+d+e+f+g+h+i;} int main(){return (int)sum9(1,2,3,4,5,6,7,8,9);}'
assert_abi 55 'float sum10f(float a,float b,float c,float d,float e,float f,float g,float h,float i,float j){return a+b+c+d+e+f+g+h+i+j;} int main(){return (int)sum10f(1,2,3,4,5,6,7,8,9,10);}'
assert_abi 79 'int mixed(int a,int b,int c,int d,int e,int f,double d1,double d2,double d3,double d4,double d5,double d6,double d7,double d8,int g,double d9){return g*10+(int)d9;} int main(){return mixed(1,2,3,4,5,6,1,2,3,4,5,6,7,8,7,9);}'
assert_abi 12 'int f(int a,int b,int c,int d,int e,int f,int g,double x){return g+(int)x;} int main(){return f(1,2,3,4,5,6,7,5);}'
assert_abi 14 'int f(double a,double b,double c,double d,double e,double f,double g,double h,double i,int x){return (int)i+x;} int main(){return f(1,2,3,4,5,6,7,8,9,5);}'
assert_abi 56 'int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;} int main(){return sum7(1,2,3,4,5,6,7)+sum7(1,2,3,4,5,6,7);}'
assert_abi 28 'int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;} int main(){int (*fp)(int,int,int,int,int,int,int)=sum7; return fp(1,2,3,4,5,6,7);}'
assert_abi 7 'int sprintf(char *str, char *fmt, ...); int main(){char buf[32]; sprintf(buf,"%d%d%d%d%d%d%d",1,2,3,4,5,6,7); return buf[6]-48;}'
assert_abi 28 'int sum7(int,int,int,int,int,int,int); int main(){return sum7(1,2,3,4,5,6,7);} int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;}'
assert_abi 250 'int pick(unsigned char a,unsigned char b,unsigned char c,unsigned char d,unsigned char e,unsigned char f,unsigned char g){return g;} int main(){return pick(1,2,3,4,5,6,250);}'
assert_abi 18 'float last9(float a,float b,float c,float d,float e,float f,float g,float h,float i){return i*2.0f;} int main(){return (int)last9(1,2,3,4,5,6,7,8,9);}'
assert_abi 100 'double last2(double a,double b,double c,double d,double e,double f,double g,double h,double i,double j){return i*10+j;} int main(){return (int)last2(1,2,3,4,5,6,7,8,9,10);}'

echo "All SysV stack-argument ABI tests passed!"
''')

readme = Path("README.md")
r = readme.read_text()
old = '- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and non-variadic function arguments/returns using SysV SSE registers. Direct calls use declared parameter types for scalar coercion; external variadic calls receive the required vector-register count and default float promotion. The built-in educational `va_list` implementation remains integer-only.\n'
new = '- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and function arguments/returns using the SysV AMD64 register/stack convention. Integer and SSE register classes exhaust independently, with overflow arguments passed on the caller stack. Direct calls use declared parameter types for scalar coercion; external variadic calls receive the required vector-register count and default float promotion. The built-in educational `va_list` implementation remains integer-only.\n'
if old not in r:
    raise SystemExit("README floating point line not found")
readme.write_text(r.replace(old, new, 1))

print("SysV stack argument migration applied")
