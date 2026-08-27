#include "minicc.h"

// parse.c

typedef struct EnumConst EnumConst;
struct EnumConst {
    EnumConst *next;
    char *name;
    int64_t val;
};

typedef struct TypeDef TypeDef;
struct TypeDef {
    TypeDef *next;
    char *name;
    Type *ty;
};

typedef enum {
    TAG_STRUCT,
    TAG_UNION,
    TAG_ENUM,
} TagKind;

typedef struct StructTag StructTag;
struct StructTag {
    StructTag *next;
    char *name;
    Type *ty;
    TagKind kind;
};

// ---- Block Scope ----
typedef struct VarScope VarScope;
struct VarScope {
    VarScope *next;
    char *name;
    Obj *var;
};

typedef struct Scope Scope;
struct Scope {
    Scope *parent;
    VarScope *vars;
    StructTag *tags;
    TypeDef *typedefs;
    EnumConst *enum_consts;
};

static Scope *current_scope;

static void enter_scope(void) {
    Scope *sc = calloc(1, sizeof(Scope));
    sc->parent = current_scope;
    current_scope = sc;
}

static void leave_scope(void) {
    current_scope = current_scope->parent;
}

static StructTag *find_tag_in_scope(Scope *scope, const char *name) {
    if (!scope)
        return NULL;
    for (StructTag *tag = scope->tags; tag; tag = tag->next)
        if (!strcmp(tag->name, name))
            return tag;
    return NULL;
}

static StructTag *find_tag(const char *name) {
    for (Scope *scope = current_scope; scope; scope = scope->parent) {
        StructTag *tag = find_tag_in_scope(scope, name);
        if (tag)
            return tag;
    }
    return NULL;
}

static const char *tag_kind_name(TagKind kind) {
    switch (kind) {
    case TAG_STRUCT: return "struct";
    case TAG_UNION: return "union";
    case TAG_ENUM: return "enum";
    }
    return "tag";
}

static StructTag *push_tag(const char *name, Type *ty, TagKind kind) {
    StructTag *tag = calloc(1, sizeof(StructTag));
    tag->name = strdup(name);
    tag->ty = ty;
    tag->kind = kind;
    tag->next = current_scope->tags;
    current_scope->tags = tag;
    return tag;
}

static bool token_matches_name(Token *tok, const char *name) {
    return tok->kind == TK_IDENT && strlen(name) == (size_t)tok->len &&
           !strncmp(tok->loc, name, tok->len);
}

// Typedef names live in the ordinary identifier namespace. A variable in a
// nearer block therefore hides an outer typedef name.
static TypeDef *find_typedef(Token *tok) {
    for (Scope *scope = current_scope; scope; scope = scope->parent) {
        for (VarScope *vs = scope->vars; vs; vs = vs->next)
            if (token_matches_name(tok, vs->name))
                return NULL;

        for (TypeDef *td = scope->typedefs; td; td = td->next)
            if (token_matches_name(tok, td->name))
                return td;
    }
    return NULL;
}

static void push_typedef(Token *ident, Type *ty) {
    TypeDef *td = calloc(1, sizeof(TypeDef));
    td->name = strndup(ident->loc, ident->len);
    td->ty = ty;
    td->next = current_scope->typedefs;
    current_scope->typedefs = td;
}

// Enumeration constants share C's ordinary identifier namespace with
// variables and typedef names. A nearer variable/typedef therefore hides an
// outer enumerator, while an enumerator in the current scope hides outer names.
static EnumConst *find_enum_const(Token *tok) {
    for (Scope *scope = current_scope; scope; scope = scope->parent) {
        for (VarScope *vs = scope->vars; vs; vs = vs->next)
            if (token_matches_name(tok, vs->name))
                return NULL;
        for (TypeDef *td = scope->typedefs; td; td = td->next)
            if (token_matches_name(tok, td->name))
                return NULL;
        for (EnumConst *ec = scope->enum_consts; ec; ec = ec->next)
            if (token_matches_name(tok, ec->name))
                return ec;
    }
    return NULL;
}

static void push_enum_const(char *name, int64_t val) {
    EnumConst *ec = calloc(1, sizeof(EnumConst));
    ec->name = name;
    ec->val = val;
    ec->next = current_scope->enum_consts;
    current_scope->enum_consts = ec;
}

// ---- End Block Scope ----

static Obj *locals;
static Obj *globals;

// goto / label tracking for current function
static Node *current_gotos;
static Node *current_labels;

static int align_up(int n, int a) { return (n + a - 1) / a * a; }

static Node *expr(Token **rest, Token *tok);
static Node *assign(Token **rest, Token *tok);
static Node *ternary(Token **rest, Token *tok);
static Node *logor(Token **rest, Token *tok);
static Node *logand(Token **rest, Token *tok);
static Node *bitor_expr(Token **rest, Token *tok);
static Node *bitxor_expr(Token **rest, Token *tok);
static Node *bitand_expr(Token **rest, Token *tok);
static Node *equality(Token **rest, Token *tok);
static Node *relational(Token **rest, Token *tok);
static Node *shift(Token **rest, Token *tok);
static Node *add(Token **rest, Token *tok);
static Node *mul(Token **rest, Token *tok);
static Node *unary(Token **rest, Token *tok);
static Node *postfix(Token **rest, Token *tok);
static Node *primary(Token **rest, Token *tok);
static Type *declspec(Token **rest, Token *tok);
static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract);
static Type *type_suffix(Token **rest, Token *tok, Type *ty);
static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident);
static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident);
static Type *type_name(Token **rest, Token *tok);
static bool type_compatible(Type *a, Type *b);
static bool assignment_compatible(Type *dst, Node *rhs);
static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op);

static Type *current_return_ty;

static bool is_typename(Token *tok) {
    if (equal(tok, "int") || equal(tok, "char") || equal(tok, "void") ||
        equal(tok, "enum") || equal(tok, "struct") || equal(tok, "union") ||
        equal(tok, "short") || equal(tok, "long") || equal(tok, "unsigned") ||
        equal(tok, "_Bool") || equal(tok, "float") || equal(tok, "double"))
        return true;
    return find_typedef(tok) != NULL;
}

// Check if the current position starts a declaration
// (storage-class-specifier | type-qualifier | type-name)
static bool is_decl_start(Token *tok) {
    if (is_typename(tok)) return true;
    if (equal(tok, "static") || equal(tok, "extern")) return true;
    if (equal(tok, "const") || equal(tok, "volatile")) return true;
    if (equal(tok, "register") || equal(tok, "inline")) return true;
    return false;
}

// Find a variable by name, respecting block scope.
static Obj *find_var(Token *tok) {
    for (Scope *sc = current_scope; sc; sc = sc->parent) {
        for (VarScope *vs = sc->vars; vs; vs = vs->next) {
            if (strlen(vs->name) == (size_t)tok->len &&
                !strncmp(tok->loc, vs->name, tok->len))
                return vs->var;
        }
    }
    for (Obj *var = globals; var; var = var->next)
        if (strlen(var->name) == (size_t)tok->len && !strncmp(tok->loc, var->name, tok->len))
            return var;
    return NULL;
}

static Node *new_node(NodeKind kind) {
    Node *node = calloc(1, sizeof(Node));
    node->kind = kind;
    return node;
}

static char *new_unique_name(void) {
    static int id = 0;
    char *buf = calloc(1, 20);
    sprintf(buf, ".L..%d", id++);
    return buf;
}

static Node *new_binary(NodeKind kind, Node *lhs, Node *rhs) {
    Node *node = new_node(kind);
    node->lhs = lhs;
    node->rhs = rhs;
    return node;
}

static Node *new_unary(NodeKind kind, Node *expr) {
    Node *node = new_node(kind);
    node->lhs = expr;
    return node;
}

static Node *new_num(int64_t val) {
    Node *node = new_node(ND_NUM);
    node->val = val;
    return node;
}

static Node *new_long(int64_t val) {
    Node *node = new_node(ND_NUM);
    node->val = val;
    node->ty = ty_long;
    return node;
}

static bool is_lvalue(Node *node) {
    add_type(node);

    switch (node->kind) {
    case ND_VAR:
        return node->ty->kind != TY_FUNC;
    case ND_DEREF:
        return node->ty->kind != TY_FUNC && node->ty->kind != TY_VOID;
    case ND_MEMBER:
        return is_lvalue(node->lhs);
    default:
        return false;
    }
}

static bool is_modifiable_lvalue(Node *node) {
    if (!is_lvalue(node))
        return false;

    Type *ty = node->ty;
    if (!ty || ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
        ty->kind == TY_VOID || ty->is_incomplete)
        return false;
    return true;
}

static bool is_addressable_expr(Node *node) {
    add_type(node);

    // A function designator is not an lvalue in C, but unary & is explicitly
    // permitted on one. Both a named function and *function_pointer reach
    // here with TY_FUNC.
    if (node->ty->kind == TY_FUNC)
        return node->kind == ND_VAR || node->kind == ND_DEREF;
    return is_lvalue(node);
}

static Node *new_checked_addr(Node *operand, Token *op) {
    if (!is_addressable_expr(operand))
        error_at(op->loc, "address-of operand is not an lvalue or function designator");
    return new_unary(ND_ADDR, operand);
}

