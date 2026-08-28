#include "minicc.h"

Type *ty_int    = &(Type){TY_INT,    4, 4, false};
Type *ty_long   = &(Type){TY_LONG,   8, 8, false};
Type *ty_llong  = &(Type){TY_LLONG,  8, 8, false};
Type *ty_char   = &(Type){TY_CHAR,   1, 1, false};
Type *ty_short  = &(Type){TY_SHORT,  2, 2, false};
Type *ty_void   = &(Type){TY_VOID,   1, 1, false};
Type *ty_bool   = &(Type){TY_BOOL,   1, 1, false};

Type *ty_uint   = &(Type){TY_INT,    4, 4, true};
Type *ty_ulong  = &(Type){TY_LONG,   8, 8, true};
Type *ty_ullong = &(Type){TY_LLONG,  8, 8, true};
Type *ty_uchar  = &(Type){TY_CHAR,   1, 1, true};
Type *ty_ushort = &(Type){TY_SHORT,  2, 2, true};

Type *ty_float  = &(Type){TY_FLOAT,  4, 4, false};
Type *ty_double = &(Type){TY_DOUBLE, 8, 8, false};

bool is_integer(Type *ty) {
    return ty->kind == TY_INT || ty->kind == TY_LONG ||
           ty->kind == TY_LLONG || ty->kind == TY_CHAR ||
           ty->kind == TY_SHORT || ty->kind == TY_BOOL;
}

bool is_flonum(Type *ty) {
    return ty->kind == TY_FLOAT || ty->kind == TY_DOUBLE;
}

bool is_numeric(Type *ty) {
    return is_integer(ty) || is_flonum(ty);
}

static SysVAbiClass merge_sysv_class(SysVAbiClass a, SysVAbiClass b) {
    if (a == SYSV_ABI_NONE)
        return b;
    if (b == SYSV_ABI_NONE)
        return a;
    if (a == SYSV_ABI_INTEGER || b == SYSV_ABI_INTEGER)
        return SYSV_ABI_INTEGER;
    return SYSV_ABI_SSE;
}

static bool classify_sysv_type(Type *ty, int offset, SysVAbiClass classes[2]) {
    if (!ty || ty->size <= 0)
        return false;

    if (ty->kind == TY_ARRAY) {
        if (ty->array_len <= 0 || !ty->base)
            return false;
        for (int i = 0; i < ty->array_len; i++)
            if (!classify_sysv_type(ty->base, offset + i * ty->base->size, classes))
                return false;
        return true;
    }

    if (ty->kind == TY_STRUCT) {
        if (ty->is_incomplete || !ty->members)
            return false;
        for (Member *m = ty->members; m; m = m->next)
            if (!classify_sysv_type(m->ty, offset + m->offset, classes))
                return false;
        return true;
    }

    SysVAbiClass cls;
    if (is_integer(ty) || ty->kind == TY_PTR)
        cls = SYSV_ABI_INTEGER;
    else if (is_flonum(ty))
        cls = SYSV_ABI_SSE;
    else
        return false;

    int first = offset / 8;
    int last = (offset + ty->size - 1) / 8;
    if (first < 0 || last >= 2)
        return false;
    for (int i = first; i <= last; i++)
        classes[i] = merge_sysv_class(classes[i], cls);
    return true;
}

int sysv_classify_record(Type *ty, SysVAbiClass classes[2]) {
    classes[0] = SYSV_ABI_NONE;
    classes[1] = SYSV_ABI_NONE;

    if (!ty || ty->kind != TY_STRUCT || ty->is_incomplete ||
        ty->size <= 0 || ty->size > 16)
        return 0;
    if (!classify_sysv_type(ty, 0, classes))
        return 0;

    int slots = (ty->size + 7) / 8;
    for (int i = 0; i < slots; i++)
        if (classes[i] == SYSV_ABI_NONE)
            return 0;
    return slots;
}

bool sysv_record_is_memory(Type *ty) {
    return ty && ty->kind == TY_STRUCT && !ty->is_incomplete && ty->size > 16;
}

