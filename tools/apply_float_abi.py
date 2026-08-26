from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}\n--- pattern ---\n{old}")
    p.write_text(text.replace(old, new, 1))


# Carry function prototype metadata on function symbols and return types on
# function definitions.
replace_once(
    "minicc.h",
    '''    // Flags
    bool is_function;  // true = function symbol (not a variable)
    bool is_static;    // static storage class
    bool is_extern;    // extern storage class
};
''',
    '''    // Function-symbol metadata
    Obj *func_params;    // declared named parameters for direct-call coercion
    bool func_variadic;  // function declaration has an ellipsis

    // Flags
    bool is_function;  // true = function symbol (not a variable)
    bool is_static;    // static storage class
    bool is_extern;    // extern storage class
};
''')
replace_once(
    "minicc.h",
    '''    Obj *params;   // Parameters
    Node *body;
''',
    '''    Obj *params;   // Parameters
    Type *return_ty; // Function return type
    Node *body;
''')

# Direct/indirect calls remember their floating return type. Direct calls also
# coerce named arguments to the declared parameter types and apply the default
# float->double promotion to variadic arguments.
replace_once(
    "parse.c",
    '''            if (var && !var->is_function) {
                // Indirect call through function pointer variable
                Node *node = new_node(ND_FUNCALL);
                node->funcname = NULL; // NULL = indirect call
                node->lhs = new_var_node(var); // callee expression
                tok = skip(tok->next, "(");

                Node head = {};
                Node *cur = &head;
                while (!equal(tok, ")")) {
                    if (cur != &head) tok = skip(tok, ",");
                    cur = cur->next = assign(&tok, tok);
                }
                *rest = skip(tok, ")");
                node->args = head.next;
                return node;
            }

            // Direct call
            Node *node = new_node(ND_FUNCALL);
            node->funcname = strndup(tok->loc, tok->len);
            tok = skip(tok->next, "(");

            Node head = {};
            Node *cur = &head;
            while (!equal(tok, ")")) {
                if (cur != &head)
                    tok = skip(tok, ",");
                cur = cur->next = assign(&tok, tok);
            }
            *rest = skip(tok, ")");
            node->args = head.next;
            return node;
''',
    '''            if (var && !var->is_function) {
                // Indirect call through function pointer variable. The current
                // declarator keeps the return type even though it does not yet
                // retain a full function-pointer parameter prototype.
                Node *node = new_node(ND_FUNCALL);
                node->funcname = NULL; // NULL = indirect call
                node->lhs = new_var_node(var); // callee expression
                if (var->ty->kind == TY_PTR && var->ty->base &&
                    var->ty->base->kind == TY_FUNC)
                    node->ty = var->ty->base->return_ty;
                tok = skip(tok->next, "(");

                Node head = {};
                Node *cur = &head;
                while (!equal(tok, ")")) {
                    if (cur != &head) tok = skip(tok, ",");
                    cur = cur->next = assign(&tok, tok);
                }
                *rest = skip(tok, ")");
                node->args = head.next;
                return node;
            }

            // Direct call
            Node *node = new_node(ND_FUNCALL);
            node->funcname = strndup(tok->loc, tok->len);
            if (var && var->is_function && var->ty->kind == TY_FUNC)
                node->ty = var->ty->return_ty;
            tok = skip(tok->next, "(");

            Obj *expected = (var && var->is_function) ? var->func_params : NULL;
            bool variadic = var && var->is_function && var->func_variadic;
            Node head = {};
            Node *cur = &head;
            while (!equal(tok, ")")) {
                if (cur != &head)
                    tok = skip(tok, ",");

                Node *arg = assign(&tok, tok);
                add_type(arg);

                if (expected) {
                    if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                        arg->ty != expected->ty) {
                        Node *cast = new_unary(ND_CAST, arg);
                        cast->ty = expected->ty;
                        arg = cast;
                    }
                    expected = expected->param_next;
                } else if (variadic) {
                    // C default argument promotions for the scalar subset.
                    Type *promoted = NULL;
                    if (arg->ty->kind == TY_FLOAT)
                        promoted = ty_double;
                    else if (arg->ty->kind == TY_BOOL || arg->ty->kind == TY_CHAR ||
                             arg->ty->kind == TY_SHORT)
                        promoted = ty_int;
                    if (promoted) {
                        Node *cast = new_unary(ND_CAST, arg);
                        cast->ty = promoted;
                        arg = cast;
                    }
                }

                cur = cur->next = arg;
            }
            *rest = skip(tok, ")");
            node->args = head.next;
            return node;
''')