static Node *new_checked_deref(Node *operand, Token *op) {
    add_type(operand);

    Type *target = NULL;
    if (operand->ty->kind == TY_PTR || operand->ty->kind == TY_ARRAY)
        target = operand->ty->base;
    else if (operand->ty->kind == TY_FUNC)
        target = operand->ty;

    if (!target || target->kind == TY_VOID)
        error_at(op->loc, "invalid pointer dereference");

    Node *node = new_unary(ND_DEREF, operand);
    node->ty = target;
    return node;
}

static Type *pointer_arithmetic_type(Type *ty) {
    if (!ty)
        return NULL;

    // Array expressions decay to a pointer to their first element in value
    // contexts.  Keep that decay explicit here so `array + n` has pointer
    // result type instead of accidentally retaining TY_ARRAY.
    if (ty->kind == TY_ARRAY)
        ty = pointer_to(ty->base);

    if (ty->kind != TY_PTR || !ty->base)
        return NULL;

    Type *base = ty->base;
    // Standard C pointer arithmetic is defined only for pointers to complete
    // object types.  In particular, void* and function pointers are not
    // arithmetic pointers (even though some host compilers accept extensions).
    if (base->kind == TY_VOID || base->kind == TY_FUNC ||
        base->is_incomplete || base->size <= 0)
        return NULL;
    return ty;
}

static Node *new_add(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_ADD, lhs, rhs);

    Type *lp = pointer_arithmetic_type(lhs->ty);
    Type *rp = pointer_arithmetic_type(rhs->ty);

    if (lp && is_integer(rhs->ty)) {
        Node *node = new_binary(ND_ADD, lhs,
                                new_binary(ND_MUL, rhs, new_long(lp->base->size)));
        node->ty = lp;
        return node;
    }

    if (is_integer(lhs->ty) && rp) {
        Node *node = new_binary(ND_ADD, rhs,
                                new_binary(ND_MUL, lhs, new_long(rp->base->size)));
        node->ty = rp;
        return node;
    }

    error("invalid operands to pointer addition");
}

static Node *new_sub(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_SUB, lhs, rhs);

    Type *lp = pointer_arithmetic_type(lhs->ty);
    Type *rp = pointer_arithmetic_type(rhs->ty);

    if (lp && is_integer(rhs->ty)) {
        Node *node = new_binary(ND_SUB, lhs,
                                new_binary(ND_MUL, rhs, new_long(lp->base->size)));
        node->ty = lp;
        return node;
    }

    if (lp && rp) {
        if (!type_compatible(lp->base, rp->base))
            error("incompatible pointer subtraction");

        Node *diff = new_binary(ND_SUB, lhs, rhs);
        diff->ty = ty_long;
        Node *node = new_binary(ND_DIV, diff, new_long(lp->base->size));
        node->ty = ty_long;
        return node;
    }

    error("invalid operands to pointer subtraction");
}

static Node *new_compound_assign(NodeKind kind, Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (!is_modifiable_lvalue(lhs))
        error("left operand of compound assignment is not a modifiable lvalue");

    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
        if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
            return new_binary(kind, lhs, rhs);

        Type *ptr = pointer_arithmetic_type(lhs->ty);
        if (ptr && lhs->ty->kind == TY_PTR && is_integer(rhs->ty)) {
            rhs = new_binary(ND_MUL, rhs, new_long(ptr->base->size));
            return new_binary(kind, lhs, rhs);
        }

        error("invalid operands to pointer compound assignment");
    }

    if ((kind == ND_MUL_EQ || kind == ND_DIV_EQ) &&
        is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(kind, lhs, rhs);

    if (is_integer(lhs->ty) && is_integer(rhs->ty))
        return new_binary(kind, lhs, rhs);

    error("invalid operands");
}

static Node *new_inc_dec(NodeKind kind, Node *expr) {
    add_type(expr);
    if (!is_modifiable_lvalue(expr))
        error("increment/decrement operand is not a modifiable lvalue");
    if (!is_numeric(expr->ty) && !pointer_arithmetic_type(expr->ty))
        error("invalid increment/decrement operand");
    return new_unary(kind, expr);
}

static Node *new_var_node(Obj *var) {
    Node *node = new_node(ND_VAR);
    node->var = var;
    return node;
}

static Obj *create_lvar(char *name) {
    Obj *var = calloc(1, sizeof(Obj));
    var->name = name;
    var->is_local = true;
    var->next = locals;
    locals = var;

    VarScope *vs = calloc(1, sizeof(VarScope));
    vs->name = name;
    vs->var = var;
    vs->next = current_scope->vars;
    current_scope->vars = vs;

    return var;
}

// Create a static local variable (allocated as a global with unique name,
// but scoped locally).
static Obj *create_static_lvar(char *name) {
    static int id = 0;
    char *unique = calloc(1, strlen(name) + 30);
    sprintf(unique, ".Lstatic.%d.%s", id++, name);

    Obj *var = calloc(1, sizeof(Obj));
    var->name = unique;
    var->is_local = false; // stored as global
    var->is_static = true;
    var->next = globals;
    globals = var;

    // Register in current scope with original name
    VarScope *vs = calloc(1, sizeof(VarScope));
    vs->name = name;
    vs->var = var;
    vs->next = current_scope->vars;
    current_scope->vars = vs;

    return var;
}

// Create an extern local reference (refers to a global, no storage allocated)
static Obj *create_extern_ref(char *name) {
    // Check if already in globals
    for (Obj *var = globals; var; var = var->next)
        if (!strcmp(var->name, name))
            return var;

    Obj *var = calloc(1, sizeof(Obj));
    var->name = name;
    var->is_local = false;
    var->is_extern = true;
    var->next = globals;
    globals = var;

    // Register in current scope
    VarScope *vs = calloc(1, sizeof(VarScope));
    vs->name = name;
    vs->var = var;
    vs->next = current_scope->vars;
    current_scope->vars = vs;

    return var;
}

static bool is_incomplete_object_type(Type *ty) {
    if (!ty)
        return false;
    if (ty->kind == TY_STRUCT)
        return ty->is_incomplete;
    if (ty->kind == TY_ARRAY)
        return is_incomplete_object_type(ty->base);
    return false;
}

static Type *new_record_type(void) {
    Type *ty = calloc(1, sizeof(Type));
    ty->kind = TY_STRUCT;
    ty->align = 1;
    ty->is_incomplete = true;
    return ty;
}

// Parse both struct and union specifiers. A tagged record is inserted into the
// current tag scope before its body is parsed so self-referential pointers work.
// Completing a forward declaration mutates the same Type object, which keeps
// typedef aliases and earlier pointers linked to the completed record.
static Type *record_decl(Token **rest, Token *tok, bool is_union) {
    const char *kind = is_union ? "union" : "struct";
    TagKind tag_kind = is_union ? TAG_UNION : TAG_STRUCT;
    char *tag_name = NULL;

    if (tok->kind == TK_IDENT) {
        tag_name = strndup(tok->loc, tok->len);
        tok = tok->next;
    }

    if (!equal(tok, "{")) {
        if (!tag_name)
            error_at(tok->loc, "expected %s tag or body", kind);

        StructTag *tag = find_tag(tag_name);
        if (!tag) {
            Type *ty = new_record_type();
            tag = push_tag(tag_name, ty, tag_kind);
        } else if (tag->kind != tag_kind) {
            error_at(tok->loc, "%s %s conflicts with %s tag", kind, tag_name,
                     tag_kind_name(tag->kind));
        }
        *rest = tok;
        return tag->ty;
    }

    Type *ty = NULL;
    if (tag_name) {
        StructTag *tag = find_tag_in_scope(current_scope, tag_name);
        if (tag) {
            if (tag->kind != tag_kind)
                error_at(tok->loc, "%s %s conflicts with %s tag", kind, tag_name,
                         tag_kind_name(tag->kind));
            if (!tag->ty->is_incomplete)
                error_at(tok->loc, "redefinition of %s %s", kind, tag_name);
            ty = tag->ty;
        } else {
            ty = new_record_type();
            push_tag(tag_name, ty, tag_kind);
        }
    } else {
        ty = new_record_type();
    }

    tok = skip(tok, "{");

    Member head = {};
    Member *cur = &head;
    while (!equal(tok, "}")) {
        Type *basety = declspec(&tok, tok);
        for (bool first = true; !consume(&tok, tok, ";"); first = false) {
            if (!first)
                tok = skip(tok, ",");

            Token *ident;
            Type *mty = declarator(&tok, tok, basety, &ident);
            if (is_incomplete_object_type(mty))
                error_at(ident->loc, "field has incomplete type");

            Member *m = calloc(1, sizeof(Member));
            m->name = strndup(ident->loc, ident->len);
            m->ty = mty;
            cur = cur->next = m;
        }
    }
    tok = skip(tok, "}");

    int align = 1;
    if (is_union) {
        int size = 0;
        for (Member *m = head.next; m; m = m->next) {
            if (m->ty->size > size)
                size = m->ty->size;
            int ma = m->ty->align > 0 ? m->ty->align : 1;
            if (ma > align)
                align = ma;
            m->offset = 0;
        }
        ty->size = align_up(size, align);
    } else {
        int offset = 0;
        for (Member *m = head.next; m; m = m->next) {
            int ma = m->ty->align > 0 ? m->ty->align : 1;
            offset = align_up(offset, ma);
            m->offset = offset;
            offset += m->ty->size;
            if (ma > align)
                align = ma;
        }
        ty->size = align_up(offset, align);
    }

    ty->align = align;
    ty->members = head.next;
    ty->is_incomplete = false;
    *rest = tok;
    return ty;
}

