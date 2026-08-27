from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text()
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"{path}: anchor count={count}")
    p.write_text(s.replace(old, new, 1))


# Unary integer operators apply integer promotions before producing a result.
replace_once(
    "type.c",
    '''    case ND_NEG:\n        if (!is_numeric(node->lhs->ty))\n            error("numeric operand required");\n        node->ty = node->lhs->ty;\n        return;\n\n    case ND_BITNOT:\n        if (!is_integer(node->lhs->ty))\n            error("integer operand required");\n        node->ty = node->lhs->ty;\n        return;\n''',
    '''    case ND_NEG:\n        if (!is_numeric(node->lhs->ty))\n            error("numeric operand required");\n        node->ty = is_integer(node->lhs->ty)\n                     ? integer_promotion(node->lhs->ty)\n                     : node->lhs->ty;\n        return;\n\n    case ND_BITNOT:\n        if (!is_integer(node->lhs->ty))\n            error("integer operand required");\n        node->ty = integer_promotion(node->lhs->ty);\n        return;\n''')

# Replace the old signed-int64-only evaluator with a type-aware evaluator that
# applies the same integer promotions/usual arithmetic conversions as runtime
# expressions. The returned int64_t carries the target integer bit pattern.
p = Path("parse.c")
s = p.read_text()
start = s.index("static int64_t cast_const_integer")
end = s.index("static Type *enum_decl", start)
new_eval = r'''static int64_t cast_const_integer(int64_t val, Type *ty) {
    if (!ty || !is_integer(ty))
        error("cast in integer constant expression must target an integer type");

    if (ty->kind == TY_BOOL)
        return val != 0;

    if (ty->size == 1)
        return ty->is_unsigned ? (uint8_t)val : (int8_t)val;
    if (ty->size == 2)
        return ty->is_unsigned ? (uint16_t)val : (int16_t)val;
    if (ty->size == 4)
        return ty->is_unsigned ? (uint32_t)val : (int32_t)val;
    return val;
}

static Type *const_binary_type(Node *node) {
    add_type(node->lhs);
    add_type(node->rhs);
    if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
        error("integer operands required in integer constant expression");
    return get_common_type(node->lhs->ty, node->rhs->ty);
}

static int64_t eval_const_expr(Node *node) {
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
s = s[:start] + new_eval + s[end:]
p.write_text(s)

# Array declarators now accept an integer constant expression, not just one
# numeric token. Empty [] remains the incomplete-array spelling used by
# initializer length inference.
replace_once(
    "parse.c",
    '''    if (equal(tok, "[")) {\n        tok = tok->next;\n        int len = 0;\n        if (tok->kind == TK_NUM) {\n            len = tok->val;\n            tok = tok->next;\n        }\n        tok = skip(tok, "]");\n        ty = type_suffix(rest, tok, ty);\n        if (ty->kind == TY_FUNC)\n            error_at(tok->loc, "array element type cannot be a function");\n        return array_of(ty, len);\n    }\n''',
    '''    if (equal(tok, "[")) {\n        Token *bracket = tok;\n        tok = tok->next;\n        int len = 0;\n        if (!equal(tok, "]")) {\n            Node *bound = ternary(&tok, tok);\n            add_type(bound);\n            if (!is_integer(bound->ty))\n                error_at(bracket->loc, "array bound must have integer type");\n\n            int64_t raw = eval_const_expr(bound);\n            if (bound->ty->is_unsigned) {\n                uint64_t val = (uint64_t)cast_const_integer(raw, bound->ty);\n                if (val == 0 || val > INT32_MAX)\n                    error_at(bracket->loc, "array bound is out of range");\n                len = (int)val;\n            } else {\n                int64_t val = cast_const_integer(raw, bound->ty);\n                if (val <= 0 || val > INT32_MAX)\n                    error_at(bracket->loc, "array bound is out of range");\n                len = (int)val;\n            }\n        }\n        tok = skip(tok, "]");\n        ty = type_suffix(rest, tok, ty);\n        if (ty->kind == TY_FUNC)\n            error_at(tok->loc, "array element type cannot be a function");\n        return array_of(ty, len);\n    }\n''')

# Register the focused regression suite.
replace_once(
    "Makefile",
    "\tbash ./test/escape_sequences.sh\n",
    "\tbash ./test/escape_sequences.sh\n\tbash ./test/constant_expressions.sh\n")

Path("test/constant_expressions.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-constexpr.c
  ./minicc tmp-constexpr.c > tmp-constexpr.s
  cc -o tmp-constexpr tmp-constexpr.s
  set +e
  ./tmp-constexpr
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "constant-expression test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(constant expression): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-constexpr.c
  if ./minicc tmp-constexpr.c > tmp-constexpr.s 2>/dev/null; then
    echo "constant-expression test unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(constant expression): rejected invalid input"
}

# Unsigned comparisons, division/remainder, and shifts must preserve high bits.
assert_run 1 'int main(){enum { A = 0xffffffffffffffffULL > 0 }; return A;}'
assert_run 1 'int main(){enum { A = (0xffffffffffffffffULL >> 63) }; return A;}'
assert_run 1 'int main(){enum { A = (0xffffffffffffffffULL / 0x7fffffffffffffffULL) == 2 }; return A;}'
assert_run 1 'int main(){enum { A = (0xffffffffffffffffULL % 0x7fffffffffffffffULL) == 1 }; return A;}'
assert_run 1 'int main(){enum { A = ((unsigned int)-1 > 1) }; return A;}'
assert_run 1 'int main(){enum { A = (~0U >> 31) }; return A;}'
assert_run 1 'int main(){enum { A = ((0xffffffffU + 1U) == 0) }; return A;}'
assert_run 1 'int main(){enum { A = ((unsigned int)0xffffffffffffffffULL == 0xffffffffU) }; return A;}'
assert_run 1 'int main(){enum { A = ((0x80000000U << 1) == 0) }; return A;}'

# Equal-width long/long-long still obey rank and signedness conversions.
assert_run 0 'int main(){enum { A = ((long long)-1 < (unsigned long)1) }; return A;}'
assert_run 1 'int main(){enum { A = ((long long)-1 > (unsigned long)1) }; return A;}'
assert_run 1 'int main(){enum { A = ((1 ? -1 : 0U) == 0xffffffffU) }; return A;}'

# Unary integer operators apply integer promotions just like runtime C.
assert_run 4 'int main(){return sizeof(~(unsigned char)0);}'
assert_run 4 'int main(){return sizeof(-(unsigned short)1);}'
assert_run 1 'int main(){return ~(unsigned char)0 == -1;}'
assert_run 1 'int main(){enum { A = ((-2 >> 1) == -1) }; return A;}'

# case labels use the same typed evaluator and are converted to switch type.
assert_run 1 'int main(){unsigned long x=(unsigned long)-1; switch(x){case 0xffffffffffffffffULL:return 1;} return 0;}'
assert_run 1 'int main(){unsigned long x=6148914691236517205ULL; switch(x){case 0xffffffffffffffffULL/3ULL:return 1;} return 0;}'
assert_reject 'int main(){unsigned int x=0; switch(x){case -1:return 1; case 0xffffffffU:return 2;} return 0;}'

# Array bounds are now parsed as integer constant expressions.
assert_run 3 'int main(){int a[(0xffffffffU >> 31)+2]; return sizeof(a)/sizeof(int);}'
assert_run 4 'int main(){enum { N=(0xffffffffffffffffULL>>63)+3 }; int a[N]; return sizeof(a)/sizeof(int);}'
assert_run 3 'int main(){int a[1 ? 3 : 1/0]; return sizeof(a)/sizeof(int);}'
assert_run 6 'int main(){int a[sizeof(int)+2]; return sizeof(a)/sizeof(int);}'

# Invalid ICE operations/bounds are diagnosed instead of inheriting host int64 behavior.
assert_reject 'int main(){enum { A = 1U / 0U }; return A;}'
assert_reject 'int main(){enum { A = 1ULL % 0ULL }; return A;}'
assert_reject 'int main(){enum { A = 1U << 32 }; return A;}'
assert_reject 'int main(){enum { A = 1ULL >> 64 }; return A;}'
assert_reject 'int main(){int x=3; int a[x]; return 0;}'
assert_reject 'int main(){int a[0]; return 0;}'
assert_reject 'int main(){int a[-1]; return 0;}'
assert_reject 'int main(){int a[0xffffffffffffffffULL]; return 0;}'

echo 'All typed integer constant-expression tests passed!'
''')
