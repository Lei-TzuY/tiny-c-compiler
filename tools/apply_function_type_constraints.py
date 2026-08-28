from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    s = s.replace(old, new, 1)
    p.write_text(s)


replace_once(
    "parse.c",
    '''    while (!equal(tok, ")")) {
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

        if (name) {
''',
    '''    while (!equal(tok, ")")) {
        if (cur != &head) {
            tok = skip(tok, ",");
            if (equal(tok, ")"))
                error_at(tok->loc, "trailing comma in parameter list");
        }

        if (equal(tok, "...")) {
            if (cur == &head)
                error_at(tok->loc, "ellipsis requires a preceding fixed parameter");
            tok = tok->next;
            fty->is_variadic = true;
            break;
        }

        Type *basety = declspec(&tok, tok);
        Token *name = NULL;
        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true);
        param_ty = adjust_param_type(param_ty);

        // The only valid non-pointer use of void in a parameter-type-list is
        // one unqualified, unnamed parameter denoting an empty parameter list.
        // Handle the semantic type as well as the literal spelling so a
        // `typedef void V; int f(V);` prototype is equivalent to `f(void)`.
        if (param_ty->kind == TY_VOID) {
            Token *at = name ? name : tok;
            if (name || param_ty->is_const || param_ty->is_volatile ||
                cur != &head || !equal(tok, ")"))
                error_at(at->loc,
                         "void parameter must be the only unqualified unnamed parameter");
            fty->params = NULL;
            fty->has_prototype = true;
            *rest = skip(tok, ")");
            return fty;
        }

        if (name) {
''',
    "parameter-list constraints",
)

replace_once(
    "parse.c",
    '''static Type *type_suffix(Token **rest, Token *tok, Type *ty) {
    if (equal(tok, "("))
        return func_params(rest, tok->next, ty);

    if (equal(tok, "[")) {
''',
    '''static Type *type_suffix(Token **rest, Token *tok, Type *ty) {
    if (equal(tok, "(")) {
        if (ty->kind == TY_ARRAY)
            error_at(tok->loc, "function cannot return an array type");
        if (ty->kind == TY_FUNC)
            error_at(tok->loc, "function cannot return a function type");
        return func_params(rest, tok->next, ty);
    }

    if (equal(tok, "[")) {
''',
    "function return type constraints",
)

replace_once(
    "parse.c",
    '''            if (is_definition)
                check_supported_function_abi(ty, ident);

            // Register the declaration before parsing a body so recursion and
''',
    '''            if (is_definition) {
                if (is_incomplete_object_type(ty->return_ty))
                    error_at(ident->loc,
                             "function definition has incomplete return type");
                for (Obj *meta = ty->params; meta; meta = meta->param_next)
                    if (is_incomplete_object_type(meta->ty))
                        error_at(ident->loc,
                                 "function definition has incomplete parameter type");
                check_supported_function_abi(ty, ident);
            }

            // Register the declaration before parsing a body so recursion and
''',
    "definition completeness constraints",
)

make = Path("Makefile")
s = make.read_text()
anchor = "\tbash ./test/control_condition_scalars.sh\n"
if anchor not in s:
    raise SystemExit("Makefile control-condition anchor missing")
s = s.replace(anchor, anchor + "\tbash ./test/function_type_constraints.sh\n", 1)
make.write_text(s)

readme = Path("README.md")
s = readme.read_text()
old = "prototypes with named or unnamed parameters, abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking"
new = "prototypes with named or unnamed parameters, standard void/variadic parameter-list constraints, incomplete-record prototypes that must be complete by function definition, non-array/non-function return-type constraints (including typedef-hidden shapes), abstract callback declarators, parameter array/function adjustment, and prototype-aware call arity checking"
if old not in s:
    raise SystemExit("README declaration anchor missing")
s = s.replace(old, new, 1)
readme.write_text(s)

Path("test/function_type_constraints.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-fn-type.c
  ./minicc tmp-fn-type.c > tmp-fn-type.s
  cc -o tmp-fn-type tmp-fn-type.s
  set +e
  ./tmp-fn-type
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function type): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(function type): $actual"
}