static int64_t cast_const_integer(int64_t val, Type *ty) {
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

static int64_t eval_const_expr(Node *node) {
    if (!node)
        error("expected integer constant expression");

    switch (node->kind) {
    case ND_NUM:
        if (node->ty && is_flonum(node->ty))
            error("floating value is not an integer constant expression");
        return node->val;
    case ND_ADD:
        return eval_const_expr(node->lhs) + eval_const_expr(node->rhs);
    case ND_SUB:
        return eval_const_expr(node->lhs) - eval_const_expr(node->rhs);
    case ND_MUL:
        return eval_const_expr(node->lhs) * eval_const_expr(node->rhs);
    case ND_DIV: {
        int64_t lhs = eval_const_expr(node->lhs);
        int64_t rhs = eval_const_expr(node->rhs);
        if (!rhs)
            error("division by zero in integer constant expression");
        return lhs / rhs;
    }
    case ND_MOD: {
        int64_t lhs = eval_const_expr(node->lhs);
        int64_t rhs = eval_const_expr(node->rhs);
        if (!rhs)
            error("modulo by zero in integer constant expression");
        return lhs % rhs;
    }
    case ND_BITAND:
        return eval_const_expr(node->lhs) & eval_const_expr(node->rhs);
    case ND_BITOR:
        return eval_const_expr(node->lhs) | eval_const_expr(node->rhs);
    case ND_BITXOR:
        return eval_const_expr(node->lhs) ^ eval_const_expr(node->rhs);
    case ND_BITNOT:
        return ~eval_const_expr(node->lhs);
    case ND_SHL:
    case ND_SHR: {
        int64_t lhs = eval_const_expr(node->lhs);
        int64_t rhs = eval_const_expr(node->rhs);
        if (rhs < 0 || rhs >= 64)
            error("invalid shift count in integer constant expression");
        return node->kind == ND_SHL ? (lhs << rhs) : (lhs >> rhs);
    }
    case ND_EQ:
        return eval_const_expr(node->lhs) == eval_const_expr(node->rhs);
    case ND_NE:
        return eval_const_expr(node->lhs) != eval_const_expr(node->rhs);
    case ND_LT:
        return eval_const_expr(node->lhs) < eval_const_expr(node->rhs);
    case ND_LE:
        return eval_const_expr(node->lhs) <= eval_const_expr(node->rhs);
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
    case ND_TERNARY:
        return eval_const_expr(node->cond) ? eval_const_expr(node->then)
                                           : eval_const_expr(node->els);
    case ND_CAST:
        return cast_const_integer(eval_const_expr(node->lhs), node->ty);
    default:
        error("not an integer constant expression");
    }
}

static Type *enum_decl(Token **rest, Token *tok) {
    char *tag_name = NULL;

    if (tok->kind == TK_IDENT) {
        tag_name = strndup(tok->loc, tok->len);
        tok = tok->next;
    }

    if (!equal(tok, "{")) {
        if (!tag_name)
            error_at(tok->loc, "expected enum tag or body");
        StructTag *tag = find_tag(tag_name);
        if (!tag)
            error_at(tok->loc, "unknown enum tag: %s", tag_name);
        if (tag->kind != TAG_ENUM)
            error_at(tok->loc, "enum %s conflicts with %s tag", tag_name,
                     tag_kind_name(tag->kind));
        *rest = tok;
        return ty_int;
    }

    if (tag_name) {
        StructTag *tag = find_tag_in_scope(current_scope, tag_name);
        if (tag) {
            if (tag->kind != TAG_ENUM)
                error_at(tok->loc, "enum %s conflicts with %s tag", tag_name,
                         tag_kind_name(tag->kind));
            error_at(tok->loc, "redefinition of enum %s", tag_name);
        }
        push_tag(tag_name, ty_int, TAG_ENUM);
    }

    tok = skip(tok, "{");
    int64_t val = 0;

    while (!equal(tok, "}")) {
        if (tok->kind != TK_IDENT)
            error_at(tok->loc, "expected enumerator name");

        char *name = strndup(tok->loc, tok->len);
        tok = tok->next;

        if (consume(&tok, tok, "=")) {
            Node *value = ternary(&tok, tok);
            val = eval_const_expr(value);
        }

        push_enum_const(name, val++);

        if (consume(&tok, tok, ","))
            continue;
        if (!equal(tok, "}"))
            error_at(tok->loc, "expected ',' or '}' in enum definition");
    }

    *rest = skip(tok, "}");
    return ty_int;
}

static Type *declspec(Token **rest, Token *tok) {
    Type *ty = NULL;

    while (is_decl_start(tok)) {
        if (consume(&tok, tok, "const") || consume(&tok, tok, "volatile") ||
            consume(&tok, tok, "register") || consume(&tok, tok, "inline") ||
            consume(&tok, tok, "static") || consume(&tok, tok, "extern"))
            continue;

        if (consume(&tok, tok, "_Bool"))  { ty = ty_bool; continue; }
        if (consume(&tok, tok, "float"))  { ty = ty_float; continue; }
        if (consume(&tok, tok, "double")) { ty = ty_double; continue; }
        if (consume(&tok, tok, "char"))   { ty = (ty && ty->is_unsigned) ? ty_uchar : ty_char; continue; }
        if (consume(&tok, tok, "void"))   { ty = ty_void; continue; }
        if (consume(&tok, tok, "short"))  { ty = (ty && ty->is_unsigned) ? ty_ushort : ty_short; continue; }

        if (consume(&tok, tok, "long")) {
            if (consume(&tok, tok, "long")) {}
            consume(&tok, tok, "int");
            ty = (ty && ty->is_unsigned) ? ty_ulong : ty_long;
            continue;
        }

        if (consume(&tok, tok, "unsigned")) {
            if (ty == ty_char) ty = ty_uchar;
            else if (ty == ty_short) ty = ty_ushort;
            else if (ty == ty_long) ty = ty_ulong;
            else ty = ty_uint;
            continue;
        }

        if (consume(&tok, tok, "int")) {
            if (!ty) ty = ty_int;
            continue;
        }

        if (equal(tok, "union")) {
            ty = record_decl(&tok, tok->next, true);
            continue;
        }

        if (equal(tok, "struct")) {
            ty = record_decl(&tok, tok->next, false);
            continue;
        }

        if (equal(tok, "enum")) {
            ty = enum_decl(&tok, tok->next);
            continue;
        }

        // Check for a typedef name visible in the current lexical scope.
        // Once a concrete type specifier was already consumed, an identifier
        // that happens to match an outer typedef is the declarator name, not a
        // second type specifier (e.g. `typedef char T;` or `int T;`).
        if (tok->kind == TK_IDENT) {
            if (ty)
                break;
            TypeDef *td = find_typedef(tok);
            if (td) {
                tok = tok->next;
                ty = td->ty;
                continue;
            }
        }

        break;
    }

    *rest = tok;
    return ty ? ty : ty_int;
}

static Type *adjust_param_type(Type *ty) {
    // C adjusts array and function parameter declarations to pointers.
    if (ty->kind == TY_ARRAY)
        return pointer_to(ty->base);
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    return ty;
}

static Type *func_params(Token **rest, Token *tok, Type *return_ty) {
    Type *fty = func_type(return_ty);
    fty->has_prototype = !equal(tok, ")");

    Obj head = {};
    Obj *cur = &head;

    // `(void)` is the strict zero-parameter prototype, unlike old-style `()`.
    if (equal(tok, "void") && equal(tok->next, ")")) {
        tok = tok->next;
        fty->has_prototype = true;
        *rest = skip(tok, ")");
        return fty;
    }

    while (!equal(tok, ")")) {
        if (cur != &head)
            tok = skip(tok, ",");

        if (equal(tok, "...")) {
            tok = tok->next;
            fty->is_variadic = true;
            break;
        }

        Type *basety = declspec(&tok, tok);
        Token *name = NULL;
        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true);
        param_ty = adjust_param_type(param_ty);

        if (is_incomplete_object_type(param_ty))
            error_at(name ? name->loc : tok->loc, "parameter has incomplete type");

        Obj *param = calloc(1, sizeof(Obj));
        param->ty = param_ty;
        if (name)
            param->name = strndup(name->loc, name->len);
        cur = cur->param_next = param;
    }

    fty->params = head.param_next;
    *rest = skip(tok, ")");
    return fty;
}

// Parse postfix type constructors. Arrays associate from the inside out, so
// `int a[2][3]` becomes array(2, array(3, int)); function suffixes retain the
// complete prototype on TY_FUNC.
static Type *type_suffix(Token **rest, Token *tok, Type *ty) {
    if (equal(tok, "("))
        return func_params(rest, tok->next, ty);

    if (equal(tok, "[")) {
        tok = tok->next;
        int len = 0;
        if (tok->kind == TK_NUM) {
            len = tok->val;
            tok = tok->next;
        }
        tok = skip(tok, "]");
        ty = type_suffix(rest, tok, ty);
        if (ty->kind == TY_FUNC)
            error_at(tok->loc, "array element type cannot be a function");
        return array_of(ty, len);
    }

    *rest = tok;
    return ty;
}

