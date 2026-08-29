from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# ---- minicc.h: persist TLS metadata on canonical objects ----
p = Path('minicc.h').read_text()
p = replace_once(
    p,
    '''    bool is_static;    // static storage class\n    bool is_extern;    // extern storage class\n    bool is_register;  // register storage class; address may not be taken\n    bool is_defined;   // function symbol already has a body\n''',
    '''    bool is_static;    // static storage class\n    bool is_extern;    // extern storage class\n    bool is_register;  // register storage class; address may not be taken\n    bool is_thread_local; // C11 _Thread_local storage duration\n    bool is_defined;   // function symbol already has a body\n''',
    'Obj thread-local flag',
)
Path('minicc.h').write_text(p)


# ---- tokenize.c: recognize the C11 keyword ----
p = Path('tokenize.c').read_text()
p = replace_once(
    p,
    '''                         "inline", "register", "_Bool", "float", "double",\n                         "_Alignas", "_Noreturn"};\n''',
    '''                         "inline", "register", "_Bool", "float", "double",\n                         "_Alignas", "_Noreturn", "_Thread_local"};\n''',
    'tokenizer _Thread_local keyword',
)
Path('tokenize.c').write_text(p)


# ---- parse.c: storage-class semantics, redeclarations, and static init safety ----
p = Path('parse.c').read_text()

p = replace_once(
    p,
    '''    bool is_extern;\n    bool is_register;\n    bool is_typedef;\n''',
    '''    bool is_extern;\n    bool is_register;\n    bool is_thread_local;\n    bool is_typedef;\n''',
    'DeclAttrs thread-local flag',
)

p = replace_once(
    p,
    '''    if (equal(tok, "register") || equal(tok, "inline")) return true;\n    if (equal(tok, "_Alignas") || equal(tok, "_Noreturn")) return true;\n''',
    '''    if (equal(tok, "register") || equal(tok, "inline") ||\n        equal(tok, "_Thread_local")) return true;\n    if (equal(tok, "_Alignas") || equal(tok, "_Noreturn")) return true;\n''',
    'declaration start _Thread_local',
)

p = replace_once(
    p,
    '''        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||\n            attrs.is_typedef || attrs.is_inline || attrs.is_noreturn)\n''',
    '''        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||\n            attrs.is_thread_local || attrs.is_typedef || attrs.is_inline || attrs.is_noreturn)\n''',
    'record member thread-local rejection',
)

p = replace_once(
    p,
    '''        Token *storage_tok = tok;\n        if (consume(&tok, tok, "auto")) {\n''',
    '''        Token *thread_tok = tok;\n        if (consume(&tok, tok, "_Thread_local")) {\n            if (!attrs)\n                error_at(thread_tok->loc,\n                         "_Thread_local is not allowed in this declaration context");\n            if (attrs->is_thread_local)\n                error_at(thread_tok->loc, "duplicate _Thread_local storage-class specifier");\n            attrs->is_thread_local = true;\n            continue;\n        }\n\n        Token *storage_tok = tok;\n        if (consume(&tok, tok, "auto")) {\n''',
    'parse _Thread_local storage class',
)

p = replace_once(
    p,
    '''        if (param_attrs.storage_class_count && !param_attrs.is_register)\n            error_at(param_spec->loc,\n                     "only register storage class is allowed on a parameter");\n''',
    '''        if (param_attrs.is_thread_local ||\n            (param_attrs.storage_class_count && !param_attrs.is_register))\n            error_at(param_spec->loc,\n                     "only register storage class is allowed on a parameter");\n''',
    'parameter thread-local rejection',
)

p = replace_once(
    p,
    '''static Obj *create_extern_ref(char *name, Type *ty) {\n''',
    '''static Obj *create_extern_ref(char *name, Type *ty, bool is_thread_local) {\n''',
    'extern ref signature',
)

p = replace_once(
    p,
    '''    bool wants_function = ty->kind == TY_FUNC;\n    VarScope *same_scope = find_var_name_in_scope(current_scope, name);\n''',
    '''    bool wants_function = ty->kind == TY_FUNC;\n    if (wants_function && is_thread_local)\n        error("_Thread_local may only declare an object");\n    VarScope *same_scope = find_var_name_in_scope(current_scope, name);\n''',
    'extern ref defensive function check',
)

