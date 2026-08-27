from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"{path}: expected one anchor, found {n}")
    p.write_text(s.replace(old, new, 1))

# Remove duplicated function-call metadata from Obj. TY_FUNC is the source of truth.
replace_once('minicc.h', '''    // Function-symbol metadata\n    Obj *func_params;    // declared named parameters for direct-call coercion\n    bool func_variadic;  // function declaration has an ellipsis\n\n''', '')

p = Path('parse.c')
s = p.read_text()

# Replace the arbitrary-callee argument parser with one shared parser used by
# direct, function-pointer, and arbitrary-expression calls.
start = s.index('static Node *indirect_funcall(Token **rest, Token *tok, Node *callee) {')
end = s.index('static Node *postfix(Token **rest, Token *tok) {', start)
shared = r'''static Type *default_argument_promotion(Type *ty) {
    if (!ty)
        return NULL;
    if (ty->kind == TY_FLOAT)
        return ty_double;
    if (ty->kind == TY_BOOL || ty->kind == TY_CHAR || ty->kind == TY_SHORT)
        return ty_int;
    return NULL;
}

static Node *cast_call_argument(Node *arg, Type *ty) {
    if (!ty || arg->ty == ty)
        return arg;
    Node *cast = new_unary(ND_CAST, arg);
    cast->ty = ty;
    return cast;
}

// Parse a call's comma-separated argument list after the opening parenthesis.
// All call forms use this one path so prototype arity, assignment compatibility,
// numeric coercion, and default argument promotions cannot drift apart.
static Node *parse_call_arguments(Token **rest, Token *tok, Type *fty) {
    Obj *expected = fty && fty->has_prototype ? fty->params : NULL;
    bool has_prototype = fty && fty->has_prototype;
    bool variadic = fty && fty->is_variadic;

    Node head = {};
    Node *cur = &head;
    while (!equal(tok, ")")) {
        if (cur != &head)
            tok = skip(tok, ",");

        if (has_prototype && !expected && !variadic)
            error_at(tok->loc, "too many arguments");

        Node *arg = assign(&tok, tok);
        add_type(arg);

        if (expected) {
            if (!assignment_compatible(expected->ty, arg))
                error_at(tok->loc, "incompatible argument type");
            if (is_numeric(arg->ty) && is_numeric(expected->ty))
                arg = cast_call_argument(arg, expected->ty);
            expected = expected->param_next;
        } else if (!has_prototype || variadic) {
            // C default argument promotions apply to every argument of an
            // unprototyped call and to the variadic tail after fixed params.
            Type *promoted = default_argument_promotion(arg->ty);
            if (promoted)
                arg = cast_call_argument(arg, promoted);
        }

        cur = cur->next = arg;
    }

    if (has_prototype && expected)
        error_at(tok->loc, "too few arguments");

    *rest = skip(tok, ")");
    return head.next;
}

static Node *indirect_funcall(Token **rest, Token *tok, Node *callee) {
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
    node->args = parse_call_arguments(&tok, tok, fty);
    *rest = tok;
    return node;
}

'''
s = s[:start] + shared + s[end:]

# Collapse the two identifier-call implementations. Function-pointer variables
# now fall through to normal ND_VAR parsing and are called by postfix(). Direct
# function symbols preserve funcname for direct code generation.
ident = s.index('    if (tok->kind == TK_IDENT) {')
call_start = s.index('        // Function call\n', ident)
ordinary = s.index('        Obj *var = find_var(tok);\n        if (!var)\n', call_start)
new_call = r'''        // Direct function calls keep a named callee for codegen. A variable
        // of function-pointer type falls through to ND_VAR and is handled by
        // the ordinary postfix-call path, sharing the same argument parser.
        if (equal(tok->next, "(")) {
            Obj *fn = find_var(tok);
            if (!fn || fn->is_function) {
                Node *node = new_node(ND_FUNCALL);
                node->funcname = strndup(tok->loc, tok->len);

                Type *fty = NULL;
                if (fn && fn->ty && fn->ty->kind == TY_FUNC) {
                    fty = fn->ty;
                    node->ty = fty->return_ty;
                }

                tok = skip(tok->next, "(");
                node->args = parse_call_arguments(&tok, tok, fty);
                *rest = tok;
                return node;
            }
        }

'''
s = s[:call_start] + new_call + s[ordinary:]

