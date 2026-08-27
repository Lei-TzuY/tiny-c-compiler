from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"{path}: expected one anchor, found {n}")
    p.write_text(s.replace(old, new, 1))

# Public AST/function metadata for compiler-backed SysV va_list operations.
replace_once('minicc.h', '''    ND_FUNCALL,   // Function call\n    ND_ADDR,      // & (address-of)\n''', '''    ND_FUNCALL,   // Function call\n    ND_VA_START,  // compiler-backed va_start\n    ND_VA_ARG,    // compiler-backed typed va_arg\n    ND_ADDR,      // & (address-of)\n''')
replace_once('minicc.h', '''    bool is_variadic;\n    int va_offset;\n    Node *gotos;''', '''    bool is_variadic;\n    int va_offset;       // SysV register-save area base, relative to RBP\n    int va_gp_offset;    // initial gp_offset for va_start\n    int va_fp_offset;    // initial fp_offset for va_start\n    int va_stack_offset; // first unnamed stack arg, relative to RBP\n    Node *gotos;''')

# Builtin stdarg header: expose a SysV-shaped va_list state object and lower
# operations through compiler builtins so va_arg can select GP vs SSE classes.
replace_once('preprocess_v2.c', '''    if (!strcmp(name, "stdarg.h")) {\n        return "typedef char *va_list;\\n"\n               "#define va_start(ap, last) ((ap) = (char*)&(last) + 8)\\n"\n               "#define va_arg(ap, type) (*(type*)((ap) += 8, (ap) - 8))\\n"\n               "#define va_end(ap) ((void)0)\\n";\n    }\n''', '''    if (!strcmp(name, "stdarg.h")) {\n        return "typedef struct __minicc_va_list {\\n"\n               "  unsigned int gp_offset;\\n"\n               "  unsigned int fp_offset;\\n"\n               "  void *overflow_arg_area;\\n"\n               "  void *reg_save_area;\\n"\n               "} va_list;\\n"\n               "#define va_start(ap, last) __builtin_va_start(&(ap))\\n"\n               "#define va_arg(ap, type) __builtin_va_arg(&(ap), type)\\n"\n               "#define va_end(ap) ((void)0)\\n";\n    }\n''')

# Parser: track whether builtins occur in a variadic function and parse typed
# va_arg's second operand as a type-name rather than an expression.
replace_once('parse.c', '''static Type *current_return_ty;\n''', '''static Type *current_return_ty;\nstatic bool current_function_variadic;\n''')

primary_anchor = '''static Node *primary(Token **rest, Token *tok) {\n    if (equal(tok, "(")) {\n'''
primary_insert = '''static Node *primary(Token **rest, Token *tok) {\n    if (equal(tok, "__builtin_va_start")) {\n        Token *builtin = tok;\n        if (!current_function_variadic)\n            error_at(builtin->loc, "va_start is only valid in a variadic function");\n        tok = skip(tok->next, "(");\n        Node *ap = assign(&tok, tok);\n        add_type(ap);\n        if (!ap->ty || ap->ty->kind != TY_PTR || !ap->ty->base ||\n            ap->ty->base->kind != TY_STRUCT)\n            error_at(builtin->loc, "va_start requires a va_list object");\n        tok = skip(tok, ")");\n        Node *node = new_unary(ND_VA_START, ap);\n        node->ty = ty_void;\n        *rest = tok;\n        return node;\n    }\n\n    if (equal(tok, "__builtin_va_arg")) {\n        Token *builtin = tok;\n        if (!current_function_variadic)\n            error_at(builtin->loc, "va_arg is only valid in a variadic function");\n        tok = skip(tok->next, "(");\n        Node *ap = assign(&tok, tok);\n        add_type(ap);\n        if (!ap->ty || ap->ty->kind != TY_PTR || !ap->ty->base ||\n            ap->ty->base->kind != TY_STRUCT)\n            error_at(builtin->loc, "va_arg requires a va_list object");\n        tok = skip(tok, ",");\n        Type *ty = type_name(&tok, tok);\n        tok = skip(tok, ")");\n\n        // This scalar SysV subset supports the promoted variadic types that\n        // occupy one GP slot or one SSE double slot. Asking for float or a\n        // narrow integer after default argument promotions is a C misuse.\n        bool gp = ty->kind == TY_PTR || (is_integer(ty) && ty->size >= 4);\n        bool fp = ty->kind == TY_DOUBLE;\n        if (!gp && !fp)\n            error_at(builtin->loc, "unsupported or unpromoted type in va_arg");\n\n        Node *node = new_unary(ND_VA_ARG, ap);\n        node->ty = ty;\n        *rest = tok;\n        return node;\n    }\n\n    if (equal(tok, "(")) {\n'''
replace_once('parse.c', primary_anchor, primary_insert)