# Preserve prototype parameter metadata on the function symbol.
replace_once(
    "parse.c",
    '''static void register_function_symbol(char *name, Type *return_ty, bool is_static) {
    // Check if already registered
    for (Obj *var = globals; var; var = var->next)
        if (!strcmp(var->name, name) && var->is_function)
            return;

    Obj *fn_obj = calloc(1, sizeof(Obj));
    fn_obj->name = name;
    fn_obj->ty = func_type(return_ty);
    fn_obj->is_local = false;
    fn_obj->is_function = true;
    fn_obj->is_static = is_static;
    fn_obj->next = globals;
    globals = fn_obj;
}
''',
    '''static void register_function_symbol(char *name, Type *return_ty, bool is_static,
                                     Obj *params, bool is_variadic) {
    // A later definition refreshes metadata from an earlier prototype.
    for (Obj *var = globals; var; var = var->next) {
        if (!strcmp(var->name, name) && var->is_function) {
            var->ty = func_type(return_ty);
            var->func_params = params;
            var->func_variadic = is_variadic;
            var->is_static = is_static;
            return;
        }
    }

    Obj *fn_obj = calloc(1, sizeof(Obj));
    fn_obj->name = name;
    fn_obj->ty = func_type(return_ty);
    fn_obj->func_params = params;
    fn_obj->func_variadic = is_variadic;
    fn_obj->is_local = false;
    fn_obj->is_function = true;
    fn_obj->is_static = is_static;
    fn_obj->next = globals;
    globals = fn_obj;
}
''')
replace_once(
    "parse.c",
    '''            // Register function symbol for function pointer usage
            register_function_symbol(name, basety, is_static);
''',
    '''            // Register function symbol for calls and function-pointer usage.
            register_function_symbol(name, basety, is_static,
                                     param_head.param_next, is_variadic);
''')
replace_once(
    "parse.c",
    '''            fn->name = name;
            fn->params = param_head.param_next;
            fn->is_static = is_static;
''',
    '''            fn->name = name;
            fn->params = param_head.param_next;
            fn->return_ty = basety;
            fn->is_static = is_static;
''')

# Codegen tracks the declared return type of the current function.
replace_once(
    "codegen.c",
    '''static char *current_fn;
static char *brk_label;
''',
    '''static char *current_fn;
static Type *current_return_ty;
static char *brk_label;
''')

# SysV AMD64 uses independent integer and SSE register sequences. Evaluate
# arguments left-to-right, spill them, then reload in reverse into their
# independently assigned ABI registers.
replace_once(
    "codegen.c",
    '''// Generate a function call (direct or indirect via function pointer)
static void gen_funcall(Node *node) {
    bool indirect = (node->funcname == NULL);

    // For indirect calls, evaluate callee first and save to stack
    if (indirect) {
        gen_expr(node->lhs);
        push(); // save function address on stack
    }

    int nargs = 0;
    for (Node *arg = node->args; arg; arg = arg->next) {
        gen_expr(arg);
        push();
        nargs++;
    }
    if (nargs > 6)
        error("too many arguments");

    for (int i = nargs - 1; i >= 0; i--)
        pop(argreg64[i]);

    int c = count();

    if (indirect) {
        // Pop callee address into %r10
        pop("%r10");
        printf("  mov %%rsp, %%rax\\n");
        printf("  and $15, %%rax\\n");
        printf("  jnz .L.call.%d\\n", c);
        printf("  mov $0, %%rax\\n");
        printf("  call *%%r10\\n");
        printf("  jmp .L.end.%d\\n", c);
        printf(".L.call.%d:\\n", c);
        printf("  sub $8, %%rsp\\n");
        printf("  mov $0, %%rax\\n");
        printf("  call *%%r10\\n");
        printf("  add $8, %%rsp\\n");
        printf(".L.end.%d:\\n", c);
    } else {
        printf("  mov %%rsp, %%rax\\n");
        printf("  and $15, %%rax\\n");
        printf("  jnz .L.call.%d\\n", c);
        printf("  mov $0, %%rax\\n");
        printf("  call %s\\n", node->funcname);
        printf("  jmp .L.end.%d\\n", c);
        printf(".L.call.%d:\\n", c);
        printf("  sub $8, %%rsp\\n");
        printf("  mov $0, %%rax\\n");
        printf("  call %s\\n", node->funcname);
        printf("  add $8, %%rsp\\n");
        printf(".L.end.%d:\\n", c);
    }
}
''',
    '''// Generate a function call (direct or indirect via function pointer).
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

    printf("  mov %%rsp, %%rax\\n");
    printf("  and $15, %%rax\\n");
    printf("  jnz .L.call.%d\\n", c);
    // For variadic callees, SysV requires AL to contain the number of vector
    // registers used. Non-variadic callees ignore it.
    printf("  mov $%d, %%eax\\n", fp_count);
    if (indirect)
        printf("  call *%%r10\\n");
    else
        printf("  call %s\\n", node->funcname);
    printf("  jmp .L.end.%d\\n", c);
    printf(".L.call.%d:\\n", c);
    printf("  sub $8, %%rsp\\n");
    printf("  mov $%d, %%eax\\n", fp_count);
    if (indirect)
        printf("  call *%%r10\\n");
    else
        printf("  call %s\\n", node->funcname);
    printf("  add $8, %%rsp\\n");
    printf(".L.end.%d:\\n", c);
}
''')