p = replace_once(
    p,
    '''        if (wants_function)\n            check_oldstyle_definition_redeclaration(old, ty, false, name);\n        if (!type_compatible(old->ty, ty))\n''',
    '''        if (wants_function)\n            check_oldstyle_definition_redeclaration(old, ty, false, name);\n        if (!wants_function && old->is_thread_local != is_thread_local)\n            error("inconsistent _Thread_local redeclaration of '%s'", name);\n        if (!type_compatible(old->ty, ty))\n''',
    'same-scope extern TLS mismatch',
)

p = replace_once(
    p,
    '''        if (wants_function)\n            check_oldstyle_definition_redeclaration(var, ty, false, name);\n        if (!type_compatible(var->ty, ty))\n''',
    '''        if (wants_function)\n            check_oldstyle_definition_redeclaration(var, ty, false, name);\n        if (!wants_function && var->is_thread_local != is_thread_local)\n            error("inconsistent _Thread_local redeclaration of '%s'", name);\n        if (!type_compatible(var->ty, ty))\n''',
    'global extern TLS mismatch',
)

p = replace_once(
    p,
    '''        var->is_local = false;\n        var->is_extern = true;\n        var->is_function = wants_function;\n''',
    '''        var->is_local = false;\n        var->is_extern = true;\n        var->is_function = wants_function;\n        var->is_thread_local = is_thread_local;\n''',
    'new extern TLS metadata',
)

p = replace_once(
    p,
    '''static Token *parse_typedef_declaration(Token *tok, Type *basety,\n                                        DeclAttrs *attrs) {\n    if (attrs->align)\n        error_at(tok->loc, "_Alignas is not allowed on a typedef declaration");\n''',
    '''static Token *parse_typedef_declaration(Token *tok, Type *basety,\n                                        DeclAttrs *attrs) {\n    if (attrs->align)\n        error_at(tok->loc, "_Alignas is not allowed on a typedef declaration");\n    if (attrs->is_thread_local)\n        error_at(tok->loc, "_Thread_local is not allowed on a typedef declaration");\n''',
    'typedef thread-local rejection',
)

p = replace_once(
    p,
    '''    bool is_static = attrs.is_static;\n    bool is_extern = attrs.is_extern;\n    if (is_static && is_extern)\n        error_at(tok->loc, "declaration cannot be both static and extern");\n    if (attrs.align && attrs.is_register)\n''',
    '''    bool is_static = attrs.is_static;\n    bool is_extern = attrs.is_extern;\n    if (is_static && is_extern)\n        error_at(tok->loc, "declaration cannot be both static and extern");\n    if (attrs.is_thread_local && (attrs.is_auto || attrs.is_register))\n        error_at(tok->loc,\n                 "_Thread_local may be combined only with static or extern storage class");\n    if (attrs.is_thread_local && !is_static && !is_extern)\n        error_at(tok->loc,\n                 "block-scope _Thread_local declaration requires static or extern");\n    if (attrs.align && attrs.is_register)\n''',
    'block-scope TLS storage constraints',
)

p = replace_once(
    p,
    '''    if (equal(tok, ";")) {\n        if (attrs.storage_class_count)\n            error_at(tok->loc, "storage class specifier requires a declarator");\n''',
    '''    if (equal(tok, ";")) {\n        if (attrs.storage_class_count || attrs.is_thread_local)\n            error_at(tok->loc, "storage class specifier requires a declarator");\n''',
    'block standalone TLS declaration',
)

p = replace_once(
    p,
    '''        if (ty->kind == TY_FUNC) {\n            if (attrs.is_auto || attrs.is_register || is_static)\n                error_at(ident->loc,\n                         "block-scope function declaration may only use extern storage class");\n            var = create_extern_ref(name, ty);\n''',
    '''        if (ty->kind == TY_FUNC) {\n            if (attrs.is_thread_local)\n                error_at(ident->loc, "_Thread_local may only declare an object");\n            if (attrs.is_auto || attrs.is_register || is_static)\n                error_at(ident->loc,\n                         "block-scope function declaration may only use extern storage class");\n            var = create_extern_ref(name, ty, false);\n''',
    'block function TLS rejection',
)

