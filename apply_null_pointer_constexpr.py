from pathlib import Path

# Move the integer constant-expression evaluator into type.c so semantic typing
# and parsing share exactly the same definition of a zero-valued ICE.
parse = Path('parse.c')
s = parse.read_text()
start = s.index('static int64_t cast_const_integer(int64_t val, Type *ty) {')
end = s.index('static Type *enum_decl(Token **rest, Token *tok) {', start)
s = s[:start] + s[end:]
old_null = '''static bool is_null_pointer_constant(Node *node) {\n    add_type(node);\n    return is_integer(node->ty) && node->kind == ND_NUM && node->val == 0;\n}\n\n'''
if old_null not in s:
    raise RuntimeError('parse null-pointer helper anchor not found')
s = s.replace(old_null, '', 1)
parse.write_text(s)

typec = Path('type.c')
t = typec.read_text()
anchor = 'static bool is_scalar_operand(Type *ty) {\n'
if anchor not in t:
    raise RuntimeError('type.c insertion anchor not found')
shared = r'''int64_t cast_const_integer(int64_t val, Type *ty) {
    if (!ty || !is_integer(ty))
        error("cast in integer constant expression must target an integer type");

    if (ty->kind == TY_BOOL)
        return val != 0;

    if (ty->size == 1) {
        if (ty->is_unsigned) return (uint8_t)val;
        return (int8_t)val;
    }
    if (ty->size == 2) {
        if (ty->is_unsigned) return (uint16_t)val;
        return (int16_t)val;
    }
    if (ty->size == 4) {
        if (ty->is_unsigned) return (uint32_t)val;
        return (int32_t)val;
    }
    return val;
}

static Type *const_binary_type(Node *node) {
    add_type(node->lhs);
    add_type(node->rhs);
    if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
        error("integer operands required in integer constant expression");
    return get_common_type(node->lhs->ty, node->rhs->ty);
}

int64_t eval_const_expr(Node *node) {
    if (!node)
        error("expected integer constant expression");

    add_type(node);

    switch (node->kind) {
    case ND_NUM:
        if (!node->ty || !is_integer(node->ty))
            error("floating value is not an integer constant expression");
        return cast_const_integer(node->val, node->ty);

    case ND_NEG: {
        if (!is_integer(node->ty))
            error("floating value is not an integer constant expression");
        int64_t val = cast_const_integer(eval_const_expr(node->lhs), node->ty);
        uint64_t bits = 0 - (uint64_t)val;
        return cast_const_integer((int64_t)bits, node->ty);
    }

    case ND_ADD:
    case ND_SUB:
    case ND_MUL: {
        if (!is_integer(node->ty))
            error("non-integer arithmetic in integer constant expression");
        Type *ty = const_binary_type(node);
        int64_t lhs = cast_const_integer(eval_const_expr(node->lhs), ty);
        int64_t rhs = cast_const_integer(eval_const_expr(node->rhs), ty);
        uint64_t bits;
        if (node->kind == ND_ADD)
            bits = (uint64_t)lhs + (uint64_t)rhs;
        else if (node->kind == ND_SUB)
            bits = (uint64_t)lhs - (uint64_t)rhs;
        else
            bits = (uint64_t)lhs * (uint64_t)rhs;
        return cast_const_integer((int64_t)bits, ty);
    }

    case ND_DIV:
    case ND_MOD: {
        Type *ty = const_binary_type(node);
        int64_t lhs = cast_const_integer(eval_const_expr(node->lhs), ty);
        int64_t rhs = cast_const_integer(eval_const_expr(node->rhs), ty);
        if (!rhs)
            error(node->kind == ND_DIV
                      ? "division by zero in integer constant expression"
                      : "modulo by zero in integer constant expression");

        if (ty->is_unsigned) {
            uint64_t uleft = (uint64_t)lhs;
            uint64_t uright = (uint64_t)rhs;
            uint64_t bits = node->kind == ND_DIV ? uleft / uright
                                                 : uleft % uright;
            return cast_const_integer((int64_t)bits, ty);
        }

        if (rhs == -1 &&
            ((ty->size == 4 && lhs == INT32_MIN) ||
             (ty->size == 8 && lhs == INT64_MIN)))
            error("signed division overflow in integer constant expression");

        int64_t val = node->kind == ND_DIV ? lhs / rhs : lhs % rhs;
        return cast_const_integer(val, ty);
    }

    case ND_BITAND:
    case ND_BITOR:
    case ND_BITXOR: {
        Type *ty = const_binary_type(node);
        uint64_t lhs = (uint64_t)cast_const_integer(eval_const_expr(node->lhs), ty);
        uint64_t rhs = (uint64_t)cast_const_integer(eval_const_expr(node->rhs), ty);
        uint64_t bits = node->kind == ND_BITAND ? lhs & rhs
                        : node->kind == ND_BITOR ? lhs | rhs
                                                 : lhs ^ rhs;
        return cast_const_integer((int64_t)bits, ty);
    }

    case ND_BITNOT: {
        if (!is_integer(node->ty))
            error("integer operand required in integer constant expression");
        int64_t val = cast_const_integer(eval_const_expr(node->lhs), node->ty);
        return cast_const_integer((int64_t)~(uint64_t)val, node->ty);
    }

    case ND_SHL:
    case ND_SHR: {
        add_type(node->lhs);
        add_type(node->rhs);
        if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
            error("integer operands required in integer constant expression");

        Type *left_ty = node->ty;
        int64_t lhs = cast_const_integer(eval_const_expr(node->lhs), left_ty);
        int64_t rhs = eval_const_expr(node->rhs);
        if (!node->rhs->ty->is_unsigned && rhs < 0)
            error("invalid shift count in integer constant expression");
        uint64_t count = (uint64_t)rhs;
        int width = left_ty->size * 8;
        if (count >= (uint64_t)width)
            error("invalid shift count in integer constant expression");

        if (node->kind == ND_SHL)
            return cast_const_integer((int64_t)((uint64_t)lhs << count), left_ty);
        if (left_ty->is_unsigned)
            return cast_const_integer((int64_t)((uint64_t)lhs >> count), left_ty);
        return cast_const_integer((int64_t)(lhs >> count), left_ty);
    }

    case ND_EQ:
    case ND_NE:
    case ND_LT:
    case ND_LE: {
        Type *ty = const_binary_type(node);
        int64_t lhs = cast_const_integer(eval_const_expr(node->lhs), ty);
        int64_t rhs = cast_const_integer(eval_const_expr(node->rhs), ty);
        if (node->kind == ND_EQ)
            return (uint64_t)lhs == (uint64_t)rhs;
        if (node->kind == ND_NE)
            return (uint64_t)lhs != (uint64_t)rhs;
        if (ty->is_unsigned)
            return node->kind == ND_LT ? (uint64_t)lhs < (uint64_t)rhs
                                       : (uint64_t)lhs <= (uint64_t)rhs;
        return node->kind == ND_LT ? lhs < rhs : lhs <= rhs;
    }

    case ND_NOT:
        return !eval_const_expr(node->lhs);

    case ND_LOGAND: {
        int64_t lhs = eval_const_expr(node->lhs);
        return lhs ? !!eval_const_expr(node->rhs) : 0;
    }

    case ND_LOGOR: {
        int64_t lhs = eval_const_expr(node->lhs);
        return lhs ? 1 : !!eval_const_expr(node->rhs);
    }

    case ND_TERNARY: {
        Node *selected = eval_const_expr(node->cond) ? node->then : node->els;
        int64_t val = eval_const_expr(selected);
        if (!is_integer(node->ty))
            error("non-integer conditional in integer constant expression");
        return cast_const_integer(val, node->ty);
    }

    case ND_CAST:
        return cast_const_integer(eval_const_expr(node->lhs), node->ty);

    default:
        error("not an integer constant expression");
    }
}

'''
t = t.replace(anchor, shared + anchor, 1)
old_type_null = '''static bool is_null_pointer_constant(Node *node) {\n    // Keep this deliberately narrow until the integer constant-expression\n    // evaluator is available here: an integer literal 0 is the canonical null\n    // pointer constant and covers the compiler's existing pointer idioms.\n    return node && node->kind == ND_NUM && is_integer(node->ty) && node->val == 0;\n}\n'''
new_type_null = '''bool is_null_pointer_constant(Node *node) {\n    if (!node)\n        return false;\n    add_type(node);\n    if (!node->ty || !is_integer(node->ty))\n        return false;\n    return eval_const_expr(node) == 0;\n}\n'''
if old_type_null not in t:
    raise RuntimeError('type null-pointer helper anchor not found')
t = t.replace(old_type_null, new_type_null, 1)
typec.write_text(t)

hdr = Path('minicc.h')
h = hdr.read_text()
anchor_h = 'Type *get_common_type(Type *ty1, Type *ty2);\nvoid add_type(Node *node);\n'
replacement_h = ('Type *get_common_type(Type *ty1, Type *ty2);\n'
                 'int64_t cast_const_integer(int64_t val, Type *ty);\n'
                 'int64_t eval_const_expr(Node *node);\n'
                 'bool is_null_pointer_constant(Node *node);\n'
                 'void add_type(Node *node);\n')
if anchor_h not in h:
    raise RuntimeError('header type helper anchor not found')
h = h.replace(anchor_h, replacement_h, 1)
hdr.write_text(h)

make = Path('Makefile')
m = make.read_text()
anchor_m = '\tbash ./test/conditional_operator.sh\n'
if anchor_m not in m:
    raise RuntimeError('Makefile anchor not found')
m = m.replace(anchor_m, anchor_m + '\tbash ./test/null_pointer_constants.sh\n', 1)
make.write_text(m)

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

# Static address initialization keeps using the same shared evaluator.
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
