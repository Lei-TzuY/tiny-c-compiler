from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


old_fn = '''// Register a function symbol as a global Obj so it can be used as a value\n// (e.g. function pointer assignment: fp = add;). Redeclarations are checked\n// against the complete recursive function type before metadata is refreshed.\nstatic void register_function_symbol(char *name, Type *return_ty, bool is_static,\n                                     Obj *params, bool is_variadic,\n                                     bool has_prototype, bool is_definition) {\n    Type *fty = func_type(return_ty);\n    fty->params = params;\n    fty->is_variadic = is_variadic;\n    fty->has_prototype = has_prototype;\n\n    Obj *var = find_global_symbol(name);\n    if (var) {\n        if (!var->is_function)\n            error("'%s' redeclared as different kind of symbol", name);\n        check_oldstyle_definition_redeclaration(var, fty, is_definition, name);\n        if (!type_compatible(var->ty, fty))\n            error("conflicting types for function '%s'", name);\n        if (is_static && !var->is_static)\n            error("static declaration of '%s' follows non-static declaration", name);\n        if (is_definition && var->is_defined)\n            error("redefinition of function '%s'", name);\n\n        var->ty = composite_redecl_type(var->ty, fty);\n        var->is_static = var->is_static || is_static;\n        var->is_defined = var->is_defined || is_definition;\n        bind_var_in_current_scope(var->name, var, true);\n        return;\n    }\n\n    Obj *fn_obj = calloc(1, sizeof(Obj));\n    fn_obj->name = strdup(name);\n    fn_obj->ty = fty;\n    fn_obj->is_local = false;\n    fn_obj->is_function = true;\n    fn_obj->is_static = is_static;\n    fn_obj->is_defined = is_definition;\n    fn_obj->next = globals;\n    globals = fn_obj;\n    bind_var_in_current_scope(fn_obj->name, fn_obj, false);\n}\n'''

new_fn = '''// Register a function symbol as a global Obj so it can be used as a value\n// (e.g. function pointer assignment: fp = add;). Redeclarations are checked\n// against the complete recursive function type before metadata is refreshed.\n// Return the canonical symbol so a definition can inherit the effective linkage\n// established by an earlier declaration.\nstatic Obj *register_function_symbol(char *name, Type *return_ty, bool is_static,\n                                     Obj *params, bool is_variadic,\n                                     bool has_prototype, bool is_definition) {\n    Type *fty = func_type(return_ty);\n    fty->params = params;\n    fty->is_variadic = is_variadic;\n    fty->has_prototype = has_prototype;\n\n    Obj *var = find_global_symbol(name);\n    if (var) {\n        if (!var->is_function)\n            error("'%s' redeclared as different kind of symbol", name);\n        check_oldstyle_definition_redeclaration(var, fty, is_definition, name);\n        if (!type_compatible(var->ty, fty))\n            error("conflicting types for function '%s'", name);\n        if (is_static && !var->is_static)\n            error("static declaration of '%s' follows non-static declaration", name);\n        if (is_definition && var->is_defined)\n            error("redefinition of function '%s'", name);\n\n        var->ty = composite_redecl_type(var->ty, fty);\n        var->is_static = var->is_static || is_static;\n        var->is_defined = var->is_defined || is_definition;\n        bind_var_in_current_scope(var->name, var, true);\n        return var;\n    }\n\n    Obj *fn_obj = calloc(1, sizeof(Obj));\n    fn_obj->name = strdup(name);\n    fn_obj->ty = fty;\n    fn_obj->is_local = false;\n    fn_obj->is_function = true;\n    fn_obj->is_static = is_static;\n    fn_obj->is_defined = is_definition;\n    fn_obj->next = globals;\n    globals = fn_obj;\n    bind_var_in_current_scope(fn_obj->name, fn_obj, false);\n    return fn_obj;\n}\n'''
replace_once("parse.c", old_fn, new_fn)