p = replace_once(
    p,
    '''        } else if (is_extern) {\n            var = create_extern_ref(name, ty);\n        } else {\n''',
    '''        } else if (is_extern) {\n            var = create_extern_ref(name, ty, attrs.is_thread_local);\n        } else {\n''',
    'block extern TLS ref',
)

p = replace_once(
    p,
    '''        apply_object_alignment(var, ty, attrs.align, ident);\n        var->is_register = attrs.is_register;\n''',
    '''        apply_object_alignment(var, ty, attrs.align, ident);\n        var->is_register = attrs.is_register;\n        var->is_thread_local = attrs.is_thread_local;\n''',
    'block object TLS metadata',
)

# Reject TLS addresses from static initializer relocation paths. Runtime &tls is
# lowered by codegen; it simply is not a link-time address constant in C11.
p = replace_once(
    p,
    '''    case ND_VAR:\n        if (node->var->is_local)\n            error("address of automatic object is not a static address constant");\n        return (StaticAddress){node->var->name, 0};\n''',
    '''    case ND_VAR:\n        if (node->var->is_thread_local)\n            error("address of thread-local object is not a static address constant");\n        if (node->var->is_local)\n            error("address of automatic object is not a static address constant");\n        return (StaticAddress){node->var->name, 0};\n''',
    'static lvalue TLS address rejection',
)

p = replace_once(
    p,
    '''    case ND_VAR:\n        // Array and function designators decay to their link-time addresses.\n        // Reading the value of an ordinary pointer object is not a constant.\n        if (node->var->is_local)\n''',
    '''    case ND_VAR:\n        // Array and function designators decay to their link-time addresses.\n        // Reading the value of an ordinary pointer object is not a constant.\n        if (node->var->is_thread_local)\n            error("thread-local object is not a static address constant");\n        if (node->var->is_local)\n''',
    'static TLS designator rejection',
)

p = replace_once(
    p,
    '''static Obj *register_global_symbol(Token *ident, Type *ty, bool is_static,\n                                   bool is_extern, bool has_storage_class) {\n''',
    '''static Obj *register_global_symbol(Token *ident, Type *ty, bool is_static,\n                                   bool is_extern, bool has_storage_class,\n                                   bool is_thread_local) {\n''',
    'global symbol TLS signature',
)

p = replace_once(
    p,
    '''        if (!type_compatible(var->ty, ty))\n            error_at(ident->loc, "conflicting types for '%s'", name);\n        if (is_static && !var->is_static)\n''',
    '''        if (!type_compatible(var->ty, ty))\n            error_at(ident->loc, "conflicting types for '%s'", name);\n        if (var->is_thread_local != is_thread_local)\n            error_at(ident->loc,\n                     "inconsistent _Thread_local redeclaration of '%s'", name);\n        if (is_static && !var->is_static)\n''',
    'global symbol TLS redeclaration check',
)

p = replace_once(
    p,
    '''    var->is_static = is_static;\n    var->is_extern = is_extern;\n    var->next = globals;\n''',
    '''    var->is_static = is_static;\n    var->is_extern = is_extern;\n    var->is_thread_local = is_thread_local;\n    var->next = globals;\n''',
    'new global TLS metadata',
)

# File-scope declaration semantics. _Thread_local alone has external linkage;
# static/extern may accompany it, while auto/register/typedef/function may not.
p = replace_once(
    p,
    '''        if (attrs.is_register)\n            error_at(tok->loc, "register storage class is not allowed at file scope");\n\n        // Standalone type declaration\n        if (consume(&tok, tok, ";")) {\n            if (attrs.storage_class_count)\n''',
    '''        if (attrs.is_register)\n            error_at(tok->loc, "register storage class is not allowed at file scope");\n\n        // Standalone type declaration\n        if (consume(&tok, tok, ";")) {\n            if (attrs.storage_class_count || attrs.is_thread_local)\n''',
    'file standalone TLS declaration',
)

p = replace_once(
    p,
    '''        if (ty->kind == TY_FUNC) {\n            if (attrs.align)\n                error_at(ident->loc, "_Alignas is not allowed on a function declaration");\n''',
    '''        if (ty->kind == TY_FUNC) {\n            if (attrs.is_thread_local)\n                error_at(ident->loc, "_Thread_local may only declare an object");\n            if (attrs.align)\n                error_at(ident->loc, "_Alignas is not allowed on a function declaration");\n''',
    'file function TLS rejection',
)

