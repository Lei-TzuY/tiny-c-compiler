from pathlib import Path

# Obj needs to remember whether a function body was already provided.
h = Path('minicc.h')
s = h.read_text()
old = '    bool is_extern;    // extern storage class\n};'
new = '    bool is_extern;    // extern storage class\n    bool is_defined;   // function symbol already has a body\n};'
if old not in s:
    raise SystemExit('Obj flag anchor not found')
h.write_text(s.replace(old, new, 1))

p = Path('parse.c')
s = p.read_text()

start = s.index('// Register a function symbol as a global Obj so it can be used as a value')
end = s.index('// program = (function | global-var | typedef)*', start)
replacement = r'''static bool type_compatible(Type *a, Type *b) {
    if (a == b)
        return true;
    if (!a || !b || a->kind != b->kind)
        return false;

    switch (a->kind) {
    case TY_CHAR:
    case TY_SHORT:
    case TY_INT:
    case TY_LONG:
        return a->is_unsigned == b->is_unsigned;
    case TY_PTR:
        return type_compatible(a->base, b->base);
    case TY_ARRAY:
        return type_compatible(a->base, b->base) &&
               (!a->array_len || !b->array_len || a->array_len == b->array_len);
    case TY_STRUCT:
        // Tagged records are completed in place, so pointer identity captures
        // C record-type identity. Distinct anonymous records are incompatible.
        return false;
    case TY_FUNC: {
        if (!type_compatible(a->return_ty, b->return_ty))
            return false;

        // An old-style f() declaration carries no parameter information. Keep
        // it compatible with a real prototype so the stronger declaration can
        // be retained, matching the compiler's existing C11-era behavior.
        if (!a->has_prototype || !b->has_prototype)
            return true;
        if (a->is_variadic != b->is_variadic)
            return false;

        Obj *pa = a->params;
        Obj *pb = b->params;
        while (pa && pb) {
            if (!type_compatible(pa->ty, pb->ty))
                return false;
            pa = pa->param_next;
            pb = pb->param_next;
        }
        return !pa && !pb;
    }
    default:
        return true;
    }
}

static Type *composite_redecl_type(Type *old_ty, Type *new_ty) {
    if (old_ty->kind == TY_ARRAY && old_ty->array_len == 0 && new_ty->array_len)
        return new_ty;
    if (old_ty->kind == TY_FUNC && !old_ty->has_prototype && new_ty->has_prototype)
        return new_ty;
    return old_ty;
}

static Obj *find_global_symbol(const char *name) {
    for (Obj *var = globals; var; var = var->next)
        if (!strcmp(var->name, name))
            return var;
    return NULL;
}

static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->init_vals_count > 0 || var->init_data;
}

static Obj *register_global_symbol(Token *ident, Type *ty, bool is_static,
                                   bool is_extern) {
    char *name = strndup(ident->loc, ident->len);
    Obj *var = find_global_symbol(name);
    if (var) {
        if (var->is_function)
            error_at(ident->loc, "'%s' redeclared as different kind of symbol", name);
        if (!type_compatible(var->ty, ty))
            error_at(ident->loc, "conflicting types for '%s'", name);
        if (is_static && !var->is_static)
            error_at(ident->loc, "static declaration of '%s' follows non-static declaration", name);

        var->ty = composite_redecl_type(var->ty, ty);
        if (var->is_static)
            is_static = true;
        var->is_static = is_static;
        if (!is_extern)
            var->is_extern = false;
        return var;
    }

    var = calloc(1, sizeof(Obj));
    var->name = name;
    var->ty = ty;
    var->is_local = false;
    var->is_static = is_static;
    var->is_extern = is_extern;
    var->next = globals;
    globals = var;
    return var;
}

// Register a function symbol as a global Obj so it can be used as a value
// (e.g. function pointer assignment: fp = add;). Redeclarations are checked
// against the complete recursive function type before metadata is refreshed.
static void register_function_symbol(char *name, Type *return_ty, bool is_static,
                                     Obj *params, bool is_variadic,
                                     bool has_prototype, bool is_definition) {
    Type *fty = func_type(return_ty);
    fty->params = params;
    fty->is_variadic = is_variadic;
    fty->has_prototype = has_prototype;

    Obj *var = find_global_symbol(name);
    if (var) {
        if (!var->is_function)
            error("'%s' redeclared as different kind of symbol", name);
        if (!type_compatible(var->ty, fty))
            error("conflicting types for function '%s'", name);
        if (is_static && !var->is_static)
            error("static declaration of '%s' follows non-static declaration", name);
        if (is_definition && var->is_defined)
            error("redefinition of function '%s'", name);

        var->ty = composite_redecl_type(var->ty, fty);
        var->func_params = var->ty->params;
        var->func_variadic = var->ty->is_variadic;
        var->is_static = var->is_static || is_static;
        var->is_defined = var->is_defined || is_definition;
        return;
    }

    Obj *fn_obj = calloc(1, sizeof(Obj));
    fn_obj->name = strdup(name);
    fn_obj->ty = fty;
    fn_obj->func_params = fty->params;
    fn_obj->func_variadic = fty->is_variadic;
    fn_obj->is_local = false;
    fn_obj->is_function = true;
    fn_obj->is_static = is_static;
    fn_obj->is_defined = is_definition;
    fn_obj->next = globals;
    globals = fn_obj;
}

'''
s = s[:start] + replacement + s[end:]