// C declarators are recursive: parentheses can change which pointer/array/
// function constructor binds first. Parse the parenthesized shape once with a
// dummy base to locate its end, attach the outer suffix to the real base, then
// replay the inner declarator with that completed base type. This supports
// arrays of function pointers, functions returning function pointers, and
// arbitrarily nested pointer/array/function groupings without syntax-specific
// special cases.
static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract) {
    while (consume(&tok, tok, "*"))
        ty = pointer_to(ty);

    // In an abstract declarator, a leading parameter list is a function
    // suffix rather than a grouping. Grouping forms such as `(*)` still enter
    // the recursive parenthesized path below.
    if (allow_abstract && equal(tok, "(") &&
        (equal(tok->next, ")") || is_typename(tok->next) ||
         equal(tok->next, "const") || equal(tok->next, "volatile") ||
         equal(tok->next, "register")))
        return type_suffix(rest, tok, ty);

    if (equal(tok, "(")) {
        Token *start = tok;
        Type dummy = {};
        declarator_impl(&tok, start->next, &dummy, ident, allow_abstract);
        tok = skip(tok, ")");
        ty = type_suffix(rest, tok, ty);
        return declarator_impl(&tok, start->next, ty, ident, allow_abstract);
    }

    if (tok->kind == TK_IDENT) {
        *ident = tok;
        tok = tok->next;
    } else if (allow_abstract) {
        *ident = NULL;
    } else {
        error_at(tok->loc, "expected a variable name");
    }

    return type_suffix(rest, tok, ty);
}

static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, false);
}

static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, true);
}

// type-name = declaration-specifiers abstract-declarator?
//
// Casts and sizeof(type-name) use the same recursive declarator machinery as
// declarations, so pointer/array/function grouping has one source of truth.
static Type *type_name(Token **rest, Token *tok) {
    Type *ty = declspec(&tok, tok);
    Token *ident = NULL;
    ty = abstract_declarator(&tok, tok, ty, &ident);
    if (ident)
        error_at(ident->loc, "identifier is not allowed in a type name");
    *rest = tok;
    return ty;
}

static bool invalid_sizeof_type(Type *ty) {
    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)
        return true;
    if (ty->kind == TY_ARRAY && ty->array_len == 0)
        return true;
    return is_incomplete_object_type(ty);
}

// Parse a constant integer (with optional sign) for global initializers
static int64_t parse_const_int(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM || tok->is_float)
        error_at(tok->loc, "expected integer constant");
    int64_t val = tok->val;
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}

static double parse_const_double(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM)
        error_at(tok->loc, "expected numeric constant");
    double val = tok->is_float ? tok->fval : (double)tok->val;
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}

// declaration = declspec (declarator ("=" (expr | "{" initializer "}"))?)
//               ("," declarator ("=" (expr | "{" initializer "}"))?)* ";"
static Node *declaration(Token **rest, Token *tok, bool is_static, bool is_extern) {
    Type *basety = declspec(&tok, tok);
    if (equal(tok, ";")) {
        *rest = tok->next;
        return new_node(ND_EXPR_STMT);
    }

    Node block_head = {};
    Node *block_cur = &block_head;
    bool first = true;

    do {
        if (!first) tok = tok->next; // skip ','
        first = false;

        Token *ident;
        Type *ty = declarator(&tok, tok, basety, &ident);
        if (!is_extern && is_incomplete_object_type(ty))
            error_at(ident->loc, "variable has incomplete type");

        Obj *var;
        if (is_static)
            var = create_static_lvar(strndup(ident->loc, ident->len));
        else if (is_extern)
            var = create_extern_ref(strndup(ident->loc, ident->len));
        else
            var = create_lvar(strndup(ident->loc, ident->len));
        var->ty = ty;

        if (!equal(tok, "="))
            continue;
        tok = tok->next; // skip '='

        // Static/extern: constant initializer only
        if (is_static || is_extern) {
            if (equal(tok, "{")) {
                tok = tok->next;
                int cap = 16, cnt = 0;
                int64_t *vals = calloc(cap, sizeof(int64_t));
                while (!equal(tok, "}")) {
                    if (cnt > 0) tok = skip(tok, ",");
                    if (equal(tok, "}")) break;
                    if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                    vals[cnt++] = parse_const_int(&tok, tok);
                }
                tok = skip(tok, "}");
                if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                    ty = array_of(ty->base, cnt);
                    var->ty = ty;
                }
                var->init_vals = vals;
                var->init_vals_count = cnt;
            } else {
                if (is_flonum(ty))
                    var->finit_val = parse_const_double(&tok, tok);
                else
                    var->init_val = parse_const_int(&tok, tok);
                var->has_init_val = true;
            }
            continue;
        }

        // Brace-enclosed initializer: { expr, expr, ... }
        if (equal(tok, "{")) {
            tok = tok->next;

            int cur_idx = 0;
            Member *cur_mem = (ty->kind == TY_STRUCT) ? ty->members : NULL;

            while (!equal(tok, "}")) {
                if (equal(tok, ",")) tok = tok->next;
                if (equal(tok, "}")) break;

                // Designated initializer: .member = expr
                if (consume(&tok, tok, ".")) {
                    if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name in designated initializer");
                    char *mname = strndup(tok->loc, tok->len);
                    tok = skip(tok->next, "=");
                    Node *e = assign(&tok, tok);

                    Member *m = ty->members;
                    for (; m; m = m->next)
                        if (!strcmp(m->name, mname)) break;
                    if (!m) error_at(tok->loc, "unknown member in designated initializer");

                    Node *var_node = new_var_node(var);
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = var_node;
                    member_node->member = m;
                    Node *a = new_checked_assign(member_node, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    if (m) cur_mem = m->next;
                    continue;
                }

                // Designated initializer: [index] = expr
                if (consume(&tok, tok, "[")) {
                    if (tok->kind != TK_NUM) error_at(tok->loc, "expected array index in designated initializer");
                    int idx = tok->val;
                    tok = skip(tok->next, "]");
                    tok = skip(tok, "=");
                    Node *e = assign(&tok, tok);

                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(idx)));
                    Node *a = new_checked_assign(lhs, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    cur_idx = idx + 1;
                    continue;
                }

                // Positional initializer
                Node *e = assign(&tok, tok);
                if (ty->kind == TY_ARRAY) {
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(cur_idx++)));
                    Node *a = new_checked_assign(lhs, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                } else if (ty->kind == TY_STRUCT && cur_mem) {
                    Node *var_node = new_var_node(var);
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = var_node;
                    member_node->member = cur_mem;
                    Node *a = new_checked_assign(member_node, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    cur_mem = cur_mem->next;
                }
            }
            tok = skip(tok, "}");

            // Infer array length
            if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                ty = array_of(ty->base, cur_idx);
                var->ty = ty;
            }
            continue;
        }

        // Simple scalar initializer
        Node *vnode = new_var_node(var);
        Node *rhs = assign(&tok, tok);
        Node *a = new_checked_assign(vnode, rhs, tok);
        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
    } while (equal(tok, ","));

    *rest = skip(tok, ";");

    if (!block_head.next) return new_node(ND_EXPR_STMT);
    if (!block_head.next->next) return block_head.next;
    Node *block = new_node(ND_BLOCK);
    block->body = block_head.next;
    return block;
}

static bool is_label(Token *tok) {
    if (tok->kind != TK_IDENT) return false;
    if (equal(tok->next, ":")) {
        if (equal(tok, "case") || equal(tok, "default"))
            return false;
        return true;
    }
    return false;
}

