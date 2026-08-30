#include "minicc.h"

static bool is_complete_object_type(Type *ty) {
    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)
        return false;
    if (ty->kind == TY_STRUCT)
        return !ty->is_incomplete;
    if (ty->kind == TY_ARRAY)
        return ty->array_len != 0 && is_complete_object_type(ty->base);
    return true;
}

static bool valid_incdec_operand(Type *ty) {
    if (!ty)
        return false;
    if (is_numeric(ty))
        return true;
    return ty->kind == TY_PTR && is_complete_object_type(ty->base);
}

static bool valid_additive_compound_operands(Type *lhs, Type *rhs) {
    if (!lhs || !rhs)
        return false;
    if (is_numeric(lhs) && is_numeric(rhs))
        return true;
    return lhs->kind == TY_PTR && is_complete_object_type(lhs->base) &&
           is_integer(rhs);
}

static bool valid_arithmetic_compound_operands(Type *lhs, Type *rhs) {
    return lhs && rhs && is_numeric(lhs) && is_numeric(rhs);
}

static bool valid_integer_compound_operands(Type *lhs, Type *rhs) {
    return lhs && rhs && is_integer(lhs) && is_integer(rhs);
}

static void validate_node(Node *node) {
    for (; node; node = node->next) {
        validate_node(node->lhs);
        validate_node(node->rhs);
        validate_node(node->cond);
        validate_node(node->then);
        validate_node(node->els);
        validate_node(node->init);
        validate_node(node->inc);
        validate_node(node->body);
        validate_node(node->args);

        switch (node->kind) {
        case ND_PRE_INC:
        case ND_PRE_DEC:
        case ND_POST_INC:
        case ND_POST_DEC:
            add_type(node->lhs);
            if (!valid_incdec_operand(node->lhs->ty))
                error("increment/decrement requires a real or complete-object pointer operand");
            break;
        case ND_ADD_EQ:
        case ND_SUB_EQ:
            add_type(node->lhs);
            add_type(node->rhs);
            if (!valid_additive_compound_operands(node->lhs->ty, node->rhs->ty))
                error("invalid operands for additive compound assignment");
            break;
        case ND_MUL_EQ:
        case ND_DIV_EQ:
            add_type(node->lhs);
            add_type(node->rhs);
            if (!valid_arithmetic_compound_operands(node->lhs->ty, node->rhs->ty))
                error("arithmetic operands required for compound assignment");
            break;
        case ND_MOD_EQ:
        case ND_AND_EQ:
        case ND_OR_EQ:
        case ND_XOR_EQ:
        case ND_SHL_EQ:
        case ND_SHR_EQ:
            add_type(node->lhs);
            add_type(node->rhs);
            if (!valid_integer_compound_operands(node->lhs->ty, node->rhs->ty))
                error("integer operands required for compound assignment");
            break;
        default:
            break;
        }
    }
}

void validate_program(Program *prog) {
    for (Function *fn = prog->fns; fn; fn = fn->next)
        validate_node(fn->body);
}