# Return expressions are converted to the function's declared return type.
replace_once(
    "codegen.c",
    '''    if (node->kind == ND_RETURN) {
        if (node->lhs) gen_expr(node->lhs);
        printf("  jmp .L.return.%s\\n", current_fn);
        return;
    }
''',
    '''    if (node->kind == ND_RETURN) {
        if (node->lhs) {
            gen_expr(node->lhs);
            cast_value(node->lhs->ty, current_return_ty);
        }
        printf("  jmp .L.return.%s\\n", current_fn);
        return;
    }
''')

# Complete the previously missed floating for-loop condition path.
replace_once(
    "codegen.c",
    '''        if (node->cond) {
            gen_expr(node->cond);
            printf("  cmp $0, %%rax\\n");
            printf("  je  .L.end.%d\\n", c);
        }
''',
    '''        if (node->cond) {
            gen_expr(node->cond);
            value_to_bool(node->cond->ty);
            printf("  cmp $0, %%rax\\n");
            printf("  je  .L.end.%d\\n", c);
        }
''')

# Callee prologue: independent GPR/SSE parameter register counters.
replace_once(
    "codegen.c",
    '''        } else {
            // Save passed-by-register arguments to the stack
            int i = 0;
            for (Obj *var = fn->params; var; var = var->param_next) {
                if (i >= 6)
                    error("too many parameters");
                if (var->ty->kind == TY_BOOL || var->ty->kind == TY_CHAR)
                    printf("  mov %s, %d(%%rbp)\\n", argreg8[i++], var->offset);
                else if (var->ty->kind == TY_SHORT)
                    printf("  mov %s, %d(%%rbp)\\n", argreg16[i++], var->offset);
                else if (var->ty->kind == TY_INT)
                    printf("  mov %s, %d(%%rbp)\\n", argreg32[i++], var->offset);
                else
                    printf("  mov %s, %d(%%rbp)\\n", argreg64[i++], var->offset);
            }
        }
''',
    '''        } else {
            // Save passed-by-register arguments to the stack. Integer and SSE
            // register numbers advance independently under SysV AMD64.
            int gp = 0;
            int fp = 0;
            for (Obj *var = fn->params; var; var = var->param_next) {
                if (is_flonum(var->ty)) {
                    if (fp >= 8)
                        error("too many floating-point parameters");
                    if (var->ty->kind == TY_FLOAT)
                        printf("  movss %%xmm%d, %d(%%rbp)\\n", fp, var->offset);
                    else
                        printf("  movsd %%xmm%d, %d(%%rbp)\\n", fp, var->offset);
                    fp++;
                    continue;
                }

                if (gp >= 6)
                    error("too many integer parameters");
                if (var->ty->kind == TY_BOOL || var->ty->kind == TY_CHAR)
                    printf("  mov %s, %d(%%rbp)\\n", argreg8[gp++], var->offset);
                else if (var->ty->kind == TY_SHORT)
                    printf("  mov %s, %d(%%rbp)\\n", argreg16[gp++], var->offset);
                else if (var->ty->kind == TY_INT)
                    printf("  mov %s, %d(%%rbp)\\n", argreg32[gp++], var->offset);
                else
                    printf("  mov %s, %d(%%rbp)\\n", argreg64[gp++], var->offset);
            }
        }
''')