# TY_FUNC metadata is now authoritative; delete the mirrors maintained on Obj.
s = s.replace('''        var->func_params = var->ty->params;\n        var->func_variadic = var->ty->is_variadic;\n''', '')
s = s.replace('''    fn_obj->func_params = fty->params;\n    fn_obj->func_variadic = fty->is_variadic;\n''', '')
if 'func_params' in s or 'func_variadic' in s:
    raise SystemExit('stale duplicated function metadata remains in parse.c')
p.write_text(s)

# Add focused regression suite.
test = r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-callargs.c
  ./minicc tmp-callargs.c > tmp-callargs.s
  cc -o tmp-callargs tmp-callargs.s
  set +e
  ./tmp-callargs
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "call-argument test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(call arguments): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-callargs.c
  if ./minicc tmp-callargs.c > /dev/null 2>&1; then
    echo "call-argument test should have been rejected"
    echo "$input"
    exit 1
  fi
  echo "OK(call arguments): rejected invalid call"
}

# Fixed prototypes use the same coercion path for direct, pointer, and
# arbitrary-expression callees.
assert_run 1 'int exact(double x){return x==1.5;} int main(){return exact(1.5f);}'
assert_run 1 'int exact(double x){return x==1.5;} int main(){int (*fp)(double)=exact;return fp(1.5f);}'
assert_run 1 'int exact(double x){return x==1.5;} int main(){int (*fp)(double)=exact;return (1?fp:fp)(1.5f);}'
assert_run 7 'int add(int a,int b){return a+b;} int main(){int (*fp)(int,int)=add;return (*fp)(3,4);}'

# Arity/type diagnostics remain identical across direct and indirect forms.
assert_reject 'int f(int); int main(){return f();}'
assert_reject 'int f(int); int main(){return f(1,2);}'
assert_reject 'int f(int); int main(){int (*fp)(int)=f;return fp();}'
assert_reject 'int f(int); int main(){int (*fp)(int)=f;return (fp)(1,2);}'
assert_reject 'int f(int *); int main(){double x=1;return f(&x);}'
assert_reject 'int f(int *); int main(){int (*fp)(int *)=f;double x=1;return fp(&x);}'

# Build host helpers to observe ABI-level default promotions on unprototyped
# calls. A float argument must arrive as double; narrow integers must arrive as int.
cat > tmp-call-helper.c <<'EOF'
int promoted_double(double x) { return x == 1.5; }
int promoted_int(int x) { return x == -1; }
EOF
cc -c -o tmp-call-helper.o tmp-call-helper.c

assert_external() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-callargs.c
  ./minicc tmp-callargs.c > tmp-callargs.s
  cc -o tmp-callargs tmp-callargs.s tmp-call-helper.o
  set +e
  ./tmp-callargs
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "external call-argument test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(call arguments external): $actual"
}

assert_external 1 'int promoted_double(); int main(){return promoted_double(1.5f);}'
assert_external 1 'int promoted_double(); int main(){int (*fp)()=promoted_double;return fp(1.5f);}'
assert_external 1 'int promoted_double(); int main(){int (*fp)()=promoted_double;return (0,fp)(1.5f);}'
assert_external 1 'int promoted_int(); int main(){return promoted_int((char)-1);}'
assert_external 1 'int promoted_int(); int main(){int (*fp)()=promoted_int;return fp((short)-1);}'

rm -f tmp-call-helper.c tmp-call-helper.o

echo 'All unified call-argument tests passed!'
'''
Path('test/call_arguments.sh').write_text(test)

# Wire the suite into make test and update the README feature summary.
replace_once('Makefile', '\tbash ./test/constant_expressions.sh\n', '\tbash ./test/constant_expressions.sh\n\tbash ./test/call_arguments.sh\n')

p = Path('README.md')
s = p.read_text()
needle = 'function'
if 'default argument promotions' not in s:
    # Keep documentation edit deliberately small and robust against wording drift.
    s += '\n- Function calls share prototype-aware argument coercion and C default argument promotions for variadic and unprototyped calls.\n'
p.write_text(s)