Type *qualify_type(Type *ty, bool is_const, bool is_volatile) {
    if (!ty || (!is_const && !is_volatile))
        return ty;
    if (ty->kind == TY_ARRAY) {
        Type *copy = calloc(1, sizeof(Type));
        *copy = *ty;
        copy->base = qualify_type(ty->base, is_const, is_volatile);
        copy->origin = ty->origin ? ty->origin : ty;
        copy->qual_next = NULL;
        return copy;
    }
    if (ty->kind == TY_FUNC)
        return ty;
    Type *copy = calloc(1, sizeof(Type));
    *copy = *ty;
    copy->origin = ty->origin ? ty->origin : ty;
    copy->is_const = copy->is_const || is_const;
    copy->is_volatile = copy->is_volatile || is_volatile;
    copy->qual_next = NULL;
    if (copy->kind == TY_STRUCT && copy->origin->is_incomplete) {
        copy->qual_next = copy->origin->qual_next;
        copy->origin->qual_next = copy;
    }
    return copy;
}

Type *pointer_to(Type *base) {
    Type *ty = calloc(1, sizeof(Type));
    ty->kind = TY_PTR;
    ty->size = 8;
    ty->align = 8;
    ty->base = base;
    return ty;
}

Type *array_of(Type *base, int len) {
    Type *ty = calloc(1, sizeof(Type));
    ty->kind = TY_ARRAY;
    ty->size = base->size * len;
    ty->align = base->align;
    ty->base = base;
    ty->array_len = len;
    return ty;
}

Type *func_type(Type *return_ty) {
    Type *ty = calloc(1, sizeof(Type));
    ty->kind = TY_FUNC;
    ty->size = 1;
    ty->align = 1;
    ty->return_ty = return_ty;
    return ty;
}

static Type *integer_promotion(Type *ty) {
    if (!is_integer(ty))
        return ty;
    if (ty->kind == TY_BOOL || ty->kind == TY_CHAR || ty->kind == TY_SHORT)
        return ty_int;
    return ty;
}

static int integer_rank(Type *ty) {
    switch (ty->kind) {
    case TY_BOOL:  return 1;
    case TY_CHAR:  return 2;
    case TY_SHORT: return 3;
    case TY_INT:   return 4;
    case TY_LONG:  return 5;
    case TY_LLONG: return 6;
    default:       return 0;
    }
}

static Type *unsigned_integer_type(Type *ty) {
    switch (ty->kind) {
    case TY_CHAR:  return ty_uchar;
    case TY_SHORT: return ty_ushort;
    case TY_INT:   return ty_uint;
    case TY_LONG:  return ty_ulong;
    case TY_LLONG: return ty_ullong;
    default:       return ty;
    }
}

Type *get_common_type(Type *ty1, Type *ty2) {
    if (ty1->base)
        return pointer_to(ty1->base);
    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)
        return ty_double;
    if (ty1->kind == TY_FLOAT || ty2->kind == TY_FLOAT)
        return ty_float;
    ty1 = integer_promotion(ty1);
    ty2 = integer_promotion(ty2);
    int r1 = integer_rank(ty1);
    int r2 = integer_rank(ty2);
    if (ty1->is_unsigned == ty2->is_unsigned)
        return r1 >= r2 ? ty1 : ty2;
    Type *u = ty1->is_unsigned ? ty1 : ty2;
    Type *s = ty1->is_unsigned ? ty2 : ty1;
    int urank = integer_rank(u);
    int srank = integer_rank(s);
    if (urank >= srank)
        return u;
    if (s->size > u->size)
        return s;
    return unsigned_integer_type(s);
}

static bool is_scalar_operand(Type *ty) {
    if (!ty)
        return false;
    if (is_numeric(ty) || ty->kind == TY_PTR)
        return true;
    return ty->kind == TY_ARRAY || ty->kind == TY_FUNC;
}

static bool is_object_pointer_operand(Type *ty) {
    if (!ty)
        return false;
    if (ty->kind == TY_ARRAY)
        return ty->base && ty->base->kind != TY_VOID && ty->base->kind != TY_FUNC;
    if (ty->kind != TY_PTR || !ty->base)
        return false;
    return ty->base->kind != TY_VOID && ty->base->kind != TY_FUNC;
}

