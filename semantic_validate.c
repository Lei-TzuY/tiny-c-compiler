#include "minicc.h"

static bool is_complete_object_type(Type *ty) {
    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)
        return false;
    if (ty->kind == TY_STRUCT)
        return !ty->is_incomplete;
    if (ty->kind == TY_ARRAY)
        return ty->array_len > 0 && is_complete_object_type(ty->base);
    return true;
}

static bool valid_incdec_operand(Type *ty) {
    if (!ty)
        return false;
    if (is_numeric(ty))
        return true;
    return ty->kind == TY_PTR && is_complete_object_type(ty->base);
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
        default:
            break;
        }
    }
}

void validate_program(Program *prog) {
    for (Function *fn = prog->fns; fn; fn = fn->next)
        validate_node(fn->body);
}
