from pathlib import Path


def repl(text, old, new, label, count=1):
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, count)

# Type metadata
p = Path("minicc.h")
s = p.read_text()
s = repl(s,
    "    Obj *params;       // TY_FUNC: declared parameter types (metadata Obj list)\n    bool is_variadic; // TY_FUNC: variadic function (...)\n",
    "    Obj *params;       // TY_FUNC: declared parameter types (metadata Obj list)\n    bool is_variadic; // TY_FUNC: variadic function (...)\n    bool has_prototype; // TY_FUNC: distinguish f(void)/f(int) from old-style f()\n",
    "Type prototype flag")
p.write_text(s)

p = Path("parse.c")
s = p.read_text()

# Function-pointer declarator: remember whether the list is a real prototype.
s = repl(s,
    "        Obj param_head = {};\n        Obj *pcur = &param_head;\n        bool is_variadic = false;\n\n        if (equal(tok, \"void\") && equal(tok->next, \")\")) {\n",
    "        Obj param_head = {};\n        Obj *pcur = &param_head;\n        bool is_variadic = false;\n        bool has_prototype = !equal(tok, \")\");\n\n        if (equal(tok, \"void\") && equal(tok->next, \")\")) {\n",
    "function pointer prototype detection")
s = repl(s,
    "        fty->params = param_head.param_next;\n        fty->is_variadic = is_variadic;\n",
    "        fty->params = param_head.param_next;\n        fty->is_variadic = is_variadic;\n        fty->has_prototype = has_prototype;\n",
    "function pointer prototype metadata")

# Generic indirect call arity.
s = repl(s,
    "    Obj *expected = fty->params;\n    bool variadic = fty->is_variadic;\n",
    "    Obj *expected = fty->params;\n    bool variadic = fty->is_variadic;\n    bool has_prototype = fty->has_prototype;\n",
    "indirect prototype state")
s = repl(s,
    "        Node *arg = assign(&tok, tok);\n        add_type(arg);\n\n        if (expected) {\n",
    "        if (has_prototype && !expected && !variadic)\n            error_at(tok->loc, \"too many arguments\");\n\n        Node *arg = assign(&tok, tok);\n        add_type(arg);\n\n        if (expected) {\n",
    "indirect too many")
s = repl(s,
    "    *rest = skip(tok, \")\");\n    node->args = head.next;\n    return node;\n}\n\nstatic Node *postfix",
    "    if (has_prototype && expected)\n        error_at(tok->loc, \"too few arguments\");\n\n    *rest = skip(tok, \")\");\n    node->args = head.next;\n    return node;\n}\n\nstatic Node *postfix",
    "indirect too few")

# Identifier function-pointer fast path arity.
s = repl(s,
    "                Obj *expected = fty ? fty->params : NULL;\n                bool variadic = fty && fty->is_variadic;\n",
    "                Obj *expected = fty ? fty->params : NULL;\n                bool variadic = fty && fty->is_variadic;\n                bool has_prototype = fty && fty->has_prototype;\n",
    "identifier indirect prototype state")
# Replace the second matching call-argument parse block only by anchoring surrounding text.
old = '''                while (!equal(tok, ")")) {
                    if (cur != &head)
                        tok = skip(tok, ",");

                    Node *arg = assign(&tok, tok);
                    add_type(arg);

                    if (expected) {
'''
new = '''                while (!equal(tok, ")")) {
                    if (cur != &head)
                        tok = skip(tok, ",");

                    if (has_prototype && !expected && !variadic)
                        error_at(tok->loc, "too many arguments");

                    Node *arg = assign(&tok, tok);
                    add_type(arg);

                    if (expected) {
'''
# At this point generic helper has different indentation, so first exact match is identifier path.
s = repl(s, old, new, "identifier indirect too many", 1)
s = repl(s,
    "                *rest = skip(tok, \")\");\n                node->args = head.next;\n                return node;\n            }\n\n            // Direct call\n",
    "                if (has_prototype && expected)\n                    error_at(tok->loc, \"too few arguments\");\n\n                *rest = skip(tok, \")\");\n                node->args = head.next;\n                return node;\n            }\n\n            // Direct call\n",
    "identifier indirect too few")

# Direct call arity.
s = repl(s,
    "            Obj *expected = (var && var->is_function) ? var->func_params : NULL;\n            bool variadic = var && var->is_function && var->func_variadic;\n",
    "            Obj *expected = (var && var->is_function) ? var->func_params : NULL;\n            bool variadic = var && var->is_function && var->func_variadic;\n            bool has_prototype = var && var->is_function && var->ty->kind == TY_FUNC &&\n                                 var->ty->has_prototype;\n",
    "direct prototype state")
old = '''            while (!equal(tok, ")")) {
                if (cur != &head)
                    tok = skip(tok, ",");

                Node *arg = assign(&tok, tok);
                add_type(arg);

                if (expected) {
'''
new = '''            while (!equal(tok, ")")) {
                if (cur != &head)
                    tok = skip(tok, ",");

                if (has_prototype && !expected && !variadic)
                    error_at(tok->loc, "too many arguments");

                Node *arg = assign(&tok, tok);
                add_type(arg);

                if (expected) {
'''
s = repl(s, old, new, "direct too many", 1)
s = repl(s,
    "            *rest = skip(tok, \")\");\n            node->args = head.next;\n            return node;\n        }\n\n        Obj *var = find_var(tok);\n",
    "            if (has_prototype && expected)\n                error_at(tok->loc, \"too few arguments\");\n\n            *rest = skip(tok, \")\");\n            node->args = head.next;\n            return node;\n        }\n\n        Obj *var = find_var(tok);\n",
    "direct too few")