replace_once(
    "codegen.c",
    '''        printf("%s:\\n", fn->name);
        current_fn = fn->name;

        // Prologue
''',
    '''        printf("%s:\\n", fn->name);
        current_fn = fn->name;
        current_return_ty = fn->return_ty;

        // Prologue
''')

# ABI regression suite, including an external variadic libc call.
Path("test/float_abi.sh").write_text(r'''#!/bin/bash
set -e

assert_abi() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-float-abi.c
  "${MINICC:-./minicc}" tmp-float-abi.c > tmp-float-abi.s
  gcc -o tmp-float-abi tmp-float-abi.s
  set +e
  ./tmp-float-abi
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(float ABI): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(float ABI): $actual"
}

assert_abi 4 'double add(double a, double b) { return a+b; } int main() { return (int)add(1.5,2.5); }'
assert_abi 6 'float mul(float a, float b) { return a*b; } int main() { return (int)mul(2.0f,3.0f); }'
assert_abi 11 'double mix(int a, double b, int c, float d) { return a+b+c+d; } int main() { return (int)mix(1,2.5,3,4.5f); }'
assert_abi 3 'double ret() { return 3.75; } int main() { return (int)ret(); }'
assert_abi 5 'float retf() { return 2.5f; } int main() { return (int)(retf()*2.0f); }'
assert_abi 6 'double twice(double x) { return x*2.0; } int main() { return (int)twice(3); }'
assert_abi 3 'float idf(float x) { return x; } int main() { return (int)idf(3.75); }'
assert_abi 5 'double twice(double x); int main() { return (int)twice(2.5); } double twice(double x) { return x*2.0; }'
assert_abi 5 'double twice(double x) { return x*2.0; } int main() { double (*fp)(double)=twice; return (int)fp(2.5); }'
assert_abi 28 'double many(int a,double b,int c,double d,int e,double f,int g) { return a+b+c+d+e+f+g; } int main() { return (int)many(1,2.0,3,4.0,5,6.0,7); }'
assert_abi 36 'double sum8(double a,double b,double c,double d,double e,double f,double g,double h) { return a+b+c+d+e+f+g+h; } int main() { return (int)sum8(1,2,3,4,5,6,7,8); }'
assert_abi 2 'int main() { double x=2.0; int n=0; for (;x;x-=1.0) n++; return n; }'
assert_abi 1 '#include <stdio.h>
int main() { char buf[32]; int n=sprintf(buf,"%.1f",2.5); return n==3 && buf[0]=='"'"'2'"'"' && buf[1]=='"'"'.'"'"' && buf[2]=='"'"'5'"'"'; }'
assert_abi 1 '#include <stdio.h>
int main() { char buf[32]; float x=2.5f; int n=sprintf(buf,"%.1f",x); return n==3 && buf[0]=='"'"'2'"'"' && buf[2]=='"'"'5'"'"'; }'

# Existing integer-only generated variadic functions remain supported.
assert_abi 10 '#include <stdarg.h>
int sum(int count, ...) { va_list ap; va_start(ap,count); int s=0; for(int i=0;i<count;i++) s+=va_arg(ap,int); va_end(ap); return s; }
int main() { return sum(4,1,2,3,4); }'

echo "All floating-point ABI tests passed!"
''')

replace_once(
    "Makefile",
    '''\tbash ./test/float.sh\n''',
    '''\tbash ./test/float.sh\n\tbash ./test/float_abi.sh\n''')

replace_once(
    "README.md",
    '''- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, and scalar global/static initializers. Floating-point function arguments/returns are not yet supported.\n''',
    '''- **Floating point**: scalar `float`/`double` literals, variables, arithmetic, comparisons, casts, truth tests, compound assignment, increment/decrement, scalar global/static initializers, and non-variadic function arguments/returns using SysV SSE registers. Direct calls use declared parameter types for scalar coercion; external variadic calls receive the required vector-register count and default float promotion. The built-in educational `va_list` implementation remains integer-only.\n''')

print("floating-point SysV ABI migration applied")