old_call = '''            register_function_symbol(name, ty->return_ty, is_static,\n                                     ty->params, ty->is_variadic, ty->has_prototype);'''
new_call = '''            register_function_symbol(name, ty->return_ty, is_static,\n                                     ty->params, ty->is_variadic, ty->has_prototype,\n                                     !equal(tok, ";"));'''
if old_call not in s:
    raise SystemExit('function registration call anchor not found')
s = s.replace(old_call, new_call, 1)

old_alloc = '''                Obj *var = calloc(1, sizeof(Obj));\n                var->name = strndup(ident->loc, ident->len);\n                var->ty = ty;\n                var->is_local = false;\n                var->is_static = is_static;\n                var->is_extern = is_extern;\n                var->next = globals;\n                globals = var;'''
new_alloc = '''                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);\n                ty = var->ty;'''
if old_alloc not in s:
    raise SystemExit('global allocation anchor not found')
s = s.replace(old_alloc, new_alloc, 1)

# Only patch the initializer check in the top-level global-declaration block.
gmark = s.index('// Global variable(s) (possibly with initializer)')
ipos = s.index('                if (consume(&tok, tok, "=")) {', gmark)
s = s[:ipos] + '''                if (equal(tok, "=") && object_has_initializer(var))\n                    error_at(ident->loc, "redefinition of global '%s'", var->name);\n\n''' + s[ipos:]

p.write_text(s)

mk = Path('Makefile')
m = mk.read_text()
anchor = '\tbash ./test/type_names.sh\n'
if anchor not in m:
    raise SystemExit('Makefile anchor not found')
mk.write_text(m.replace(anchor, anchor + '\tbash ./test/type_compatibility.sh\n', 1))

readme = Path('README.md')
r = readme.read_text()
old = '- **Declarations**: recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), recursive abstract type names shared by casts and `sizeof(type-name)`, local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
new = '- **Declarations**: recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), recursive abstract type names shared by casts and `sizeof(type-name)`, compatible file-scope object/function redeclarations with recursive type checking and composite array/prototype retention, local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
if old not in r:
    raise SystemExit('README declaration anchor not found')
readme.write_text(r.replace(old, new, 1))

Path('test/type_compatibility.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-typecompat.c
  ./minicc tmp-typecompat.c > tmp-typecompat.s
  cc -o tmp-typecompat tmp-typecompat.s
  set +e
  ./tmp-typecompat
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "type compatibility failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(type compatibility): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-typecompat-bad.c
  if ./minicc tmp-typecompat-bad.c > tmp-typecompat-bad.s 2>/dev/null; then
    echo "type compatibility unexpectedly accepted invalid redeclaration"
    echo "$input"
    exit 1
  fi
  echo "OK(type compatibility): rejected conflict"
}

# Compatible file-scope object redeclarations merge into one symbol.
assert_run 7 'int x; int x; int main(){x=7;return x;}'
assert_run 5 'extern int x; int x=5; int main(){return x;}'
assert_run 12 'extern int a[]; int a[3]; int main(){return sizeof(a);}'
assert_run 4 'int a[4]; extern int a[]; int main(){return sizeof(a)/sizeof(int);}'
assert_run 6 'int inc(int); int inc(int x){return x+1;} int main(){return inc(5);}'
assert_run 7 'int f(int); int f(); int f(int x){return x;} int main(){return f(7);}'
assert_run 8 'int inc(int x){return x+1;} int (*fp)(int); extern int (*fp)(int); int main(){fp=inc;return fp(7);}'
assert_run 9 'struct S{int x;}; struct S obj; extern struct S obj; int main(){obj.x=9;return obj.x;}'
assert_run 3 'struct S{int x;}; struct S *p; extern struct S *p; struct S s; int main(){p=&s;p->x=3;return p->x;}'

# Recursive incompatibilities are constraints, not duplicate symbols for ld.
assert_fail 'int x; double x; int main(){return 0;}'
assert_fail 'int *x; double *x; int main(){return 0;}'
assert_fail 'int a[2]; int a[3]; int main(){return 0;}'
assert_fail 'int f(int); double f(int); int main(){return 0;}'
assert_fail 'int f(int); int f(double); int main(){return 0;}'
assert_fail 'int f(int,...); int f(int); int main(){return 0;}'
assert_fail 'int f(int); int f; int main(){return 0;}'
assert_fail 'int f; int f(int); int main(){return 0;}'
assert_fail 'int (*fp)(int); int (*fp)(double); int main(){return 0;}'
assert_fail 'struct {int x;} a; struct {int x;} a; int main(){return 0;}'
assert_fail 'int f(int x){return x;} int f(int x){return x+1;} int main(){return f(1);}'
assert_fail 'int x=1; int x=2; int main(){return x;}'

echo 'All type-compatibility tests passed!'
''')

print('Type compatibility migration applied')
