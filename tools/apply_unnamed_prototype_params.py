from pathlib import Path

p = Path("parse.c")
s = p.read_text()

old = '''            Obj param_head = {};
            Obj *pcur = &param_head;

            bool is_variadic = false;
            // Parse void parameter list
            if (equal(tok, "void") && equal(tok->next, ")")) {
                tok = tok->next;
            } else {
                while (!equal(tok, ")")) {
                    if (pcur != &param_head)
                        tok = skip(tok, ",");
                    if (equal(tok, "...")) {
                        tok = tok->next;
                        is_variadic = true;
                        break;
                    }
                    // Skip qualifiers
                    consume(&tok, tok, "const");
                    consume(&tok, tok, "volatile");
                    consume(&tok, tok, "register");

                    Type *param_basety = declspec(&tok, tok);
                    Token *pident;
                    Type *param_ty = declarator(&tok, tok, param_basety, &pident);
                    if (is_incomplete_object_type(param_ty))
                        error_at(pident->loc, "parameter has incomplete type");

                    char *pname = strndup(pident->loc, pident->len);
                    Obj *var = create_lvar(pname);
                    var->ty = param_ty;
                    pcur = pcur->param_next = var;
                }
            }
            tok = skip(tok, ")");

            // Register function symbol for calls and function-pointer usage.
            register_function_symbol(name, basety, is_static,
                                     param_head.param_next, is_variadic);

            // Function prototype
            if (consume(&tok, tok, ";")) {
                leave_scope();
                continue;
            }

            tok = skip(tok, "{");
'''

new = '''            Obj param_head = {};
            Obj *pcur = &param_head;

            bool is_variadic = false;
            bool has_unnamed_params = false;
            // Parse void parameter list
            if (equal(tok, "void") && equal(tok->next, ")")) {
                tok = tok->next;
            } else {
                while (!equal(tok, ")")) {
                    if (pcur != &param_head)
                        tok = skip(tok, ",");
                    if (equal(tok, "...")) {
                        tok = tok->next;
                        is_variadic = true;
                        break;
                    }
                    // Skip qualifiers
                    consume(&tok, tok, "const");
                    consume(&tok, tok, "volatile");
                    consume(&tok, tok, "register");

                    Type *param_ty = declspec(&tok, tok);
                    while (consume(&tok, tok, "*"))
                        param_ty = pointer_to(param_ty);

                    Token *pident = NULL;
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

                    if (is_incomplete_object_type(param_ty))
                        error_at(pident ? pident->loc : tok->loc,
                                 "parameter has incomplete type");

                    var->ty = param_ty;
                    pcur = pcur->param_next = var;
                }
            }
            tok = skip(tok, ")");

            // Register function symbol for calls and function-pointer usage.
            register_function_symbol(name, basety, is_static,
                                     param_head.param_next, is_variadic);

            // Function prototype
            if (consume(&tok, tok, ";")) {
                leave_scope();
                continue;
            }

            if (has_unnamed_params)
                error_at(ident->loc, "parameter name omitted in function definition");

            tok = skip(tok, "{");
'''

if old not in s:
    raise SystemExit("function parameter parser block not found")
s = s.replace(old, new, 1)
p.write_text(s)

make = Path("Makefile")
m = make.read_text()
needle = '\tbash ./test/abi_stack_args.sh\n'
if needle not in m:
    raise SystemExit("stack ABI test line not found")
if '\tbash ./test/prototype_params.sh\n' not in m:
    m = m.replace(needle, needle + '\tbash ./test/prototype_params.sh\n', 1)
make.write_text(m)

Path("test/prototype_params.sh").write_text(r'''#!/bin/bash
set -e

assert_proto() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-proto.c
  "${MINICC:-./minicc}" tmp-proto.c > tmp-proto.s
  gcc -o tmp-proto tmp-proto.s
  set +e
  ./tmp-proto
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(prototype params): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype params): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-proto-reject.c
  if "${MINICC:-./minicc}" tmp-proto-reject.c > /dev/null 2>&1; then
    echo "FAIL(prototype params): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(prototype params): rejected invalid definition"
}

assert_proto 28 'int sum7(int,int,int,int,int,int,int); int main(){return sum7(1,2,3,4,5,6,7);} int sum7(int a,int b,int c,int d,int e,int f,int g){return a+b+c+d+e+f+g;}'
assert_proto 4 'double add(double,double); int main(){return (int)add(1,3);} double add(double a,double b){return a+b;}'
assert_proto 65 'int first(char *); int main(){return first("ABC");} int first(char *s){return s[0];}'
assert_proto 9 'int mix(int a,int,double c); int main(){return mix(1,3,5);} int mix(int a,int b,double c){return a+b+(int)c;}'
assert_proto 7 'int sprintf(char *, char *, ...); int main(){char buf[16]; sprintf(buf,"%d",7); return buf[0]-48;}'
assert_proto 11 'typedef int I; int add(I,I); int main(){return add(5,6);} int add(I a,I b){return a+b;}'
assert_proto 5 'int f(void); int main(){return f();} int f(void){return 5;}'
assert_reject 'int f(int) { return 1; } int main(){return f(3);}'

echo "All unnamed prototype parameter tests passed!"
''')

readme = Path("README.md")
r = readme.read_text()
old = '- **Declarations**: local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions and prototypes\n'
new = '- **Declarations**: local/global variables with initializers, `{ }` brace-enclosed initializers for arrays and structs, array length inference from initializer, function definitions, and prototypes with named or unnamed scalar/pointer parameters\n'
if old not in r:
    raise SystemExit("README declaration line not found")
readme.write_text(r.replace(old, new, 1))

print("unnamed prototype parameter migration applied")
