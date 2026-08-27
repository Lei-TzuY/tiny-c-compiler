from pathlib import Path


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"missing migration anchor: {label}")
    return text.replace(old, new, 1)

p = Path("parse.c")
s = p.read_text()

s = replace_once(
    s,
    "static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident);\n",
    "static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident);\n"
    "static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident);\n",
    "declarator forward declaration",
)

s = replace_once(
    s,
    "static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {\n",
    "static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,\n"
    "                             bool allow_abstract) {\n",
    "declarator implementation",
)

s = replace_once(
    s,
    "        if (tok->kind != TK_IDENT)\n"
    "            error_at(tok->loc, \"expected identifier in function pointer declarator\");\n"
    "        *ident = tok;\n"
    "        tok = tok->next;\n"
    "        tok = skip(tok, \")\");\n",
    "        if (tok->kind == TK_IDENT) {\n"
    "            *ident = tok;\n"
    "            tok = tok->next;\n"
    "        } else if (allow_abstract) {\n"
    "            *ident = NULL;\n"
    "        } else {\n"
    "            error_at(tok->loc, \"expected identifier in function pointer declarator\");\n"
    "        }\n"
    "        tok = skip(tok, \")\");\n",
    "abstract function pointer identifier",
)

s = replace_once(
    s,
    "                    param_ty = declarator(&tok, tok, param_ty, &pident);\n",
    "                    param_ty = declarator_impl(&tok, tok, param_ty, &pident, true);\n",
    "nested function pointer parameter",
)

s = replace_once(
    s,
    "    if (tok->kind != TK_IDENT)\n"
    "        error_at(tok->loc, \"expected a variable name\");\n\n"
    "    *ident = tok;\n"
    "    tok = tok->next;\n",
    "    if (tok->kind != TK_IDENT) {\n"
    "        if (!allow_abstract)\n"
    "            error_at(tok->loc, \"expected a variable name\");\n"
    "        *ident = NULL;\n"
    "        *rest = tok;\n"
    "        return ty;\n"
    "    }\n\n"
    "    *ident = tok;\n"
    "    tok = tok->next;\n",
    "abstract plain declarator",
)

s = replace_once(
    s,
    "    *rest = tok;\n"
    "    return ty;\n"
    "}\n\n"
    "// Parse a constant integer (with optional sign) for global initializers\n",
    "    *rest = tok;\n"
    "    return ty;\n"
    "}\n\n"
    "static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {\n"
    "    return declarator_impl(rest, tok, ty, ident, false);\n"
    "}\n\n"
    "static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident) {\n"
    "    return declarator_impl(rest, tok, ty, ident, true);\n"
    "}\n\n"
    "// Parse a constant integer (with optional sign) for global initializers\n",
    "declarator wrappers",
)

old_param = '''                    Token *pident = NULL;
                    Obj *var = NULL;
                    if (tok->kind == TK_IDENT ||
                        (equal(tok, "(") && equal(tok->next, "*"))) {
                        param_ty = declarator(&tok, tok, param_ty, &pident);
                        char *pname = strndup(pident->loc, pident->len);
                        var = create_lvar(pname);
                    } else {
                        // Prototype parameter names are optional in C. Keep an
                        // anonymous metadata Obj so direct-call coercion still
                        // sees the declared parameter type.
                        if (!equal(tok, ",") && !equal(tok, ")"))
                            error_at(tok->loc, "expected parameter name or delimiter");
                        has_unnamed_params = true;
                        var = calloc(1, sizeof(Obj));
                        var->is_local = true;
                    }
'''
new_param = '''                    Token *pident = NULL;
                    Obj *var = NULL;
                    if (tok->kind == TK_IDENT ||
                        (equal(tok, "(") && equal(tok->next, "*"))) {
                        // Function prototypes may use abstract callback declarators,
                        // e.g. `int apply(int (*)(int), int);`. Definitions still
                        // require names and are rejected below when pident is NULL.
                        param_ty = abstract_declarator(&tok, tok, param_ty, &pident);
                        if (pident) {
                            char *pname = strndup(pident->loc, pident->len);
                            var = create_lvar(pname);
                        } else {
                            has_unnamed_params = true;
                            var = calloc(1, sizeof(Obj));
                            var->is_local = true;
                        }
                    } else {
                        // Prototype parameter names are optional in C. Keep an
                        // anonymous metadata Obj so direct-call coercion still
                        // sees the declared parameter type.
                        if (!equal(tok, ",") && !equal(tok, ")"))
                            error_at(tok->loc, "expected parameter name or delimiter");
                        has_unnamed_params = true;
                        var = calloc(1, sizeof(Obj));
                        var->is_local = true;
                    }
'''
s = replace_once(s, old_param, new_param, "top-level abstract callback parameter")

