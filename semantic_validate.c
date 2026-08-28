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

static bool program_has_function_symbol(Program *prog, const char *name) {
    if (!prog || !name)
        return false;

    for (Obj *obj = prog->globals; obj; obj = obj->next)
        if (obj->is_function && obj->name && !strcmp(obj->name, name))
            return true;
    return false;
}

static void validate_node(Program *prog, Node *node) {
    for (; node; node = node->next) {
        validate_node(prog, node->lhs);
        validate_node(prog, node->rhs);
        validate_node(prog, node->cond);
        validate_node(prog, node->then);
        validate_node(prog, node->els);
        validate_node(prog, node->init);
        validate_node(prog, node->inc);
        validate_node(prog, node->body);
        validate_node(prog, node->args);

        switch (node->kind) {
        case ND_FUNCALL:
            // Direct calls retain their source-level callee name.  The parser
            // historically allowed an unknown identifier here and assigned an
            // implicit int return type, deferring misspellings to the linker.
            // Reject calls that never resolve to any function declaration in
            // the translation unit; indirect calls have funcname == NULL and
            // were already type-checked against their function-pointer type.
            if (node->funcname && !program_has_function_symbol(prog, node->funcname))
                error("call to undeclared function '%s'", node->funcname);
            break;
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
        validate_node(prog, fn->body);
}