replace_once('parse.c', '''            Type *saved_return_ty = current_return_ty;\n            current_return_ty = ty->return_ty;\n            Node *block = compound_stmt(&tok, tok);\n            current_return_ty = saved_return_ty;\n''', '''            Type *saved_return_ty = current_return_ty;\n            bool saved_variadic = current_function_variadic;\n            current_return_ty = ty->return_ty;\n            current_function_variadic = ty->is_variadic;\n            Node *block = compound_stmt(&tok, tok);\n            current_return_ty = saved_return_ty;\n            current_function_variadic = saved_variadic;\n''')

# Codegen: reserve the canonical SysV scalar register-save area (48 bytes GP +
# 8*16 bytes SSE), calculate the initial va_list offsets from named parameters,
# and allocate all named params as ordinary locals even in variadic functions.
p = Path('codegen.c')
s = p.read_text()
s = s.replace('static char *current_fn;\n', 'static char *current_fn;\nstatic Function *current_fn_obj;\n', 1)

start = s.index('static void assign_lvar_offsets(Program *prog) {')
end = s.index('static void emit_data(Program *prog) {', start)
assign = r'''static void assign_lvar_offsets(Program *prog) {
    for (Function *fn = prog->fns; fn; fn = fn->next) {
        int offset = 0;

        if (fn->is_variadic) {
            // SysV AMD64 register_save_area: 6 GP slots followed by 8 16-byte
            // SSE slots. RBP is 16-byte aligned here, so -176 is aligned too.
            offset = 176;
            fn->va_offset = -offset;
        }

        for (Obj *var = fn->locals; var; var = var->next) {
            int align = var->ty->align > 0 ? var->ty->align : 1;
            offset += var->ty->size;
            offset = align_up_cg(offset, align);
            var->offset = -offset;
        }

        if (fn->is_variadic) {
            int gp = 0;
            int fp = 0;
            int stack_arg = 0;
            for (Obj *p = fn->params; p; p = p->param_next) {
                if (is_flonum(p->ty)) {
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

'''
s = s[:start] + assign + s[end:]

# Lower compiler-backed va_start/va_arg before ordinary calls.
anchor = '''    if (node->kind == ND_FUNCALL) {\n        gen_funcall(node);\n        return;\n    }\n\n'''
va_codegen = r'''    if (node->kind == ND_VA_START) {
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
        gen_expr(node->lhs); // RAX = &va_list
        printf("  mov %%rax, %%rdi\n");
        int c = count();

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

'''
if anchor not in s:
    raise SystemExit('codegen gen_expr anchor missing')
s = s.replace(anchor, va_codegen, 1)

# Rebuild prologue argument handling: variadic callees first snapshot all incoming
# register classes, then named parameters use the same GP/SSE/stack classifier as
# non-variadic functions.
prologue_start = s.index('        if (fn->is_variadic) {', s.index('// Prologue'))
prologue_end = s.index('\n\n        for (Node *n = fn->body;', prologue_start)
prologue = r'''        if (fn->is_variadic) {
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
        }'''
s = s[:prologue_start] + prologue + s[prologue_end:]
s = s.replace('        current_fn = fn->name;\n        current_return_ty = fn->return_ty;\n', '        current_fn = fn->name;\n        current_fn_obj = fn;\n        current_return_ty = fn->return_ty;\n', 1)
p.write_text(s)

