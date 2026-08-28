from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(s.replace(old, new, 1))


replace_once(
    "minicc.h",
    "bool is_numeric(Type *ty);\n",
    "bool is_numeric(Type *ty);\nType *default_argument_promotion(Type *ty);\nbool prototype_compatible_with_unprototyped(Type *fty);\n",
    "shared promotion prototypes",
)

replace_once(
    "type.c",
    '''bool is_numeric(Type *ty) {
    return is_integer(ty) || is_flonum(ty);
}
''',
    '''bool is_numeric(Type *ty) {
    return is_integer(ty) || is_flonum(ty);
}

// Default argument promotions used by unprototyped calls, variadic tails,
// and the C function-type compatibility rule for an empty parameter list.
// NULL means the type is unchanged by the default promotions.
Type *default_argument_promotion(Type *ty) {
    if (!ty)
        return NULL;
    if (ty->kind == TY_FLOAT)
        return ty_double;
    if (ty->kind == TY_BOOL || ty->kind == TY_CHAR || ty->kind == TY_SHORT)
        return ty_int;
    return NULL;
}

// C permits a prototype to be compatible with an old-style empty parameter
// list only when it has no ellipsis and every parameter type is unchanged by
// the default argument promotions. Parameter array/function adjustment has
// already happened while parsing the prototype.
bool prototype_compatible_with_unprototyped(Type *fty) {
    if (!fty || fty->kind != TY_FUNC || !fty->has_prototype || fty->is_variadic)
        return false;

    for (Obj *param = fty->params; param; param = param->param_next)
        if (default_argument_promotion(param->ty))
            return false;
    return true;
}
''',
    "shared default promotions",
)

replace_once(
    "parse.c",
    '''static Type *default_argument_promotion(Type *ty) {
    if (!ty)
        return NULL;
    if (ty->kind == TY_FLOAT)
        return ty_double;
    if (ty->kind == TY_BOOL || ty->kind == TY_CHAR || ty->kind == TY_SHORT)
        return ty_int;
    return NULL;
}

''',
    "",
    "remove parser-local promotion helper",
)

replace_once(
    "parse.c",
    '''        // Old-style f() remains compatible with a prototype. For prototype
        // comparison, C ignores only the top-level qualifiers on each parameter
        // after array/function parameter adjustment; nested pointer qualifiers
        // remain significant.
        if (!a->has_prototype || !b->has_prototype)
            return true;
''',
    '''        // Two unprototyped function types are compatible. If exactly one
        // side has a prototype, C additionally requires a non-variadic prototype
        // whose parameter types are unchanged by the default argument promotions.
        if (!a->has_prototype || !b->has_prototype) {
            if (!a->has_prototype && !b->has_prototype)
                return true;
            Type *proto = a->has_prototype ? a : b;
            return prototype_compatible_with_unprototyped(proto);
        }
''',
    "parser function compatibility",
)

replace_once(
    "type.c",
    '''        if (!a->has_prototype || !b->has_prototype)
            return true;
''',
    '''        if (!a->has_prototype || !b->has_prototype) {
            if (!a->has_prototype && !b->has_prototype)
                return true;
            Type *proto = a->has_prototype ? a : b;
            return prototype_compatible_with_unprototyped(proto);
        }
''',
    "type-analysis function compatibility",
)

# An empty parameter-list function definition has exactly zero parameters even
# though its function type remains unprototyped. Preserve that definition fact
# across later declarations so a compatible declaration rule cannot erase the
# definition's known arity.
create_static_anchor = '''    var->next = globals;
    globals = var;
    return var;
}

// Create a block-scope declaration with linkage. A prior file-scope or earlier
'''
create_static_new = '''    var->next = globals;
    globals = var;
    return var;
}

static void check_oldstyle_definition_redeclaration(Obj *old, Type *new_ty,
                                                    bool new_is_definition,
                                                    const char *name) {
    if (!old || !old->is_function || !old->ty || old->ty->kind != TY_FUNC ||
        !new_ty || new_ty->kind != TY_FUNC)
        return;

    // This compiler does not implement identifier-list definitions, so an
    // unprototyped `f(){...}` definition has exactly zero parameters.
    if (new_is_definition && !old->is_defined && !new_ty->has_prototype &&
        old->ty->has_prototype && old->ty->params)
        error("function definition of '%s' has no parameters but prior prototype does", name);

    if (!new_is_definition && old->is_defined && !old->ty->has_prototype &&
        new_ty->has_prototype && new_ty->params)
        error("prototype for '%s' declares parameters after a no-parameter definition", name);
}

// Create a block-scope declaration with linkage. A prior file-scope or earlier
'''
replace_once("parse.c", create_static_anchor, create_static_new,
             "old-style definition redeclaration helper")