void add_type(Node *node) {
    if (!node) return;

    add_type(node->lhs);
    add_type(node->rhs);
    add_type(node->cond);
    add_type(node->then);
    add_type(node->els);
    add_type(node->init);
    add_type(node->inc);

    for (Node *n = node->body; n; n = n->next)
        add_type(n);
    for (Node *n = node->args; n; n = n->next)
        add_type(n);

    if (node->ty) return;

    switch (node->kind) {
    case ND_ADD:
        if (node->lhs->ty->base) {
            node->ty = node->lhs->ty;
            return;
        }
        if (node->rhs->ty && node->rhs->ty->base) {
            node->ty = node->rhs->ty;
            return;
        }
        if (!is_numeric(node->lhs->ty) || !is_numeric(node->rhs->ty))
            error("invalid arithmetic operands");
        node->ty = get_common_type(node->lhs->ty, node->rhs->ty);
        return;

    case ND_SUB:
        if (node->lhs->ty->base) {
            node->ty = node->lhs->ty;
            return;
        }
        if (node->rhs->ty && node->rhs->ty->base)
            error("invalid arithmetic operands");
        if (!is_numeric(node->lhs->ty) || !is_numeric(node->rhs->ty))
            error("invalid arithmetic operands");
        node->ty = get_common_type(node->lhs->ty, node->rhs->ty);
        return;

    case ND_MUL:
    case ND_DIV:
        if (!is_numeric(node->lhs->ty) || !is_numeric(node->rhs->ty))
            error("invalid arithmetic operands");
        node->ty = get_common_type(node->lhs->ty, node->rhs->ty);
        return;

    case ND_MOD:
    case ND_BITAND:
    case ND_BITOR:
    case ND_BITXOR:
        if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
            error("integer operands required");
        node->ty = get_common_type(node->lhs->ty, node->rhs->ty);
        return;

    case ND_SHL:
    case ND_SHR:
        if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
            error("integer operands required");
        node->ty = integer_promotion(node->lhs->ty);
        return;

    case ND_POS:
    case ND_NEG:
        if (!is_numeric(node->lhs->ty))
            error("numeric operand required");
        node->ty = is_integer(node->lhs->ty) ? integer_promotion(node->lhs->ty) : node->lhs->ty;
        return;

    case ND_BITNOT:
        if (!is_integer(node->lhs->ty))
            error("integer operand required");
        node->ty = integer_promotion(node->lhs->ty);
        return;

    case ND_LOGAND:
    case ND_LOGOR:
        if (!is_scalar_operand(node->lhs->ty) || !is_scalar_operand(node->rhs->ty))
            error("scalar operands required for logical operator");
        node->ty = ty_int;
        return;

    case ND_NOT:
        if (!is_scalar_operand(node->lhs->ty))
            error("scalar operand required for logical not");
        node->ty = ty_int;
        return;

    case ND_EQ:
    case ND_NE:
        if (!is_scalar_operand(node->lhs->ty) || !is_scalar_operand(node->rhs->ty))
            error("scalar operands required for comparison operator");
        node->ty = ty_int;
        return;

    case ND_LT:
    case ND_LE:
        if ((is_numeric(node->lhs->ty) && is_numeric(node->rhs->ty)) ||
            (is_object_pointer_operand(node->lhs->ty) &&
             is_object_pointer_operand(node->rhs->ty))) {
            node->ty = ty_int;
            return;
        }
        error("invalid operands for relational comparison");
        return;

    case ND_FUNCALL:
        node->ty = ty_int;
        return;

    case ND_NUM:
        node->ty = ty_int;
        return;

    case ND_TERNARY:
        if (is_numeric(node->then->ty) && is_numeric(node->els->ty))
            node->ty = get_common_type(node->then->ty, node->els->ty);
        else
            node->ty = node->then->ty;
        return;

    case ND_COMMA:
        node->ty = node->rhs->ty;
        return;

    case ND_ASSIGN:
    case ND_ADD_EQ:
    case ND_SUB_EQ:
    case ND_MUL_EQ:
    case ND_DIV_EQ:
    case ND_MOD_EQ:
    case ND_AND_EQ:
    case ND_OR_EQ:
    case ND_XOR_EQ:
    case ND_SHL_EQ:
    case ND_SHR_EQ:
    case ND_PRE_INC:
    case ND_PRE_DEC:
    case ND_POST_INC:
    case ND_POST_DEC:
        node->ty = node->lhs->ty;
        return;

    case ND_VAR:
        node->ty = node->var->ty;
        return;
    case ND_MEMBER:
        node->ty = qualify_type(node->member->ty,
                                node->lhs->ty && node->lhs->ty->is_const,
                                node->lhs->ty && node->lhs->ty->is_volatile);
        return;
    case ND_ADDR:
        node->ty = pointer_to(node->lhs->ty);
        return;
    case ND_DEREF:
        if (!node->lhs->ty->base)
            error("invalid pointer dereference");
        node->ty = node->lhs->ty->base;
        return;
    }
}
