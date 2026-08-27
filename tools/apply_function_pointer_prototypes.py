from pathlib import Path

# Extend function types with parameter metadata.
p = Path('minicc.h')
s = p.read_text()
old = '''    Type *return_ty;  // TY_FUNC: return type\n    bool is_variadic; // TY_FUNC: variadic function (...)\n'''
new = '''    Type *return_ty;  // TY_FUNC: return type\n    Obj *params;       // TY_FUNC: declared parameter types (metadata Obj list)\n    bool is_variadic; // TY_FUNC: variadic function (...)\n'''
if old not in s:
    raise SystemExit('Type function metadata block not found')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('parse.c')
s = p.read_text()

old_fp = r'''        // Skip parameter declarations (we don't store them)
        if (equal(tok, "void") && equal(tok->next, ")")) {
            tok = tok->next; // void param list = no params
        } else {
            while (!equal(tok, ")")) {
                if (!equal(tok, ",") || equal(tok, ")")) {
                    // Skip tokens until ',' or ')'
                    // Simple approach: skip type + optional name
                    if (is_typename(tok) || equal(tok, "const") || equal(tok, "volatile")) {
                        Type *dummy_ty = declspec(&tok, tok);
                        (void)dummy_ty;
                        while (consume(&tok, tok, "*")) {} // skip pointer stars
                        // Skip optional parameter name
                        if (tok->kind == TK_IDENT && !equal(tok->next, "("))
                            tok = tok->next;
                        // Skip array declarators in params: int arr[]
                        if (consume(&tok, tok, "[")) {
                            while (!equal(tok, "]")) tok = tok->next;
                            tok = skip(tok, "]");
                        }
                    } else {
                        tok = tok->next;
                    }
                }
                if (!equal(tok, ")"))
                    consume(&tok, tok, ",");
            }
        }
        tok = skip(tok, ")");

        // Build type: pointer_to(func_type(return_ty))
        Type *fty = func_type(ty); // ty is the return type (the base)
        ty = pointer_to(fty);
'''

new_fp = r'''        // Retain the complete scalar/pointer prototype on TY_FUNC so calls
        // through function pointers can perform the same coercions as direct calls.
        Obj param_head = {};
        Obj *pcur = &param_head;
        bool is_variadic = false;

        if (equal(tok, "void") && equal(tok->next, ")")) {
            tok = tok->next; // void parameter list = no parameters
        } else {
            while (!equal(tok, ")")) {
                if (pcur != &param_head)
                    tok = skip(tok, ",");
                if (equal(tok, "...")) {
                    tok = tok->next;
                    is_variadic = true;
                    break;
                }

                consume(&tok, tok, "const");
                consume(&tok, tok, "volatile");
                consume(&tok, tok, "register");

                Type *param_ty = declspec(&tok, tok);
                while (consume(&tok, tok, "*"))
                    param_ty = pointer_to(param_ty);

                // Parameter names inside a function-pointer prototype are optional.
                // If present, consume the full declarator (including nested callbacks).
                Token *pident = NULL;
                if (tok->kind == TK_IDENT ||
                    (equal(tok, "(") && equal(tok->next, "*"))) {
                    param_ty = declarator(&tok, tok, param_ty, &pident);
                } else if (!equal(tok, ",") && !equal(tok, ")")) {
                    error_at(tok->loc, "expected function pointer parameter declarator");
                }

                if (is_incomplete_object_type(param_ty))
                    error_at(pident ? pident->loc : tok->loc,
                             "parameter has incomplete type");

                Obj *param = calloc(1, sizeof(Obj));
                param->ty = param_ty;
                pcur = pcur->param_next = param;
            }
        }
        tok = skip(tok, ")");

        // Build type: pointer_to(func_type(return_ty)) and attach prototype metadata.
        Type *fty = func_type(ty); // ty is the return type (the base)
        fty->params = param_head.param_next;
        fty->is_variadic = is_variadic;
        ty = pointer_to(fty);
'''
if old_fp not in s:
    raise SystemExit('function pointer declarator block not found')
s = s.replace(old_fp, new_fp, 1)

old_indirect = r'''            if (var && !var->is_function) {
                // Indirect call through function pointer variable. The current
                // declarator keeps the return type even though it does not yet
                // retain a full function-pointer parameter prototype.
                Node *node = new_node(ND_FUNCALL);
                node->funcname = NULL; // NULL = indirect call
                node->lhs = new_var_node(var); // callee expression
                if (var->ty->kind == TY_PTR && var->ty->base &&
                    var->ty->base->kind == TY_FUNC)
                    node->ty = var->ty->base->return_ty;
                tok = skip(tok->next, "(");

                Node head = {};
                Node *cur = &head;
                while (!equal(tok, ")")) {
                    if (cur != &head) tok = skip(tok, ",");
                    cur = cur->next = assign(&tok, tok);
                }
                *rest = skip(tok, ")");
                node->args = head.next;
                return node;
            }
'''

