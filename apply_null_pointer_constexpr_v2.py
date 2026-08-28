from pathlib import Path

p = Path('parse.c')
s = p.read_text()

# Export the existing typed integer constant-expression evaluator so type.c and
# parser semantic checks share one definition of a zero-valued ICE.
old = 'static int64_t eval_const_expr(Node *node) {'
if old not in s:
    raise RuntimeError('eval_const_expr anchor not found')
s = s.replace(old, 'int64_t eval_const_expr(Node *node) {', 1)

old_null = '''static bool is_null_pointer_constant(Node *node) {\n    add_type(node);\n    return is_integer(node->ty) && node->kind == ND_NUM && node->val == 0;\n}\n\n'''
if old_null not in s:
    raise RuntimeError('parse null helper anchor not found')
s = s.replace(old_null, '', 1)
p.write_text(s)

p = Path('type.c')
s = p.read_text()
old_type_null = '''static bool is_null_pointer_constant(Node *node) {\n    // Keep this deliberately narrow until the integer constant-expression\n    // evaluator is available here: an integer literal 0 is the canonical null\n    // pointer constant and covers the compiler's existing pointer idioms.\n    return node && node->kind == ND_NUM && is_integer(node->ty) && node->val == 0;\n}\n'''
new_type_null = '''bool is_null_pointer_constant(Node *node) {\n    if (!node)\n        return false;\n    add_type(node);\n    if (!node->ty || !is_integer(node->ty))\n        return false;\n    return eval_const_expr(node) == 0;\n}\n'''
if old_type_null not in s:
    raise RuntimeError('type null helper anchor not found')
s = s.replace(old_type_null, new_type_null, 1)
p.write_text(s)

p = Path('minicc.h')
s = p.read_text()
anchor = 'Type *get_common_type(Type *ty1, Type *ty2);\nvoid add_type(Node *node);\n'
replacement = ('Type *get_common_type(Type *ty1, Type *ty2);\n'
               'int64_t eval_const_expr(Node *node);\n'
               'bool is_null_pointer_constant(Node *node);\n'
               'void add_type(Node *node);\n')
if anchor not in s:
    raise RuntimeError('header anchor not found')
s = s.replace(anchor, replacement, 1)
p.write_text(s)

p = Path('Makefile')
s = p.read_text()
anchor = '\tbash ./test/conditional_operator.sh\n'
if anchor not in s:
    raise RuntimeError('Makefile anchor not found')
s = s.replace(anchor, anchor + '\tbash ./test/null_pointer_constants.sh\n', 1)
p.write_text(s)

Path('test/null_pointer_constants.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-nullptr.c
  ./minicc tmp-nullptr.c > tmp-nullptr.s
  cc -o tmp-nullptr tmp-nullptr.s
  set +e
  ./tmp-nullptr
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(null pointer constant): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(null pointer constant): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-nullptr-reject.c
  if ./minicc tmp-nullptr-reject.c > /dev/null 2>&1; then
    echo "FAIL(null pointer constant): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(null pointer constant): rejected"
}

# Assignment and initialization accept any zero-valued integer constant expression.
assert_run 0 'int main(void){ int *p=1-1; return p!=0; }'
assert_run 0 'int main(void){ int *p=(int)0; return p!=0; }'
assert_run 0 'int main(void){ int *p=(3*7)-(4+17); return p!=0; }'
assert_run 0 'int main(void){ int *p=1U-1U; return p!=0; }'
assert_run 0 'enum { Z=0 }; int main(void){ int *p=Z; return p!=0; }'
# PR #74 types sizeof as unsigned long; its zero result is still an ICE null constant.
assert_run 0 'int main(void){ int (*fp)(void)=sizeof(long)-8; return fp!=0; }'

# The same rule applies to return values and fixed function arguments.
assert_run 0 'int *f(void){ return 8/2-4; } int main(void){ return f()!=0; }'
assert_run 0 'int takes(int *p){ return p==0; } int main(void){ return !takes((9%3)); }'

# Equality operators recognize zero-valued ICEs in either operand position.
assert_run 0 'int main(void){ int x; int *p=&x; return (p==(6-6)) || ((7-7)==p); }'
assert_run 0 'int main(void){ int *p=0; return !((p==(5-5)) && ((12/3-4)==p)); }'

# Conditional pointer composition accepts zero ICEs on either arm.
assert_run 0 'int main(void){ int x=4; int *p=1 ? &x : (11-11); return p!=&x; }'
assert_run 0 'int main(void){ int x=4; int *p=0 ? (14-14) : &x; return p!=&x; }'
assert_run 0 'int main(void){ int x=4; int *p=1 ? &x : (0 && (1/0)); return p!=&x; }'

# Static address initialization keeps using the same evaluator.
assert_run 0 'int g; int *p=(5*5)-25; int main(void){ return p!=0; }'
assert_run 0 'int g; int main(void){ static int *p=(2<<3)-16; return p!=0; }'

# Nonconstant or nonzero integer expressions are not null pointer constants.
assert_reject 'int main(void){ int z=0; int *p=z; return 0; }'
assert_reject 'int main(void){ const int z=0; int *p=z; return 0; }'
assert_reject 'int main(void){ int *p=2-1; return 0; }'
assert_reject 'int main(void){ int *p=0; return p==(3-2); }'
assert_reject 'int main(void){ int x; int *p=1 ? &x : 1; return 0; }'
assert_reject 'int takes(int *p){return 0;} int main(void){return takes(1);}'
assert_reject 'int *f(void){ return 1; } int main(void){ return 0; }'
assert_reject 'int main(void){ int *p=0.0; return 0; }'
assert_reject 'int main(void){ int *p=(0,0); return 0; }'
assert_reject 'int zero(void){return 0;} int main(void){ int *p=zero(); return 0; }'

# Existing integer-constant diagnostics still fire through the shared evaluator.
assert_reject 'int main(void){ int *p=1/0; return 0; }'
assert_reject 'int main(void){ int *p=1<<64; return 0; }'

echo "All null pointer constant tests passed!"
''')
