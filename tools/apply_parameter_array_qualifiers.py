from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(s.replace(old, new, 1))


replace_once(
    "minicc.h",
    "    int array_len;    // Array\n",
    "    int array_len;    // Array\n"
    "    // Parameter-array qualifiers written inside the outermost [] apply\n"
    "    // to the pointer produced by C's array-parameter adjustment. These\n"
    "    // fields exist only until func_params() performs that adjustment.\n"
    "    bool param_array_const;\n"
    "    bool param_array_volatile;\n"
    "    bool param_array_restrict;\n",
    "parameter array qualifier metadata",
)

replace_once(
    "parse.c",
    "static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,\n"
    "                             bool allow_abstract);\n"
    "static Type *type_suffix(Token **rest, Token *tok, Type *ty);\n",
    "static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,\n"
    "                             bool allow_abstract, bool parameter_declarator);\n"
    "static Type *type_suffix(Token **rest, Token *tok, Type *ty,\n"
    "                         bool allow_parameter_array_syntax);\n",
    "declarator prototypes",
)

replace_once(
    "parse.c",
    '''static Type *adjust_param_type(Type *ty) {
    // C adjusts array and function parameter declarations to pointers.
    if (ty->kind == TY_ARRAY)
        return pointer_to(ty->base);
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    return ty;
}
''',
    '''static Type *adjust_param_type(Type *ty) {
    // C adjusts array and function parameter declarations to pointers. Type
    // qualifiers written inside the outermost parameter-array brackets qualify
    // the adjusted pointer itself, not the element type.
    if (ty->kind == TY_ARRAY) {
        Type *ptr = pointer_to(ty->base);
        return qualify_type(ptr, ty->param_array_const, ty->param_array_volatile,
                            ty->param_array_restrict);
    }
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    return ty;
}
''',
    "parameter adjustment qualifiers",
)

replace_once(
    "parse.c",
    "        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true);\n",
    "        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true, true);\n",
    "parameter declarator context",
)

old_suffix = '''static Type *type_suffix(Token **rest, Token *tok, Type *ty) {
    if (equal(tok, "(")) {
        if (ty->kind == TY_ARRAY)
            error_at(tok->loc, "function cannot return an array type");
        if (ty->kind == TY_FUNC)
            error_at(tok->loc, "function cannot return a function type");
        return func_params(rest, tok->next, ty);
    }

    if (equal(tok, "[")) {
        Token *bracket = tok;
        tok = tok->next;
        int len = 0;
        if (!equal(tok, "]")) {
            Node *bound = ternary(&tok, tok);
            add_type(bound);
            if (!is_integer(bound->ty))
                error_at(bracket->loc, "array bound must have integer type");

            int64_t raw = eval_const_expr(bound);
            if (bound->ty->is_unsigned) {
                uint64_t val = (uint64_t)cast_const_integer(raw, bound->ty);
                if (val == 0 || val > INT32_MAX)
                    error_at(bracket->loc, "array bound is out of range");
                len = (int)val;
            } else {
                int64_t val = cast_const_integer(raw, bound->ty);
                if (val <= 0 || val > INT32_MAX)
                    error_at(bracket->loc, "array bound is out of range");
                len = (int)val;
            }
        }
        tok = skip(tok, "]");
        ty = type_suffix(rest, tok, ty);
        if (ty->kind == TY_FUNC)
            error_at(bracket->loc, "array element type cannot be a function");
        if (ty->kind == TY_VOID)
            error_at(bracket->loc, "array element type cannot be void");
        if (is_incomplete_object_type(ty))
            error_at(bracket->loc, "array element type is incomplete");
        if (ty->kind == TY_STRUCT && ty->has_flexible_array_member)
            error_at(bracket->loc,
                     "array element type contains a flexible array member");
        return array_of(ty, len);
    }

    *rest = tok;
    return ty;
}
'''