assert_accept() {
  input="$1"
  printf '%s\n' "$input" > tmp-fn-type-accept.c
  ./minicc tmp-fn-type-accept.c > tmp-fn-type-accept.s
  cc -o tmp-fn-type-accept tmp-fn-type-accept.s
  ./tmp-fn-type-accept
  echo "OK(function type): accepted declaration shape"
}

assert_reject_msg() {
  pattern="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-fn-type-reject.c
  if ./minicc tmp-fn-type-reject.c > /dev/null 2>tmp-fn-type.err; then
    echo "FAIL(function type): expected rejection"
    echo "$input"
    exit 1
  fi
  if ! grep -q "$pattern" tmp-fn-type.err; then
    echo "FAIL(function type): missing diagnostic '$pattern'"
    cat tmp-fn-type.err
    exit 1
  fi
  echo "OK(function type): rejected with $pattern"
}

# Incomplete records are representable in prototypes and become valid by-value
# ABI types once the same tagged type is completed before the definition.
assert_run 7 'struct S; int get(struct S); struct S{int x;}; int get(struct S s){return s.x;} int main(void){struct S s={7};return get(s);}'
assert_run 9 'struct S; struct S make(void); struct S{int x;}; struct S make(void){struct S s={9};return s;} int main(void){return make().x;}'
assert_run 11 'struct S; struct S id(struct S); struct S{int x;}; struct S id(struct S s){return s;} int main(void){struct S s={11};return id(s).x;}'
# A typedef naming unqualified void has the same zero-parameter meaning as (void).
assert_run 4 'typedef void V; int f(V); int f(void){return 4;} int main(void){return f();}'
# Pointer-to-void remains an ordinary parameter type.
assert_run 5 'int f(void *p){return p?5:1;} int main(void){int x=0;return f(&x);}'
# Standard variadic form requires a fixed parameter before the ellipsis.
assert_accept 'int ext(int,...); int main(void){return 0;}'
# Returning pointers to array/function types is valid; only returning those
# types themselves is forbidden.
assert_accept 'typedef int A[3]; A *factory(void); int main(void){return 0;}'
assert_accept 'typedef int F(void); F *factory(void); int main(void){return 0;}'
# A prototype may remain incomplete when no definition is present.
assert_accept 'struct Opaque; int consume(struct Opaque); struct Opaque produce(void); int main(void){return 0;}'

# Invalid void parameter forms.
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(void x); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'typedef void V; int f(V x); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(const void); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(void,int); int main(void){return 0;}'
assert_reject_msg 'void parameter must be the only unqualified unnamed parameter' 'int f(void,...); int main(void){return 0;}'
# C11 variadic syntax needs at least one fixed parameter and disallows a
# trailing comma before ')'.
assert_reject_msg 'ellipsis requires a preceding fixed parameter' 'int f(...); int main(void){return 0;}'
assert_reject_msg 'trailing comma in parameter list' 'int f(int,); int main(void){return 0;}'

# Typedefs must not hide an illegal array/function return type.
assert_reject_msg 'function cannot return an array type' 'typedef int A[3]; A f(void); int main(void){return 0;}'
assert_reject_msg 'function cannot return a function type' 'typedef int F(void); F f(void); int main(void){return 0;}'
assert_reject_msg 'function cannot return a function type' 'typedef int F(void); typedef F G(void); int main(void){return 0;}'

# Incomplete by-value object types are allowed in a declaration, but a
# definition immediately needs their complete representation.
assert_reject_msg 'function definition has incomplete parameter type' 'struct S; int f(struct S s){return 0;} int main(void){return 0;}'
assert_reject_msg 'function definition has incomplete parameter type' 'typedef struct S S; int f(S s){return 0;} int main(void){return 0;}'
assert_reject_msg 'function definition has incomplete return type' 'struct S; struct S f(void){for(;;){}} int main(void){return 0;}'
assert_reject_msg 'function definition has incomplete return type' 'typedef struct S S; S f(void){for(;;){}} int main(void){return 0;}'

echo 'All function-type constraint tests passed!'
''')