static Node *stmt(Token **rest, Token *tok) {
    if (equal(tok, "return")) {
        Token *ret_tok = tok;
        Node *node = new_node(ND_RETURN);
        if (!equal(tok->next, ";")) {
            node->lhs = expr(&tok, tok->next);
            if (!current_return_ty || current_return_ty->kind == TY_VOID)
                error_at(ret_tok->loc, "void function should not return a value");
            if (!assignment_compatible(current_return_ty, node->lhs))
                error_at(ret_tok->loc, "incompatible return type");
        } else {
            tok = tok->next;
            if (current_return_ty && current_return_ty->kind != TY_VOID)
                error_at(ret_tok->loc, "non-void function should return a value");
        }
        *rest = skip(tok, ";");
        return node;
    }

    if (equal(tok, "break")) {
        *rest = skip(tok->next, ";");
        return new_node(ND_BREAK);
    }

    if (equal(tok, "continue")) {
        *rest = skip(tok->next, ";");
        return new_node(ND_CONTINUE);
    }

    if (equal(tok, "goto")) {
        tok = tok->next;
        if (tok->kind != TK_IDENT)
            error_at(tok->loc, "expected label name after 'goto'");
        Node *node = new_node(ND_GOTO);
        node->label_name = strndup(tok->loc, tok->len);
        node->goto_next = current_gotos;
        current_gotos = node;
        *rest = skip(tok->next, ";");
        return node;
    }

    if (equal(tok, "do")) {
        Node *node = new_node(ND_DO);
        node->then = stmt(&tok, tok->next);
        tok = skip(tok, "while");
        tok = skip(tok, "(");
        node->cond = expr(&tok, tok);
        tok = skip(tok, ")");
        *rest = skip(tok, ";");
        return node;
    }

    if (equal(tok, "switch")) {
        Node *node = new_node(ND_SWITCH);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        tok = skip(tok, ")");
        node->then = stmt(rest, tok);
        return node;
    }

    if (equal(tok, "case")) {
        if (tok->next->kind != TK_NUM)
            error_at(tok->next->loc, "expected integer constant after 'case'");
        Node *node = new_node(ND_CASE);
        node->val = tok->next->val;
        tok = skip(tok->next->next, ":");
        *rest = tok;
        return node;
    }

    if (equal(tok, "default")) {
        tok = skip(tok->next, ":");
        Node *node = new_node(ND_DEFAULT);
        *rest = tok;
        return node;
    }

    if (equal(tok, "if")) {
        Node *node = new_node(ND_IF);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        tok = skip(tok, ")");
        node->then = stmt(&tok, tok);
        if (equal(tok, "else"))
            node->els = stmt(&tok, tok->next);
        *rest = tok;
        return node;
    }

    if (equal(tok, "while")) {
        Node *node = new_node(ND_WHILE);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        tok = skip(tok, ")");
        node->then = stmt(&tok, tok);
        *rest = tok;
        return node;
    }

    if (equal(tok, "for")) {
        Node *node = new_node(ND_FOR);
        tok = skip(tok->next, "(");
        enter_scope();

        if (equal(tok, ";")) {
            tok = skip(tok, ";");
        } else if (is_decl_start(tok)) {
            bool is_s = consume(&tok, tok, "static");
            bool is_e = consume(&tok, tok, "extern");
            consume(&tok, tok, "register");
            consume(&tok, tok, "inline");
            node->init = declaration(&tok, tok, is_s, is_e);
        } else {
            node->init = new_node(ND_EXPR_STMT);
            node->init->lhs = expr(&tok, tok);
            tok = skip(tok, ";");
        }

        if (!equal(tok, ";"))
            node->cond = expr(&tok, tok);
        tok = skip(tok, ";");

        if (!equal(tok, ")"))
            node->inc = expr(&tok, tok);
        tok = skip(tok, ")");

        node->then = stmt(rest, tok);
        leave_scope();
        return node;
    }

    if (equal(tok, "{")) {
        enter_scope();
        Node head = {};
        Node *cur = &head;
        tok = tok->next;
        while (!equal(tok, "}")) {
            Node *n = stmt(&tok, tok);
            if (n->kind != ND_EXPR_STMT || n->lhs)
                cur = cur->next = n;
        }
        *rest = skip(tok, "}");
        Node *node = new_node(ND_BLOCK);
        node->body = head.next;
        leave_scope();
        return node;
    }

    if (equal(tok, "typedef")) {
        tok = tok->next;
        Type *basety = declspec(&tok, tok);
        if (!equal(tok, ";")) {
            for (;;) {
                Token *ident;
                Type *ty = declarator(&tok, tok, basety, &ident);
                push_typedef(ident, ty);
                if (!consume(&tok, tok, ","))
                    break;
            }
        }
        *rest = skip(tok, ";");
        return new_node(ND_EXPR_STMT);
    }

    // Labeled statement: ident ":"  stmt
    if (is_label(tok)) {
        Node *node = new_node(ND_LABEL);
        node->label_name = strndup(tok->loc, tok->len);
        node->unique_label = new_unique_name();
        node->label_next = current_labels;
        current_labels = node;
        tok = skip(tok->next, ":");
        node->lhs = stmt(rest, tok);
        return node;
    }

    // Declaration (with optional static/extern)
    if (is_decl_start(tok)) {
        bool is_s = consume(&tok, tok, "static");
        bool is_e = consume(&tok, tok, "extern");
        consume(&tok, tok, "register");
        consume(&tok, tok, "inline");
        return declaration(rest, tok, is_s, is_e);
    }

    Node *node = new_node(ND_EXPR_STMT);
    if (!equal(tok, ";"))
        node->lhs = expr(&tok, tok);
    *rest = skip(tok, ";");
    return node;
}

// expr = assign ("," assign)*   (comma operator)
static Node *expr(Token **rest, Token *tok) {
    Node *node = assign(&tok, tok);

    while (equal(tok, ","))
        node = new_binary(ND_COMMA, node, assign(&tok, tok->next));

    *rest = tok;
    return node;
}

static bool is_null_pointer_constant(Node *node) {
    add_type(node);
    return is_integer(node->ty) && node->kind == ND_NUM && node->val == 0;
}

static bool pointer_assignment_compatible(Type *dst, Type *src) {
    if (!dst || !src || dst->kind != TY_PTR)
        return false;

    // Function designators are assignable to compatible function pointers.
    if (src->kind == TY_FUNC)
        return dst->base && dst->base->kind == TY_FUNC &&
               type_compatible(dst->base, src);

    // Array expressions decay to pointers to their first element in value
    // contexts such as assignment, initialization, return and arguments.
    if (src->kind == TY_ARRAY)
        return type_compatible(dst->base, src->base) ||
               (dst->base && dst->base->kind == TY_VOID);

    if (src->kind != TY_PTR)
        return false;
    if (type_compatible(dst->base, src->base))
        return true;

    // C permits object pointers to convert to/from void*. Function pointers
    // deliberately do not participate in this conversion.
    bool dst_void = dst->base && dst->base->kind == TY_VOID;
    bool src_void = src->base && src->base->kind == TY_VOID;
    bool dst_func = dst->base && dst->base->kind == TY_FUNC;
    bool src_func = src->base && src->base->kind == TY_FUNC;
    return !dst_func && !src_func && (dst_void || src_void);
}

static bool assignment_compatible(Type *dst, Node *rhs) {
    add_type(rhs);
    Type *src = rhs->ty;

    if (!dst || !src || dst->kind == TY_ARRAY || dst->kind == TY_FUNC)
        return false;
    if (is_numeric(dst) && is_numeric(src))
        return true;

    // _Bool accepts any scalar value, including pointers/function designators.
    if (dst->kind == TY_BOOL &&
        (src->kind == TY_PTR || src->kind == TY_FUNC))
        return true;

    if (dst->kind == TY_PTR)
        return pointer_assignment_compatible(dst, src) ||
               is_null_pointer_constant(rhs);

    if (dst->kind == TY_STRUCT && src->kind == TY_STRUCT)
        return type_compatible(dst, src);

    return type_compatible(dst, src);
}

static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op) {
    add_type(lhs);
    if (!is_modifiable_lvalue(lhs))
        error_at(op->loc, "left operand is not a modifiable lvalue");
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(op->loc, "incompatible types in assignment");
    return new_binary(ND_ASSIGN, lhs, rhs);
}

static Type *decay_value_type(Type *ty) {
    if (!ty)
        return NULL;
    if (ty->kind == TY_ARRAY)
        return pointer_to(ty->base);
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    return ty;
}

static bool is_scalar_expr(Node *node) {
    add_type(node);
    Type *ty = decay_value_type(node->ty);
    return ty && (is_numeric(ty) || ty->kind == TY_PTR);
}

static bool pointer_pair_compatible(Type *a, Type *b, bool relational_only) {
    a = decay_value_type(a);
    b = decay_value_type(b);
    if (!a || !b || a->kind != TY_PTR || b->kind != TY_PTR)
        return false;

    if (type_compatible(a->base, b->base)) {
        if (!relational_only)
            return true;
        return a->base && a->base->kind != TY_VOID && a->base->kind != TY_FUNC;
    }

    if (relational_only)
        return false;

    bool a_void = a->base && a->base->kind == TY_VOID;
    bool b_void = b->base && b->base->kind == TY_VOID;
    bool a_func = a->base && a->base->kind == TY_FUNC;
    bool b_func = b->base && b->base->kind == TY_FUNC;
    return !a_func && !b_func && (a_void || b_void);
}

static bool equality_operands_compatible(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return true;

    Type *lt = decay_value_type(lhs->ty);
    Type *rt = decay_value_type(rhs->ty);
    bool lp = lt && lt->kind == TY_PTR;
    bool rp = rt && rt->kind == TY_PTR;

    if (lp && is_null_pointer_constant(rhs))
        return true;
    if (rp && is_null_pointer_constant(lhs))
        return true;
    return lp && rp && pointer_pair_compatible(lt, rt, false);
}

static bool relational_operands_compatible(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);
    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return true;
    return pointer_pair_compatible(lhs->ty, rhs->ty, true);
}

static Type *conditional_result_type(Node *then, Node *els, Token *question) {
    add_type(then);
    add_type(els);

    if (is_numeric(then->ty) && is_numeric(els->ty))
        return get_common_type(then->ty, els->ty);

    if (then->ty->kind == TY_VOID && els->ty->kind == TY_VOID)
        return ty_void;

    if (then->ty->kind == TY_STRUCT && els->ty->kind == TY_STRUCT &&
        type_compatible(then->ty, els->ty))
        return then->ty;

    Type *tt = decay_value_type(then->ty);
    Type *et = decay_value_type(els->ty);
    bool tp = tt && tt->kind == TY_PTR;
    bool ep = et && et->kind == TY_PTR;

    if (tp && is_null_pointer_constant(els))
        return tt;
    if (ep && is_null_pointer_constant(then))
        return et;

    if (tp && ep) {
        if (type_compatible(tt->base, et->base))
            return tt;

        bool t_void = tt->base && tt->base->kind == TY_VOID;
        bool e_void = et->base && et->base->kind == TY_VOID;
        bool t_func = tt->base && tt->base->kind == TY_FUNC;
        bool e_func = et->base && et->base->kind == TY_FUNC;
        if (!t_func && !e_func && (t_void || e_void))
            return pointer_to(ty_void);
    }

    error_at(question->loc, "incompatible conditional operands");
}