new_suffix = '''static Type *type_suffix(Token **rest, Token *tok, Type *ty,
                         bool allow_parameter_array_syntax) {
    if (equal(tok, "(")) {
        if (ty->kind == TY_ARRAY)
            error_at(tok->loc, "function cannot return an array type");
        if (ty->kind == TY_FUNC)
            error_at(tok->loc, "function cannot return a function type");
        return func_params(rest, tok->next, ty);
    }

    if (equal(tok, "[")) {
        Token *bracket = tok;
        tok = tok->next;

        bool param_const = false;
        bool param_volatile = false;
        bool param_restrict = false;
        bool param_static = false;

        if (!allow_parameter_array_syntax &&
            (equal(tok, "const") || equal(tok, "volatile") ||
             equal(tok, "restrict") || equal(tok, "static")))
            error_at(tok->loc,
                     "array qualifiers/static are only allowed in the outermost function parameter array");

        if (allow_parameter_array_syntax) {
            while (equal(tok, "const") || equal(tok, "volatile") ||
                   equal(tok, "restrict")) {
                if (consume(&tok, tok, "const"))
                    param_const = true;
                else if (consume(&tok, tok, "volatile"))
                    param_volatile = true;
                else {
                    consume(&tok, tok, "restrict");
                    param_restrict = true;
                }
            }

            if (consume(&tok, tok, "static")) {
                param_static = true;
                while (equal(tok, "const") || equal(tok, "volatile") ||
                       equal(tok, "restrict")) {
                    if (consume(&tok, tok, "const"))
                        param_const = true;
                    else if (consume(&tok, tok, "volatile"))
                        param_volatile = true;
                    else {
                        consume(&tok, tok, "restrict");
                        param_restrict = true;
                    }
                }
            }

            if (equal(tok, "static"))
                error_at(tok->loc, "duplicate static in parameter array declarator");
            if (equal(tok, "*"))
                error_at(tok->loc,
                         "variable-length parameter array '*' bounds are not supported");
            if (param_static && equal(tok, "]"))
                error_at(bracket->loc,
                         "static parameter array declarator requires an explicit bound");
        }

        int len = 0;
        if (!equal(tok, "]")) {
            Node *bound = ternary(&tok, tok);
            add_type(bound);
            if (!is_integer(bound->ty))
                error_at(bracket->loc, "array bound must have integer type");

            int64_t raw = eval_const_expr(bound);
            if (bound->ty->is_unsigned) {
                uint64_t val = (uint64_t)cast_const_integer(raw, bound->ty);
                if (val == 0 || val > INT32_MAX)
                    error_at(bracket->loc, "array bound is out of range");
                len = (int)val;
            } else {
                int64_t val = cast_const_integer(raw, bound->ty);
                if (val <= 0 || val > INT32_MAX)
                    error_at(bracket->loc, "array bound is out of range");
                len = (int)val;
            }
        }
        tok = skip(tok, "]");
        ty = type_suffix(rest, tok, ty, false);
        if (ty->kind == TY_FUNC)
            error_at(bracket->loc, "array element type cannot be a function");
        if (ty->kind == TY_VOID)
            error_at(bracket->loc, "array element type cannot be void");
        if (is_incomplete_object_type(ty))
            error_at(bracket->loc, "array element type is incomplete");
        if (ty->kind == TY_STRUCT && ty->has_flexible_array_member)
            error_at(bracket->loc,
                     "array element type contains a flexible array member");

        Type *arr = array_of(ty, len);
        if (allow_parameter_array_syntax) {
            arr->param_array_const = param_const;
            arr->param_array_volatile = param_volatile;
            arr->param_array_restrict = param_restrict;
        }
        (void)param_static; // `static` is a call-site minimum-bound contract, not type identity.
        return arr;
    }

    *rest = tok;
    return ty;
}
'''
replace_once("parse.c", old_suffix, new_suffix, "parameter array suffix parser")

replace_once(
    "parse.c",
    '''static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract) {
''',
    '''static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract, bool parameter_declarator) {
''',
    "declarator implementation signature",
)

replace_once(
    "parse.c",
    '''    if (allow_abstract && equal(tok, "(") &&
        (equal(tok->next, ")") || is_typename(tok->next) ||
         equal(tok->next, "const") || equal(tok->next, "volatile") ||
         equal(tok->next, "restrict") || equal(tok->next, "register")))
        return type_suffix(rest, tok, ty);
''',
    '''    if (allow_abstract && equal(tok, "(") &&
        (equal(tok->next, ")") || is_typename(tok->next) ||
         equal(tok->next, "const") || equal(tok->next, "volatile") ||
         equal(tok->next, "restrict") || equal(tok->next, "register")))
        return type_suffix(rest, tok, ty, false);
''',
    "abstract function suffix",
)

replace_once(
    "parse.c",
    '''    if (equal(tok, "(")) {
        Token *start = tok;
        Type dummy = {};
        declarator_impl(&tok, start->next, &dummy, ident, allow_abstract);
        tok = skip(tok, ")");
        ty = type_suffix(rest, tok, ty);
        return declarator_impl(&tok, start->next, ty, ident, allow_abstract);
    }
''',
    '''    if (equal(tok, "(")) {
        Token *start = tok;
        Type dummy = {};
        declarator_impl(&tok, start->next, &dummy, ident, allow_abstract,
                        parameter_declarator);
        tok = skip(tok, ")");
        // A suffix outside a parenthesized declarator is not the direct
        // outermost array derivation of the parameter identifier. Parameter
        // array qualifiers/static are therefore forbidden at this level.
        ty = type_suffix(rest, tok, ty, false);
        return declarator_impl(&tok, start->next, ty, ident, allow_abstract,
                               parameter_declarator);
    }
''',
    "grouped declarator parameter context",
)