new_indirect = r'''            if (var && !var->is_function) {
                // Indirect call through a function-pointer variable. If the
                // pointer carries a prototype, use it for scalar coercion and
                // default promotions of variadic arguments.
                Node *node = new_node(ND_FUNCALL);
                node->funcname = NULL; // NULL = indirect call
                node->lhs = new_var_node(var); // callee expression

                Type *fty = NULL;
                if (var->ty->kind == TY_PTR && var->ty->base &&
                    var->ty->base->kind == TY_FUNC) {
                    fty = var->ty->base;
                    node->ty = fty->return_ty;
                }
                tok = skip(tok->next, "(");

                Obj *expected = fty ? fty->params : NULL;
                bool variadic = fty && fty->is_variadic;
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
if old_indirect not in s:
    raise SystemExit('indirect call block not found')
s = s.replace(old_indirect, new_indirect, 1)

old_register = r'''        if (!strcmp(var->name, name) && var->is_function) {
            var->ty = func_type(return_ty);
            var->func_params = params;
            var->func_variadic = is_variadic;
            var->is_static = is_static;
            return;
        }
'''
new_register = r'''        if (!strcmp(var->name, name) && var->is_function) {
            var->ty = func_type(return_ty);
            var->ty->params = params;
            var->ty->is_variadic = is_variadic;
            var->func_params = params;
            var->func_variadic = is_variadic;
            var->is_static = is_static;
            return;
        }
'''
if old_register not in s:
    raise SystemExit('existing function symbol block not found')
s = s.replace(old_register, new_register, 1)

old_new_symbol = r'''    fn_obj->name = name;
    fn_obj->ty = func_type(return_ty);
    fn_obj->func_params = params;
    fn_obj->func_variadic = is_variadic;
'''
new_new_symbol = r'''    fn_obj->name = name;
    fn_obj->ty = func_type(return_ty);
    fn_obj->ty->params = params;
    fn_obj->ty->is_variadic = is_variadic;
    fn_obj->func_params = params;
    fn_obj->func_variadic = is_variadic;
'''
if old_new_symbol not in s:
    raise SystemExit('new function symbol block not found')
s = s.replace(old_new_symbol, new_new_symbol, 1)
p.write_text(s)

# Add focused regression suite.
make = Path('Makefile')
m = make.read_text()
needle = '\tbash ./test/prototype_params.sh\n'
if needle not in m:
    raise SystemExit('prototype test line not found')
if '\tbash ./test/function_pointer_prototype.sh\n' not in m:
    m = m.replace(needle, needle + '\tbash ./test/function_pointer_prototype.sh\n', 1)
make.write_text(m)

Path('test/function_pointer_prototype.sh').write_text(r'''#!/bin/bash
set -e

assert_fp() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-fp-proto.c
  "${MINICC:-./minicc}" tmp-fp-proto.c > tmp-fp-proto.s
  gcc -o tmp-fp-proto tmp-fp-proto.s
  set +e
  ./tmp-fp-proto
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(function pointer prototype): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(function pointer prototype): $actual"
}

assert_fp 5 'double add2(double x){return x+2;} int main(){double (*fp)(double)=add2; return (int)fp(3);}'
assert_fp 6 'float twice(float x){return x*2;} int main(){float (*fp)(float)=twice; return (int)fp(3);}'
assert_fp 5 'double mix(int a,double b){return a+b;} int main(){double (*fp)(int,double)=mix; return (int)fp(2,3);}'
assert_fp 5 'double add1(double x){return x+1;} int apply(double (*cb)(double),int x){return (int)cb(x);} int main(){return apply(add1,4);}'
assert_fp 7 'typedef double (*Fn)(double); double add3(double x){return x+3;} int main(){Fn fp=add3; return (int)fp(4);}'
assert_fp 65 'int first(char *s){return s[0];} int main(){int (*fp)(char *)=first; return fp("A");}'
assert_fp 12 'double tail(int a,int b,int c,int d,int e,int f,int g,double x){return g+x;} int main(){double (*fp)(int,int,int,int,int,int,int,double)=tail; return (int)fp(1,2,3,4,5,6,7,5);}'
assert_fp 19 'int tail2(double a,double b,double c,double d,double e,double f,double g,double h,double i,int z){return (int)i+z;} int main(){int (*fp)(double,double,double,double,double,double,double,double,double,int)=tail2; return fp(1,2,3,4,5,6,7,8,9,10);}'
assert_fp 1 'int sprintf(char *s,char *fmt,...); int main(){int (*fp)(char *,char *,...)=sprintf; char b[32]; float x=1.5f; fp(b,"%g",x); return b[0]==49;}'
assert_fp 8 'double add_named(int a,double b){return a+b;} int main(){double (*fp)(int x,double y)=add_named; return (int)fp(3,5);}'

echo "All function-pointer prototype tests passed!"
''')

readme = Path('README.md')
r = readme.read_text()
old_doc = 'Direct calls use declared parameter types for scalar coercion; external variadic calls receive the required vector-register count and default float promotion.'
new_doc = 'Direct calls and prototype-bearing function-pointer calls use declared parameter types for scalar coercion; external variadic calls, including indirect calls, receive the required vector-register count and default float promotion.'
if old_doc not in r:
    raise SystemExit('README ABI sentence not found')
r = r.replace(old_doc, new_doc, 1)
readme.write_text(r)

print('Function pointer prototype migration applied')