# Regression suite: minicc caller/callee, register and stack overflow, fixed SSE
# named parameters, pointers, and GCC-host caller -> minicc variadic callee ABI.
test = r'''#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-va.c
  ./minicc tmp-va.c > tmp-va.s
  cc -o tmp-va tmp-va.s
  ./tmp-va
  echo "OK(sysv va): minicc caller/callee"
}

compile_and_run <<'EOF'
#include <stdarg.h>
int probe(double fixed, int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int a = va_arg(ap, int);
  double b = va_arg(ap, double);
  long c = va_arg(ap, long);
  double d = va_arg(ap, double);
  int x = 9;
  int *p = va_arg(ap, int *);
  va_end(ap);
  return fixed == 0.5 && tag == 3 && a == 7 && b == 1.5 &&
         c == 11 && d == 2.25 && *p == 9;
}
int main(void) {
  int x = 9;
  return !probe(0.5, 3, 7, 1.5f, 11L, 2.25, &x);
}
EOF

compile_and_run <<'EOF'
#include <stdarg.h>
int overflow(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int i1=va_arg(ap,int), i2=va_arg(ap,int), i3=va_arg(ap,int);
  int i4=va_arg(ap,int), i5=va_arg(ap,int), i6=va_arg(ap,int);
  double d1=va_arg(ap,double), d2=va_arg(ap,double), d3=va_arg(ap,double);
  double d4=va_arg(ap,double), d5=va_arg(ap,double), d6=va_arg(ap,double);
  double d7=va_arg(ap,double), d8=va_arg(ap,double), d9=va_arg(ap,double);
  return i1==1 && i2==2 && i3==3 && i4==4 && i5==5 && i6==6 &&
         d1==1.0 && d2==2.0 && d3==3.0 && d4==4.0 && d5==5.0 &&
         d6==6.0 && d7==7.0 && d8==8.0 && d9==9.0;
}
int main(void) {
  return !overflow(0,1,2,3,4,5,6,1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0);
}
EOF

# Compile variadic callees with minicc and call them from the host compiler.
cat > tmp-va-callee.c <<'EOF'
#include <stdarg.h>
int host_bridge(double fixed, int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int a = va_arg(ap, int);
  double b = va_arg(ap, double);
  unsigned long c = va_arg(ap, unsigned long);
  double d = va_arg(ap, double);
  return fixed==0.25 && tag==4 && a==12 && b==1.75 && c==33UL && d==2.5;
}
int host_overflow(int tag, ...) {
  va_list ap;
  va_start(ap, tag);
  int a1=va_arg(ap,int), a2=va_arg(ap,int), a3=va_arg(ap,int);
  int a4=va_arg(ap,int), a5=va_arg(ap,int), a6=va_arg(ap,int);
  double d1=va_arg(ap,double), d2=va_arg(ap,double), d3=va_arg(ap,double);
  double d4=va_arg(ap,double), d5=va_arg(ap,double), d6=va_arg(ap,double);
  double d7=va_arg(ap,double), d8=va_arg(ap,double), d9=va_arg(ap,double);
  return a1+a2+a3+a4+a5+a6==21 && d1+d2+d3+d4+d5+d6+d7+d8+d9==45.0;
}
EOF
./minicc tmp-va-callee.c > tmp-va-callee.s
cc -c -o tmp-va-callee.o tmp-va-callee.s
cat > tmp-va-host.c <<'EOF'
int host_bridge(double, int, ...);
int host_overflow(int, ...);
int main(void) {
  if (!host_bridge(0.25,4,12,1.75f,33UL,2.5)) return 1;
  if (!host_overflow(0,1,2,3,4,5,6,1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0)) return 2;
  return 0;
}
EOF
cc -o tmp-va-host tmp-va-host.c tmp-va-callee.o
./tmp-va-host
echo "OK(sysv va): host caller -> minicc callee"

# Default promotions make these va_arg requests invalid in a conforming call.
for badtype in float char short; do
  cat > tmp-va-bad.c <<EOF
#include <stdarg.h>
int f(int n, ...) { va_list ap; va_start(ap,n); return va_arg(ap,$badtype); }
EOF
  if ./minicc tmp-va-bad.c >/dev/null 2>&1; then
    echo "expected va_arg($badtype) rejection"
    exit 1
  fi
done

cat > tmp-va-bad.c <<'EOF'
#include <stdarg.h>
int f(void) { va_list ap; va_start(ap, ap); return 0; }
EOF
if ./minicc tmp-va-bad.c >/dev/null 2>&1; then
  echo "expected va_start outside variadic function rejection"
  exit 1
fi

rm -f tmp-va.c tmp-va.s tmp-va tmp-va-callee.c tmp-va-callee.s tmp-va-callee.o tmp-va-host.c tmp-va-host tmp-va-bad.c

echo 'All SysV variadic callee tests passed!'
'''
Path('test/sysv_variadic_callee.sh').write_text(test)
replace_once('Makefile', '\tbash ./test/call_arguments.sh\n', '\tbash ./test/call_arguments.sh\n\tbash ./test/sysv_variadic_callee.sh\n')

p = Path('README.md')
s = p.read_text()
if 'SysV variadic callees' not in s:
    s += '\n- SysV variadic callees use a GP/SSE register-save area and typed compiler-backed `va_start`/`va_arg`, including floating variadic arguments and stack overflow.\n'
p.write_text(s)