p = replace_once(
    p,
    '''                Obj *var = register_global_symbol(ident, ty, is_static, is_extern,\n                                                  attrs.storage_class_count != 0);\n''',
    '''                Obj *var = register_global_symbol(ident, ty, is_static, is_extern,\n                                                  attrs.storage_class_count != 0,\n                                                  attrs.is_thread_local);\n''',
    'global symbol TLS registration',
)

Path('parse.c').write_text(p)


# ---- codegen.c: x86-64 ELF local-exec TLS addressing and TLS sections ----
p = Path('codegen.c').read_text()

p = replace_once(
    p,
    '''    if (node->kind == ND_VAR) {\n        if (node->var->is_local)\n            printf("  lea %d(%%rbp), %%rax\\n", node->var->offset);\n        else if (node->var->is_function && !node->var->is_static)\n''',
    '''    if (node->kind == ND_VAR) {\n        if (node->var->is_local)\n            printf("  lea %d(%%rbp), %%rax\\n", node->var->offset);\n        else if (node->var->is_thread_local) {\n            // Linux x86-64 local-exec TLS: obtain the thread pointer from FS\n            // and add the linker's per-symbol TPOFF relocation. This works for\n            // executable-local definitions and external TLS symbols resolved at\n            // final link time.\n            printf("  mov %%fs:0, %%rax\\n");\n            printf("  lea %s@tpoff(%%rax), %%rax\\n", node->var->name);\n        }\n        else if (node->var->is_function && !node->var->is_static)\n''',
    'TLS address lowering',
)

p = replace_once(
    p,
    '''static void emit_data_alignment(Obj *var) {\n    int align = var->align > 0 ? var->align\n                               : (var->ty && var->ty->align > 0 ? var->ty->align : 1);\n    if (align > 1)\n        printf("  .balign %d\\n", align);\n}\n\nstatic void assign_lvar_offsets(Program *prog) {\n''',
    '''static void emit_data_alignment(Obj *var) {\n    int align = var->align > 0 ? var->align\n                               : (var->ty && var->ty->align > 0 ? var->ty->align : 1);\n    if (align > 1)\n        printf("  .balign %d\\n", align);\n}\n\nstatic void emit_object_section(Obj *var, bool initialized) {\n    if (var->is_thread_local) {\n        if (initialized)\n            printf("  .section .tdata,\\\"awT\\\",@progbits\\n");\n        else\n            printf("  .section .tbss,\\\"awT\\\",@nobits\\n");\n        return;\n    }\n    printf("  .data\\n");\n}\n\nstatic void assign_lvar_offsets(Program *prog) {\n''',
    'TLS section helper',
)

p = replace_once(
    p,
    '''        if (var->init_image) {\n            printf("  .data\\n");\n''',
    '''        if (var->init_image) {\n            emit_object_section(var, true);\n''',
    'TLS init image section',
)

p = replace_once(
    p,
    '''            else {\n                printf("  .data\\n");\n                if (!var->is_static)\n''',
    '''            else {\n                emit_object_section(var, true);\n                if (!var->is_static)\n''',
    'TLS string data section',
)

p = replace_once(
    p,
    '''        } else if (var->init_vals) {\n            printf("  .data\\n");\n''',
    '''        } else if (var->init_vals) {\n            emit_object_section(var, true);\n''',
    'TLS legacy aggregate section',
)

p = replace_once(
    p,
    '''        } else if (var->has_init_reloc) {\n            printf("  .data\\n");\n''',
    '''        } else if (var->has_init_reloc) {\n            emit_object_section(var, true);\n''',
    'TLS relocation section',
)

p = replace_once(
    p,
    '''        } else if (var->has_init_val) {\n            printf("  .data\\n");\n''',
    '''        } else if (var->has_init_val) {\n            emit_object_section(var, true);\n''',
    'TLS scalar section',
)

