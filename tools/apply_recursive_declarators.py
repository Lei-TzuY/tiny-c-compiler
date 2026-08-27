from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = 'static Type *declspec(Token **rest, Token *tok);\n'
insert = '''static Type *declspec(Token **rest, Token *tok);\nstatic Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,\n                             bool allow_abstract);\nstatic Type *type_suffix(Token **rest, Token *tok, Type *ty);\n'''
if anchor not in s:
    raise SystemExit('forward declaration anchor not found')
s = s.replace(anchor, insert, 1)

start = s.index('static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,\n                             bool allow_abstract) {')
end = s.index('// Parse a constant integer (with optional sign) for global initializers', start)
new_decl = r'''static Type *adjust_param_type(Type *ty) {
    // C adjusts array and function parameter declarations to pointers.
    if (ty->kind == TY_ARRAY)
        return pointer_to(ty->base);
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    return ty;
}

static Type *func_params(Token **rest, Token *tok, Type *return_ty) {
    Type *fty = func_type(return_ty);
    fty->has_prototype = !equal(tok, ")");

    Obj head = {};
    Obj *cur = &head;

    // `(void)` is the strict zero-parameter prototype, unlike old-style `()`.
    if (equal(tok, "void") && equal(tok->next, ")")) {
        tok = tok->next;
        fty->has_prototype = true;
        *rest = skip(tok, ")");
        return fty;
    }

    while (!equal(tok, ")")) {
        if (cur != &head)
            tok = skip(tok, ",");

        if (equal(tok, "...")) {
            tok = tok->next;
            fty->is_variadic = true;
            break;
        }

        Type *basety = declspec(&tok, tok);
        Token *name = NULL;
        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true);
        param_ty = adjust_param_type(param_ty);

        if (is_incomplete_object_type(param_ty))
            error_at(name ? name->loc : tok->loc, "parameter has incomplete type");

        Obj *param = calloc(1, sizeof(Obj));
        param->ty = param_ty;
        if (name)
            param->name = strndup(name->loc, name->len);
        cur = cur->param_next = param;
    }

    fty->params = head.param_next;
    *rest = skip(tok, ")");
    return fty;
}

// Parse postfix type constructors. Arrays associate from the inside out, so
// `int a[2][3]` becomes array(2, array(3, int)); function suffixes retain the
// complete prototype on TY_FUNC.
static Type *type_suffix(Token **rest, Token *tok, Type *ty) {
    if (equal(tok, "("))
        return func_params(rest, tok->next, ty);

    if (equal(tok, "[")) {
        tok = tok->next;
        int len = 0;
        if (tok->kind == TK_NUM) {
            len = tok->val;
            tok = tok->next;
        }
        tok = skip(tok, "]");
        ty = type_suffix(rest, tok, ty);
        if (ty->kind == TY_FUNC)
            error_at(tok->loc, "array element type cannot be a function");
        return array_of(ty, len);
    }

    *rest = tok;
    return ty;
}

// C declarators are recursive: parentheses can change which pointer/array/
// function constructor binds first. Parse the parenthesized shape once with a
// dummy base to locate its end, attach the outer suffix to the real base, then
// replay the inner declarator with that completed base type. This supports
// arrays of function pointers, functions returning function pointers, and
// arbitrarily nested pointer/array/function groupings without syntax-specific
// special cases.
static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract) {
    while (consume(&tok, tok, "*"))
        ty = pointer_to(ty);

    if (equal(tok, "(")) {
        Token *start = tok;
        Type dummy = {};
        declarator_impl(&tok, start->next, &dummy, ident, allow_abstract);
        tok = skip(tok, ")");
        ty = type_suffix(rest, tok, ty);
        return declarator_impl(&tok, start->next, ty, ident, allow_abstract);
    }

    if (tok->kind == TK_IDENT) {
        *ident = tok;
        tok = tok->next;
    } else if (allow_abstract) {
        *ident = NULL;
    } else {
        error_at(tok->loc, "expected a variable name");
    }

    return type_suffix(rest, tok, ty);
}

static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, false);
}

static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, true);
}

'''
s = s[:start] + new_decl + s[end:]

