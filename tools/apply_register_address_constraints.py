from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "minicc.h",
    '''    bool is_function;  // true = function symbol (not a variable)\n    bool is_static;    // static storage class\n    bool is_extern;    // extern storage class\n    bool is_defined;   // function symbol already has a body\n''',
    '''    bool is_function;  // true = function symbol (not a variable)\n    bool is_static;    // static storage class\n    bool is_extern;    // extern storage class\n    bool is_register;  // object/parameter declared with register storage class\n    bool is_defined;   // function symbol already has a body\n''')

replace_once(
    "parse.c",
    '''        Obj *param = calloc(1, sizeof(Obj));\n        param->ty = param_ty;\n        if (name)\n            param->name = strndup(name->loc, name->len);\n''',
    '''        Obj *param = calloc(1, sizeof(Obj));\n        param->ty = param_ty;\n        param->is_register = param_attrs.is_register;\n        if (name)\n            param->name = strndup(name->loc, name->len);\n''')

replace_once(
    "parse.c",
    '''        } else {\n            var = create_lvar(name);\n            var->ty = ty;\n        }\n        apply_object_alignment(var, ty, attrs.align, ident);\n''',
    '''        } else {\n            var = create_lvar(name);\n            var->ty = ty;\n        }\n        var->is_register = attrs.is_register;\n        apply_object_alignment(var, ty, attrs.align, ident);\n''')

replace_once(
    "parse.c",
    '''                Obj *var = create_lvar(meta->name);\n                var->ty = meta->ty;\n                pcur = pcur->param_next = var;\n''',
    '''                Obj *var = create_lvar(meta->name);\n                var->ty = meta->ty;\n                var->is_register = meta->is_register;\n                pcur = pcur->param_next = var;\n''')

replace_once(
    "parse.c",
    '''static Node *new_checked_addr(Node *operand, Token *op) {\n    if (!is_addressable_expr(operand))\n        error_at(op->loc, "address-of operand is not an lvalue or function designator");\n    return new_unary(ND_ADDR, operand);\n}\n''',
    '''static bool address_designates_register_object(Node *node) {\n    if (!node)\n        return false;\n\n    // C forbids computing the address of an object declared with register\n    // storage, including an explicitly selected subobject of that object.\n    // Do not recurse through dereference: &*p computes the address stored in p,\n    // not the address of the register pointer object p itself.\n    if (node->kind == ND_VAR)\n        return node->var && node->var->is_register;\n    if (node->kind == ND_MEMBER)\n        return address_designates_register_object(node->lhs);\n    return false;\n}\n\nstatic Node *new_checked_addr(Node *operand, Token *op) {\n    if (!is_addressable_expr(operand))\n        error_at(op->loc, "address-of operand is not an lvalue or function designator");\n    if (address_designates_register_object(operand))\n        error_at(op->loc, "cannot take address of register object");\n    return new_unary(ND_ADDR, operand);\n}\n''')

makefile = Path("Makefile")
text = makefile.read_text()
old = '''\tbash ./test/block_extern_initializer.sh\n\tbash ./test/char_type_identity.sh\n'''
new = '''\tbash ./test/block_extern_initializer.sh\n\tbash ./test/register_address_constraints.sh\n\tbash ./test/char_type_identity.sh\n'''
if text.count(old) != 1:
    raise SystemExit("Makefile test insertion point not unique")
makefile.write_text(text.replace(old, new, 1))

readme = Path("README.md")
text = readme.read_text()
needle = "rejection of block-scope `extern` initializers, block-scope `auto` objects with single-storage-class constraint checking"
replacement = "rejection of block-scope `extern` initializers, block-scope `auto`/`register` objects with single-storage-class constraint checking and register-address restrictions"
if text.count(needle) != 1:
    raise SystemExit("README declaration feature insertion point not unique")
readme.write_text(text.replace(needle, replacement, 1))

test = Path("test/register_address_constraints.sh")
test.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-register-addr.c
  ./minicc tmp-register-addr.c > tmp-register-addr.s
  cc -o tmp-register-addr tmp-register-addr.s
  set +e
  ./tmp-register-addr
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(register address): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-register-addr.c
  ./minicc tmp-register-addr.c > tmp-register-addr.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-register-addr-bad.c
  if ./minicc tmp-register-addr-bad.c > /dev/null 2>tmp-register-addr.err; then
    echo "FAIL(register address): expected rejection"
    echo "$input"
    exit 1
  fi
}

# register remains a normal automatic object for value access and mutation.
assert_run 7 'int main(void){register int x=3;x+=4;return x;}'
assert_run 8 'int f(register int x){return x+1;}int main(void){return f(7);}'
assert_run 3 'struct S{int x;};int main(void){register struct S s={3};return s.x;}'

# A register pointer can be used as a pointer. &*p addresses the pointed-to
# object, not the register pointer variable itself, so it remains valid.
assert_run 0 'int main(void){int x=9;register int *p=&x;return (&*p==&x)?0:1;}'
assert_run 9 'int main(void){int x=9;register int *p=&x;return *p;}'

# register on a prototype parameter is accepted and is not part of function
# type compatibility.
assert_compile 'int f(register int);int f(int x){return x;}int main(void){return f(1);}'
assert_compile 'int f(int);int f(register int x){return x;}int main(void){return f(1);}'

# Ordinary non-register objects remain addressable.
assert_run 4 'int main(void){int x=4;int *p=&x;return *p;}'
assert_run 5 'struct S{int x;};int main(void){struct S s={5};int *p=&s.x;return *p;}'

# The address of a register object cannot be computed explicitly.
assert_reject 'int main(void){register int x=1;return &x!=0;}'
assert_reject 'int main(void){register int x=1;return &(x)!=0;}'
assert_reject 'int f(register int x){return &x!=0;}int main(void){return f(1);}'
assert_reject 'int main(void){int x=1;register int *p=&x;return &p!=0;}'
assert_reject 'int main(void){register int a=1,b=2;return &b!=0;}'
assert_reject 'typedef int I;int main(void){register I x=1;return &x!=0;}'
assert_reject 'int main(void){register int a[2];return &a!=0;}'

# Computing the address of an explicitly selected part of a register aggregate
# is forbidden as well, including nested member chains.
assert_reject 'struct S{int x;};int main(void){register struct S s={1};return &s!=0;}'
assert_reject 'struct S{int x;};int main(void){register struct S s={1};return &s.x!=0;}'
assert_reject 'struct I{int x;};struct O{struct I i;};int main(void){register struct O o={{1}};return &o.i.x!=0;}'

rm -f tmp-register-addr.c tmp-register-addr.s tmp-register-addr \
      tmp-register-addr-bad.c tmp-register-addr.err

echo 'All register address constraint tests passed!'
''')

print("register address constraint migration applied")