static Node *assign(Token **rest, Token *tok) {
    Node *node = ternary(&tok, tok);
    if (equal(tok, "=")) {
        Token *op = tok;
        node = new_checked_assign(node, assign(&tok, tok->next), op);
    }
    else if (equal(tok, "+="))
        node = new_compound_assign(ND_ADD_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "-="))
        node = new_compound_assign(ND_SUB_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "*="))
        node = new_compound_assign(ND_MUL_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "/="))
        node = new_compound_assign(ND_DIV_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "%="))
        node = new_compound_assign(ND_MOD_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "&="))
        node = new_compound_assign(ND_AND_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "|="))
        node = new_compound_assign(ND_OR_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "^="))
        node = new_compound_assign(ND_XOR_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, "<<="))
        node = new_compound_assign(ND_SHL_EQ, node, assign(&tok, tok->next));
    else if (equal(tok, ">>="))
        node = new_compound_assign(ND_SHR_EQ, node, assign(&tok, tok->next));
    *rest = tok;
    return node;
}

static Node *ternary(Token **rest, Token *tok) {
    Node *cond = logor(&tok, tok);
    if (!equal(tok, "?")) {
        *rest = tok;
        return cond;
    }

    Token *question = tok;
    if (!is_scalar_expr(cond))
        error_at(question->loc, "conditional expression requires scalar condition");

    Node *node = new_node(ND_TERNARY);
    node->cond = cond;
    tok = tok->next;
    node->then = expr(&tok, tok);
    tok = skip(tok, ":");
    node->els = ternary(rest, tok);
    node->ty = conditional_result_type(node->then, node->els, question);
    return node;
}

static Node *logor(Token **rest, Token *tok) {
    Node *node = logand(&tok, tok);
    while (equal(tok, "||")) {
        Token *op = tok;
        Node *rhs = logand(&tok, tok->next);
        if (!is_scalar_expr(node) || !is_scalar_expr(rhs))
            error_at(op->loc, "logical operator requires scalar operands");
        node = new_binary(ND_LOGOR, node, rhs);
    }
    *rest = tok;
    return node;
}

static Node *logand(Token **rest, Token *tok) {
    Node *node = bitor_expr(&tok, tok);
    while (equal(tok, "&&")) {
        Token *op = tok;
        Node *rhs = bitor_expr(&tok, tok->next);
        if (!is_scalar_expr(node) || !is_scalar_expr(rhs))
            error_at(op->loc, "logical operator requires scalar operands");
        node = new_binary(ND_LOGAND, node, rhs);
    }
    *rest = tok;
    return node;
}

static Node *bitor_expr(Token **rest, Token *tok) {
    Node *node = bitxor_expr(&tok, tok);
    while (equal(tok, "|"))
        node = new_binary(ND_BITOR, node, bitxor_expr(&tok, tok->next));
    *rest = tok;
    return node;
}

static Node *bitxor_expr(Token **rest, Token *tok) {
    Node *node = bitand_expr(&tok, tok);
    while (equal(tok, "^"))
        node = new_binary(ND_BITXOR, node, bitand_expr(&tok, tok->next));
    *rest = tok;
    return node;
}

static Node *bitand_expr(Token **rest, Token *tok) {
    Node *node = equality(&tok, tok);
    while (equal(tok, "&"))
        node = new_binary(ND_BITAND, node, equality(&tok, tok->next));
    *rest = tok;
    return node;
}

static Node *equality(Token **rest, Token *tok) {
    Node *node = relational(&tok, tok);
    for (;;) {
        if (equal(tok, "==") || equal(tok, "!=")) {
            Token *op = tok;
            NodeKind kind = equal(tok, "==") ? ND_EQ : ND_NE;
            Node *rhs = relational(&tok, tok->next);
            if (!equality_operands_compatible(node, rhs))
                error_at(op->loc, "invalid equality operands");
            node = new_binary(kind, node, rhs);
            continue;
        }
        *rest = tok;
        return node;
    }
}

static Node *shift(Token **rest, Token *tok) {
    Node *node = add(&tok, tok);
    for (;;) {
        if (equal(tok, "<<")) { node = new_binary(ND_SHL, node, add(&tok, tok->next)); continue; }
        if (equal(tok, ">>")) { node = new_binary(ND_SHR, node, add(&tok, tok->next)); continue; }
        *rest = tok;
        return node;
    }
}

static Node *relational(Token **rest, Token *tok) {
    Node *node = shift(&tok, tok);
    for (;;) {
        if (equal(tok, "<") || equal(tok, "<=") ||
            equal(tok, ">") || equal(tok, ">=")) {
            Token *op = tok;
            bool reverse = equal(tok, ">") || equal(tok, ">=");
            bool inclusive = equal(tok, "<=") || equal(tok, ">=");
            Node *rhs = shift(&tok, tok->next);
            if (!relational_operands_compatible(node, rhs))
                error_at(op->loc, "invalid relational operands");
            node = reverse ? new_binary(inclusive ? ND_LE : ND_LT, rhs, node)
                           : new_binary(inclusive ? ND_LE : ND_LT, node, rhs);
            continue;
        }
        *rest = tok;
        return node;
    }
}

static Node *add(Token **rest, Token *tok) {
    Node *node = mul(&tok, tok);
    for (;;) {
        if (equal(tok, "+")) { node = new_add(node, mul(&tok, tok->next)); continue; }
        if (equal(tok, "-")) { node = new_sub(node, mul(&tok, tok->next)); continue; }
        *rest = tok;
        return node;
    }
}

static Node *mul(Token **rest, Token *tok) {
    Node *node = unary(&tok, tok);
    for (;;) {
        if (equal(tok, "*")) { node = new_binary(ND_MUL, node, unary(&tok, tok->next)); continue; }
        if (equal(tok, "/")) { node = new_binary(ND_DIV, node, unary(&tok, tok->next)); continue; }
        if (equal(tok, "%")) { node = new_binary(ND_MOD, node, unary(&tok, tok->next)); continue; }
        *rest = tok;
        return node;
    }
}

static Node *unary(Token **rest, Token *tok) {
    if (equal(tok, "(") && is_typename(tok->next)) {
        tok = tok->next;
        Type *ty = type_name(&tok, tok);
        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC)
            error_at(tok->loc, "cast specifies non-scalar type");
        tok = skip(tok, ")");
        Node *node = new_unary(ND_CAST, unary(rest, tok));
        node->ty = ty;
        return node;
    }

    if (equal(tok, "+"))  return unary(rest, tok->next);
    if (equal(tok, "-"))  return new_binary(ND_SUB, new_num(0), unary(rest, tok->next));
    if (equal(tok, "&")) {
        Token *op = tok;
        return new_checked_addr(unary(rest, tok->next), op);
    }
    if (equal(tok, "*")) {
        Token *op = tok;
        return new_checked_deref(unary(rest, tok->next), op);
    }
    if (equal(tok, "!")) {
        Token *op = tok;
        Node *operand = unary(rest, tok->next);
        if (!is_scalar_expr(operand))
            error_at(op->loc, "logical not requires scalar operand");
        return new_unary(ND_NOT, operand);
    }
    if (equal(tok, "~"))  return new_unary(ND_BITNOT, unary(rest, tok->next));
    if (equal(tok, "++")) return new_inc_dec(ND_PRE_INC, unary(rest, tok->next));
    if (equal(tok, "--")) return new_inc_dec(ND_PRE_DEC, unary(rest, tok->next));

    return postfix(rest, tok);
}

static Node *indirect_funcall(Token **rest, Token *tok, Node *callee) {
    add_type(callee);

    Type *fty = NULL;
    if (callee->ty->kind == TY_FUNC)
        fty = callee->ty;
    else if (callee->ty->kind == TY_PTR && callee->ty->base &&
             callee->ty->base->kind == TY_FUNC)
        fty = callee->ty->base;

    if (!fty)
        error_at(tok->loc, "called object is not a function or function pointer");

    Node *node = new_node(ND_FUNCALL);
    node->funcname = NULL;
    node->lhs = callee;
    node->ty = fty->return_ty;
    tok = skip(tok, "(");

    Obj *expected = fty->params;
    bool variadic = fty->is_variadic;
    bool has_prototype = fty->has_prototype;
    Node head = {};
    Node *cur = &head;

    while (!equal(tok, ")")) {
        if (cur != &head)
            tok = skip(tok, ",");

        if (has_prototype && !expected && !variadic)
            error_at(tok->loc, "too many arguments");

        Node *arg = assign(&tok, tok);
        add_type(arg);

        if (expected) {
            if (!assignment_compatible(expected->ty, arg))
                error_at(tok->loc, "incompatible argument type");
            if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                arg->ty != expected->ty) {
                Node *cast = new_unary(ND_CAST, arg);
                cast->ty = expected->ty;
                arg = cast;
            }
            expected = expected->param_next;
        } else if (variadic) {
            Type *promoted = NULL;
            if (arg->ty->kind == TY_FLOAT)
                promoted = ty_double;
            else if (arg->ty->kind == TY_BOOL || arg->ty->kind == TY_CHAR ||
                     arg->ty->kind == TY_SHORT)
                promoted = ty_int;
            if (promoted) {
                Node *cast = new_unary(ND_CAST, arg);
                cast->ty = promoted;
                arg = cast;
            }
        }

        cur = cur->next = arg;
    }

    if (has_prototype && expected)
        error_at(tok->loc, "too few arguments");

    *rest = skip(tok, ")");
    node->args = head.next;
    return node;
}