replace_once(
    "parse.c",
    '''    return type_suffix(rest, tok, ty);
}

static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, false);
}

static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, true);
}
''',
    '''    return type_suffix(rest, tok, ty, parameter_declarator);
}

static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, false, false);
}

static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, true, false);
}
''',
    "declarator wrappers",
)

# Makefile registration.
make = Path("Makefile")
s = make.read_text()
anchor = "\tbash ./test/prototype_params.sh\n"
if anchor not in s:
    raise SystemExit("Makefile prototype anchor missing")
make.write_text(s.replace(anchor, anchor + "\tbash ./test/parameter_array_qualifiers.sh\n", 1))

# README declaration feature description.
readme = Path("README.md")
s = readme.read_text()
old = "abstract callback declarators, parameter array/function adjustment, C-compatible old-style `f()` versus prototype compatibility"
new = "abstract callback declarators, parameter array/function adjustment including outermost `[]` qualifiers and constant-bound `static` array parameters, C-compatible old-style `f()` versus prototype compatibility"
if old not in s:
    raise SystemExit("README parameter adjustment anchor missing")
readme.write_text(s.replace(old, new, 1))

Path("test/parameter_array_qualifiers.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-param-array.c
  ./minicc tmp-param-array.c > tmp-param-array.s
  cc -o tmp-param-array tmp-param-array.s
  set +e
  ./tmp-param-array
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(parameter array): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(parameter array): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-param-array-bad.c
  if ./minicc tmp-param-array-bad.c > /dev/null 2>tmp-param-array.err; then
    echo "FAIL(parameter array): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(parameter array): rejected"
}

# C11 outermost parameter-array syntax adjusts to a pointer and keeps indexing.
assert_run 7 'int f(int a[static 3]){return a[2];} int main(void){int a[3]={1,2,7};return f(a);}'
assert_run 8 'int f(int a[const static 3]){return a[2];} int main(void){int a[3]={1,2,8};return f(a);}'
assert_run 9 'int f(int a[static const 3]){return a[2];} int main(void){int a[3]={1,2,9};return f(a);}'
assert_run 10 'int f(int a[volatile static 3]){return a[2];} int main(void){int a[3]={1,2,10};return f(a);}'
assert_run 11 'int f(int a[restrict static 3]){return a[2];} int main(void){int a[3]={1,2,11};return f(a);}'
assert_run 12 'int f(int a[static const volatile restrict 3]){return a[2];} int main(void){int a[3]={1,2,12};return f(a);}'
assert_run 13 'int f(int a[const restrict]){return a[0];} int main(void){int a[1]={13};return f(a);}'

# Bracket qualifiers qualify the adjusted pointer itself. They are ignored for
# function type compatibility as top-level parameter qualifiers, but const is
# observable on the parameter object inside a definition.
assert_run 14 'int f(int a[const 3]); int f(int *a){return a[0];} int main(void){int a[3]={14};return f(a);}'
assert_run 15 'int f(int *); int f(int a[restrict 3]){return a[0];} int main(void){int a[3]={15};return f(a);}'
assert_run 16 'int f(int a[static 3]); int f(int *a){return a[0];} int main(void){int a[3]={16};return f(a);}'
assert_run 17 'typedef int F(int a[const 3]); typedef int G(int *a); int id(int *a){return *a;} int main(void){F *f=id;G *g=f;int x=17;return g(&x);}'
assert_reject 'int f(int a[const 3]){a=0;return 0;} int main(void){return 0;}'

# Only the direct outermost array derivation may carry the special syntax.
assert_run 18 'int f(int a[static 2][3]){return a[1][2];} int main(void){int a[2][3]={{0},{0,0,18}};return f(a);}'
assert_run 19 'int f(int *a[static 2]){return *a[1];} int main(void){int x=0,y=19;int *a[2]={&x,&y};return f(a);}'
assert_reject 'int f(int a[3][const 4]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[3][static 4]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int (*a)[static 3]){return 0;} int main(void){return 0;}'

# Parameter-only syntax must not leak into ordinary array declarators/type names.
assert_reject 'int a[const 3]; int main(void){return 0;}'
assert_reject 'int a[static 3]; int main(void){return 0;}'
assert_reject 'int main(void){int a[restrict 3];return 0;}'
assert_reject 'int main(void){return sizeof(int [const 3]);}'

# static requires a bound; VLA-star parameter forms stay outside the current
# compiler subset rather than being silently misparsed as pointer syntax.
assert_reject 'int f(int a[static]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[const static]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[static static 3]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[*]){return 0;} int main(void){return 0;}'
assert_reject 'int f(int a[const *]){return 0;} int main(void){return 0;}'

rm -f tmp-param-array.c tmp-param-array.s tmp-param-array \
      tmp-param-array-bad.c tmp-param-array.err

echo 'All parameter-array qualifier tests passed!'
''')