helper = r'''static Node *indirect_funcall(Token **rest, Token *tok, Node *callee) {
    add_type(callee);

    Type *fty = NULL;
    if (callee->ty->kind == TY_FUNC)
        fty = callee->ty;
    else if (callee->ty->kind == TY_PTR && callee->ty->base &&
             callee->ty->base->kind == TY_FUNC)
        fty = callee->ty->base;

    if (!fty)
        error_at(tok->loc, "called object is not a function or function pointer");

    Node *node = new_node(ND_FUNCALL);
    node->funcname = NULL;
    node->lhs = callee;
    node->ty = fty->return_ty;
    tok = skip(tok, "(");

    Obj *expected = fty->params;
    bool variadic = fty->is_variadic;
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
}

'''
s = replace_once(
    s,
    "static Node *postfix(Token **rest, Token *tok) {\n",
    helper + "static Node *postfix(Token **rest, Token *tok) {\n",
    "generic indirect call helper",
)

s = replace_once(
    s,
    "    for (;;) {\n"
    "        if (equal(tok, \"[\")) {\n",
    "    for (;;) {\n"
    "        // A call is a postfix operator in C, so the callee may be any\n"
    "        // expression whose type is function or pointer-to-function. This\n"
    "        // covers `(fp)(x)`, `(*fp)(x)`, `(&fn)(x)`, ternary/comma callees,\n"
    "        // and deeper pointer chains after explicit dereference.\n"
    "        if (equal(tok, \"(\")) {\n"
    "            node = indirect_funcall(&tok, tok, node);\n"
    "            continue;\n"
    "        }\n\n"
    "        if (equal(tok, \"[\")) {\n",
    "postfix call suffix",
)

p.write_text(s)

m = Path("Makefile")
ms = m.read_text()
anchor = "\tbash ./test/function_pointer_prototype.sh\n"
if anchor not in ms:
    raise SystemExit("missing Makefile test anchor")
ms = ms.replace(anchor, anchor + "\tbash ./test/callable_declarators.sh\n", 1)
m.write_text(ms)

r = Path("README.md")
rs = r.read_text()
old = "- **Declarations**: local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, and prototypes with named or unnamed scalar/pointer parameters\n"
new = "- **Declarations**: local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed scalar/pointer parameters, and abstract nested function-pointer callback declarators\n"
if old not in rs:
    raise SystemExit("missing README declarations anchor")
rs = rs.replace(old, new, 1)
old2 = "Direct calls and prototype-bearing function-pointer calls use declared parameter types for scalar coercion; external variadic calls, including indirect calls, receive the required vector-register count and default float promotion."
new2 = "Direct and indirect calls use declared parameter types for scalar coercion; indirect calls accept arbitrary function-valued postfix expressions such as `(fp)(x)` and `(*fp)(x)`. External variadic calls, including indirect calls, receive the required vector-register count and default float promotion."
if old2 not in rs:
    raise SystemExit("missing README ABI anchor")
rs = rs.replace(old2, new2, 1)
r.write_text(rs)

Path("test/callable_declarators.sh").write_text(r'''#!/bin/bash
set -e

assert_call() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-callable.c
  "${MINICC:-./minicc}" tmp-callable.c > tmp-callable.s
  gcc -o tmp-callable tmp-callable.s
  set +e
  ./tmp-callable
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(callable declarator): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(callable declarator): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-callable-bad.c
  if "${MINICC:-./minicc}" tmp-callable-bad.c > tmp-callable-bad.s 2>/dev/null; then
    echo "FAIL(callable declarator): accepted invalid call"
    echo "$input"
    exit 1
  fi
  echo "OK(callable declarator): rejected non-callable expression"
}

assert_call 5 'double add2(double x){return x+2;} int main(){double (*fp)(double)=add2; return (int)(fp)(3);}'
assert_call 5 'double add2(double x){return x+2;} int main(){double (*fp)(double)=add2; return (int)(*fp)(3);}'
assert_call 8 'int add(int a,int b){return a+b;} int main(){return (add)(3,5);}'
assert_call 8 'int add(int a,int b){return a+b;} int main(){return (&add)(3,5);}'
assert_call 8 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add; int (**pp)(int,int)=&fp; return (**pp)(3,5);}'
assert_call 5 'int add1(int x){return x+1;} int add2(int x){return x+2;} int main(){int (*a)(int)=add1; int (*b)(int)=add2; return (0?a:b)(3);}'
assert_call 7 'int add4(int x){return x+4;} int main(){int (*fp)(int)=add4; return (0,fp)(3);}'
assert_call 5 'int apply(int (*)(int), int); int inc(int x){return x+1;} int apply(int (*f)(int),int x){return f(x);} int main(){return apply(inc,4);}'
assert_call 6 'typedef int (*Apply)(int (*)(int),int); int inc(int x){return x+1;} int apply(int (*f)(int),int x){return f(x);} int main(){Apply p=apply; return p(inc,5);}'
assert_call 1 'int sprintf(char *s,char *fmt,...); int main(){int (*fp)(char *,char *,...)=sprintf; char b[32]; float x=2.5f; (fp)(b,"%g",x); return b[0]==50;}'
assert_reject 'int main(){int x=3; return (x)(1);}'

echo "All callable-expression/declarator tests passed!"
''')

print("Callable declarator migration applied")