static Node *postfix(Token **rest, Token *tok) {
    Node *node = primary(&tok, tok);

    for (;;) {
        // A call is a postfix operator in C, so the callee may be any
        // expression whose type is function or pointer-to-function. This
        // covers `(fp)(x)`, `(*fp)(x)`, `(&fn)(x)`, ternary/comma callees,
        // and deeper pointer chains after explicit dereference.
        if (equal(tok, "(")) {
            node = indirect_funcall(&tok, tok, node);
            continue;
        }

        if (equal(tok, "[")) {
            Node *idx = expr(&tok, tok->next);
            tok = skip(tok, "]");
            node = new_unary(ND_DEREF, new_add(node, idx));
            continue;
        }

        if (equal(tok, "++")) {
            node = new_inc_dec(ND_POST_INC, node);
            tok = tok->next;
            continue;
        }

        if (equal(tok, "--")) {
            node = new_inc_dec(ND_POST_DEC, node);
            tok = tok->next;
            continue;
        }

        if (equal(tok, ".")) {
            tok = tok->next;
            if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name");
            add_type(node);
            if (node->ty->kind != TY_STRUCT) error_at(tok->loc, "not a struct");
            if (node->ty->is_incomplete) error_at(tok->loc, "incomplete struct type");
            Member *mem = node->ty->members;
            for (; mem; mem = mem->next)
                if ((int)strlen(mem->name) == tok->len &&
                    !strncmp(mem->name, tok->loc, tok->len)) break;
            if (!mem) error_at(tok->loc, "unknown member");
            Node *n = new_node(ND_MEMBER);
            n->lhs = node; n->member = mem;
            tok = tok->next; node = n;
            continue;
        }

        if (equal(tok, "->")) {
            tok = tok->next;
            if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name");
            add_type(node);
            if (node->ty->kind != TY_PTR || node->ty->base->kind != TY_STRUCT)
                error_at(tok->loc, "not a pointer to struct");
            if (node->ty->base->is_incomplete)
                error_at(tok->loc, "incomplete struct type");
            Node *deref = new_unary(ND_DEREF, node);
            add_type(deref);
            Member *mem = deref->ty->members;
            for (; mem; mem = mem->next)
                if ((int)strlen(mem->name) == tok->len &&
                    !strncmp(mem->name, tok->loc, tok->len)) break;
            if (!mem) error_at(tok->loc, "unknown member");
            Node *n = new_node(ND_MEMBER);
            n->lhs = deref; n->member = mem;
            tok = tok->next; node = n;
            continue;
        }

        break;
    }
    *rest = tok;
    return node;
}

static Node *primary(Token **rest, Token *tok) {
    if (equal(tok, "(")) {
        Node *node = expr(&tok, tok->next);
        *rest = skip(tok, ")");
        return node;
    }

    if (equal(tok, "sizeof")) {
        tok = tok->next;
        if (equal(tok, "(") && is_typename(tok->next)) {
            tok = tok->next;
            Type *ty = type_name(&tok, tok);
            if (invalid_sizeof_type(ty))
                error_at(tok->loc, "invalid operand type for sizeof");
            *rest = skip(tok, ")");
            return new_num(ty->size);
        }
        Node *n = unary(rest, tok);
        add_type(n);
        if (invalid_sizeof_type(n->ty))
            error_at(tok->loc, "invalid operand type for sizeof");
        return new_num(n->ty->size);
    }

    if (tok->kind == TK_IDENT) {
        // Check for an enumeration constant visible in lexical scope.
        EnumConst *ec = find_enum_const(tok);
        if (ec) {
            *rest = tok->next;
            return new_num(ec->val);
        }

        // Function call
        if (equal(tok->next, "(")) {
            // Check if this is a variable (function pointer) or a direct call
            Obj *var = find_var(tok);

            if (var && !var->is_function) {
                // Indirect call through a function-pointer variable. If the
                // pointer carries a prototype, use it for scalar coercion and
                // default promotions of variadic arguments.
                Node *node = new_node(ND_FUNCALL);
                node->funcname = NULL; // NULL = indirect call
                node->lhs = new_var_node(var); // callee expression

                Type *fty = NULL;
                if (var->ty->kind == TY_PTR && var->ty->base &&
                    var->ty->base->kind == TY_FUNC) {
                    fty = var->ty->base;
                    node->ty = fty->return_ty;
                }
                tok = skip(tok->next, "(");

                Obj *expected = fty ? fty->params : NULL;
                bool variadic = fty && fty->is_variadic;
                bool has_prototype = fty && fty->has_prototype;
                Node head = {};
                Node *cur = &head;
                while (!equal(tok, ")")) {
                    if (cur != &head)
                        tok = skip(tok, ",");

                    if (has_prototype && !expected && !variadic)
                        error_at(tok->loc, "too many arguments");

                    Node *arg = assign(&tok, tok);
                    add_type(arg);

                    if (expected) {
                        if (!assignment_compatible(expected->ty, arg))
                            error_at(tok->loc, "incompatible argument type");
                        if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                            arg->ty != expected->ty) {
                            Node *cast = new_unary(ND_CAST, arg);
                            cast->ty = expected->ty;
                            arg = cast;
                        }
                        expected = expected->param_next;
                    } else if (variadic) {
                        Type *promoted = NULL;
                        if (arg->ty->kind == TY_FLOAT)
                            promoted = ty_double;
                        else if (arg->ty->kind == TY_BOOL || arg->ty->kind == TY_CHAR ||
                                 arg->ty->kind == TY_SHORT)
                            promoted = ty_int;
                        if (promoted) {
                            Node *cast = new_unary(ND_CAST, arg);
                            cast->ty = promoted;
                            arg = cast;
                        }
                    }

                    cur = cur->next = arg;
                }
                if (has_prototype && expected)
                    error_at(tok->loc, "too few arguments");

                *rest = skip(tok, ")");
                node->args = head.next;
                return node;
            }

            // Direct call
            Node *node = new_node(ND_FUNCALL);
            node->funcname = strndup(tok->loc, tok->len);
            if (var && var->is_function && var->ty->kind == TY_FUNC)
                node->ty = var->ty->return_ty;
            tok = skip(tok->next, "(");

            Obj *expected = (var && var->is_function) ? var->func_params : NULL;
            bool variadic = var && var->is_function && var->func_variadic;
            bool has_prototype = var && var->is_function && var->ty->kind == TY_FUNC &&
                                 var->ty->has_prototype;
            Node head = {};
            Node *cur = &head;
            while (!equal(tok, ")")) {
                if (cur != &head)
                    tok = skip(tok, ",");

                if (has_prototype && !expected && !variadic)
                    error_at(tok->loc, "too many arguments");

                Node *arg = assign(&tok, tok);
                add_type(arg);

                if (expected) {
                    if (!assignment_compatible(expected->ty, arg))
                        error_at(tok->loc, "incompatible argument type");
                    if (is_numeric(arg->ty) && is_numeric(expected->ty) &&
                        arg->ty != expected->ty) {
                        Node *cast = new_unary(ND_CAST, arg);
                        cast->ty = expected->ty;
                        arg = cast;
                    }
                    expected = expected->param_next;
                } else if (variadic) {
                    // C default argument promotions for the scalar subset.
                    Type *promoted = NULL;
                    if (arg->ty->kind == TY_FLOAT)
                        promoted = ty_double;
                    else if (arg->ty->kind == TY_BOOL || arg->ty->kind == TY_CHAR ||
                             arg->ty->kind == TY_SHORT)
                        promoted = ty_int;
                    if (promoted) {
                        Node *cast = new_unary(ND_CAST, arg);
                        cast->ty = promoted;
                        arg = cast;
                    }
                }

                cur = cur->next = arg;
            }
            if (has_prototype && expected)
                error_at(tok->loc, "too few arguments");

            *rest = skip(tok, ")");
            node->args = head.next;
            return node;
        }

        Obj *var = find_var(tok);
        if (!var)
            error_at(tok->loc, "undefined variable");
        Node *node = new_node(ND_VAR);
        node->var = var;
        *rest = tok->next;
        return node;
    }

    if (tok->kind == TK_STR) {
        Obj *var = calloc(1, sizeof(Obj));
        var->name = new_unique_name();
        var->ty = tok->ty;
        var->is_local = false;
        var->init_data = tok->str;
        var->next = globals;
        globals = var;

        Node *node = new_var_node(var);
        *rest = tok->next;
        return node;
    }

    if (tok->kind == TK_NUM) {
        Node *node = new_num(tok->val);
        if (tok->is_float) {
            node->fval = tok->fval;
            node->ty = tok->ty;
        }
        *rest = tok->next;
        return node;
    }

    error_at(tok->loc, "expected an expression");
    return NULL;
}

static Node *compound_stmt(Token **rest, Token *tok) {
    enter_scope();
    Node head = {};
    Node *cur = &head;

    while (!equal(tok, "}")) {
        Node *n = stmt(&tok, tok);
        if (n->kind != ND_EXPR_STMT || n->lhs)
            cur = cur->next = n;
    }

    *rest = skip(tok, "}");
    Node *node = new_node(ND_BLOCK);
    node->body = head.next;
    leave_scope();
    return node;
}