replace_once(
    "parse.c",
    '''    if (same_scope) {
        Obj *old = same_scope->var;
        if (old->is_local || strcmp(old->name, name) ||
            old->is_function != wants_function || !type_compatible(old->ty, ty))
            error("conflicting block-scope declaration of '%s'", name);
        old->ty = composite_redecl_type(old->ty, ty);
        return old;
    }
''',
    '''    if (same_scope) {
        Obj *old = same_scope->var;
        if (old->is_local || strcmp(old->name, name) ||
            old->is_function != wants_function)
            error("conflicting block-scope declaration of '%s'", name);
        if (wants_function)
            check_oldstyle_definition_redeclaration(old, ty, false, name);
        if (!type_compatible(old->ty, ty))
            error("conflicting block-scope declaration of '%s'", name);
        old->ty = composite_redecl_type(old->ty, ty);
        return old;
    }
''',
    "same-scope function redeclaration",
)

replace_once(
    "parse.c",
    '''    if (var) {
        if (var->is_function != wants_function)
            error("'%s' redeclared as different kind of symbol", name);
        if (!type_compatible(var->ty, ty))
            error("conflicting types for '%s'", name);
        var->ty = composite_redecl_type(var->ty, ty);
    } else {
''',
    '''    if (var) {
        if (var->is_function != wants_function)
            error("'%s' redeclared as different kind of symbol", name);
        if (wants_function)
            check_oldstyle_definition_redeclaration(var, ty, false, name);
        if (!type_compatible(var->ty, ty))
            error("conflicting types for '%s'", name);
        var->ty = composite_redecl_type(var->ty, ty);
    } else {
''',
    "global function block redeclaration",
)

replace_once(
    "parse.c",
    '''    if (var) {
        if (!var->is_function)
            error("'%s' redeclared as different kind of symbol", name);
        if (!type_compatible(var->ty, fty))
            error("conflicting types for function '%s'", name);
''',
    '''    if (var) {
        if (!var->is_function)
            error("'%s' redeclared as different kind of symbol", name);
        check_oldstyle_definition_redeclaration(var, fty, is_definition, name);
        if (!type_compatible(var->ty, fty))
            error("conflicting types for function '%s'", name);
''',
    "file function definition redeclaration",
)

make = Path("Makefile")
s = make.read_text()
anchor = "\tbash ./test/function_type_constraints.sh\n"
if anchor not in s:
    raise SystemExit("Makefile function-type anchor missing")
s = s.replace(anchor, anchor + "\tbash ./test/oldstyle_function_compatibility.sh\n", 1)
make.write_text(s)

readme = Path("README.md")
s = readme.read_text()
old = "parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)"
new = "parameter array/function adjustment, C-compatible old-style `f()` versus prototype compatibility using default argument promotions (including variadic incompatibility), and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)"
if old not in s:
    raise SystemExit("README old-style compatibility anchor missing")
s = s.replace(old, new, 1)
readme.write_text(s)

Path("test/oldstyle_function_compatibility.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-oldstyle.c
  ./minicc tmp-oldstyle.c > tmp-oldstyle.s
  cc -o tmp-oldstyle tmp-oldstyle.s
  set +e
  ./tmp-oldstyle
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(old-style compatibility): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(old-style compatibility): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-oldstyle-bad.c
  if ./minicc tmp-oldstyle-bad.c > /dev/null 2>tmp-oldstyle.err; then
    echo "FAIL(old-style compatibility): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(old-style compatibility): rejected"
}

