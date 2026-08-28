from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    '''static Type *const_binary_type(Node *node) {\n    add_type(node->lhs);\n    add_type(node->rhs);\n    if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))\n        error("integer operands required in integer constant expression");\n    return get_common_type(node->lhs->ty, node->rhs->ty);\n}\n\nint64_t eval_const_expr(Node *node) {\n''',
    '''static Type *const_binary_type(Node *node) {\n    add_type(node->lhs);\n    add_type(node->rhs);\n    if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))\n        error("integer operands required in integer constant expression");\n    return get_common_type(node->lhs->ty, node->rhs->ty);\n}\n\nstatic int64_t signed_const_min(Type *ty) {\n    if (!ty || !is_integer(ty) || ty->is_unsigned)\n        error("signed integer type required in integer constant expression");\n    if (ty->size == 1) return INT8_MIN;\n    if (ty->size == 2) return INT16_MIN;\n    if (ty->size == 4) return INT32_MIN;\n    return INT64_MIN;\n}\n\nstatic int64_t signed_const_max(Type *ty) {\n    if (!ty || !is_integer(ty) || ty->is_unsigned)\n        error("signed integer type required in integer constant expression");\n    if (ty->size == 1) return INT8_MAX;\n    if (ty->size == 2) return INT16_MAX;\n    if (ty->size == 4) return INT32_MAX;\n    return INT64_MAX;\n}\n\nstatic int64_t checked_signed_add(int64_t lhs, int64_t rhs, Type *ty) {\n    int64_t min = signed_const_min(ty);\n    int64_t max = signed_const_max(ty);\n    if ((rhs > 0 && lhs > max - rhs) ||\n        (rhs < 0 && lhs < min - rhs))\n        error("signed overflow in integer constant expression");\n    return lhs + rhs;\n}\n\nstatic int64_t checked_signed_sub(int64_t lhs, int64_t rhs, Type *ty) {\n    int64_t min = signed_const_min(ty);\n    int64_t max = signed_const_max(ty);\n    if ((rhs < 0 && lhs > max + rhs) ||\n        (rhs > 0 && lhs < min + rhs))\n        error("signed overflow in integer constant expression");\n    return lhs - rhs;\n}\n\nstatic int64_t checked_signed_mul(int64_t lhs, int64_t rhs, Type *ty) {\n    int64_t min = signed_const_min(ty);\n    int64_t max = signed_const_max(ty);\n\n    if (!lhs || !rhs)\n        return 0;\n    if (lhs == -1) {\n        if (rhs == min)\n            error("signed overflow in integer constant expression");\n        return -rhs;\n    }\n    if (rhs == -1) {\n        if (lhs == min)\n            error("signed overflow in integer constant expression");\n        return -lhs;\n    }\n\n    if (lhs > 0) {\n        if (rhs > 0) {\n            if (lhs > max / rhs)\n                error("signed overflow in integer constant expression");\n        } else if (rhs < min / lhs) {\n            error("signed overflow in integer constant expression");\n        }\n    } else if (rhs > 0) {\n        if (lhs < min / rhs)\n            error("signed overflow in integer constant expression");\n    } else if (lhs < max / rhs) {\n        error("signed overflow in integer constant expression");\n    }\n\n    return lhs * rhs;\n}\n\nint64_t eval_const_expr(Node *node) {\n''',
    "signed overflow helpers",
)

replace_once(
    "parse.c",
    '''    case ND_NEG: {\n        if (!is_integer(node->ty))\n            error("floating value is not an integer constant expression");\n        int64_t val = cast_const_integer(eval_const_expr(node->lhs), node->ty);\n        uint64_t bits = 0 - (uint64_t)val;\n        return cast_const_integer((int64_t)bits, node->ty);\n    }\n''',
    '''    case ND_NEG: {\n        if (!is_integer(node->ty))\n            error("floating value is not an integer constant expression");\n        int64_t val = cast_const_integer(eval_const_expr(node->lhs), node->ty);\n        if (node->ty->is_unsigned) {\n            uint64_t bits = 0 - (uint64_t)val;\n            return cast_const_integer((int64_t)bits, node->ty);\n        }\n        if (val == signed_const_min(node->ty))\n            error("signed overflow in integer constant expression");\n        return -val;\n    }\n''',
    "unary negation overflow",
)

replace_once(
    "parse.c",
    '''    case ND_ADD:\n    case ND_SUB:\n    case ND_MUL: {\n        if (!is_integer(node->ty))\n            error("non-integer arithmetic in integer constant expression");\n        Type *ty = const_binary_type(node);\n        int64_t lhs = cast_const_integer(eval_const_expr(node->lhs), ty);\n        int64_t rhs = cast_const_integer(eval_const_expr(node->rhs), ty);\n        uint64_t bits;\n        if (node->kind == ND_ADD)\n            bits = (uint64_t)lhs + (uint64_t)rhs;\n        else if (node->kind == ND_SUB)\n            bits = (uint64_t)lhs - (uint64_t)rhs;\n        else\n            bits = (uint64_t)lhs * (uint64_t)rhs;\n        return cast_const_integer((int64_t)bits, ty);\n    }\n''',
    '''    case ND_ADD:\n    case ND_SUB:\n    case ND_MUL: {\n        if (!is_integer(node->ty))\n            error("non-integer arithmetic in integer constant expression");\n        Type *ty = const_binary_type(node);\n        int64_t lhs = cast_const_integer(eval_const_expr(node->lhs), ty);\n        int64_t rhs = cast_const_integer(eval_const_expr(node->rhs), ty);\n\n        if (ty->is_unsigned) {\n            uint64_t bits;\n            if (node->kind == ND_ADD)\n                bits = (uint64_t)lhs + (uint64_t)rhs;\n            else if (node->kind == ND_SUB)\n                bits = (uint64_t)lhs - (uint64_t)rhs;\n            else\n                bits = (uint64_t)lhs * (uint64_t)rhs;\n            return cast_const_integer((int64_t)bits, ty);\n        }\n\n        int64_t val;\n        if (node->kind == ND_ADD)\n            val = checked_signed_add(lhs, rhs, ty);\n        else if (node->kind == ND_SUB)\n            val = checked_signed_sub(lhs, rhs, ty);\n        else\n            val = checked_signed_mul(lhs, rhs, ty);\n        return cast_const_integer(val, ty);\n    }\n''',
    "binary signed overflow",
)