static void resolve_gotos(void) {
    for (Node *g = current_gotos; g; g = g->goto_next) {
        bool found = false;
        for (Node *l = current_labels; l; l = l->label_next) {
            if (!strcmp(g->label_name, l->label_name)) {
                g->unique_label = l->unique_label;
                found = true;
                break;
            }
        }
        if (!found)
            error("undefined label: %s", g->label_name);
    }
}

static bool type_compatible(Type *a, Type *b) {
    if (a == b)
        return true;
    if (!a || !b || a->kind != b->kind)
        return false;

    switch (a->kind) {
    case TY_CHAR:
    case TY_SHORT:
    case TY_INT:
    case TY_LONG:
        return a->is_unsigned == b->is_unsigned;
    case TY_PTR:
        return type_compatible(a->base, b->base);
    case TY_ARRAY:
        return type_compatible(a->base, b->base) &&
               (!a->array_len || !b->array_len || a->array_len == b->array_len);
    case TY_STRUCT:
        // Tagged records are completed in place, so pointer identity captures
        // C record-type identity. Distinct anonymous records are incompatible.
        return false;
    case TY_FUNC: {
        if (!type_compatible(a->return_ty, b->return_ty))
            return false;

        // An old-style f() declaration carries no parameter information. Keep
        // it compatible with a real prototype so the stronger declaration can
        // be retained, matching the compiler's existing C11-era behavior.
        if (!a->has_prototype || !b->has_prototype)
            return true;
        if (a->is_variadic != b->is_variadic)
            return false;

        Obj *pa = a->params;
        Obj *pb = b->params;
        while (pa && pb) {
            if (!type_compatible(pa->ty, pb->ty))
                return false;
            pa = pa->param_next;
            pb = pb->param_next;
        }
        return !pa && !pb;
    }
    default:
        return true;
    }
}

static Type *composite_redecl_type(Type *old_ty, Type *new_ty) {
    if (old_ty->kind == TY_ARRAY && old_ty->array_len == 0 && new_ty->array_len)
        return new_ty;
    if (old_ty->kind == TY_FUNC && !old_ty->has_prototype && new_ty->has_prototype)
        return new_ty;
    return old_ty;
}

static Obj *find_global_symbol(const char *name) {
    for (Obj *var = globals; var; var = var->next)
        if (!strcmp(var->name, name))
            return var;
    return NULL;
}

static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->init_vals_count > 0 || var->init_data;
}

static Obj *register_global_symbol(Token *ident, Type *ty, bool is_static,
                                   bool is_extern) {
    char *name = strndup(ident->loc, ident->len);
    Obj *var = find_global_symbol(name);
    if (var) {
        if (var->is_function)
            error_at(ident->loc, "'%s' redeclared as different kind of symbol", name);
        if (!type_compatible(var->ty, ty))
            error_at(ident->loc, "conflicting types for '%s'", name);
        if (is_static && !var->is_static)
            error_at(ident->loc, "static declaration of '%s' follows non-static declaration", name);

        var->ty = composite_redecl_type(var->ty, ty);
        if (var->is_static)
            is_static = true;
        var->is_static = is_static;
        if (!is_extern)
            var->is_extern = false;
        return var;
    }

    var = calloc(1, sizeof(Obj));
    var->name = name;
    var->ty = ty;
    var->is_local = false;
    var->is_static = is_static;
    var->is_extern = is_extern;
    var->next = globals;
    globals = var;
    return var;
}

// Register a function symbol as a global Obj so it can be used as a value
// (e.g. function pointer assignment: fp = add;). Redeclarations are checked
// against the complete recursive function type before metadata is refreshed.
static void register_function_symbol(char *name, Type *return_ty, bool is_static,
                                     Obj *params, bool is_variadic,
                                     bool has_prototype, bool is_definition) {
    Type *fty = func_type(return_ty);
    fty->params = params;
    fty->is_variadic = is_variadic;
    fty->has_prototype = has_prototype;

    Obj *var = find_global_symbol(name);
    if (var) {
        if (!var->is_function)
            error("'%s' redeclared as different kind of symbol", name);
        if (!type_compatible(var->ty, fty))
            error("conflicting types for function '%s'", name);
        if (is_static && !var->is_static)
            error("static declaration of '%s' follows non-static declaration", name);
        if (is_definition && var->is_defined)
            error("redefinition of function '%s'", name);

        var->ty = composite_redecl_type(var->ty, fty);
        var->func_params = var->ty->params;
        var->func_variadic = var->ty->is_variadic;
        var->is_static = var->is_static || is_static;
        var->is_defined = var->is_defined || is_definition;
        return;
    }

    Obj *fn_obj = calloc(1, sizeof(Obj));
    fn_obj->name = strdup(name);
    fn_obj->ty = fty;
    fn_obj->func_params = fty->params;
    fn_obj->func_variadic = fty->is_variadic;
    fn_obj->is_local = false;
    fn_obj->is_function = true;
    fn_obj->is_static = is_static;
    fn_obj->is_defined = is_definition;
    fn_obj->next = globals;
    globals = fn_obj;
}

// program = (function | global-var | typedef)*
Program *parse(Token *tok) {
    globals = NULL;
    Function head = {};
    Function *cur = &head;

    current_scope = calloc(1, sizeof(Scope));

    while (tok->kind != TK_EOF) {
        // Top-level typedef
        if (equal(tok, "typedef")) {
            tok = tok->next;
            Type *basety = declspec(&tok, tok);
            if (!equal(tok, ";")) {
                for (;;) {
                    Token *ident;
                    Type *ty = declarator(&tok, tok, basety, &ident);
                    push_typedef(ident, ty);
                    if (!consume(&tok, tok, ","))
                        break;
                }
            }
            tok = skip(tok, ";");
            continue;
        }

        // Storage class specifiers
        bool is_static = consume(&tok, tok, "static");
        bool is_extern = consume(&tok, tok, "extern");
        consume(&tok, tok, "inline");

        Type *basety = declspec(&tok, tok);

        // Standalone type declaration
        if (consume(&tok, tok, ";"))
            continue;

        Token *ident;
        Type *ty = declarator(&tok, tok, basety, &ident);

        if (ty->kind == TY_FUNC) {
            char *name = strndup(ident->loc, ident->len);

            // Register the declaration before parsing a body so recursion and
            // function-address expressions inside the definition see it.
            register_function_symbol(name, ty->return_ty, is_static,
                                     ty->params, ty->is_variadic, ty->has_prototype,
                                     !equal(tok, ";"));

            // Prototype only: the recursive declarator has already consumed
            // the complete parameter list.
            if (consume(&tok, tok, ";"))
                continue;

            locals = NULL;
            current_gotos = NULL;
            current_labels = NULL;
            enter_scope();

            Obj param_head = {};
            Obj *pcur = &param_head;
            for (Obj *meta = ty->params; meta; meta = meta->param_next) {
                if (!meta->name)
                    error_at(ident->loc, "parameter name omitted in function definition");
                Obj *var = create_lvar(meta->name);
                var->ty = meta->ty;
                pcur = pcur->param_next = var;
            }

            tok = skip(tok, "{");

            Function *fn = calloc(1, sizeof(Function));
            fn->name = name;
            fn->params = param_head.param_next;
            fn->return_ty = ty->return_ty;
            fn->is_static = is_static;
            fn->is_variadic = ty->is_variadic;

            Type *saved_return_ty = current_return_ty;
            current_return_ty = ty->return_ty;
            Node *block = compound_stmt(&tok, tok);
            current_return_ty = saved_return_ty;
            fn->body = block->body;
            fn->locals = locals;

            resolve_gotos();
            fn->gotos = current_gotos;
            fn->labels = current_labels;

            leave_scope();
            cur = cur->next = fn;
        } else {
            // Global variable(s) (possibly with initializer)
            for (;;) {
                if (!is_extern && is_incomplete_object_type(ty))
                    error_at(ident->loc, "variable has incomplete type");

                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);
                ty = var->ty;

                if (equal(tok, "=") && object_has_initializer(var))
                    error_at(ident->loc, "redefinition of global '%s'", var->name);

                if (consume(&tok, tok, "=")) {
                    if (equal(tok, "{")) {
                        tok = tok->next;
                        int cap = 16, cnt = 0;
                        int64_t *vals = calloc(cap, sizeof(int64_t));
                        while (!equal(tok, "}")) {
                            if (cnt > 0) tok = skip(tok, ",");
                            if (equal(tok, "}")) break;
                            if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                            vals[cnt++] = parse_const_int(&tok, tok);
                        }
                        tok = skip(tok, "}");

                        if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                            ty = array_of(ty->base, cnt);
                            var->ty = ty;
                        }

                        var->init_vals = vals;
                        var->init_vals_count = cnt;
                    } else if (tok->kind == TK_STR) {
                        // String initializer: char s[] = "hello";
                        var->init_data = tok->str;
                        if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                            ty = array_of(ty->base, tok->ty->array_len);
                            var->ty = ty;
                        }
                        tok = tok->next;
                    } else {
                        if (is_flonum(ty))
                            var->finit_val = parse_const_double(&tok, tok);
                        else
                            var->init_val = parse_const_int(&tok, tok);
                        var->has_init_val = true;
                    }
                }

                if (!consume(&tok, tok, ","))
                    break;
                ty = declarator(&tok, tok, basety, &ident);
            }
            tok = skip(tok, ";");
        }
    }

    Program *prog = calloc(1, sizeof(Program));
    prog->globals = globals;
    prog->fns = head.next;
    return prog;
}