old_start = s.index('        if (consume(&tok, tok, "(")) {\n            // Function definition or prototype.')
old_end = s.index('        } else {\n            // Global variable(s) (possibly with initializer)', old_start)
new_func = r'''        if (ty->kind == TY_FUNC) {
            char *name = strndup(ident->loc, ident->len);

            // Register the declaration before parsing a body so recursion and
            // function-address expressions inside the definition see it.
            register_function_symbol(name, ty->return_ty, is_static,
                                     ty->params, ty->is_variadic, ty->has_prototype);

            // Prototype only: the recursive declarator has already consumed
            // the complete parameter list.
            if (consume(&tok, tok, ";"))
                continue;

            locals = NULL;
            current_gotos = NULL;
            current_labels = NULL;
            enter_scope();

            Obj param_head = {};
            Obj *pcur = &param_head;
            for (Obj *meta = ty->params; meta; meta = meta->param_next) {
                if (!meta->name)
                    error_at(ident->loc, "parameter name omitted in function definition");
                Obj *var = create_lvar(meta->name);
                var->ty = meta->ty;
                pcur = pcur->param_next = var;
            }

            tok = skip(tok, "{");

            Function *fn = calloc(1, sizeof(Function));
            fn->name = name;
            fn->params = param_head.param_next;
            fn->return_ty = ty->return_ty;
            fn->is_static = is_static;
            fn->is_variadic = ty->is_variadic;

            Node *block = compound_stmt(&tok, tok);
            fn->body = block->body;
            fn->locals = locals;

            resolve_gotos();
            fn->gotos = current_gotos;
            fn->labels = current_labels;

            leave_scope();
            cur = cur->next = fn;
'''
s = s[:old_start] + new_func + s[old_end:]

p.write_text(s)

mk = Path('Makefile')
m = mk.read_text()
anchor = '\tbash ./test/prototype_arity.sh\n'
if anchor not in m:
    raise SystemExit('Makefile anchor not found')
m = m.replace(anchor, anchor + '\tbash ./test/recursive_declarators.sh\n', 1)
mk.write_text(m)

readme = Path('README.md')
r = readme.read_text()
old = '- **Declarations**: local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed scalar/pointer parameters, abstract nested function-pointer callback declarators, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
new = '- **Declarations**: recursive C declarators with pointer/array/function grouping (including arrays of function pointers and functions returning function pointers), local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)'
if old not in r:
    raise SystemExit('README declaration line not found')
r = r.replace(old, new, 1)
readme.write_text(r)

Path('test/recursive_declarators.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  ./minicc "$input" > tmp.s
  cc -o tmp tmp.s
  set +e
  ./tmp
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "recursive declarator failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(recursive declarator): $actual"
}

assert_fail() {
  input="$1"
  if ./minicc "$input" > tmp.s 2>/dev/null; then
    echo "recursive declarator unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(recursive declarator): rejected invalid input"
}

assert_run 10 'int inc(int x){return x+1;} int dbl(int x){return x*2;} int main(){int (*table[2])(int); table[0]=inc; table[1]=dbl; return table[0](3)+table[1](3);}'
assert_run 16 'int main(){int (*table[2])(int); return sizeof(table);}'
assert_run 6 'int inc(int x){return x+1;} int (*factory(void))(int){return inc;} int main(){return factory()(5);}'
assert_run 8 'int (*factory(void))(int); int add3(int x){return x+3;} int (*factory(void))(int){return add3;} int main(){return factory()(5);}'
assert_run 32 'int main(){int (*(*p)[4])(double); return sizeof(*p);}'
assert_run 9 'typedef int Fn(int); int inc(int x){return x+1;} int main(){Fn *p=inc; return p(8);}'
assert_run 7 'int pick(int a[3]){return a[1];} int main(){int a[3]; a[1]=7; return pick(a);}'
assert_run 6 'int inc(int x){return x+1;} int apply(int cb(int), int x){return cb(x);} int main(){return apply(inc,5);}'
assert_run 8 'int inc(int x){return x+1;} int dbl(int x){return x*2;} int main(){int (*table[2])(int); int (*(*p)[2])(int)=&table; (*p)[0]=inc; (*p)[1]=dbl; return (*p)[1](4);}'
assert_run 12 'typedef int (*Fn)(int); int add4(int x){return x+4;} Fn factory(void){return add4;} int main(){return factory()(8);}'
assert_run 11 'int add5(int x){return x+5;} int (*table[2])(int); int main(){table[1]=add5; return table[1](6);}'
assert_fail 'int bad[2](int); int main(){return 0;}'

echo 'All recursive declarator tests passed!'
''')
print('Recursive declarator migration applied')