replace_once(
    "parse.c",
    '''            register_function_symbol(name, ty->return_ty, is_static,\n                                     ty->params, ty->is_variadic, ty->has_prototype,\n                                     is_definition);\n''',
    '''            Obj *fn_symbol = register_function_symbol(\n                name, ty->return_ty, is_static, ty->params, ty->is_variadic,\n                ty->has_prototype, is_definition);\n''')

replace_once(
    "parse.c",
    '''            fn->return_ty = ty->return_ty;\n            fn->is_static = is_static;\n            fn->is_variadic = ty->is_variadic;\n''',
    '''            fn->return_ty = ty->return_ty;\n            fn->is_static = fn_symbol->is_static;\n            fn->is_variadic = ty->is_variadic;\n''')

makefile = Path("Makefile")
text = makefile.read_text()
old = '''\tbash ./test/object_linkage_redeclarations.sh\n\tbash ./test/unresolved_function_calls.sh\n'''
new = '''\tbash ./test/object_linkage_redeclarations.sh\n\tbash ./test/function_linkage_emission.sh\n\tbash ./test/unresolved_function_calls.sh\n'''
if text.count(old) != 1:
    raise SystemExit("Makefile function linkage insertion point not unique")
makefile.write_text(text.replace(old, new, 1))

readme = Path("README.md")
text = readme.read_text()
needle = "compatible file-scope object/function redeclarations with recursive type checking, object linkage-transition validation, and composite array/prototype retention"
replacement = "compatible file-scope object/function redeclarations with recursive type checking, object/function linkage-transition validation, and composite array/prototype retention"
if text.count(needle) != 1:
    raise SystemExit("README function linkage insertion point not unique")
readme.write_text(text.replace(needle, replacement, 1))

test = Path("test/function_linkage_emission.sh")
test.write_text(r'''#!/bin/bash
set -eu

compile_asm() {
  input="$1"
  printf '%s\n' "$input" > tmp-fn-linkage.c
  ./minicc tmp-fn-linkage.c > tmp-fn-linkage.s
}

assert_internal() {
  expected="$1"
  input="$2"
  compile_asm "$input"
  if grep -Eq '^[[:space:]]*\.globl[[:space:]]+f([[:space:]]|$)' tmp-fn-linkage.s; then
    echo "FAIL(function linkage): internal f was emitted global"
    echo "$input"
    exit 1
  fi
  cc -o tmp-fn-linkage tmp-fn-linkage.s
  set +e
  ./tmp-fn-linkage
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function linkage): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_external() {
  expected="$1"
  input="$2"
  compile_asm "$input"
  if ! grep -Eq '^[[:space:]]*\.globl[[:space:]]+f([[:space:]]|$)' tmp-fn-linkage.s; then
    echo "FAIL(function linkage): external f was not emitted global"
    echo "$input"
    exit 1
  fi
  cc -o tmp-fn-linkage tmp-fn-linkage.s
  set +e
  ./tmp-fn-linkage
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function linkage): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# A no-storage-class function declaration has extern semantics. When a prior
# visible declaration established internal linkage, later declarations and the
# definition inherit that linkage even if `static` is not repeated.
assert_internal 3 'static int f(void);int f(void){return 3;}int main(void){return f();}'
assert_internal 4 'static int f(void);extern int f(void);int f(void){return 4;}int main(void){return f();}'
assert_internal 5 'static int f(void);extern int f(void){return 5;}int main(void){return f();}'
assert_internal 6 'static int f(void);int f(void);int f(void){return 6;}int main(void){return f();}'
assert_internal 7 'static int f();int f(void){return 7;}int main(void){return f();}'
assert_internal 8 'static int f(void);static int f(void);int f(void){return 8;}int main(void){return f();}'

# Functions with no prior internal-linkage declaration remain externally visible.
assert_external 9 'int f(void);int f(void){return 9;}int main(void){return f();}'
assert_external 10 'extern int f(void);int f(void){return 10;}int main(void){return f();}'
assert_external 11 'int f(void){return 11;}int main(void){return f();}'

rm -f tmp-fn-linkage.c tmp-fn-linkage.s tmp-fn-linkage

echo 'All function linkage emission tests passed!'
''')

print("function linkage emission migration applied")