p = replace_once(
    p,
    '''        } else {\n            printf("  .data\\n");\n            if (!var->is_static)\n                printf("  .globl %s\\n", var->name);\n            emit_data_alignment(var);\n            printf("%s:\\n", var->name);\n            printf("  .zero %d\\n", var->ty->size);\n        }\n''',
    '''        } else {\n            emit_object_section(var, false);\n            if (!var->is_static)\n                printf("  .globl %s\\n", var->name);\n            emit_data_alignment(var);\n            printf("%s:\\n", var->name);\n            printf("  .zero %d\\n", var->ty->size);\n        }\n''',
    'TLS zero section',
)

Path('codegen.c').write_text(p)


# ---- regression suite ----
test = r'''#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-thread-local.c
  "$MINICC" tmp-thread-local.c > tmp-thread-local.s
  cc -pthread -o tmp-thread-local tmp-thread-local.s
  set +e
  ./tmp-thread-local
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(_Thread_local): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-thread-local-bad.c
  if "$MINICC" tmp-thread-local-bad.c > /dev/null 2>tmp-thread-local.err; then
    echo 'FAIL(_Thread_local): expected rejection'
    echo "$input"
    exit 1
  fi
}

# File-scope TLS is real storage with per-thread lifetime and ordinary value/address access.
assert_run 7 '_Thread_local int x=7;int main(void){return x;}'
assert_run 0 '_Thread_local int x;int main(void){return x;}'
assert_run 0 '_Thread_local int a[2]={3,4};int main(void){return a[0]!=3||a[1]!=4;}'
assert_run 0 '_Thread_local char s[]="abc";int main(void){return sizeof(s)!=4||s[2]!=\047c\047||s[3]!=0;}'
assert_run 0 '_Alignas(16) _Thread_local char x;int main(void){return (unsigned long)&x%16;}'
assert_run 0 'static _Thread_local int x=5;int main(void){return x!=5;}'
assert_run 0 '_Thread_local static int x=6;int main(void){return x!=6;}'
assert_run 0 'extern _Thread_local int x;_Thread_local int x=9;int main(void){return x!=9;}'
assert_run 0 'extern _Thread_local int x=10;int main(void){return x!=10;}'
assert_run 0 'static _Thread_local int x=11;extern _Thread_local int x;int main(void){return x!=11;}'

# Block-scope TLS must carry static or extern. Static-local TLS keeps its value
# for the lifetime of the current thread; extern binds the canonical TLS object.
assert_run 0 'int f(void){static _Thread_local int x=2;return ++x;}int main(void){return f()!=3||f()!=4;}'
assert_run 0 '_Thread_local int x=12;int f(void){extern _Thread_local int x;return x;}int main(void){return f()!=12;}'

# A worker starts with the TLS initializer independently from main, and writes
# do not leak back to the main thread.
assert_run 0 'int pthread_create(unsigned long*,void*,void*(*)(void*),void*);int pthread_join(unsigned long,void**);_Thread_local int x=1;void *worker(void *p){if(x!=1)return (void*)1;x=7;return (void*)(long)x;}int main(void){unsigned long t;void *r=0;x=3;if(pthread_create(&t,0,worker,0))return 2;if(pthread_join(t,&r))return 3;return x==3&&(long)r==7?0:4;}'

# Cross-object ELF TLS interoperability: consume a host-defined TLS symbol.
cat > tmp-host-tls-def.c <<'EOF'
_Thread_local int host_tls = 21;
EOF
cc -std=c11 -c tmp-host-tls-def.c -o tmp-host-tls-def.o
printf '%s\n' 'extern _Thread_local int host_tls;int main(void){return host_tls==21?0:1;}' > tmp-thread-local.c
"$MINICC" tmp-thread-local.c > tmp-thread-local.s
cc -o tmp-thread-local tmp-thread-local.s tmp-host-tls-def.o
./tmp-thread-local

# And expose a minicc-defined TLS symbol to host C.
printf '%s\n' '_Thread_local int minicc_tls=22;' > tmp-thread-local.c
"$MINICC" tmp-thread-local.c > tmp-thread-local.s
cc -c tmp-thread-local.s -o tmp-thread-local.o
cat > tmp-host-tls-use.c <<'EOF'
extern _Thread_local int minicc_tls;
int main(void){ return minicc_tls == 22 ? 0 : 1; }
EOF
cc -std=c11 -o tmp-host-tls-use tmp-host-tls-use.c tmp-thread-local.o
./tmp-host-tls-use

# The emitted object must carry true ELF TLS symbols and both initialized and
# zero-initialized TLS sections rather than ordinary .data storage.
printf '%s\n' '_Thread_local int tls_init=4;_Thread_local int tls_zero;int main(void){return tls_init+tls_zero-4;}' > tmp-thread-local.c
"$MINICC" tmp-thread-local.c > tmp-thread-local.s
cc -c tmp-thread-local.s -o tmp-thread-local.o
readelf -sW tmp-thread-local.o | grep -Eq 'TLS[[:space:]]+GLOBAL.*tls_init'
readelf -sW tmp-thread-local.o | grep -Eq 'TLS[[:space:]]+GLOBAL.*tls_zero'
readelf -SW tmp-thread-local.o | grep -q '\.tdata'
readelf -SW tmp-thread-local.o | grep -q '\.tbss'

# C11 storage-class and declaration constraints.
assert_reject '_Thread_local int f(void);int main(void){return 0;}'
assert_reject 'int f(_Thread_local int x){return x;}int main(void){return 0;}'
assert_reject 'struct S{_Thread_local int x;};int main(void){return 0;}'
assert_reject 'typedef _Thread_local int T;int main(void){return 0;}'
assert_reject 'int main(void){_Thread_local int x;return 0;}'
assert_reject 'int main(void){auto _Thread_local int x;return 0;}'
assert_reject 'int main(void){register _Thread_local int x;return 0;}'
assert_reject 'auto _Thread_local int x;int main(void){return 0;}'
assert_reject 'register _Thread_local int x;int main(void){return 0;}'
assert_reject '_Thread_local _Thread_local int x;int main(void){return 0;}'
assert_reject '_Thread_local static extern int x;int main(void){return 0;}'
assert_reject '_Thread_local int;int main(void){return 0;}'

# Every declaration of one object must agree on thread storage duration.
assert_reject '_Thread_local int x;extern int x;int main(void){return 0;}'
assert_reject 'int x;extern _Thread_local int x;int main(void){return 0;}'
assert_reject 'extern _Thread_local int x;extern int x;int main(void){return 0;}'
assert_reject '_Thread_local int x;int f(void){extern int x;return x;}int main(void){return 0;}'
assert_reject 'int x;int f(void){extern _Thread_local int x;return x;}int main(void){return 0;}'

# TLS addresses are runtime values and therefore cannot appear in static
# address-constant initializers.
assert_reject '_Thread_local int x;int *p=&x;int main(void){return 0;}'
assert_reject '_Thread_local int x;_Thread_local int *p=&x;int main(void){return 0;}'

rm -f tmp-thread-local.c tmp-thread-local.s tmp-thread-local tmp-thread-local.o \
      tmp-thread-local-bad.c tmp-thread-local.err tmp-host-tls-def.c \
      tmp-host-tls-def.o tmp-host-tls-use.c tmp-host-tls-use

echo 'All _Thread_local tests passed!'
'''
Path('test/thread_local.sh').write_text(test)

# Make the TLS regression part of the ordinary full suite.
p = Path('Makefile').read_text()
p = replace_once(
    p,
    '''\tbash ./test/storage_class_specifiers.sh\n\tbash ./test/register_addressability.sh\n''',
    '''\tbash ./test/storage_class_specifiers.sh\n\tbash ./test/register_addressability.sh\n\tbash ./test/thread_local.sh\n''',
    'Makefile TLS test',
)
Path('Makefile').write_text(p)

# Document real TLS support and the selected ELF model.
p = Path('README.md').read_text()
old = 'block-scope `auto`/`register` objects with single-storage-class constraint checking, C address-taking restrictions for register objects/parameters, and strict diagnostics for register-array value conversions that require an address, C11 `_Noreturn` function declarations'
new = 'block-scope `auto`/`register` objects with single-storage-class constraint checking, C address-taking restrictions for register objects/parameters, strict diagnostics for register-array value conversions that require an address, real C11 `_Thread_local` objects (file scope plus `static`/`extern` block scope) lowered to Linux x86-64 ELF `.tdata`/`.tbss` with local-exec TLS addressing, C11 `_Noreturn` function declarations'
p = replace_once(p, old, new, 'README TLS declaration feature')
Path('README.md').write_text(p)