# Function-symbol metadata. Preserve a prior real prototype if a later old-style
# declaration/definition uses an empty parameter list.
s = repl(s,
    "static void register_function_symbol(char *name, Type *return_ty, bool is_static,\n                                     Obj *params, bool is_variadic) {\n",
    "static void register_function_symbol(char *name, Type *return_ty, bool is_static,\n                                     Obj *params, bool is_variadic, bool has_prototype) {\n",
    "register signature")
old = '''        if (!strcmp(var->name, name) && var->is_function) {
            var->ty = func_type(return_ty);
            var->ty->params = params;
            var->ty->is_variadic = is_variadic;
            var->func_params = params;
            var->func_variadic = is_variadic;
            var->is_static = is_static;
            return;
        }
'''
new = '''        if (!strcmp(var->name, name) && var->is_function) {
            Type *old_ty = var->ty;
            Type *fty = func_type(return_ty);
            if (!has_prototype && old_ty && old_ty->kind == TY_FUNC &&
                old_ty->has_prototype) {
                // An old-style `f()` redeclaration must not erase a previously
                // known prototype.
                fty->params = old_ty->params;
                fty->is_variadic = old_ty->is_variadic;
                fty->has_prototype = true;
            } else {
                fty->params = params;
                fty->is_variadic = is_variadic;
                fty->has_prototype = has_prototype;
            }
            var->ty = fty;
            var->func_params = fty->params;
            var->func_variadic = fty->is_variadic;
            var->is_static = is_static;
            return;
        }
'''
s = repl(s, old, new, "register refresh")
s = repl(s,
    "    fn_obj->ty->params = params;\n    fn_obj->ty->is_variadic = is_variadic;\n",
    "    fn_obj->ty->params = params;\n    fn_obj->ty->is_variadic = is_variadic;\n    fn_obj->ty->has_prototype = has_prototype;\n",
    "register new symbol")

# Top-level function parsing: empty () is old-style/no prototype; (void), typed
# lists, and variadic lists are prototypes.
s = repl(s,
    "        if (consume(&tok, tok, \"(\")) {\n            // Function definition or prototype\n",
    "        if (consume(&tok, tok, \"(\")) {\n            // Function definition or prototype. In C11, an empty `()` does\n            // not provide a parameter prototype; `(void)` does.\n            bool has_prototype = !equal(tok, \")\");\n",
    "top-level prototype detection")
s = repl(s,
    "            register_function_symbol(name, basety, is_static,\n                                     param_head.param_next, is_variadic);\n",
    "            register_function_symbol(name, basety, is_static,\n                                     param_head.param_next, is_variadic, has_prototype);\n",
    "register call")
p.write_text(s)

# Regression suite
m = Path("Makefile")
ms = m.read_text()
anchor = "\tbash ./test/callable_declarators.sh\n"
if anchor not in ms:
    raise SystemExit("missing Makefile anchor")
ms = ms.replace(anchor, anchor + "\tbash ./test/prototype_arity.sh\n", 1)
m.write_text(ms)

r = Path("README.md")
rs = r.read_text()
old = "- **Declarations**: local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed scalar/pointer parameters, and abstract nested function-pointer callback declarators\n"
new = "- **Declarations**: local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, prototypes with named or unnamed scalar/pointer parameters, abstract nested function-pointer callback declarators, and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)\n"
if old not in rs:
    raise SystemExit("missing README anchor")
r.write_text(rs.replace(old, new, 1))

Path("test/prototype_arity.sh").write_text(r'''#!/bin/bash
set -e

assert_ok() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-arity.c
  "${MINICC:-./minicc}" tmp-arity.c > tmp-arity.s
  gcc -o tmp-arity tmp-arity.s
  set +e
  ./tmp-arity
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(prototype arity): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype arity): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-arity-bad.c
  if "${MINICC:-./minicc}" tmp-arity-bad.c > tmp-arity-bad.s 2>/dev/null; then
    echo "FAIL(prototype arity): accepted invalid argument count"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype arity): rejected invalid argument count"
}

# Real prototypes are strict.
assert_ok 3 'int zero(void){return 3;} int main(){return zero();}'
assert_ok 6 'int sum(int a,int b,...){return a+b;} int main(){return sum(1,5,7,9);}'
assert_ok 7 'int old(); int main(){return old(7);} int old(int x){return x;}'
assert_ok 5 'int one(int x){return x;} int main(){int (*fp)()=one; return fp(5);}'

assert_reject 'int add(int,int); int main(){return add(1);}'
assert_reject 'int add(int,int); int main(){return add(1,2,3);}'
assert_reject 'int zero(void); int main(){return zero(1);}'
assert_reject 'int sum(int,int,...); int main(){return sum(1);}'
assert_reject 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add; return fp(1);}'
assert_reject 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add; return (fp)(1,2,3);}'
assert_reject 'int apply(int (*)(int),int); int inc(int x){return x+1;} int main(){return apply(inc);}'
assert_reject 'int apply(int (*)(int),int); int inc(int x){return x+1;} int main(){return apply(inc,1,2);}'

# A prior prototype is not erased by a later old-style declaration.
assert_reject 'int add(int,int); int add(); int main(){return add(1);}'

echo "All prototype arity tests passed!"
''')

print("Prototype arity migration applied")