# A prototype is compatible with f() only when each parameter is unchanged by
# the default argument promotions and the prototype is not variadic.
assert_run 7 'int f(); int f(int); int f(int x){return x;} int main(void){return f(7);}'
assert_run 8 'int f(int); int f(); int f(int x){return x;} int main(void){return f(8);}'
assert_run 0 'int f(); int f(double); int f(double x){return x==9.0?0:1;} int main(void){return f(9.0);}'
assert_run 10 'int f(); int f(long); int f(long x){return x;} int main(void){return f(10);}'
assert_run 11 'int f(); int f(unsigned int); int f(unsigned int x){return x;} int main(void){return f(11);}'
assert_run 3 'int f(void); int f(){return 3;} int main(void){return f();}'
assert_run 4 'int f(){return 4;} int f(void); int main(void){return f();}'
assert_run 5 'int f(); int f(int *); int f(int *p){return *p;} int main(void){int x=5;return f(&x);}'
assert_run 6 'struct S{int x;}; int f(); int f(struct S); int f(struct S s){return s.x;} int main(void){struct S s={6};return f(s);}'
assert_run 0 'int id(int x){return x;} int main(void){int (*old)()=id;int (*proto)(int)=id;old=proto;return old(12)==12?0:1;}'
assert_run 0 'int id(int x){return x;} int main(void){int (*old)()=id;int (*proto)(int)=id;return old==proto?0:1;}'
assert_run 0 'int id(int x){return x;} int main(void){int (*old)()=id;int (*proto)(int)=id;int (*p)(int)=1?old:proto;return p(13)==13?0:1;}'
assert_run 0 'typedef int Old(); typedef int WithInt(int); int id(int x){return x;} int main(void){Old *a=id;WithInt *b=id;a=b;return a(14)==14?0:1;}'

# Moving the promotion helper into the shared type layer must not change actual
# unprototyped-call ABI behavior: float becomes double and small integers become int.
cat > tmp-oldstyle-host.c <<'EOF'
double host_fp(double x) { return x; }
int host_small(int x) { return x; }
EOF
cc -c -o tmp-oldstyle-host.o tmp-oldstyle-host.c
cat > tmp-oldstyle-interop.c <<'EOF'
double host_fp();
int host_small();
int main(void) {
  float f = 15.0;
  signed char c = 16;
  return host_fp(f) == 15.0 && host_small(c) == 16 ? 0 : 1;
}
EOF
./minicc tmp-oldstyle-interop.c > tmp-oldstyle-interop.s
cc -o tmp-oldstyle-interop tmp-oldstyle-interop.s tmp-oldstyle-host.o
./tmp-oldstyle-interop
echo 'OK(old-style compatibility): host ABI promotions'

# Types changed by default argument promotions cannot match f().
assert_reject 'int f(); int f(float); int main(void){return 0;}'
assert_reject 'int f(float); int f(); int main(void){return 0;}'
assert_reject 'int f(); int f(char); int main(void){return 0;}'
assert_reject 'int f(); int f(signed char); int main(void){return 0;}'
assert_reject 'int f(); int f(unsigned char); int main(void){return 0;}'
assert_reject 'int f(); int f(short); int main(void){return 0;}'
assert_reject 'int f(); int f(unsigned short); int main(void){return 0;}'
assert_reject 'int f(); int f(_Bool); int main(void){return 0;}'
assert_reject 'int f(); int f(int,...); int main(void){return 0;}'

# Function-pointer compatibility uses the same rule for assignment, equality,
# conditional operands, and typedef-hidden function types.
assert_reject 'int main(void){int (*a)();int (*b)(float);a=b;return 0;}'
assert_reject 'int main(void){int (*a)();int (*b)(float);return a==b;}'
assert_reject 'int main(void){int (*a)();int (*b)(float);return (1?a:b)!=0;}'
assert_reject 'typedef int Old(); typedef int WithFloat(float); int main(void){Old *a;WithFloat *b;a=b;return 0;}'

# Although an f() declaration may be compatible with a promotion-safe
# prototype, an f(){...} definition in this compiler has exactly zero
# parameters. It therefore cannot define or later acquire a nonzero prototype.
assert_reject 'int f(int); int f(){return 0;} int main(void){return 0;}'
assert_reject 'int f(double); int f(){return 0;} int main(void){return 0;}'
assert_reject 'int f(){return 0;} int f(int); int main(void){return 0;}'
assert_reject 'int f(){return 0;} int f(double); int main(void){return 0;}'
assert_reject 'int f(){return 0;} int main(void){int f(int);return 0;}'
assert_reject 'int main(void){int f(int);return 0;} int f(){return 0;}'

rm -f tmp-oldstyle.c tmp-oldstyle.s tmp-oldstyle tmp-oldstyle-bad.c tmp-oldstyle.err \
      tmp-oldstyle-host.c tmp-oldstyle-host.o tmp-oldstyle-interop.c \
      tmp-oldstyle-interop.s tmp-oldstyle-interop

echo 'All old-style function compatibility tests passed!'
''')
