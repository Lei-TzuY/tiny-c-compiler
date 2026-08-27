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


// Conservative SysV AMD64 aggregate subset shared by semantic ABI checks and
// code generation. A record is supported by value only when its complete
// representation fits in one or two eightbytes and every resulting eightbyte
// is INTEGER-class. Arrays/nested records recurse. For unions, the SysV merge
// rule makes INTEGER dominate SSE in an overlapping eightbyte; conservatively
// recognize that case only when one INTEGER-only member spans the full union
// representation. Other SSE and >16-byte MEMORY shapes remain behind the ABI
// firewall until the full classifier/lowering is implemented.
static bool sysv_integer_record_component(Type *ty) {
    if (!ty)
        return false;
    if (is_integer(ty) || ty->kind == TY_PTR)
        return true;
    if (ty->kind == TY_ARRAY)
        return ty->array_len > 0 && sysv_integer_record_component(ty->base);
    if (ty->kind == TY_STRUCT) {
        if (ty->is_incomplete || !ty->members)
            return false;

        if (ty->is_union) {
            for (Member *m = ty->members; m; m = m->next)
                if (m->ty->size == ty->size &&
                    sysv_integer_record_component(m->ty))
                    return true;
            return false;
        }

        for (Member *m = ty->members; m; m = m->next)
            if (!sysv_integer_record_component(m->ty))
                return false;
        return true;
    }
    return false;
}

int sysv_integer_record_slots(Type *ty) {
    if (!ty || ty->kind != TY_STRUCT || ty->is_incomplete ||
        ty->size <= 0 || ty->size > 16 || !sysv_integer_record_component(ty))
        return 0;
    return (ty->size + 7) / 8;
}

Type *qualify_type(Type *ty, bool is_const, bool is_volatile) {
    if (!ty || (!is_const && !is_volatile))
        return ty;

    // Qualifying an array type through a typedef qualifies its element type.
    // Direct declarations such as `const int a[3]` already arrive in this
    // shape because the declaration specifiers qualify the element base first.
    if (ty->kind == TY_ARRAY) {
        Type *copy = calloc(1, sizeof(Type));
        *copy = *ty;
        copy->base = qualify_type(ty->base, is_const, is_volatile);
        copy->origin = ty->origin ? ty->origin : ty;
        copy->qual_next = NULL;
        return copy;
    }

    // Qualifiers on function types have no useful semantics in this compiler;
    // pointer qualifiers are attached to TY_PTR by the declarator parser.
    if (ty->kind == TY_FUNC)
        return ty;

    Type *copy = calloc(1, sizeof(Type));
    *copy = *ty;
    copy->origin = ty->origin ? ty->origin : ty;
    copy->is_const = copy->is_const || is_const;
    copy->is_volatile = copy->is_volatile || is_volatile;
    copy->qual_next = NULL;

    // A qualified clone of a forward-declared record must observe completion
    // of the canonical tag later in the translation unit.
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

// Integer promotions for the LP64 target used by minicc.  All supported
// char/short/_Bool values fit in int, including their unsigned variants.
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

// Usual arithmetic conversions for the x86-64 LP64 target.  `long` and
// `long long` are both 64-bit here but retain distinct C ranks, so size alone
// is insufficient (notably unsigned long + long long -> unsigned long long).
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

    // The higher-rank signed type wins only when it can represent every value
    // of the lower-rank unsigned type. On this target that requires more bits.
    if (s->size > u->size)
        return s;

    return unsigned_integer_type(s);
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
        // Subtraction is not commutative: only pointer - integer is a valid
        // pointer-valued form.  A pointer on the right (notably the parser's
        // internal `0 - operand` representation of unary minus) must not turn
        // an otherwise-invalid expression such as `-ptr` or `-array` into
        // pointer arithmetic.
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
        // Each operand is integer-promoted independently; unlike ordinary
        // arithmetic there is no common type, and the result has the promoted
        // type of the left operand.
        node->ty = integer_promotion(node->lhs->ty);
        return;

    case ND_NEG:
        if (!is_numeric(node->lhs->ty))
            error("numeric operand required");
        node->ty = is_integer(node->lhs->ty)
                     ? integer_promotion(node->lhs->ty)
                     : node->lhs->ty;
        return;

    case ND_BITNOT:
        if (!is_integer(node->lhs->ty))
            error("integer operand required");
        node->ty = integer_promotion(node->lhs->ty);
        return;

    case ND_EQ:
    case ND_NE:
    case ND_LT:
    case ND_LE:
    case ND_LOGAND:
    case ND_LOGOR:
    case ND_NOT:
        node->ty = ty_int;
        return;

    case ND_FUNCALL:
        // Function-call return types are still resolved as int until the
        // SysV floating-point function ABI work lands.
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
        // Accessing a member through a const/volatile aggregate carries those
        // qualifiers onto the member lvalue. This makes both `s.x` and
        // `p->x` honor a qualified struct/union object.
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