replace_once(
    "parse.c",
    '''        if (rhs == -1 &&\n            ((ty->size == 4 && lhs == INT32_MIN) ||\n             (ty->size == 8 && lhs == INT64_MIN)))\n            error("signed division overflow in integer constant expression");\n''',
    '''        if (rhs == -1 && lhs == signed_const_min(ty))\n            error("signed overflow in integer constant expression");\n''',
    "division overflow",
)

replace_once(
    "parse.c",
    '''        if (node->kind == ND_SHL)\n            return cast_const_integer((int64_t)((uint64_t)lhs << count), left_ty);\n        if (left_ty->is_unsigned)\n            return cast_const_integer((int64_t)((uint64_t)lhs >> count), left_ty);\n''',
    '''        if (node->kind == ND_SHL) {\n            if (left_ty->is_unsigned)\n                return cast_const_integer((int64_t)((uint64_t)lhs << count), left_ty);\n            if (lhs < 0)\n                error("invalid signed left shift in integer constant expression");\n            int64_t max = signed_const_max(left_ty);\n            if (count && lhs > (max >> count))\n                error("signed overflow in integer constant expression");\n            return cast_const_integer(lhs << count, left_ty);\n        }\n        if (left_ty->is_unsigned)\n            return cast_const_integer((int64_t)((uint64_t)lhs >> count), left_ty);\n''',
    "signed left shift overflow",
)

replace_once(
    "test/constant_expressions.sh",
    '''assert_run 1 'int main(){enum { A = ((0x80000000U << 1) == 0) }; return A;}'\n''',
    '''assert_run 1 'int main(){enum { A = ((0x80000000U << 1) == 0) }; return A;}'\nassert_run 1 'int main(){enum { A = ((0xffffffffffffffffULL + 1ULL) == 0) }; return A;}'\nassert_run 1 'int main(){enum { A = ((0x8000000000000000ULL << 1) == 0) }; return A;}'\n\n# Signed arithmetic must stay inside the result type's representable range.\nassert_run 1 'int main(){enum { A = (2147483646 + 1 == 2147483647) }; return A;}'\nassert_run 1 'int main(){enum { A = ((-2147483647 - 1) + 1 == -2147483647) }; return A;}'\nassert_run 1 'int main(){enum { A = ((1 << 30) == 1073741824) }; return A;}'\nassert_run 1 'int main(){enum { A = ((0 && (2147483647 + 1)) == 0) }; return A;}'\nassert_run 1 'int main(){enum { A = (1 ? 1 : 2147483647 + 1) }; return A;}'\n''',
    "positive overflow boundary tests",
)

replace_once(
    "test/constant_expressions.sh",
    '''assert_reject 'int main(){enum { A = 1ULL >> 64 }; return A;}'\n''',
    '''assert_reject 'int main(){enum { A = 1ULL >> 64 }; return A;}'\nassert_reject 'int main(){enum { A = 2147483647 + 1 }; return A;}'\nassert_reject 'int main(){enum { A = (-2147483647 - 1) - 1 }; return A;}'\nassert_reject 'int main(){enum { A = 1073741824 * 2 }; return A;}'\nassert_reject 'int main(){enum { A = -(-2147483647 - 1) }; return A;}'\nassert_reject 'int main(){enum { A = 1 << 31 }; return A;}'\nassert_reject 'int main(){enum { A = (-1) << 1 }; return A;}'\nassert_reject 'int main(){enum { A = (-2147483647 - 1) / -1 }; return A;}'\nassert_reject 'int main(){enum { A = (-2147483647 - 1) % -1 }; return A;}'\nassert_reject 'long x = 9223372036854775807L + 1L; int main(){return 0;}'\nassert_reject 'long x = 4611686018427387904L * 2L; int main(){return 0;}'\nassert_reject '_Static_assert(2147483647 + 1, "overflow"); int main(){return 0;}'\nassert_reject 'int a[2147483647 + 1]; int main(){return 0;}'\nassert_reject 'int main(){switch(0){case 2147483647 + 1:return 1;}return 0;}'\nassert_reject 'static int x = 2147483647 + 1; int main(){return x;}'\nassert_reject '_Alignas(2147483647 + 1) int x; int main(){return 0;}'\n''',
    "signed overflow rejection tests",
)

replace_once(
    "README.md",
    '''- Static/global integer scalar and array initializers accept type-aware integer constant expressions, including enum constants, casts, shifts, short-circuit logic, and ternary expressions.\n''',
    '''- Static/global integer scalar and array initializers accept type-aware integer constant expressions, including enum constants, casts, shifts, short-circuit logic, and ternary expressions. Signed integer constant-expression arithmetic diagnoses overflow and invalid signed left shifts instead of wrapping, while unsigned arithmetic retains modulo semantics.\n''',
    "README signed ICE overflow semantics",
)
