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

static bool type_compatible(Type *a, Type *b);
static Type *composite_redecl_type(Type *old_ty, Type *new_ty);
static Obj *find_global_symbol(const char *name);

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

static VarScope *find_var_name_in_scope(Scope *scope, const char *name) {
    if (!scope)
        return NULL;
    for (VarScope *vs = scope->vars; vs; vs = vs->next)
        if (!strcmp(vs->name, name))
            return vs;
    return NULL;
}

static TypeDef *find_typedef_name_in_scope(Scope *scope, const char *name) {
    if (!scope)
        return NULL;
    for (TypeDef *td = scope->typedefs; td; td = td->next)
        if (!strcmp(td->name, name))
            return td;
    return NULL;
}

static EnumConst *find_enum_name_in_scope(Scope *scope, const char *name) {
    if (!scope)
        return NULL;
    for (EnumConst *ec = scope->enum_consts; ec; ec = ec->next)
        if (!strcmp(ec->name, name))
            return ec;
    return NULL;
}

static void bind_var_in_current_scope(char *name, Obj *var, bool allow_same) {
    if (find_typedef_name_in_scope(current_scope, name) ||
        find_enum_name_in_scope(current_scope, name))
        error("ordinary identifier '%s' conflicts with typedef or enumerator", name);

    VarScope *old = find_var_name_in_scope(current_scope, name);
    if (old) {
        if (allow_same && old->var == var)
            return;
        error("redefinition of ordinary identifier '%s'", name);
    }

    VarScope *vs = calloc(1, sizeof(VarScope));
    vs->name = name;
    vs->var = var;
    vs->next = current_scope->vars;
    current_scope->vars = vs;
}

// Typedef names, object/function identifiers and enumeration constants share
// C's ordinary identifier namespace. A binding in a nearer lexical scope hides
// every outer binding of the same namespace, regardless of its kind.
static TypeDef *find_typedef(Token *tok) {
    for (Scope *scope = current_scope; scope; scope = scope->parent) {
        for (VarScope *vs = scope->vars; vs; vs = vs->next)
            if (token_matches_name(tok, vs->name))
                return NULL;
        for (EnumConst *ec = scope->enum_consts; ec; ec = ec->next)
            if (token_matches_name(tok, ec->name))
                return NULL;
        for (TypeDef *td = scope->typedefs; td; td = td->next)
            if (token_matches_name(tok, td->name))
                return td;
    }
    return NULL;
}

static void push_typedef(Token *ident, Type *ty) {
    char *name = strndup(ident->loc, ident->len);
    if (find_var_name_in_scope(current_scope, name) ||
        find_enum_name_in_scope(current_scope, name))
        error_at(ident->loc, "typedef name conflicts with ordinary identifier");

    TypeDef *old = find_typedef_name_in_scope(current_scope, name);
    if (old) {
        if (!type_compatible(old->ty, ty))
            error_at(ident->loc, "conflicting typedef for '%s'", name);
        free(name);
        return;
    }

    TypeDef *td = calloc(1, sizeof(TypeDef));
    td->name = name;
    td->ty = ty;
    td->next = current_scope->typedefs;
    current_scope->typedefs = td;
}

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

static void push_enum_const(Token *ident, int64_t val) {
    char *name = strndup(ident->loc, ident->len);
    if (find_var_name_in_scope(current_scope, name) ||
        find_typedef_name_in_scope(current_scope, name) ||
        find_enum_name_in_scope(current_scope, name))
        error_at(ident->loc, "redefinition of ordinary identifier '%s'", name);

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
typedef struct {
    bool is_auto;
    bool is_static;
    bool is_extern;
    bool is_register;
    bool is_inline;
    bool is_noreturn;
    int storage_class_count;
    int align;
} DeclAttrs;

static Type *declspec(Token **rest, Token *tok);
static Type *declspec_with_attrs(Token **rest, Token *tok, DeclAttrs *attrs);
static int validate_requested_alignment(Type *ty, int requested, Token *at);
static void apply_object_alignment(Obj *var, Type *ty, int requested, Token *at);
static Type *declarator_impl(Token **rest, Token *tok, Type *ty, Token **ident,
                             bool allow_abstract, bool parameter_declarator);
static Type *type_suffix(Token **rest, Token *tok, Type *ty,
                         bool allow_parameter_array_syntax);
static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident);
static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident);
static Type *type_name(Token **rest, Token *tok);
static bool type_compatible(Type *a, Type *b);
static bool type_compatible_ignoring_top_qual(Type *a, Type *b);
static bool assignment_compatible(Type *dst, Node *rhs);
static bool is_scalar_expr(Node *node);
static Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at);
static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op);

static Type *current_return_ty;
static bool current_function_variadic;

typedef struct CaseValue CaseValue;
struct CaseValue {
    int64_t val;
    CaseValue *next;
};

typedef struct SwitchContext SwitchContext;
struct SwitchContext {
    Type *ty;
    CaseValue *cases;
    bool has_default;
    SwitchContext *prev;
};

static SwitchContext *current_switch;
static int current_loop_depth;

static bool is_typename(Token *tok) {
    if (equal(tok, "int") || equal(tok, "char") || equal(tok, "void") ||
        equal(tok, "enum") || equal(tok, "struct") || equal(tok, "union") ||
        equal(tok, "short") || equal(tok, "long") || equal(tok, "signed") ||
        equal(tok, "unsigned") || equal(tok, "const") ||
        equal(tok, "volatile") || equal(tok, "restrict") ||
        equal(tok, "_Bool") || equal(tok, "float") || equal(tok, "double"))
        return true;
    return find_typedef(tok) != NULL;
}

// Check if the current position starts a declaration
// (storage-class-specifier | type-qualifier | type-name)
static bool is_decl_start(Token *tok) {
    if (is_typename(tok)) return true;
    if (equal(tok, "auto") || equal(tok, "static") || equal(tok, "extern")) return true;
    if (equal(tok, "const") || equal(tok, "volatile") || equal(tok, "restrict")) return true;
    if (equal(tok, "register") || equal(tok, "inline")) return true;
    if (equal(tok, "_Alignas") || equal(tok, "_Noreturn")) return true;
    return false;
}

// Find a variable by name, respecting block scope.
static Obj *find_var(Token *tok) {
    for (Scope *sc = current_scope; sc; sc = sc->parent) {
        for (VarScope *vs = sc->vars; vs; vs = vs->next)
            if (token_matches_name(tok, vs->name))
                return vs->var;
        for (TypeDef *td = sc->typedefs; td; td = td->next)
            if (token_matches_name(tok, td->name))
                return NULL;
        for (EnumConst *ec = sc->enum_consts; ec; ec = ec->next)
            if (token_matches_name(tok, ec->name))
                return NULL;
    }
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

static Node *new_size_t_num(int64_t val) {
    Node *node = new_node(ND_NUM);
    node->val = val;
    // The x86-64 SysV target uses the LP64 data model, so size_t is
    // represented by unsigned long.
    node->ty = ty_ulong;
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

static bool type_has_const_subobject(Type *ty) {
    if (!ty)
        return false;
    if (ty->is_const)
        return true;
    if (ty->kind == TY_ARRAY)
        return type_has_const_subobject(ty->base);
    if (ty->kind == TY_STRUCT) {
        for (Member *m = ty->members; m; m = m->next)
            if (type_has_const_subobject(m->ty))
                return true;
    }
    return false;
}

static bool is_modifiable_lvalue(Node *node) {
    if (!is_lvalue(node))
        return false;

    Type *ty = node->ty;
    if (!ty || ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
        ty->kind == TY_VOID || ty->is_incomplete ||
        type_has_const_subobject(ty))
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
        if (!type_compatible_ignoring_top_qual(lp->base, rp->base))
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
    bind_var_in_current_scope(name, var, false);
    var->next = locals;
    locals = var;
    return var;
}


static bool supported_record_abi(Type *ty) {
    SysVAbiClass classes[2];
    return ty && ty->kind == TY_STRUCT &&
           (sysv_record_is_memory(ty) || sysv_classify_record(ty, classes) > 0);
}

// Aggregate expressions are represented by an address in the backend. Every
// by-value record call therefore owns an anonymous local result object: small
// records are materialized from return registers, while MEMORY-class callees
// receive that object's address directly as their hidden sret destination.
static void prepare_record_call_result(Node *node) {
    if (!current_return_ty || !node || !supported_record_abi(node->ty))
        return;

    Obj *buf = create_lvar(new_unique_name());
    buf->ty = node->ty;
    node->ret_buffer = buf;
}

// Create a static local variable (allocated as a global with unique name,
// but scoped locally).
static Obj *create_static_lvar(char *name) {
    static int id = 0;
    char *unique = calloc(1, strlen(name) + 30);
    sprintf(unique, ".Lstatic.%d.%s", id++, name);

    Obj *var = calloc(1, sizeof(Obj));
    var->name = unique;
    var->is_local = false;
    var->is_static = true;
    bind_var_in_current_scope(name, var, false);
    var->next = globals;
    globals = var;
    return var;
}

static void check_oldstyle_definition_redeclaration(Obj *old, Type *new_ty,
                                                    bool new_is_definition,
                                                    const char *name) {
    if (!old || !old->is_function || !old->ty || old->ty->kind != TY_FUNC ||
        !new_ty || new_ty->kind != TY_FUNC)
        return;

    // This compiler does not implement identifier-list definitions, so an
    // unprototyped `f(){...}` definition has exactly zero parameters.
    if (new_is_definition && !old->is_defined && !new_ty->has_prototype &&
        old->ty->has_prototype && old->ty->params)
        error("function definition of '%s' has no parameters but prior prototype does", name);

    if (!new_is_definition && old->is_defined && !old->ty->has_prototype &&
        new_ty->has_prototype && new_ty->params)
        error("prototype for '%s' declares parameters after a no-parameter definition", name);
}

// Create a block-scope declaration with linkage. A prior file-scope or earlier
// block-scope extern declaration is reused when compatible, but the lexical
// binding itself belongs only to the current block.
static Obj *create_extern_ref(char *name, Type *ty) {
    if (find_typedef_name_in_scope(current_scope, name) ||
        find_enum_name_in_scope(current_scope, name))
        error("extern declaration of '%s' conflicts with ordinary identifier", name);

    bool wants_function = ty->kind == TY_FUNC;
    VarScope *same_scope = find_var_name_in_scope(current_scope, name);
    if (same_scope) {
        Obj *old = same_scope->var;
        if (old->is_local || strcmp(old->name, name) ||
            old->is_function != wants_function)
            error("conflicting block-scope declaration of '%s'", name);
        if (wants_function)
            check_oldstyle_definition_redeclaration(old, ty, false, name);
        if (!type_compatible(old->ty, ty))
            error("conflicting block-scope declaration of '%s'", name);
        old->ty = composite_redecl_type(old->ty, ty);
        return old;
    }

    Obj *var = find_global_symbol(name);
    if (var) {
        if (var->is_function != wants_function)
            error("'%s' redeclared as different kind of symbol", name);
        if (wants_function)
            check_oldstyle_definition_redeclaration(var, ty, false, name);
        if (!type_compatible(var->ty, ty))
            error("conflicting types for '%s'", name);
        var->ty = composite_redecl_type(var->ty, ty);
    } else {
        var = calloc(1, sizeof(Obj));
        var->name = name;
        var->ty = ty;
        var->is_local = false;
        var->is_extern = true;
        var->is_function = wants_function;
        var->next = globals;
        globals = var;
    }

    bind_var_in_current_scope(name, var, false);
    return var;
}

static bool is_incomplete_object_type(Type *ty) {
    if (!ty)
        return false;
    if (ty->kind == TY_STRUCT)
        return ty->is_incomplete;
    if (ty->kind == TY_ARRAY)
        return ty->array_len == 0 || is_incomplete_object_type(ty->base);
    return false;
}

static bool is_unknown_bound_array_with_complete_element(Type *ty) {
    return ty && ty->kind == TY_ARRAY && ty->array_len == 0 &&
           !is_incomplete_object_type(ty->base);
}

static Type *new_record_type(bool is_union) {
    Type *ty = calloc(1, sizeof(Type));
    ty->kind = TY_STRUCT;
    ty->align = 1;
    ty->is_incomplete = true;
    ty->is_union = is_union;
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
            Type *ty = new_record_type(is_union);
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
            ty = new_record_type(is_union);
            push_tag(tag_name, ty, tag_kind);
        }
    } else {
        ty = new_record_type(is_union);
    }

    tok = skip(tok, "{");

    Member head = {};
    Member *cur = &head;
    bool has_flexible_member = false;
    while (!equal(tok, "}")) {
        DeclAttrs attrs = {};
        Type *basety = declspec_with_attrs(&tok, tok, &attrs);
        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||
            attrs.is_inline || attrs.is_noreturn)
            error_at(tok->loc, "storage/function specifier is not allowed on a record member");
        for (bool first = true; !consume(&tok, tok, ";"); first = false) {
            if (!first)
                tok = skip(tok, ",");

            Token *ident;
            Type *mty = declarator(&tok, tok, basety, &ident);
            if (mty->kind == TY_VOID)
                error_at(ident->loc, "record member cannot have void type");
            if (mty->kind == TY_FUNC)
                error_at(ident->loc, "record member cannot have function type");
            bool flexible = mty->kind == TY_ARRAY && mty->array_len == 0;

            if (flexible) {
                if (is_union)
                    error_at(ident->loc, "flexible array member is not allowed in a union");
                if (!head.next)
                    error_at(ident->loc,
                             "flexible array member requires a preceding named member");
                if (!equal(tok, ";") || !equal(tok->next, "}"))
                    error_at(ident->loc, "flexible array member must be the last member");
                has_flexible_member = true;
            } else {
                if (is_incomplete_object_type(mty))
                    error_at(ident->loc, "field has incomplete type");
                if (mty->kind == TY_STRUCT && mty->has_flexible_array_member)
                    error_at(ident->loc,
                             "record containing a flexible array member cannot be embedded");
            }

            Member *m = calloc(1, sizeof(Member));
            m->name = strndup(ident->loc, ident->len);
            m->ty = mty;
            m->align = validate_requested_alignment(mty, attrs.align, ident);
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
            int ma = m->align > 0 ? m->align : (m->ty->align > 0 ? m->ty->align : 1);
            if (ma > align)
                align = ma;
            m->offset = 0;
        }
        ty->size = align_up(size, align);
    } else {
        int offset = 0;
        for (Member *m = head.next; m; m = m->next) {
            int ma = m->align > 0 ? m->align : (m->ty->align > 0 ? m->ty->align : 1);
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
    ty->is_union = is_union;
    ty->has_flexible_array_member = has_flexible_member;
    ty->is_incomplete = false;
    for (Type *q = ty->qual_next; q; q = q->qual_next) {
        q->size = ty->size;
        q->align = ty->align;
        q->members = ty->members;
        q->is_union = ty->is_union;
        q->has_flexible_array_member = ty->has_flexible_array_member;
        q->is_incomplete = false;
    }
    *rest = tok;
    return ty;
}

static int64_t cast_const_integer(int64_t val, Type *ty) {
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

        Token *enumerator = tok;
        tok = tok->next;

        if (consume(&tok, tok, "=")) {
            Node *value = ternary(&tok, tok);
            val = eval_const_expr(value);
        }

        push_enum_const(enumerator, val++);

        if (consume(&tok, tok, ","))
            continue;
        if (!equal(tok, "}"))
            error_at(tok->loc, "expected ',' or '}' in enum definition");
    }

    *rest = skip(tok, "}");
    return ty_int;
}

static int parse_alignment_specifier(Token **rest, Token *tok) {
    Token *kw = tok;
    tok = skip(tok->next, "(");
    int align = 0;

    if (is_typename(tok) || equal(tok, "const") || equal(tok, "volatile") ||
        equal(tok, "restrict")) {
        Type *aty = type_name(&tok, tok);
        if (!aty || aty->kind == TY_VOID || aty->kind == TY_FUNC ||
            is_incomplete_object_type(aty))
            error_at(kw->loc, "_Alignas type must be a complete object type");
        align = aty->align > 0 ? aty->align : 1;
    } else {
        Node *expr_node = ternary(&tok, tok);
        add_type(expr_node);
        if (!is_integer(expr_node->ty))
            error_at(kw->loc, "_Alignas requires an integer constant expression or type name");
        int64_t raw = eval_const_expr(expr_node);
        if (expr_node->ty->is_unsigned) {
            uint64_t value = (uint64_t)cast_const_integer(raw, expr_node->ty);
            if (value > INT32_MAX)
                error_at(kw->loc, "_Alignas value is out of range");
            align = (int)value;
        } else {
            int64_t value = cast_const_integer(raw, expr_node->ty);
            if (value < 0 || value > INT32_MAX)
                error_at(kw->loc, "_Alignas value is out of range");
            align = (int)value;
        }
    }

    tok = skip(tok, ")");
    if (align != 0 && ((align & (align - 1)) != 0 || align > 16))
        error_at(kw->loc, "unsupported _Alignas value; expected 0 or a power of two up to 16");
    *rest = tok;
    return align;
}

static int validate_requested_alignment(Type *ty, int requested, Token *at) {
    if (!requested)
        return 0;
    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)
        error_at(at->loc, "_Alignas may only be applied to an object type");
    int natural = ty->align > 0 ? ty->align : 1;
    if (requested < natural)
        error_at(at->loc, "_Alignas cannot weaken the natural alignment");
    return requested;
}

static void apply_object_alignment(Obj *var, Type *ty, int requested, Token *at) {
    requested = validate_requested_alignment(ty, requested, at);
    if (!requested)
        return;
    if (var->align && var->align != requested)
        error_at(at->loc, "conflicting _Alignas requirements for '%s'", var->name);
    var->align = requested;
}

static bool is_restrict_qualifiable_type(Type *ty) {
    if (!ty)
        return false;
    if (ty->kind == TY_ARRAY)
        return is_restrict_qualifiable_type(ty->base);
    return ty->kind == TY_PTR && ty->base && ty->base->kind != TY_FUNC;
}

static void note_storage_class(DeclAttrs *attrs, Token *tok) {
    if (!attrs)
        error_at(tok->loc,
                 "storage class specifier is not allowed in this declaration context");
    attrs->storage_class_count++;
    if (attrs->storage_class_count > 1)
        error_at(tok->loc, "multiple storage class specifiers in one declaration");
}

typedef struct {
    Token *first;
    int n_bool;
    int n_float;
    int n_double;
    int n_char;
    int n_void;
    int n_short;
    int n_int;
    int n_long;
    int n_named;
} TypeSpecState;

static void mark_type_specifier(TypeSpecState *state, Token *tok) {
    if (!state->first)
        state->first = tok;
}

static void note_type_specifier(TypeSpecState *state, Token *tok, int *counter) {
    mark_type_specifier(state, tok);
    (*counter)++;
}

static void invalid_type_specifier_set(TypeSpecState *state) {
    error_at(state->first->loc, "invalid type specifier combination");
}

static void validate_type_specifier_set(TypeSpecState *state,
                                        bool saw_signed, bool saw_unsigned) {
    if (!state->first)
        return; // Preserve this compiler's existing implicit-int behavior.

    if (state->n_bool > 1 || state->n_float > 1 || state->n_double > 1 ||
        state->n_char > 1 || state->n_void > 1 || state->n_short > 1 ||
        state->n_int > 1 || state->n_long > 2 || state->n_named > 1)
        invalid_type_specifier_set(state);

    bool has_sign = saw_signed || saw_unsigned;
    int integer_specs = state->n_short + state->n_int + state->n_long;
    int primitive_specs = state->n_bool + state->n_float + state->n_double +
                          state->n_char + state->n_void + integer_specs;

    if (state->n_named) {
        if (primitive_specs || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_void) {
        if (primitive_specs != 1 || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_bool) {
        if (primitive_specs != 1 || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_char) {
        if (state->n_float || state->n_double || state->n_void || state->n_bool ||
            integer_specs)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_float) {
        if (primitive_specs != 1 || has_sign)
            invalid_type_specifier_set(state);
        return;
    }

    if (state->n_double) {
        if (state->n_bool || state->n_float || state->n_char || state->n_void ||
            state->n_short || state->n_int || has_sign || state->n_long > 1)
            invalid_type_specifier_set(state);
        if (state->n_long == 1)
            error_at(state->first->loc, "long double is not supported by this target");
        return;
    }

    // Remaining legal spellings are the signed/unsigned integer family:
    // [signed|unsigned] [short|long|long long] [int], in any order.
    if (state->n_short && state->n_long)
        invalid_type_specifier_set(state);
}

static Type *declspec_impl(Token **rest, Token *tok, DeclAttrs *attrs) {
    Type *ty = NULL;
    bool is_const = false;
    bool is_volatile = false;
    bool is_restrict = false;
    Token *restrict_tok = NULL;
    TypeSpecState specs = {};
    bool saw_signed = false;
    bool saw_unsigned = false;
    bool saw_non_signable_type = false;
    bool saw_typedef_type = false;
    Token *sign_spec = NULL;

    while (is_decl_start(tok)) {
        if (equal(tok, "_Alignas")) {
            if (!attrs)
                error_at(tok->loc, "_Alignas is not allowed in this declaration context");
            int a = parse_alignment_specifier(&tok, tok);
            if (a > attrs->align)
                attrs->align = a;
            continue;
        }
        if (consume(&tok, tok, "const")) {
            is_const = true;
            continue;
        }
        if (consume(&tok, tok, "volatile")) {
            is_volatile = true;
            continue;
        }
        Token *qual_tok = tok;
        if (consume(&tok, tok, "restrict")) {
            is_restrict = true;
            if (!restrict_tok)
                restrict_tok = qual_tok;
            continue;
        }
        Token *storage_tok = tok;
        if (consume(&tok, tok, "auto")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_auto = true;
            continue;
        }
        storage_tok = tok;
        if (consume(&tok, tok, "register")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_register = true;
            continue;
        }
        Token *inline_tok = tok;
        if (consume(&tok, tok, "inline")) {
            if (!attrs)
                error_at(inline_tok->loc,
                         "inline is only allowed in a function declaration");
            attrs->is_inline = true;
            continue;
        }
        Token *noreturn_tok = tok;
        if (consume(&tok, tok, "_Noreturn")) {
            if (!attrs)
                error_at(noreturn_tok->loc,
                         "_Noreturn is only allowed in a function declaration");
            attrs->is_noreturn = true;
            continue;
        }
        storage_tok = tok;
        if (consume(&tok, tok, "static")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_static = true;
            continue;
        }
        storage_tok = tok;
        if (consume(&tok, tok, "extern")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_extern = true;
            continue;
        }

        Token *base_tok = tok;
        if (consume(&tok, tok, "_Bool")) {
            note_type_specifier(&specs, base_tok, &specs.n_bool);
            saw_non_signable_type = true;
            ty = ty_bool;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "float")) {
            note_type_specifier(&specs, base_tok, &specs.n_float);
            saw_non_signable_type = true;
            ty = ty_float;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "double")) {
            note_type_specifier(&specs, base_tok, &specs.n_double);
            saw_non_signable_type = true;
            ty = ty_double;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "char")) {
            note_type_specifier(&specs, base_tok, &specs.n_char);
            if (saw_unsigned || (ty && ty->is_unsigned))
                ty = ty_uchar;
            else if (saw_signed)
                ty = ty_schar;
            else
                ty = ty_char;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "void")) {
            note_type_specifier(&specs, base_tok, &specs.n_void);
            saw_non_signable_type = true;
            ty = ty_void;
            continue;
        }
        base_tok = tok;
        if (consume(&tok, tok, "short")) {
            note_type_specifier(&specs, base_tok, &specs.n_short);
            ty = (ty && ty->is_unsigned) ? ty_ushort : ty_short;
            continue;
        }

        Token *long_tok = tok;
        if (consume(&tok, tok, "long")) {
            note_type_specifier(&specs, long_tok, &specs.n_long);
            bool already_long = ty == ty_long || ty == ty_ulong;
            bool already_llong = ty == ty_llong || ty == ty_ullong;
            Token *second_long_tok = tok;
            bool adjacent_long = consume(&tok, tok, "long");
            if (adjacent_long)
                note_type_specifier(&specs, second_long_tok, &specs.n_long);
            if (already_llong)
                error_at(tok->loc, "too many 'long' specifiers");
            Token *long_int_tok = tok;
            if (consume(&tok, tok, "int"))
                note_type_specifier(&specs, long_int_tok, &specs.n_int);
            bool is_unsigned = ty && ty->is_unsigned;
            bool is_llong = already_long || adjacent_long;
            ty = is_llong ? (is_unsigned ? ty_ullong : ty_llong)
                          : (is_unsigned ? ty_ulong : ty_long);
            continue;
        }

        Token *sign_tok = tok;
        if (consume(&tok, tok, "signed")) {
            mark_type_specifier(&specs, sign_tok);
            if (saw_signed)
                error_at(sign_tok->loc, "duplicate 'signed' type specifier");
            if (saw_unsigned)
                error_at(sign_tok->loc, "cannot combine 'signed' and 'unsigned'");
            if (saw_non_signable_type || saw_typedef_type)
                error_at(sign_tok->loc, "invalid type specifier combination with 'signed'");
            saw_signed = true;
            sign_spec = sign_tok;
            if (!ty)
                ty = ty_int;
            else if (ty == ty_char)
                ty = ty_schar;
            else if (ty != ty_int && ty != ty_schar && ty != ty_short &&
                     ty != ty_long && ty != ty_llong)
                error_at(sign_tok->loc, "invalid type specifier combination with 'signed'");
            continue;
        }

        sign_tok = tok;
        if (consume(&tok, tok, "unsigned")) {
            mark_type_specifier(&specs, sign_tok);
            if (saw_unsigned)
                error_at(sign_tok->loc, "duplicate 'unsigned' type specifier");
            if (saw_signed)
                error_at(sign_tok->loc, "cannot combine 'signed' and 'unsigned'");
            if (saw_non_signable_type || saw_typedef_type)
                error_at(sign_tok->loc, "invalid type specifier combination with 'unsigned'");
            saw_unsigned = true;
            sign_spec = sign_tok;
            if (ty == ty_char) ty = ty_uchar;
            else if (ty == ty_short) ty = ty_ushort;
            else if (ty == ty_long) ty = ty_ulong;
            else if (ty == ty_llong) ty = ty_ullong;
            else if (!ty || ty == ty_int) ty = ty_uint;
            else error_at(sign_tok->loc, "invalid type specifier combination with 'unsigned'");
            continue;
        }

        Token *int_tok = tok;
        if (consume(&tok, tok, "int")) {
            note_type_specifier(&specs, int_tok, &specs.n_int);
            if (!ty) ty = ty_int;
            continue;
        }

        if (equal(tok, "union")) {
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, true);
            continue;
        }

        if (equal(tok, "struct")) {
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, false);
            continue;
        }

        if (equal(tok, "enum")) {
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
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
                note_type_specifier(&specs, tok, &specs.n_named);
                tok = tok->next;
                ty = td->ty;
                saw_typedef_type = true;
                continue;
            }
        }

        break;
    }

    *rest = tok;
    ty = ty ? ty : ty_int;
    if ((saw_signed || saw_unsigned) && saw_non_signable_type)
        error_at(sign_spec->loc, "signed/unsigned type specifier requires an integer base type");
    validate_type_specifier_set(&specs, saw_signed, saw_unsigned);
    if (is_restrict && !is_restrict_qualifiable_type(ty))
        error_at(restrict_tok->loc,
                 "restrict qualifier requires a pointer to object or incomplete type");
    return qualify_type(ty, is_const, is_volatile, is_restrict);
}

static Type *declspec(Token **rest, Token *tok) {
    return declspec_impl(rest, tok, NULL);
}

static Type *declspec_with_attrs(Token **rest, Token *tok, DeclAttrs *attrs) {
    *attrs = (DeclAttrs){};
    return declspec_impl(rest, tok, attrs);
}

static Type *adjust_param_type(Type *ty) {
    // C adjusts array and function parameter declarations to pointers. Type
    // qualifiers written inside the outermost parameter-array brackets qualify
    // the adjusted pointer itself, not the element type.
    if (ty->kind == TY_ARRAY) {
        Type *ptr = pointer_to(ty->base);
        return qualify_type(ptr, ty->param_array_const, ty->param_array_volatile,
                            ty->param_array_restrict);
    }
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
        if (cur != &head) {
            tok = skip(tok, ",");
            if (equal(tok, ")"))
                error_at(tok->loc, "trailing comma in parameter list");
        }

        if (equal(tok, "...")) {
            if (cur == &head)
                error_at(tok->loc, "ellipsis requires a preceding fixed parameter");
            tok = tok->next;
            fty->is_variadic = true;
            break;
        }

        DeclAttrs param_attrs = {};
        Token *param_spec = tok;
        Type *basety = declspec_with_attrs(&tok, tok, &param_attrs);
        if (param_attrs.storage_class_count && !param_attrs.is_register)
            error_at(param_spec->loc,
                     "only register storage class is allowed on a parameter");
        if (param_attrs.is_inline || param_attrs.is_noreturn)
            error_at(param_spec->loc,
                     "function specifier is not allowed on a parameter");
        if (param_attrs.align)
            error_at(param_spec->loc, "_Alignas is not allowed on a parameter");
        Token *name = NULL;
        Type *param_ty = declarator_impl(&tok, tok, basety, &name, true, true);
        param_ty = adjust_param_type(param_ty);

        // The only valid non-pointer use of void in a parameter-type-list is
        // one unqualified, unnamed parameter denoting an empty parameter list.
        // Handle the semantic type as well as the literal spelling so a
        // `typedef void V; int f(V);` prototype is equivalent to `f(void)`.
        if (param_ty->kind == TY_VOID) {
            Token *at = name ? name : tok;
            if (name || param_ty->is_const || param_ty->is_volatile ||
                param_ty->is_restrict ||
                cur != &head || !equal(tok, ")"))
                error_at(at->loc,
                         "void parameter must be the only unqualified unnamed parameter");
            fty->params = NULL;
            fty->has_prototype = true;
            *rest = skip(tok, ")");
            return fty;
        }

        if (name) {
            for (Obj *prev = head.param_next; prev; prev = prev->param_next)
                if (prev->name && token_matches_name(name, prev->name))
                    error_at(name->loc, "duplicate parameter name");
        }

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
static Type *type_suffix(Token **rest, Token *tok, Type *ty,
                         bool allow_parameter_array_syntax) {
    if (equal(tok, "(")) {
        if (ty->kind == TY_ARRAY)
            error_at(tok->loc, "function cannot return an array type");
        if (ty->kind == TY_FUNC)
            error_at(tok->loc, "function cannot return a function type");
        return func_params(rest, tok->next, ty);
    }

    if (equal(tok, "[")) {
        Token *bracket = tok;
        tok = tok->next;

        bool param_const = false;
        bool param_volatile = false;
        bool param_restrict = false;
        bool param_static = false;

        if (!allow_parameter_array_syntax &&
            (equal(tok, "const") || equal(tok, "volatile") ||
             equal(tok, "restrict") || equal(tok, "static")))
            error_at(tok->loc,
                     "array qualifiers/static are only allowed in the outermost function parameter array");

        if (allow_parameter_array_syntax) {
            while (equal(tok, "const") || equal(tok, "volatile") ||
                   equal(tok, "restrict")) {
                if (consume(&tok, tok, "const"))
                    param_const = true;
                else if (consume(&tok, tok, "volatile"))
                    param_volatile = true;
                else {
                    consume(&tok, tok, "restrict");
                    param_restrict = true;
                }
            }

            if (consume(&tok, tok, "static")) {
                param_static = true;
                while (equal(tok, "const") || equal(tok, "volatile") ||
                       equal(tok, "restrict")) {
                    if (consume(&tok, tok, "const"))
                        param_const = true;
                    else if (consume(&tok, tok, "volatile"))
                        param_volatile = true;
                    else {
                        consume(&tok, tok, "restrict");
                        param_restrict = true;
                    }
                }
            }

            if (equal(tok, "static"))
                error_at(tok->loc, "duplicate static in parameter array declarator");
            if (equal(tok, "*"))
                error_at(tok->loc,
                         "variable-length parameter array '*' bounds are not supported");
            if (param_static && equal(tok, "]"))
                error_at(bracket->loc,
                         "static parameter array declarator requires an explicit bound");
        }

        int len = 0;
        if (!equal(tok, "]")) {
            Node *bound = ternary(&tok, tok);
            add_type(bound);
            if (!is_integer(bound->ty))
                error_at(bracket->loc, "array bound must have integer type");

            int64_t raw = eval_const_expr(bound);
            if (bound->ty->is_unsigned) {
                uint64_t val = (uint64_t)cast_const_integer(raw, bound->ty);
                if (val == 0 || val > INT32_MAX)
                    error_at(bracket->loc, "array bound is out of range");
                len = (int)val;
            } else {
                int64_t val = cast_const_integer(raw, bound->ty);
                if (val <= 0 || val > INT32_MAX)
                    error_at(bracket->loc, "array bound is out of range");
                len = (int)val;
            }
        }
        tok = skip(tok, "]");
        ty = type_suffix(rest, tok, ty, false);
        if (ty->kind == TY_FUNC)
            error_at(bracket->loc, "array element type cannot be a function");
        if (ty->kind == TY_VOID)
            error_at(bracket->loc, "array element type cannot be void");
        if (is_incomplete_object_type(ty))
            error_at(bracket->loc, "array element type is incomplete");
        if (ty->kind == TY_STRUCT && ty->has_flexible_array_member)
            error_at(bracket->loc,
                     "array element type contains a flexible array member");

        Type *arr = array_of(ty, len);
        if (allow_parameter_array_syntax) {
            arr->param_array_const = param_const;
            arr->param_array_volatile = param_volatile;
            arr->param_array_restrict = param_restrict;
        }
        (void)param_static; // `static` is a call-site minimum-bound contract, not type identity.
        return arr;
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
                             bool allow_abstract, bool parameter_declarator) {
    while (consume(&tok, tok, "*")) {
        ty = pointer_to(ty);
        bool ptr_const = false;
        bool ptr_volatile = false;
        bool ptr_restrict = false;
        Token *ptr_restrict_tok = NULL;
        while (equal(tok, "const") || equal(tok, "volatile") ||
               equal(tok, "restrict")) {
            if (consume(&tok, tok, "const"))
                ptr_const = true;
            else if (consume(&tok, tok, "volatile"))
                ptr_volatile = true;
            else {
                ptr_restrict_tok = tok;
                consume(&tok, tok, "restrict");
                ptr_restrict = true;
            }
        }
        if (ptr_restrict && !is_restrict_qualifiable_type(ty))
            error_at(ptr_restrict_tok->loc,
                     "restrict qualifier requires a pointer to object or incomplete type");
        ty = qualify_type(ty, ptr_const, ptr_volatile, ptr_restrict);
    }

    // In an abstract declarator, a leading parameter list is a function
    // suffix rather than a grouping. Grouping forms such as `(*)` still enter
    // the recursive parenthesized path below.
    if (allow_abstract && equal(tok, "(") &&
        (equal(tok->next, ")") || is_typename(tok->next) ||
         equal(tok->next, "const") || equal(tok->next, "volatile") ||
         equal(tok->next, "restrict") || equal(tok->next, "register")))
        return type_suffix(rest, tok, ty, false);

    if (equal(tok, "(")) {
        Token *start = tok;
        Type dummy = {};
        Type *shape = declarator_impl(&tok, start->next, &dummy, ident,
                                      allow_abstract, parameter_declarator);
        tok = skip(tok, ")");

        // Redundant grouping around the identifier does not stop a following
        // array suffix from being the parameter's outermost array derivation:
        // `int (a)[const 3]` adjusts just like `int a[const 3]`. If the grouped
        // declarator introduced any real derived type (`(*a)`, `(a[2])`, ...),
        // the following array is nested and may not carry parameter-only syntax.
        bool direct_parameter_array = parameter_declarator && shape == &dummy;
        ty = type_suffix(rest, tok, ty, direct_parameter_array);
        return declarator_impl(&tok, start->next, ty, ident, allow_abstract,
                               parameter_declarator);
    }

    if (tok->kind == TK_IDENT) {
        *ident = tok;
        tok = tok->next;
    } else if (allow_abstract) {
        *ident = NULL;
    } else {
        error_at(tok->loc, "expected a variable name");
    }

    return type_suffix(rest, tok, ty, parameter_declarator);
}

static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, false, false);
}

static Type *abstract_declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    return declarator_impl(rest, tok, ty, ident, true, false);
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

// Parse and evaluate an integer constant expression used by an object with
// static storage duration. Reuse the same type-aware evaluator as enums, case
// labels, and array bounds so signedness, integer promotions, short-circuiting,
// casts, and shift/division diagnostics cannot drift between contexts.
static int64_t parse_static_integer_initializer(Token **rest, Token *tok,
                                                Type *target) {
    Token *start = tok;
    Node *node = assign(&tok, tok);
    add_type(node);

    if (!is_integer(node->ty))
        error_at(start->loc, "static initializer is not an integer constant expression");

    int64_t val = eval_const_expr(node);

    if (target) {
        if (is_integer(target)) {
            val = cast_const_integer(val, target);
        } else if (target->kind == TY_PTR) {
            // A null pointer constant is an integer constant expression with
            // value zero. Address constants are intentionally a separate
            // feature; reject arbitrary nonzero integer-to-pointer statics.
            if (val != 0)
                error_at(start->loc, "nonzero integer is not a valid static pointer initializer");
            val = 0;
        } else {
            error_at(start->loc, "unsupported static integer initializer target type");
        }
    }

    *rest = tok;
    return val;
}

typedef struct {
    Type *ty;
    bool is_fp;
    int64_t ival;
    double fval;
} ConstNumber;

static ConstNumber eval_const_number(Node *node);

static double const_number_as_double(ConstNumber v) {
    if (v.is_fp)
        return v.fval;

    if (!v.ty || !is_integer(v.ty))
        error("arithmetic constant expression required");

    int64_t val = cast_const_integer(v.ival, v.ty);
    if (v.ty->is_unsigned)
        return (double)(uint64_t)val;
    return (double)val;
}

static bool const_number_truth(ConstNumber v) {
    if (v.is_fp)
        return v.fval != 0.0;
    return cast_const_integer(v.ival, v.ty) != 0;
}

static ConstNumber const_number_cast(ConstNumber v, Type *ty) {
    if (!ty || (!is_integer(ty) && !is_flonum(ty)))
        error("arithmetic type required in constant expression cast");

    ConstNumber out = {.ty = ty};
    if (is_flonum(ty)) {
        double x = const_number_as_double(v);
        out.is_fp = true;
        out.fval = ty->kind == TY_FLOAT ? (double)(float)x : x;
        return out;
    }

    out.is_fp = false;
    if (ty->kind == TY_BOOL) {
        out.ival = const_number_truth(v);
        return out;
    }

    if (!v.is_fp) {
        out.ival = cast_const_integer(v.ival, ty);
        return out;
    }

    double x = v.fval;
    if (ty->is_unsigned) {
        if (!(x >= 0.0) || x >= 18446744073709551616.0)
            error("floating-to-unsigned conversion is out of range in constant expression");
        out.ival = cast_const_integer((int64_t)(uint64_t)x, ty);
        return out;
    }

    if (x < (double)INT64_MIN || x >= 9223372036854775808.0)
        error("floating-to-integer conversion is out of range in constant expression");
    out.ival = cast_const_integer((int64_t)x, ty);
    return out;
}

static ConstNumber eval_const_number(Node *node) {
    if (!node)
        error("expected arithmetic constant expression");

    add_type(node);

    if (is_integer(node->ty)) {
        switch (node->kind) {
        case ND_EQ:
        case ND_NE:
        case ND_LT:
        case ND_LE: {
            add_type(node->lhs);
            add_type(node->rhs);
            if (!is_flonum(node->lhs->ty) && !is_flonum(node->rhs->ty))
                return (ConstNumber){.ty = node->ty, .ival = eval_const_expr(node)};

            ConstNumber lhs = eval_const_number(node->lhs);
            ConstNumber rhs = eval_const_number(node->rhs);
            double a = const_number_as_double(lhs);
            double b = const_number_as_double(rhs);
            bool r = node->kind == ND_EQ ? a == b
                   : node->kind == ND_NE ? a != b
                   : node->kind == ND_LT ? a < b
                                         : a <= b;
            return (ConstNumber){.ty = node->ty, .ival = r};
        }
        case ND_LOGAND: {
            ConstNumber lhs = eval_const_number(node->lhs);
            if (!const_number_truth(lhs))
                return (ConstNumber){.ty = node->ty, .ival = 0};
            return (ConstNumber){.ty = node->ty,
                                 .ival = const_number_truth(eval_const_number(node->rhs))};
        }
        case ND_LOGOR: {
            ConstNumber lhs = eval_const_number(node->lhs);
            if (const_number_truth(lhs))
                return (ConstNumber){.ty = node->ty, .ival = 1};
            return (ConstNumber){.ty = node->ty,
                                 .ival = const_number_truth(eval_const_number(node->rhs))};
        }
        case ND_NOT:
            return (ConstNumber){.ty = node->ty,
                                 .ival = !const_number_truth(eval_const_number(node->lhs))};
        case ND_TERNARY: {
            Node *chosen = const_number_truth(eval_const_number(node->cond))
                               ? node->then
                               : node->els;
            return const_number_cast(eval_const_number(chosen), node->ty);
        }
        case ND_CAST:
            return const_number_cast(eval_const_number(node->lhs), node->ty);
        default:
            return (ConstNumber){.ty = node->ty, .ival = eval_const_expr(node)};
        }
    }

    if (!is_flonum(node->ty))
        error("not an arithmetic constant expression");

    switch (node->kind) {
    case ND_NUM:
        return (ConstNumber){.ty = node->ty, .is_fp = true,
                             .fval = node->ty->kind == TY_FLOAT
                                         ? (double)(float)node->fval
                                         : node->fval};
    case ND_NEG: {
        ConstNumber v = const_number_cast(eval_const_number(node->lhs), node->ty);
        v.fval = node->ty->kind == TY_FLOAT ? (double)(float)-v.fval : -v.fval;
        return v;
    }
    case ND_ADD:
    case ND_SUB:
    case ND_MUL:
    case ND_DIV: {
        double a = const_number_as_double(eval_const_number(node->lhs));
        double b = const_number_as_double(eval_const_number(node->rhs));
        double r = node->kind == ND_ADD ? a + b
                   : node->kind == ND_SUB ? a - b
                   : node->kind == ND_MUL ? a * b
                                          : a / b;
        if (node->ty->kind == TY_FLOAT)
            r = (double)(float)r;
        return (ConstNumber){.ty = node->ty, .is_fp = true, .fval = r};
    }
    case ND_TERNARY: {
        Node *chosen = const_number_truth(eval_const_number(node->cond))
                           ? node->then
                           : node->els;
        return const_number_cast(eval_const_number(chosen), node->ty);
    }
    case ND_CAST:
        return const_number_cast(eval_const_number(node->lhs), node->ty);
    default:
        error("not an arithmetic constant expression");
    }
}

static double parse_const_double(Token **rest, Token *tok) {
    Node *node = assign(&tok, tok);
    add_type(node);
    if (!is_numeric(node->ty))
        error("static floating initializer requires an arithmetic constant expression");

    ConstNumber value = const_number_cast(eval_const_number(node), ty_double);
    *rest = tok;
    return value.fval;
}



typedef struct {
    char *label;
    int64_t addend;
} StaticAddress;

static StaticAddress eval_static_address(Node *node);

static StaticAddress eval_static_lvalue_address(Node *node) {
    add_type(node);

    switch (node->kind) {
    case ND_VAR:
        if (node->var->is_local)
            error("address of automatic object is not a static address constant");
        return (StaticAddress){node->var->name, 0};
    case ND_DEREF:
        // &*p is the value of p, subject to static-address constraints.
        return eval_static_address(node->lhs);
    case ND_MEMBER: {
        StaticAddress addr = eval_static_lvalue_address(node->lhs);
        addr.addend += node->member->offset;
        return addr;
    }
    default:
        error("unsupported lvalue in static address initializer");
    }
}

static StaticAddress eval_static_address(Node *node) {
    add_type(node);

    // Integer constant-expression zero is the null pointer constant case.
    if (is_integer(node->ty)) {
        int64_t val = eval_const_expr(node);
        if (val != 0)
            error("nonzero integer is not a valid static pointer initializer");
        return (StaticAddress){0};
    }

    switch (node->kind) {
    case ND_VAR:
        // Array and function designators decay to their link-time addresses.
        // Reading the value of an ordinary pointer object is not a constant.
        if (node->var->is_local)
            error("automatic object is not a static address constant");
        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_FUNC)
            error("object value is not a static address constant");
        return (StaticAddress){node->var->name, 0};

    case ND_ADDR:
        return eval_static_lvalue_address(node->lhs);

    case ND_ADD:
    case ND_SUB: {
        add_type(node->lhs);
        add_type(node->rhs);
        StaticAddress addr = eval_static_address(node->lhs);
        int64_t delta = eval_const_expr(node->rhs);
        addr.addend += node->kind == ND_ADD ? delta : -delta;
        return addr;
    }

    case ND_CAST:
        // Pointer-preserving casts are link-time no-ops. Casts of integer zero
        // reach the integer branch above when recursively evaluated.
        return eval_static_address(node->lhs);

    case ND_TERNARY:
        return eval_static_address(eval_const_expr(node->cond) ? node->then : node->els);

    default:
        error("not a static address constant");
    }
}

static StaticAddress parse_static_address_initializer(Token **rest, Token *tok,
                                                       Type *target) {
    Token *start = tok;
    Node *node = assign(&tok, tok);
    add_type(node);

    if (is_integer(node->ty)) {
        int64_t val = eval_const_expr(node);
        if (val != 0)
            error_at(start->loc, "nonzero integer is not a valid static pointer initializer");
        *rest = tok;
        return (StaticAddress){0};
    }

    if (!assignment_compatible(target, node))
        error_at(start->loc, "incompatible static pointer initializer");

    StaticAddress addr = eval_static_address(node);
    *rest = tok;
    return addr;
}

static void parse_static_pointer_initializer(Obj *var, Token **rest, Token *tok,
                                             Type *target) {
    StaticAddress addr = parse_static_address_initializer(rest, tok, target);
    if (!addr.label) {
        var->init_val = 0;
        var->has_init_val = true;
    } else {
        var->init_reloc_label = addr.label;
        var->init_reloc_addend = addr.addend;
        var->has_init_reloc = true;
    }
}

static void parse_static_scalar_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty) {
    if (is_flonum(ty)) {
        var->finit_val = parse_const_double(rest, tok);
        var->has_init_val = true;
        return;
    }
    if (is_integer(ty)) {
        var->init_val = parse_static_integer_initializer(rest, tok, ty);
        var->has_init_val = true;
        return;
    }
    if (ty->kind == TY_PTR) {
        parse_static_pointer_initializer(var, rest, tok, ty);
        return;
    }
    error_at(tok->loc, "unsupported scalar static initializer type");
}

static Token *string_initializer_token(Token *tok, Token **after) {
    if (tok->kind == TK_STR) {
        *after = tok->next;
        return tok;
    }

    if (!equal(tok, "{") || tok->next->kind != TK_STR)
        return NULL;

    Token *str = tok->next;
    Token *end = str->next;
    if (equal(end, ","))
        end = end->next;
    if (!equal(end, "}"))
        return NULL;

    *after = end->next;
    return str;
}

static bool is_character_array(Type *ty) {
    return ty && ty->kind == TY_ARRAY && ty->base && ty->base->kind == TY_CHAR;
}

static void validate_string_array_initializer(Type *ty, Token *str) {
    if (!is_character_array(ty))
        error_at(str->loc, "string literal can initialize only a character array here");

    int payload_len = str->ty->array_len - 1;
    if (ty->array_len > 0 && ty->array_len < payload_len)
        error_at(str->loc, "initializer string is too long for character array");
}

static void prepare_string_array_type(Obj *var, Type **ty, Token *str) {
    validate_string_array_initializer(*ty, str);

    if ((*ty)->array_len == 0) {
        *ty = array_of((*ty)->base, str->ty->array_len);
        var->ty = *ty;
    }
}

static char *build_string_array_image(Type *ty, Token *str) {
    char *data = calloc(ty->array_len, 1);
    int copy = str->ty->array_len;
    if (copy > ty->array_len)
        copy = ty->array_len;
    memcpy(data, str->str, copy);
    return data;
}

// Character arrays are special aggregate subobjects: C permits a string
// literal to initialize them directly, including when they are members or
// elements of a larger aggregate. Materialize the bytes as ordinary automatic
// assignments so writable local arrays retain the existing initializer model.
static bool append_automatic_string_array_initializer(Node **tail, Node *lhs,
                                                       Type *ty, Token **rest,
                                                       Token *tok) {
    if (!is_character_array(ty))
        return false;

    Token *after = NULL;
    Token *str = string_initializer_token(tok, &after);
    if (!str)
        return false;

    if (ty->array_len == 0)
        error_at(str->loc, "nested incomplete character arrays are not supported");
    validate_string_array_initializer(ty, str);

    for (int i = 0; i < ty->array_len; i++) {
        int value = 0;
        if (i < str->ty->array_len)
            value = (unsigned char)str->str[i];
        Node *elem = new_unary(ND_DEREF, new_add(lhs, new_num(i)));
        Node *assign = new_initializer_assign(elem, new_num(value), str);
        *tail = (*tail)->next = new_unary(ND_EXPR_STMT, assign);
    }

    *rest = after;
    return true;
}


// Append zero-initialization statements for an automatic aggregate subobject.
// C requires omitted array elements and record members to be initialized as if
// they had static storage duration. Recurse so omitted nested aggregates are
// fully zeroed rather than attempting an invalid aggregate-from-integer assign.
static void append_zero_initializer(Node **tail, Node *lhs, Type *ty, Token *where) {
    if (ty->kind == TY_ARRAY) {
        for (int i = 0; i < ty->array_len; i++) {
            Node *elem = new_unary(ND_DEREF, new_add(lhs, new_num(i)));
            append_zero_initializer(tail, elem, ty->base, where);
        }
        return;
    }

    if (ty->kind == TY_STRUCT) {
        if (ty->is_union) {
            Member *m = ty->members;
            if (m) {
                Node *member = new_node(ND_MEMBER);
                member->lhs = lhs;
                member->member = m;
                append_zero_initializer(tail, member, m->ty, where);
            }
            return;
        }

        for (Member *m = ty->members; m; m = m->next) {
            Node *member = new_node(ND_MEMBER);
            member->lhs = lhs;
            member->member = m;
            append_zero_initializer(tail, member, m->ty, where);
        }
        return;
    }

    Node *assign = new_initializer_assign(lhs, new_num(0), where);
    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, assign);
}

static int record_member_index(Type *ty, Member *target) {
    int index = 0;
    for (Member *m = ty->members; m; m = m->next, index++)
        if (m == target)
            return index;
    return -1;
}

static int record_member_count(Type *ty) {
    int count = 0;
    for (Member *m = ty->members; m; m = m->next)
        count++;
    return count;
}

// Array designators use an integer constant expression, not merely a numeric
// token. Evaluate with the shared type-aware constant-expression machinery so
// enum constants, casts, arithmetic, and unsigned range checks behave exactly
// like array bounds and case labels.
static int parse_array_designator_index(Token **rest, Token *tok, Token *where) {
    Node *index = ternary(&tok, tok);
    add_type(index);
    if (!is_integer(index->ty))
        error_at(where->loc, "array designator index must have integer type");

    int64_t raw = eval_const_expr(index);
    int64_t converted = cast_const_integer(raw, index->ty);
    if (index->ty->is_unsigned) {
        uint64_t value = (uint64_t)converted;
        if (value > INT32_MAX)
            error_at(where->loc, "array designator index is out of range");
        *rest = tok;
        return (int)value;
    }

    if (converted < 0 || converted > INT32_MAX)
        error_at(where->loc, "array designator index is out of range");
    *rest = tok;
    return (int)converted;
}

// Parse a static-storage-duration integer array initializer. The backing value
// vector is indexed by the actual designated subscript, so omitted elements are
// represented as zero and out-of-order/repeated designators retain C semantics.
static void parse_static_integer_array_initializer(Obj *var, Type **ty,
                                                   Token **rest, Token *tok) {
    Token *brace = tok;
    if ((*ty)->kind != TY_ARRAY || !is_integer((*ty)->base))
        error_at(brace->loc, "static brace initializer currently supports integer arrays");

    Type *elem_ty = (*ty)->base;
    tok = tok->next;
    int cap = (*ty)->array_len > 0 ? (*ty)->array_len : 16;
    if (cap < 1)
        cap = 16;
    int64_t *vals = calloc(cap, sizeof(int64_t));
    int cur_idx = 0;
    int max_idx = -1;
    bool first_elem = true;

    while (!equal(tok, "}")) {
        if (!first_elem) {
            tok = skip(tok, ",");
            if (equal(tok, "}"))
                break;
        }
        first_elem = false;

        if (equal(tok, "."))
            error_at(tok->loc, "member designator requires a record initializer");

        if (equal(tok, "[")) {
            Token *designator = tok;
            tok = tok->next;
            cur_idx = parse_array_designator_index(&tok, tok, designator);
            tok = skip(tok, "]");
            tok = skip(tok, "=");
        }

        if ((*ty)->array_len > 0 && cur_idx >= (*ty)->array_len)
            error_at(tok->loc, "array designator index exceeds array bounds");

        while (cur_idx >= cap) {
            int old_cap = cap;
            cap *= 2;
            vals = realloc(vals, cap * sizeof(int64_t));
            memset(vals + old_cap, 0, (cap - old_cap) * sizeof(int64_t));
        }

        vals[cur_idx] = parse_static_integer_initializer(&tok, tok, elem_ty);
        if (cur_idx > max_idx)
            max_idx = cur_idx;
        cur_idx++;
    }
    tok = skip(tok, "}");

    if ((*ty)->array_len == 0) {
        int inferred = max_idx + 1;
        if (inferred <= 0)
            error_at(brace->loc, "cannot infer array size from empty initializer");
        *ty = array_of(elem_ty, inferred);
        var->ty = *ty;
    }

    var->init_vals = vals;
    var->init_vals_count = max_idx + 1;
    *rest = tok;
}

static void ensure_static_image(Obj *var, int size) {
    if (size <= var->init_image_size)
        return;
    int old = var->init_image_size;
    var->init_image = realloc(var->init_image, size);
    memset(var->init_image + old, 0, size - old);
    var->init_image_size = size;
}

static void clear_static_reloc_range(Obj *var, int offset, int size) {
    Relocation head = {};
    Relocation *tail = &head;
    for (Relocation *rel = var->init_relocs; rel;) {
        Relocation *next = rel->next;
        if (rel->offset < offset || rel->offset >= offset + size) {
            tail = tail->next = rel;
            rel->next = NULL;
        } else {
            free(rel);
        }
        rel = next;
    }
    var->init_relocs = head.next;
}

static void reset_static_subobject(Obj *var, int offset, int size) {
    ensure_static_image(var, offset + size);
    memset(var->init_image + offset, 0, size);
    clear_static_reloc_range(var, offset, size);
}

// Static aggregate images use the same character-array string rule. The image
// is already writable .data storage; copy at most the destination width so a
// char[N] may omit the terminating NUL when N equals the string payload length.
static bool parse_static_string_array_initializer(Obj *var, Token **rest,
                                                  Token *tok, Type *ty,
                                                  int offset) {
    if (!is_character_array(ty))
        return false;

    Token *after = NULL;
    Token *str = string_initializer_token(tok, &after);
    if (!str)
        return false;

    if (ty->array_len == 0)
        error_at(str->loc, "nested incomplete character arrays are not supported");
    validate_string_array_initializer(ty, str);
    reset_static_subobject(var, offset, ty->size);

    int copy = str->ty->array_len;
    if (copy > ty->array_len)
        copy = ty->array_len;
    memcpy(var->init_image + offset, str->str, copy);
    *rest = after;
    return true;
}

static void add_static_image_reloc(Obj *var, int offset, StaticAddress addr) {
    Relocation *rel = calloc(1, sizeof(Relocation));
    rel->offset = offset;
    rel->label = addr.label;
    rel->addend = addr.addend;
    rel->next = var->init_relocs;
    var->init_relocs = rel;
}

static void write_static_integer_bytes(Obj *var, int offset, Type *ty, int64_t val) {
    ensure_static_image(var, offset + ty->size);
    uint64_t bits = (uint64_t)val;
    for (int i = 0; i < ty->size; i++)
        var->init_image[offset + i] = (char)(bits >> (i * 8));
}

static void parse_static_image_scalar(Obj *var, Token **rest, Token *tok,
                                      Type *ty, int offset) {
    reset_static_subobject(var, offset, ty->size);

    if (is_integer(ty)) {
        int64_t val = parse_static_integer_initializer(rest, tok, ty);
        write_static_integer_bytes(var, offset, ty, val);
        return;
    }

    if (is_flonum(ty)) {
        double val = parse_const_double(rest, tok);
        if (ty->kind == TY_FLOAT) {
            float f = (float)val;
            memcpy(var->init_image + offset, &f, sizeof(f));
        } else {
            memcpy(var->init_image + offset, &val, sizeof(val));
        }
        return;
    }

    if (ty->kind == TY_PTR) {
        StaticAddress addr = parse_static_address_initializer(rest, tok, ty);
        if (addr.label)
            add_static_image_reloc(var, offset, addr);
        return;
    }

    error_at(tok->loc, "unsupported scalar in static aggregate initializer");
}

static Member *find_static_initializer_member(Type *ty, Token *tok) {
    for (Member *m = ty->members; m; m = m->next)
        if ((int)strlen(m->name) == tok->len &&
            !strncmp(m->name, tok->loc, tok->len))
            return m;
    return NULL;
}

static bool is_initializer_aggregate(Type *ty) {
    return ty && (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT);
}

typedef enum {
    INIT_DESIGNATOR_INDEX,
    INIT_DESIGNATOR_MEMBER,
} InitializerDesignatorKind;

typedef struct InitializerDesignator InitializerDesignator;
struct InitializerDesignator {
    InitializerDesignator *next;
    InitializerDesignatorKind kind;
    int index;
    Member *member;
    Type *result_ty;
};

typedef struct {
    InitializerDesignator *head;
    InitializerDesignator *tail;
    Type *target_ty;
    int first_index;
    Member *first_member;
    int depth;
} InitializerDesignatorPath;

static InitializerDesignatorPath
parse_initializer_designator_path(Token **rest, Token *tok, Type *root_ty) {
    InitializerDesignatorPath path = {.first_index = -1};
    Type *cur = root_ty;

    while (equal(tok, "[") || equal(tok, ".")) {
        InitializerDesignator *step = calloc(1, sizeof(InitializerDesignator));

        if (equal(tok, "[")) {
            Token *where = tok;
            if (!cur || cur->kind != TY_ARRAY)
                error_at(where->loc, "array designator requires an array subobject");
            if (cur->array_len == 0 && path.depth > 0)
                error_at(where->loc, "nested incomplete arrays are not supported");

            tok = tok->next;
            int index = parse_array_designator_index(&tok, tok, where);
            tok = skip(tok, "]");
            if (cur->array_len > 0 && index >= cur->array_len)
                error_at(where->loc, "array designator index exceeds array bounds");

            step->kind = INIT_DESIGNATOR_INDEX;
            step->index = index;
            step->result_ty = cur->base;
            if (path.depth == 0)
                path.first_index = index;
            cur = cur->base;
        } else {
            Token *where = tok;
            if (!cur || cur->kind != TY_STRUCT)
                error_at(where->loc, "member designator requires a record subobject");
            tok = tok->next;
            if (tok->kind != TK_IDENT)
                error_at(tok->loc, "expected member name in designated initializer");

            Member *member = find_static_initializer_member(cur, tok);
            if (!member)
                error_at(tok->loc, "unknown member in designated initializer");
            tok = tok->next;

            step->kind = INIT_DESIGNATOR_MEMBER;
            step->member = member;
            step->result_ty = member->ty;
            if (path.depth == 0)
                path.first_member = member;
            cur = member->ty;
        }

        if (!path.head)
            path.head = step;
        else
            path.tail->next = step;
        path.tail = step;
        path.depth++;
    }

    if (!path.depth)
        error_at(tok->loc, "expected initializer designator");

    path.target_ty = cur;
    *rest = skip(tok, "=");
    return path;
}

static void free_initializer_designator_path(InitializerDesignatorPath *path) {
    for (InitializerDesignator *step = path->head; step;) {
        InitializerDesignator *next = step->next;
        free(step);
        step = next;
    }
    path->head = path->tail = NULL;
}

static int apply_static_designator_path(Obj *var, Type *root_ty, int root_offset,
                                        InitializerDesignatorPath *path) {
    Type *cur = root_ty;
    int offset = root_offset;

    for (InitializerDesignator *step = path->head; step; step = step->next) {
        if (step->kind == INIT_DESIGNATOR_INDEX) {
            offset += step->index * cur->base->size;
        } else {
            // Selecting a union member replaces the complete overlapping
            // representation.  Clear both bytes and relocations before walking
            // farther into the selected member.
            if (cur->is_union)
                reset_static_subobject(var, offset, cur->size);
            offset += step->member->offset;
        }
        cur = step->result_ty;
    }
    return offset;
}

typedef struct {
    Node *lhs;
    Type *ty;
    Node *top_lhs;
    Type *top_ty;
} AutomaticDesignatedTarget;

static AutomaticDesignatedTarget
apply_automatic_designator_path(Node *root_lhs, Type *root_ty,
                                 InitializerDesignatorPath *path) {
    Node *lhs = root_lhs;
    Type *cur = root_ty;
    Node *top_lhs = NULL;
    Type *top_ty = NULL;

    for (InitializerDesignator *step = path->head; step; step = step->next) {
        if (step->kind == INIT_DESIGNATOR_INDEX) {
            lhs = new_unary(ND_DEREF, new_add(lhs, new_num(step->index)));
        } else {
            Node *member = new_node(ND_MEMBER);
            member->lhs = lhs;
            member->member = step->member;
            lhs = member;
        }
        cur = step->result_ty;
        if (!top_lhs) {
            top_lhs = lhs;
            top_ty = cur;
        }
    }

    return (AutomaticDesignatedTarget){
        .lhs = lhs,
        .ty = cur,
        .top_lhs = top_lhs,
        .top_ty = top_ty,
    };
}


static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty, int offset);

// A nested aggregate may omit its own braces. Consume exactly the number of
// positional subobjects belonging to this aggregate and leave the separator
// before the next enclosing subobject untouched. The backing static image is
// already zero-filled, so an early enclosing '}' naturally leaves the remainder
// of the elided aggregate initialized to zero.
static void parse_static_image_elided(Obj *var, Token **rest, Token *tok,
                                      Type *ty, int offset, Token *where) {
    if (!is_initializer_aggregate(ty))
        error_at(where->loc, "internal error: brace elision requires aggregate type");

    if (ty->kind == TY_ARRAY) {
        if (ty->array_len == 0)
            error_at(where->loc, "nested incomplete arrays are not supported");
        ensure_static_image(var, offset + ty->size);

        for (int i = 0; i < ty->array_len; i++) {
            if (i > 0) {
                if (equal(tok, "}"))
                    break;
                tok = skip(tok, ",");
                if (equal(tok, "}"))
                    break;
            }
            if (equal(tok, "[") || equal(tok, "."))
                error_at(tok->loc, "designators in brace-elided nested aggregates are not yet supported");

            Type *child_ty = ty->base;
            int child_offset = offset + i * child_ty->size;
            reset_static_subobject(var, child_offset, child_ty->size);

            if (parse_static_string_array_initializer(var, &tok, tok,
                                                       child_ty, child_offset))
                continue;
            if (is_initializer_aggregate(child_ty) && !equal(tok, "{")) {
                parse_static_image_elided(var, &tok, tok, child_ty,
                                          child_offset, where);
                continue;
            }

            Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                          child_ty, child_offset);
            if (parsed != child_ty)
                error_at(where->loc, "nested incomplete arrays are not supported");
        }
        *rest = tok;
        return;
    }

    ensure_static_image(var, offset + ty->size);
    int initialized = 0;
    for (Member *m = ty->members; m; m = m->next) {
        if (initialized > 0) {
            if (equal(tok, "}"))
                break;
            tok = skip(tok, ",");
            if (equal(tok, "}"))
                break;
        }
        if (equal(tok, "[") || equal(tok, "."))
            error_at(tok->loc, "designators in brace-elided nested aggregates are not yet supported");

        if (ty->is_union)
            reset_static_subobject(var, offset, ty->size);
        else
            reset_static_subobject(var, offset + m->offset, m->ty->size);

        int child_offset = offset + m->offset;
        if (parse_static_string_array_initializer(var, &tok, tok,
                                                   m->ty, child_offset)) {
            initialized++;
        } else if (is_initializer_aggregate(m->ty) && !equal(tok, "{")) {
            parse_static_image_elided(var, &tok, tok, m->ty,
                                      child_offset, where);
            initialized++;
        } else {
            Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                          m->ty, child_offset);
            if (parsed != m->ty)
                error_at(where->loc, "incomplete array record members are not supported");
            initialized++;
        }

        if (ty->is_union)
            break;
    }
    *rest = tok;
}

static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty, int offset) {
    if (parse_static_string_array_initializer(var, rest, tok, ty, offset))
        return ty;

    if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT) {
        if (equal(tok, "{")) {
            Token *brace = tok;
            tok = tok->next;
            if (equal(tok, "}"))
                error_at(brace->loc, "empty scalar initializer");
            parse_static_image_scalar(var, &tok, tok, ty, offset);
            if (equal(tok, ","))
                tok = tok->next;
            *rest = skip(tok, "}");
            return ty;
        }
        parse_static_image_scalar(var, rest, tok, ty, offset);
        return ty;
    }

    Token *brace = tok;
    if (!equal(tok, "{"))
        error_at(tok->loc, "nested static aggregate initializer requires braces");
    tok = tok->next;

    if (ty->kind == TY_ARRAY) {
        if (ty->array_len > 0)
            ensure_static_image(var, offset + ty->size);

        int next_index = 0;
        int max_index = -1;
        bool first = true;
        while (!equal(tok, "}")) {
            if (!first) {
                tok = skip(tok, ",");
                if (equal(tok, "}"))
                    break;
            }
            first = false;

            if (equal(tok, "."))
                error_at(tok->loc, "member designator requires a record initializer");

            if (equal(tok, "[") || equal(tok, ".")) {
                InitializerDesignatorPath path =
                    parse_initializer_designator_path(&tok, tok, ty);
                if (path.first_index < 0)
                    error_at(brace->loc, "array initializer designator must start with an index");

                int index = path.first_index;
                Type *target_ty = path.target_ty;
                int target_offset = apply_static_designator_path(var, ty, offset, &path);
                reset_static_subobject(var, target_offset, target_ty->size);
                free_initializer_designator_path(&path);

                if (parse_static_string_array_initializer(var, &tok, tok,
                                                           target_ty, target_offset)) {
                    // String literal consumed as the designated character array.
                } else {
                    Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                                  target_ty, target_offset);
                    if (parsed != target_ty)
                        error_at(brace->loc, "nested incomplete arrays are not supported");
                }

                if (index > max_index)
                    max_index = index;
                next_index = index + 1;
                continue;
            }

            int index = next_index;
            if (ty->array_len > 0 && index >= ty->array_len)
                error_at(tok->loc, "excess elements in array initializer");

            Type *elem_ty = ty->base;
            int elem_offset = offset + index * elem_ty->size;
            reset_static_subobject(var, elem_offset, elem_ty->size);
            if (parse_static_string_array_initializer(var, &tok, tok,
                                                       elem_ty, elem_offset)) {
                // Character-array string initializer consumed as one subobject.
            } else if (is_initializer_aggregate(elem_ty) && !equal(tok, "{")) {
                parse_static_image_elided(var, &tok, tok, elem_ty,
                                          elem_offset, brace);
            } else {
                Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                              elem_ty, elem_offset);
                if (parsed != elem_ty)
                    error_at(brace->loc, "nested incomplete arrays are not supported");
            }

            if (index > max_index)
                max_index = index;
            next_index = index + 1;
        }
        tok = skip(tok, "}");

        if (ty->array_len == 0) {
            if (max_index < 0)
                error_at(brace->loc, "cannot infer array size from empty initializer");
            ty = array_of(ty->base, max_index + 1);
        }
        ensure_static_image(var, offset + ty->size);
        *rest = tok;
        return ty;
    }

    ensure_static_image(var, offset + ty->size);
    Member *next_member = ty->members;
    bool first = true;
    int initialized_members = 0;
    while (!equal(tok, "}")) {
        if (!first) {
            tok = skip(tok, ",");
            if (equal(tok, "}"))
                break;
        }
        first = false;

        if (ty->is_union && initialized_members)
            error_at(tok->loc, "excess elements in union initializer");

        if (equal(tok, ".") || equal(tok, "[")) {
            InitializerDesignatorPath path =
                parse_initializer_designator_path(&tok, tok, ty);
            if (!path.first_member)
                error_at(brace->loc, "record initializer designator must start with a member");

            Member *member = path.first_member;
            Type *target_ty = path.target_ty;
            int target_offset = apply_static_designator_path(var, ty, offset, &path);
            reset_static_subobject(var, target_offset, target_ty->size);
            free_initializer_designator_path(&path);

            if (parse_static_string_array_initializer(var, &tok, tok,
                                                       target_ty, target_offset)) {
                // String literal consumed as the designated character array.
            } else {
                Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                              target_ty, target_offset);
                if (parsed != target_ty)
                    error_at(brace->loc, "incomplete array record members are not supported");
            }

            initialized_members++;
            next_member = member->next;
            continue;
        }

        Member *member = next_member;
        if (!member)
            error_at(tok->loc, "excess elements in record initializer");

        // All union members overlap at offset zero. Clear the complete union so
        // a positional pointer member cannot leave stale relocation/data bytes.
        if (ty->is_union)
            reset_static_subobject(var, offset, ty->size);
        else
            reset_static_subobject(var, offset + member->offset, member->ty->size);

        int member_offset = offset + member->offset;
        if (parse_static_string_array_initializer(var, &tok, tok,
                                                   member->ty, member_offset)) {
            // Character-array string initializer consumed as one subobject.
        } else if (is_initializer_aggregate(member->ty) && !equal(tok, "{")) {
            parse_static_image_elided(var, &tok, tok, member->ty,
                                      member_offset, brace);
        } else {
            Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                          member->ty, member_offset);
            if (parsed != member->ty)
                error_at(brace->loc, "incomplete array record members are not supported");
        }
        initialized_members++;
        next_member = member->next;
    }

    *rest = skip(tok, "}");
    return ty;
}

// Parse one nested automatic aggregate subobject, with or without its own
// braces. Zero the complete subobject first, then overwrite explicitly supplied
// positional leaves. In unbraced mode the helper consumes only separators that
// belong inside the subobject and leaves the next enclosing comma untouched.
static void parse_automatic_designated_initializer(Node **tail, Node *lhs,
                                                    Type *ty, Token **rest,
                                                    Token *tok, Token *where);

static void parse_automatic_aggregate_subobject(Node **tail, Node *lhs, Type *ty,
                                                 Token **rest, Token *tok,
                                                 Token *where) {
    if (!is_initializer_aggregate(ty))
        error_at(where->loc, "internal error: automatic aggregate initializer expected");
    if (ty->kind == TY_ARRAY && ty->array_len == 0)
        error_at(where->loc, "nested incomplete arrays are not supported");

    // Automatic aggregates are zero-initialized before their explicit
    // initializer-list entries are applied.  This is especially important for
    // repeated nested designators: later writes must preserve earlier siblings
    // rather than re-zeroing the whole enclosing subobject.
    append_zero_initializer(tail, lhs, ty, where);
    bool braced = consume(&tok, tok, "{");

    // A braced nested initializer is a real initializer-list, so it may contain
    // designators at any entry.  Reuse the same designator-path parser used by
    // top-level automatic initializers and then lower the resolved path to an
    // lvalue rooted at this nested subobject.
    if (braced) {
        if (ty->kind == TY_ARRAY) {
            int next_index = 0;
            bool first = true;

            while (!equal(tok, "}")) {
                if (!first) {
                    tok = skip(tok, ",");
                    if (equal(tok, "}"))
                        break;
                }
                first = false;

                if (equal(tok, "[") || equal(tok, ".")) {
                    InitializerDesignatorPath path =
                        parse_initializer_designator_path(&tok, tok, ty);
                    if (path.first_index < 0)
                        error_at(where->loc,
                                 "array initializer designator must start with an index");

                    int index = path.first_index;
                    AutomaticDesignatedTarget target =
                        apply_automatic_designator_path(lhs, ty, &path);
                    free_initializer_designator_path(&path);

                    parse_automatic_designated_initializer(tail, target.lhs,
                                                            target.ty, &tok, tok,
                                                            where);
                    next_index = index + 1;
                    continue;
                }

                if (next_index >= ty->array_len)
                    error_at(tok->loc, "excess elements in array initializer");

                int index = next_index++;
                Node *child = new_unary(ND_DEREF,
                                        new_add(lhs, new_num(index)));
                if (append_automatic_string_array_initializer(tail, child,
                                                               ty->base,
                                                               &tok, tok))
                    continue;
                if (is_initializer_aggregate(ty->base)) {
                    parse_automatic_aggregate_subobject(tail, child, ty->base,
                                                         &tok, tok, where);
                    continue;
                }

                Node *rhs = assign(&tok, tok);
                Node *a = new_initializer_assign(child, rhs, where);
                *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
            }
        } else {
            Member *next_member = ty->members;
            bool first = true;
            int initialized_union_members = 0;

            while (!equal(tok, "}")) {
                if (!first) {
                    tok = skip(tok, ",");
                    if (equal(tok, "}"))
                        break;
                }
                first = false;

                if (ty->is_union && initialized_union_members)
                    error_at(tok->loc, "excess elements in union initializer");

                if (equal(tok, ".") || equal(tok, "[")) {
                    InitializerDesignatorPath path =
                        parse_initializer_designator_path(&tok, tok, ty);
                    if (!path.first_member)
                        error_at(where->loc,
                                 "record initializer designator must start with a member");

                    Member *member = path.first_member;
                    AutomaticDesignatedTarget target =
                        apply_automatic_designator_path(lhs, ty, &path);
                    free_initializer_designator_path(&path);

                    parse_automatic_designated_initializer(tail, target.lhs,
                                                            target.ty, &tok, tok,
                                                            where);
                    if (ty->is_union)
                        initialized_union_members++;
                    next_member = member->next;
                    continue;
                }

                if (!next_member)
                    error_at(tok->loc, "excess elements in record initializer");

                Node *child = new_node(ND_MEMBER);
                child->lhs = lhs;
                child->member = next_member;
                if (append_automatic_string_array_initializer(tail, child,
                                                               next_member->ty,
                                                               &tok, tok)) {
                    // String literal consumed as one member initializer.
                } else if (is_initializer_aggregate(next_member->ty)) {
                    parse_automatic_aggregate_subobject(tail, child,
                                                         next_member->ty,
                                                         &tok, tok, where);
                } else {
                    Node *rhs = assign(&tok, tok);
                    Node *a = new_initializer_assign(child, rhs, where);
                    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
                }

                if (ty->is_union)
                    initialized_union_members++;
                next_member = next_member->next;
            }
        }

        if (equal(tok, ","))
            tok = tok->next;
        *rest = skip(tok, "}");
        return;
    }

    // Brace elision remains positional.  A designator is part of an
    // initializer-list grammar and therefore requires braces at this nested
    // level; direct chained designators are handled by the enclosing list.
    if (ty->kind == TY_ARRAY) {
        for (int i = 0; i < ty->array_len; i++) {
            if (i > 0) {
                if (equal(tok, "}"))
                    break;
                tok = skip(tok, ",");
                if (equal(tok, "}"))
                    break;
            }
            if (equal(tok, "[") || equal(tok, "."))
                error_at(tok->loc,
                         "designators in brace-elided nested aggregates require braces");

            Node *child = new_unary(ND_DEREF, new_add(lhs, new_num(i)));
            if (append_automatic_string_array_initializer(tail, child, ty->base,
                                                           &tok, tok))
                continue;
            if (is_initializer_aggregate(ty->base)) {
                parse_automatic_aggregate_subobject(tail, child, ty->base,
                                                     &tok, tok, where);
                continue;
            }

            Node *rhs = assign(&tok, tok);
            Node *a = new_initializer_assign(child, rhs, where);
            *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
        }
    } else {
        int initialized = 0;
        for (Member *m = ty->members; m; m = m->next) {
            if (initialized > 0) {
                if (equal(tok, "}"))
                    break;
                tok = skip(tok, ",");
                if (equal(tok, "}"))
                    break;
            }
            if (equal(tok, "[") || equal(tok, "."))
                error_at(tok->loc,
                         "designators in brace-elided nested aggregates require braces");

            Node *child = new_node(ND_MEMBER);
            child->lhs = lhs;
            child->member = m;
            if (append_automatic_string_array_initializer(tail, child, m->ty,
                                                           &tok, tok)) {
                initialized++;
            } else if (is_initializer_aggregate(m->ty)) {
                parse_automatic_aggregate_subobject(tail, child, m->ty,
                                                     &tok, tok, where);
                initialized++;
            } else {
                Node *rhs = assign(&tok, tok);
                Node *a = new_initializer_assign(child, rhs, where);
                *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
                initialized++;
            }

            if (ty->is_union)
                break;
        }
    }

    *rest = tok;
}static void parse_automatic_designated_initializer(Node **tail, Node *lhs, Type *ty,
                                                    Token **rest, Token *tok,
                                                    Token *where) {
    if (append_automatic_string_array_initializer(tail, lhs, ty, rest, tok))
        return;

    if (is_initializer_aggregate(ty) && equal(tok, "{")) {
        parse_automatic_aggregate_subobject(tail, lhs, ty, rest, tok, where);
        return;
    }

    Node *rhs = assign(&tok, tok);
    Node *a = new_initializer_assign(lhs, rhs, where);
    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
    *rest = tok;
}


// declaration = declspec (declarator ("=" (expr | "{" initializer "}"))?)
//               ("," declarator ("=" (expr | "{" initializer "}"))?)* ";"
static Node *declaration(Token **rest, Token *tok) {
    DeclAttrs attrs = {};
    Type *basety = declspec_with_attrs(&tok, tok, &attrs);
    bool is_static = attrs.is_static;
    bool is_extern = attrs.is_extern;
    if (is_static && is_extern)
        error_at(tok->loc, "declaration cannot be both static and extern");
    if (attrs.align && attrs.is_register)
        error_at(tok->loc, "_Alignas is not allowed on a register object");
    if (equal(tok, ";")) {
        if (attrs.storage_class_count)
            error_at(tok->loc, "storage class specifier requires a declarator");
        if (attrs.align)
            error_at(tok->loc, "_Alignas requires an object declarator");
        if (attrs.is_inline || attrs.is_noreturn)
            error_at(tok->loc, "function specifier requires a function declarator");
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
        if (attrs.align && ty->kind == TY_FUNC)
            error_at(ident->loc, "_Alignas is not allowed on a function declaration");
        if ((attrs.is_inline || attrs.is_noreturn) && ty->kind != TY_FUNC)
            error_at(ident->loc, "function specifier may only declare a function");
        if (ty->kind == TY_VOID)
            error_at(ident->loc, "object cannot have void type");
        bool inferable_array = is_unknown_bound_array_with_complete_element(ty) &&
                               equal(tok, "=");
        if (!is_extern && is_incomplete_object_type(ty) && !inferable_array)
            error_at(ident->loc, "variable has incomplete type");

        char *name = strndup(ident->loc, ident->len);
        Obj *var;
        if (ty->kind == TY_FUNC) {
            if (attrs.is_auto || attrs.is_register || is_static)
                error_at(ident->loc,
                         "block-scope function declaration may only use extern storage class");
            var = create_extern_ref(name, ty);
        } else if (is_static) {
            var = create_static_lvar(name);
            var->ty = ty;
        } else if (is_extern) {
            var = create_extern_ref(name, ty);
        } else {
            var = create_lvar(name);
            var->ty = ty;
        }
        apply_object_alignment(var, ty, attrs.align, ident);

        if (!equal(tok, "="))
            continue;
        tok = tok->next; // skip '='

        Token *after_string = NULL;
        Token *string_tok = string_initializer_token(tok, &after_string);
        if (string_tok && ty->kind == TY_ARRAY) {
            prepare_string_array_type(var, &ty, string_tok);

            if (is_static || is_extern) {
                var->init_data = build_string_array_image(ty, string_tok);
                tok = after_string;
                continue;
            }

            for (int i = 0; i < ty->array_len; i++) {
                int value = 0;
                if (i < string_tok->ty->array_len)
                    value = (unsigned char)string_tok->str[i];
                Node *lhs = new_unary(ND_DEREF,
                                      new_add(new_var_node(var), new_num(i)));
                Node *a = new_initializer_assign(lhs, new_num(value), string_tok);
                block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
            }
            tok = after_string;
            continue;
        }

        // Static/extern: constant initializer only. Brace-enclosed objects
        // use typed byte images plus linker relocations, sharing PR #40's
        // integer-constant-expression array designator parser.
        if (is_static || is_extern) {
            if (equal(tok, "{")) {
                ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
                var->ty = ty;
            } else {
                parse_static_scalar_initializer(var, &tok, tok, ty);
            }
            continue;
        }

        // Brace-enclosed initializer: { expr, expr, ... }
        if (equal(tok, "{")) {
            Token *brace = tok;
            tok = tok->next;

            if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT)
                error_at(brace->loc, "brace initializer requires an aggregate type");

            int cur_idx = 0;
            int max_idx = -1;
            int elem_cap = ty->kind == TY_ARRAY && ty->array_len > 0 ? ty->array_len : 8;
            bool *elem_init = ty->kind == TY_ARRAY ? calloc(elem_cap, sizeof(bool)) : NULL;
            int member_count = ty->kind == TY_STRUCT ? record_member_count(ty) : 0;
            bool *member_init = member_count ? calloc(member_count, sizeof(bool)) : NULL;
            Member *cur_mem = (ty->kind == TY_STRUCT) ? ty->members : NULL;
            Node *before_init = block_cur;
            int initialized_union_members = 0;

            while (!equal(tok, "}")) {
                if (equal(tok, ",")) tok = tok->next;
                if (equal(tok, "}")) break;
                if (ty->kind == TY_STRUCT && ty->is_union && initialized_union_members)
                    error_at(tok->loc, "excess elements in union initializer");

                // Designated initializer-list. A chain such as
                // [1][2], [1].field, .inner.x, or .rows[1] resolves to one
                // nested target before parsing its initializer.
                if (equal(tok, ".") || equal(tok, "[")) {
                    Token *designator = tok;
                    InitializerDesignatorPath path =
                        parse_initializer_designator_path(&tok, tok, ty);
                    AutomaticDesignatedTarget target =
                        apply_automatic_designator_path(new_var_node(var), ty, &path);

                    bool was_initialized = false;
                    if (ty->kind == TY_ARRAY) {
                        if (path.first_index < 0)
                            error_at(designator->loc,
                                     "array initializer designator must start with an index");
                        int idx = path.first_index;
                        while (idx >= elem_cap) {
                            int old_cap = elem_cap;
                            elem_cap *= 2;
                            elem_init = realloc(elem_init, elem_cap * sizeof(bool));
                            memset(elem_init + old_cap, 0,
                                   (elem_cap - old_cap) * sizeof(bool));
                        }
                        was_initialized = elem_init[idx];
                        elem_init[idx] = true;
                        if (idx > max_idx)
                            max_idx = idx;
                        cur_idx = idx + 1;
                    } else {
                        if (!path.first_member)
                            error_at(designator->loc,
                                     "record initializer designator must start with a member");
                        Member *member = path.first_member;
                        int mi = record_member_index(ty, member);
                        if (mi < 0)
                            error_at(designator->loc, "invalid record initializer member");
                        was_initialized = member_init[mi];
                        member_init[mi] = true;
                        cur_mem = member->next;
                        if (ty->is_union)
                            initialized_union_members++;
                    }

                    // A path that enters a nested aggregate initializes that
                    // complete top-level subobject. Zero it on the first path
                    // only; subsequent paths into the same subobject must keep
                    // values written by earlier designators.
                    if (!was_initialized && path.depth > 1 &&
                        is_initializer_aggregate(target.top_ty))
                        append_zero_initializer(&block_cur, target.top_lhs,
                                                target.top_ty, brace);

                    free_initializer_designator_path(&path);
                    parse_automatic_designated_initializer(&block_cur,
                                                           target.lhs, target.ty,
                                                           &tok, tok, brace);
                    continue;
                }

                // Positional initializer
                if (ty->kind == TY_ARRAY) {
                    if (ty->array_len > 0 && cur_idx >= ty->array_len)
                        error_at(tok->loc, "excess elements in array initializer");
                    while (cur_idx >= elem_cap) {
                        int old_cap = elem_cap;
                        elem_cap *= 2;
                        elem_init = realloc(elem_init, elem_cap * sizeof(bool));
                        memset(elem_init + old_cap, 0, (elem_cap - old_cap) * sizeof(bool));
                    }
                    int idx = cur_idx++;
                    elem_init[idx] = true;
                    if (idx > max_idx) max_idx = idx;
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(idx)));
                    if (!append_automatic_string_array_initializer(&block_cur, lhs,
                                                                    ty->base,
                                                                    &tok, tok)) {
                        if (is_initializer_aggregate(ty->base)) {
                            parse_automatic_aggregate_subobject(&block_cur, lhs,
                                                                ty->base, &tok, tok, brace);
                        } else {
                            Node *e = assign(&tok, tok);
                            Node *a = new_initializer_assign(lhs, e, tok);
                            block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                        }
                    }
                } else {
                    if (!cur_mem)
                        error_at(tok->loc, "excess elements in record initializer");
                    int mi = record_member_index(ty, cur_mem);
                    if (mi >= 0) member_init[mi] = true;
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = new_var_node(var);
                    member_node->member = cur_mem;
                    if (!append_automatic_string_array_initializer(&block_cur,
                                                                    member_node,
                                                                    cur_mem->ty,
                                                                    &tok, tok)) {
                        if (is_initializer_aggregate(cur_mem->ty)) {
                            parse_automatic_aggregate_subobject(&block_cur, member_node,
                                                                cur_mem->ty, &tok, tok, brace);
                        } else {
                            Node *e = assign(&tok, tok);
                            Node *a = new_initializer_assign(member_node, e, tok);
                            block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                        }
                    }
                    if (ty->is_union)
                        initialized_union_members++;
                    cur_mem = cur_mem->next;
                }
            }
            tok = skip(tok, "}");

            // Infer array length from the largest initialized subscript, not
            // merely the last designator seen.
            if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                int inferred = max_idx + 1;
                if (inferred <= 0)
                    error_at(brace->loc, "cannot infer array size from empty initializer");
                ty = array_of(ty->base, inferred);
                var->ty = ty;
            }

            // Materialize implicit zero initialization before the explicit
            // initializer expressions while touching only omitted subobjects.
            Node zero_head = {};
            Node *zero_cur = &zero_head;
            if (ty->kind == TY_ARRAY) {
                for (int i = 0; i < ty->array_len; i++) {
                    if (i < elem_cap && elem_init[i]) continue;
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(i)));
                    append_zero_initializer(&zero_cur, lhs, ty->base, brace);
                }
            } else if (ty->is_union) {
                if (!initialized_union_members && ty->members) {
                    Member *m = ty->members;
                    Node *member = new_node(ND_MEMBER);
                    member->lhs = new_var_node(var);
                    member->member = m;
                    append_zero_initializer(&zero_cur, member, m->ty, brace);
                }
            } else {
                int mi = 0;
                for (Member *m = ty->members; m; m = m->next, mi++) {
                    if (mi < member_count && member_init[mi]) continue;
                    Node *member = new_node(ND_MEMBER);
                    member->lhs = new_var_node(var);
                    member->member = m;
                    append_zero_initializer(&zero_cur, member, m->ty, brace);
                }
            }

            if (zero_head.next) {
                Node *explicit_first = before_init->next;
                zero_cur->next = explicit_first;
                before_init->next = zero_head.next;
                if (block_cur == before_init)
                    block_cur = zero_cur;
            }
            free(elem_init);
            free(member_init);
            continue;
        }

        // Simple scalar initializer
        Node *vnode = new_var_node(var);
        Node *rhs = assign(&tok, tok);
        Node *a = new_initializer_assign(vnode, rhs, tok);
        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
    } while (equal(tok, ","));

    *rest = skip(tok, ";");

    if (!block_head.next) return new_node(ND_EXPR_STMT);
    if (!block_head.next->next) return block_head.next;
    Node *block = new_node(ND_BLOCK);
    block->body = block_head.next;
    return block;
}

// Parse C11 _Static_assert(constant-expression, string-literal); at either
// file or block scope. The controlling expression must be an integer constant
// expression and is evaluated entirely during parsing, so no runtime node is
// emitted for a successful assertion.
static Token *parse_static_assertion(Token *tok) {
    Token *keyword = tok;
    tok = skip(tok->next, "(");

    Node *cond = ternary(&tok, tok);
    add_type(cond);
    if (!is_integer(cond->ty))
        error_at(keyword->loc, "_Static_assert requires an integer constant expression");
    int64_t value = eval_const_expr(cond);

    tok = skip(tok, ",");
    if (tok->kind != TK_STR)
        error_at(tok->loc, "_Static_assert requires a string literal message");
    char *message = tok->str;
    tok = skip(tok->next, ")");
    tok = skip(tok, ";");

    if (!value)
        error_at(keyword->loc, "static assertion failed: %s", message);
    return tok;
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

static void require_scalar_condition(Node *cond, Token *keyword,
                                     const char *construct) {
    if (!is_scalar_expr(cond))
        error_at(keyword->loc, "%s condition must have scalar type", construct);
}

static Node *stmt(Token **rest, Token *tok) {
    if (equal(tok, "_Static_assert")) {
        *rest = parse_static_assertion(tok);
        return new_node(ND_EXPR_STMT);
    }

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
        if (current_loop_depth == 0 && !current_switch)
            error_at(tok->loc, "break statement not within loop or switch");
        *rest = skip(tok->next, ";");
        return new_node(ND_BREAK);
    }

    if (equal(tok, "continue")) {
        if (current_loop_depth == 0)
            error_at(tok->loc, "continue statement not within loop");
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
        Token *do_tok = tok;
        Node *node = new_node(ND_DO);
        current_loop_depth++;
        node->then = stmt(&tok, tok->next);
        current_loop_depth--;
        tok = skip(tok, "while");
        tok = skip(tok, "(");
        node->cond = expr(&tok, tok);
        require_scalar_condition(node->cond, do_tok, "do-while");
        tok = skip(tok, ")");
        *rest = skip(tok, ";");
        return node;
    }

    if (equal(tok, "switch")) {
        Token *switch_tok = tok;
        Node *node = new_node(ND_SWITCH);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        add_type(node->cond);
        if (!is_integer(node->cond->ty))
            error_at(switch_tok->loc, "switch condition must have integer type");

        // The controlling expression undergoes integer promotion.  Using int
        // as the second operand requests exactly that promotion for the small
        // integer types supported by this LP64 target.
        node->ty = get_common_type(node->cond->ty, ty_int);
        tok = skip(tok, ")");

        SwitchContext ctx = {};
        ctx.ty = node->ty;
        ctx.prev = current_switch;
        current_switch = &ctx;
        node->then = stmt(rest, tok);
        current_switch = ctx.prev;
        return node;
    }

    if (equal(tok, "case")) {
        Token *case_tok = tok;
        if (!current_switch)
            error_at(case_tok->loc, "case label is not within a switch statement");

        Node *value = ternary(&tok, tok->next);
        add_type(value);
        if (!is_integer(value->ty))
            error_at(case_tok->loc, "case label does not reduce to an integer constant expression");

        int64_t val = eval_const_expr(value);
        val = cast_const_integer(val, current_switch->ty);

        for (CaseValue *cv = current_switch->cases; cv; cv = cv->next)
            if (cv->val == val)
                error_at(case_tok->loc, "duplicate case value");

        CaseValue *cv = calloc(1, sizeof(CaseValue));
        cv->val = val;
        cv->next = current_switch->cases;
        current_switch->cases = cv;

        tok = skip(tok, ":");
        Node *node = new_node(ND_CASE);
        node->val = val;
        node->unique_label = new_unique_name();
        node->lhs = stmt(rest, tok);
        return node;
    }

    if (equal(tok, "default")) {
        Token *default_tok = tok;
        if (!current_switch)
            error_at(default_tok->loc, "default label is not within a switch statement");
        if (current_switch->has_default)
            error_at(default_tok->loc, "multiple default labels in one switch");
        current_switch->has_default = true;

        tok = skip(tok->next, ":");
        Node *node = new_node(ND_DEFAULT);
        node->unique_label = new_unique_name();
        node->lhs = stmt(rest, tok);
        return node;
    }

    if (equal(tok, "if")) {
        Token *if_tok = tok;
        Node *node = new_node(ND_IF);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        require_scalar_condition(node->cond, if_tok, "if");
        tok = skip(tok, ")");
        node->then = stmt(&tok, tok);
        if (equal(tok, "else"))
            node->els = stmt(&tok, tok->next);
        *rest = tok;
        return node;
    }

    if (equal(tok, "while")) {
        Token *while_tok = tok;
        Node *node = new_node(ND_WHILE);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        require_scalar_condition(node->cond, while_tok, "while");
        tok = skip(tok, ")");
        current_loop_depth++;
        node->then = stmt(&tok, tok);
        current_loop_depth--;
        *rest = tok;
        return node;
    }

    if (equal(tok, "for")) {
        Token *for_tok = tok;
        Node *node = new_node(ND_FOR);
        tok = skip(tok->next, "(");
        enter_scope();

        if (equal(tok, ";")) {
            tok = skip(tok, ";");
        } else if (is_decl_start(tok)) {
            node->init = declaration(&tok, tok);
        } else {
            node->init = new_node(ND_EXPR_STMT);
            node->init->lhs = expr(&tok, tok);
            tok = skip(tok, ";");
        }

        if (!equal(tok, ";")) {
            node->cond = expr(&tok, tok);
            require_scalar_condition(node->cond, for_tok, "for");
        }
        tok = skip(tok, ";");

        if (!equal(tok, ")"))
            node->inc = expr(&tok, tok);
        tok = skip(tok, ")");

        current_loop_depth++;
        node->then = stmt(rest, tok);
        current_loop_depth--;
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

    // Declaration (storage classes, qualifiers and alignment specifiers may
    // appear in any declaration-specifier order).
    if (is_decl_start(tok))
        return declaration(rest, tok);

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

static bool qualifier_superset(Type *dst, Type *src) {
    return dst && src &&
           (!src->is_const || dst->is_const) &&
           (!src->is_volatile || dst->is_volatile) &&
           (!src->is_restrict || dst->is_restrict);
}

static bool pointed_assignment_compatible(Type *dst, Type *src) {
    if (!dst || !src || !qualifier_superset(dst, src))
        return false;
    if (type_compatible_ignoring_top_qual(dst, src))
        return true;

    bool dst_void = dst->kind == TY_VOID;
    bool src_void = src->kind == TY_VOID;
    bool dst_func = dst->kind == TY_FUNC;
    bool src_func = src->kind == TY_FUNC;
    return !dst_func && !src_func && (dst_void || src_void);
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
        return pointed_assignment_compatible(dst->base, src->base);

    if (src->kind != TY_PTR)
        return false;
    return pointed_assignment_compatible(dst->base, src->base);
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

static Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at) {
    add_type(lhs);
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(at->loc, "incompatible types in initializer");
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

static bool cast_compatible(Type *dst, Node *expr) {
    add_type(expr);

    // A cast to void explicitly discards the value and accepts any complete
    // expression type, including aggregates and void-valued expressions.
    if (dst && dst->kind == TY_VOID)
        return true;

    Type *src = decay_value_type(expr->ty);
    if (!dst || !src)
        return false;

    // Non-void cast targets must be scalar.  Arrays/functions have already
    // decayed above when they appear as values.
    bool dst_arith = is_numeric(dst);
    bool src_arith = is_numeric(src);
    bool dst_ptr = dst->kind == TY_PTR;
    bool src_ptr = src->kind == TY_PTR;

    if (dst_arith && src_arith)
        return true;
    if (dst_ptr && src_ptr)
        return true;
    if (dst_ptr && is_integer(src))
        return true;
    if (is_integer(dst) && src_ptr)
        return true;
    return false;
}

static bool pointer_pair_compatible(Type *a, Type *b, bool relational_only) {
    a = decay_value_type(a);
    b = decay_value_type(b);
    if (!a || !b || a->kind != TY_PTR || b->kind != TY_PTR)
        return false;

    if (type_compatible_ignoring_top_qual(a->base, b->base)) {
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
        bool merged_const = tt->base->is_const || et->base->is_const;
        bool merged_volatile = tt->base->is_volatile || et->base->is_volatile;
        bool merged_restrict = tt->base->is_restrict || et->base->is_restrict;

        if (type_compatible_ignoring_top_qual(tt->base, et->base))
            return pointer_to(qualify_type(tt->base, merged_const, merged_volatile,
                                           merged_restrict));

        bool t_void = tt->base && tt->base->kind == TY_VOID;
        bool e_void = et->base && et->base->kind == TY_VOID;
        bool t_func = tt->base && tt->base->kind == TY_FUNC;
        bool e_func = et->base && et->base->kind == TY_FUNC;
        if (!t_func && !e_func && (t_void || e_void))
            return pointer_to(qualify_type(ty_void, merged_const, merged_volatile, false));
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
        Token *cast_tok = tok;
        tok = tok->next;
        Type *ty = type_name(&tok, tok);
        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
            (ty->kind != TY_VOID && !is_numeric(ty) && ty->kind != TY_PTR))
            error_at(cast_tok->loc, "cast specifies non-scalar type");
        tok = skip(tok, ")");
        Node *operand = unary(rest, tok);
        if (!cast_compatible(ty, operand))
            error_at(cast_tok->loc, "invalid cast operand type");
        Node *node = new_unary(ND_CAST, operand);
        node->ty = ty;
        return node;
    }

    if (equal(tok, "+"))  return new_unary(ND_POS, unary(rest, tok->next));
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

static Node *cast_call_argument(Node *arg, Type *ty) {
    if (!ty || arg->ty == ty)
        return arg;
    Node *cast = new_unary(ND_CAST, arg);
    cast->ty = ty;
    return cast;
}

// Keep the record-ABI gate shape-aware: <=16-byte records use per-eightbyte
// INTEGER/SSE lowering and larger complete records use the SysV MEMORY class.
// Prototypes remain representable even before an ABI boundary is crossed.
static void check_supported_function_abi(Type *fty, Token *at) {
    if (!fty || fty->kind != TY_FUNC)
        return;

    if (fty->return_ty && fty->return_ty->kind == TY_STRUCT &&
        !supported_record_abi(fty->return_ty))
        error_at(at->loc, "unsupported record return ABI for x86-64 backend");

    if (!fty->has_prototype)
        return;
    for (Obj *param = fty->params; param; param = param->param_next)
        if (param->ty && param->ty->kind == TY_STRUCT &&
            !supported_record_abi(param->ty))
            error_at(at->loc, "unsupported record parameter ABI for x86-64 backend");
}

// Parse a call's comma-separated argument list after the opening parenthesis.
// All call forms use this one path so prototype arity, assignment compatibility,
// numeric coercion, and default argument promotions cannot drift apart.
static Node *parse_call_arguments(Token **rest, Token *tok, Type *fty) {
    Obj *expected = fty && fty->has_prototype ? fty->params : NULL;
    bool has_prototype = fty && fty->has_prototype;
    bool variadic = fty && fty->is_variadic;

    Node head = {};
    Node *cur = &head;
    while (!equal(tok, ")")) {
        if (cur != &head)
            tok = skip(tok, ",");

        if (has_prototype && !expected && !variadic)
            error_at(tok->loc, "too many arguments");

        Token *arg_tok = tok;
        Node *arg = assign(&tok, tok);
        add_type(arg);

        // Unprototyped calls and variadic tails have no declared parameter to
        // inspect, so classify aggregate actuals directly before codegen.
        if (arg->ty && arg->ty->kind == TY_STRUCT &&
            !supported_record_abi(arg->ty))
            error_at(arg_tok->loc, "unsupported record argument ABI for x86-64 backend");

        if (expected) {
            if (!assignment_compatible(expected->ty, arg))
                error_at(tok->loc, "incompatible argument type");
            if (is_numeric(arg->ty) && is_numeric(expected->ty))
                arg = cast_call_argument(arg, expected->ty);
            expected = expected->param_next;
        } else if (!has_prototype || variadic) {
            // C default argument promotions apply to every argument of an
            // unprototyped call and to the variadic tail after fixed params.
            Type *promoted = default_argument_promotion(arg->ty);
            if (promoted)
                arg = cast_call_argument(arg, promoted);
        }

        cur = cur->next = arg;
    }

    if (has_prototype && expected)
        error_at(tok->loc, "too few arguments");

    *rest = skip(tok, ")");
    return head.next;
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
    check_supported_function_abi(fty, tok);

    Node *node = new_node(ND_FUNCALL);
    node->funcname = NULL;
    node->lhs = callee;
    node->ty = fty->return_ty;

    tok = skip(tok, "(");
    node->args = parse_call_arguments(&tok, tok, fty);
    prepare_record_call_result(node);
    *rest = tok;
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
    if (equal(tok, "__builtin_va_start")) {
        Token *builtin = tok;
        if (!current_function_variadic)
            error_at(builtin->loc, "va_start is only valid in a variadic function");
        tok = skip(tok->next, "(");
        Node *ap = assign(&tok, tok);
        add_type(ap);
        if (!ap->ty || ap->ty->kind != TY_PTR || !ap->ty->base ||
            ap->ty->base->kind != TY_STRUCT)
            error_at(builtin->loc, "va_start requires a va_list object");
        tok = skip(tok, ")");
        Node *node = new_unary(ND_VA_START, ap);
        node->ty = ty_void;
        *rest = tok;
        return node;
    }

    if (equal(tok, "__builtin_va_arg")) {
        Token *builtin = tok;
        if (!current_function_variadic)
            error_at(builtin->loc, "va_arg is only valid in a variadic function");
        tok = skip(tok->next, "(");
        Node *ap = assign(&tok, tok);
        add_type(ap);
        if (!ap->ty || ap->ty->kind != TY_PTR || !ap->ty->base ||
            ap->ty->base->kind != TY_STRUCT)
            error_at(builtin->loc, "va_arg requires a va_list object");
        tok = skip(tok, ",");
        Type *ty = type_name(&tok, tok);
        tok = skip(tok, ")");

        // Default-promoted scalar types continue to use one GP/SSE slot.
        // Records use the same INTEGER/SSE/MEMORY classifier as ordinary calls
        // and are materialized into an anonymous local result object.
        bool gp = ty->kind == TY_PTR || (is_integer(ty) && ty->size >= 4);
        bool fp = ty->kind == TY_DOUBLE;
        bool record = ty->kind == TY_STRUCT && supported_record_abi(ty);
        if (!gp && !fp && !record)
            error_at(builtin->loc, "unsupported or unpromoted type in va_arg");

        Node *node = new_unary(ND_VA_ARG, ap);
        node->ty = ty;
        if (record) {
            Obj *buf = create_lvar(new_unique_name());
            buf->ty = ty;
            node->ret_buffer = buf;
        }
        *rest = tok;
        return node;
    }

    if (equal(tok, "_Generic")) {
        Token *op = tok;
        tok = skip(tok->next, "(");
        Node *control = assign(&tok, tok);
        add_type(control);
        tok = skip(tok, ",");

        typedef struct GenericType GenericType;
        struct GenericType {
            GenericType *next;
            Type *ty;
        };

        GenericType *seen = NULL;
        Node *selected = NULL;
        Node *default_expr = NULL;
        bool have_assoc = false;

        for (;;) {
            have_assoc = true;
            if (equal(tok, "default")) {
                if (default_expr)
                    error_at(tok->loc, "duplicate default generic association");
                tok = skip(tok->next, ":");
                default_expr = assign(&tok, tok);
            } else {
                if (!is_typename(tok))
                    error_at(tok->loc, "expected type name or default in _Generic");
                Token *type_tok = tok;
                Type *assoc_ty = type_name(&tok, tok);
                if (!assoc_ty || assoc_ty->kind == TY_VOID || assoc_ty->kind == TY_FUNC ||
                    assoc_ty->is_incomplete ||
                    (assoc_ty->kind == TY_ARRAY && assoc_ty->array_len == 0))
                    error_at(type_tok->loc,
                             "generic association requires a complete object type");

                for (GenericType *g = seen; g; g = g->next)
                    if (type_compatible(g->ty, assoc_ty))
                        error_at(type_tok->loc,
                                 "duplicate compatible type in generic association");
                GenericType *g = calloc(1, sizeof(GenericType));
                g->ty = assoc_ty;
                g->next = seen;
                seen = g;

                tok = skip(tok, ":");
                Node *expr_node = assign(&tok, tok);
                if (type_compatible(control->ty, assoc_ty)) {
                    if (selected)
                        error_at(type_tok->loc,
                                 "controlling type matches multiple generic associations");
                    selected = expr_node;
                }
            }

            if (!equal(tok, ","))
                break;
            tok = tok->next;
        }

        if (!have_assoc)
            error_at(op->loc, "_Generic requires at least one association");
        tok = skip(tok, ")");
        if (!selected)
            selected = default_expr;
        if (!selected)
            error_at(op->loc, "no matching generic association");

        *rest = tok;
        return selected;
    }

    if (equal(tok, "(")) {
        Node *node = expr(&tok, tok->next);
        *rest = skip(tok, ")");
        return node;
    }

    if (equal(tok, "_Alignof")) {
        Token *op = tok;
        tok = skip(tok->next, "(");
        if (!is_typename(tok))
            error_at(op->loc, "_Alignof requires a type name");
        Type *ty = type_name(&tok, tok);
        if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC ||
            is_incomplete_object_type(ty))
            error_at(op->loc, "invalid type for _Alignof");
        *rest = skip(tok, ")");
        return new_size_t_num(ty->align);
    }

    if (equal(tok, "sizeof")) {
        tok = tok->next;
        if (equal(tok, "(") && is_typename(tok->next)) {
            tok = tok->next;
            Type *ty = type_name(&tok, tok);
            if (invalid_sizeof_type(ty))
                error_at(tok->loc, "invalid operand type for sizeof");
            *rest = skip(tok, ")");
            return new_size_t_num(ty->size);
        }
        Node *n = unary(rest, tok);
        add_type(n);
        if (invalid_sizeof_type(n->ty))
            error_at(tok->loc, "invalid operand type for sizeof");
        return new_size_t_num(n->ty->size);
    }

    if (tok->kind == TK_IDENT) {
        // Check for an enumeration constant visible in lexical scope.
        EnumConst *ec = find_enum_const(tok);
        if (ec) {
            *rest = tok->next;
            return new_num(ec->val);
        }

        // Direct function calls keep a named callee for codegen. A variable
        // of function-pointer type falls through to ND_VAR and is handled by
        // the ordinary postfix-call path, sharing the same argument parser.
        if (equal(tok->next, "(")) {
            Obj *fn = find_var(tok);
            if (!fn && find_typedef(tok))
                error_at(tok->loc, "typedef name is not callable");
            if (!fn || fn->is_function) {
                Node *node = new_node(ND_FUNCALL);
                node->funcname = strndup(tok->loc, tok->len);

                Type *fty = NULL;
                if (fn && fn->ty && fn->ty->kind == TY_FUNC) {
                    fty = fn->ty;
                    node->ty = fty->return_ty;
                }
                check_supported_function_abi(fty, tok);

                tok = skip(tok->next, "(");
                node->args = parse_call_arguments(&tok, tok, fty);
                prepare_record_call_result(node);
                *rest = tok;
                return node;
            }
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
        var->is_string_literal = true;
        var->next = globals;
        globals = var;

        Node *node = new_var_node(var);
        *rest = tok->next;
        return node;
    }

    if (tok->kind == TK_NUM) {
        Node *node = new_num(tok->val);
        if (tok->is_float)
            node->fval = tok->fval;
        if (tok->ty)
            node->ty = tok->ty;
        *rest = tok->next;
        return node;
    }

    error_at(tok->loc, "expected an expression");
    return NULL;
}

static Node *compound_stmt(Token **rest, Token *tok) {
    // The caller creates the function-definition scope before binding parameters.
    // Keep the outermost compound statement in that same scope so a declaration
    // cannot redeclare a parameter; nested `{ ... }` statements still create
    // ordinary child block scopes in stmt().
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

static Type *type_identity(Type *ty) {
    return ty && ty->origin ? ty->origin : ty;
}

static bool type_compatible_impl(Type *a, Type *b, bool ignore_top_qual) {
    if (a == b)
        return true;
    if (!a || !b || a->kind != b->kind)
        return false;
    if (!ignore_top_qual &&
        (a->is_const != b->is_const || a->is_volatile != b->is_volatile ||
         a->is_restrict != b->is_restrict))
        return false;

    switch (a->kind) {
    case TY_CHAR:
        return a->is_unsigned == b->is_unsigned &&
               a->is_plain_char == b->is_plain_char;
    case TY_SHORT:
    case TY_INT:
    case TY_LONG:
    case TY_LLONG:
        return a->is_unsigned == b->is_unsigned;
    case TY_PTR:
        return type_compatible_impl(a->base, b->base, false);
    case TY_ARRAY:
        return type_compatible_impl(a->base, b->base, false) &&
               (!a->array_len || !b->array_len || a->array_len == b->array_len);
    case TY_STRUCT:
        return type_identity(a) == type_identity(b);
    case TY_FUNC: {
        if (!type_compatible_impl(a->return_ty, b->return_ty, false))
            return false;

        // Two unprototyped function types are compatible. If exactly one
        // side has a prototype, C additionally requires a non-variadic prototype
        // whose parameter types are unchanged by the default argument promotions.
        if (!a->has_prototype || !b->has_prototype) {
            if (!a->has_prototype && !b->has_prototype)
                return true;
            Type *proto = a->has_prototype ? a : b;
            return prototype_compatible_with_unprototyped(proto);
        }
        if (a->is_variadic != b->is_variadic)
            return false;

        Obj *pa = a->params;
        Obj *pb = b->params;
        while (pa && pb) {
            if (!type_compatible_impl(pa->ty, pb->ty, true))
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

static bool type_compatible(Type *a, Type *b) {
    return type_compatible_impl(a, b, false);
}

static bool type_compatible_ignoring_top_qual(Type *a, Type *b) {
    return type_compatible_impl(a, b, true);
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
    return var->has_init_val || var->has_init_reloc || var->init_image ||
           var->init_vals_count > 0 || var->init_data;
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
        bind_var_in_current_scope(var->name, var, true);
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
    bind_var_in_current_scope(var->name, var, false);
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
        check_oldstyle_definition_redeclaration(var, fty, is_definition, name);
        if (!type_compatible(var->ty, fty))
            error("conflicting types for function '%s'", name);
        if (is_static && !var->is_static)
            error("static declaration of '%s' follows non-static declaration", name);
        if (is_definition && var->is_defined)
            error("redefinition of function '%s'", name);

        var->ty = composite_redecl_type(var->ty, fty);
        var->is_static = var->is_static || is_static;
        var->is_defined = var->is_defined || is_definition;
        bind_var_in_current_scope(var->name, var, true);
        return;
    }

    Obj *fn_obj = calloc(1, sizeof(Obj));
    fn_obj->name = strdup(name);
    fn_obj->ty = fty;
    fn_obj->is_local = false;
    fn_obj->is_function = true;
    fn_obj->is_static = is_static;
    fn_obj->is_defined = is_definition;
    fn_obj->next = globals;
    globals = fn_obj;
    bind_var_in_current_scope(fn_obj->name, fn_obj, false);
}

// C99 defines __func__ inside every function as if the implementation inserted
// `static const char __func__[] = "function-name";` immediately after the
// opening brace. Model it as one compiler-generated static object bound in the
// function scope so array extent, pointer identity, and const element semantics
// all follow ordinary variable rules.
static void bind_predefined_func_name(const char *name) {
    Obj *var = calloc(1, sizeof(Obj));
    var->name = new_unique_name();
    var->ty = array_of(qualify_type(ty_char, true, false, false), strlen(name) + 1);
    var->is_local = false;
    var->is_static = true;
    var->is_string_literal = true;
    var->init_data = strdup(name);
    var->next = globals;
    globals = var;
    bind_var_in_current_scope("__func__", var, false);
}

// program = (function | global-var | typedef)*
Program *parse(Token *tok) {
    globals = NULL;
    Function head = {};
    Function *cur = &head;

    current_scope = calloc(1, sizeof(Scope));
    current_loop_depth = 0;

    while (tok->kind != TK_EOF) {
        if (equal(tok, "_Static_assert")) {
            tok = parse_static_assertion(tok);
            continue;
        }

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

        DeclAttrs attrs = {};
        Type *basety = declspec_with_attrs(&tok, tok, &attrs);
        bool is_static = attrs.is_static;
        bool is_extern = attrs.is_extern;
        if (is_static && is_extern)
            error_at(tok->loc, "declaration cannot be both static and extern");
        if (attrs.is_auto)
            error_at(tok->loc, "auto storage class is not allowed at file scope");
        if (attrs.is_register)
            error_at(tok->loc, "register storage class is not allowed at file scope");

        // Standalone type declaration
        if (consume(&tok, tok, ";")) {
            if (attrs.storage_class_count)
                error_at(tok->loc, "storage class specifier requires a declarator");
            if (attrs.align)
                error_at(tok->loc, "_Alignas requires an object declarator");
            if (attrs.is_inline || attrs.is_noreturn)
                error_at(tok->loc, "function specifier requires a function declarator");
            continue;
        }

        Token *ident;
        Type *ty = declarator(&tok, tok, basety, &ident);
        if ((attrs.is_inline || attrs.is_noreturn) && ty->kind != TY_FUNC)
            error_at(ident->loc, "function specifier may only declare a function");
        if (ty->kind == TY_VOID)
            error_at(ident->loc, "object cannot have void type");

        if (ty->kind == TY_FUNC) {
            if (attrs.align)
                error_at(ident->loc, "_Alignas is not allowed on a function declaration");
            char *name = strndup(ident->loc, ident->len);
            bool is_definition = !equal(tok, ";");

            // Prototypes may describe ABI shapes the educational backend does
            // not lower yet, but a definition would immediately require the
            // callee side of that ABI and must therefore be diagnosed.
            if (is_definition) {
                if (is_incomplete_object_type(ty->return_ty))
                    error_at(ident->loc,
                             "function definition has incomplete return type");
                for (Obj *meta = ty->params; meta; meta = meta->param_next)
                    if (is_incomplete_object_type(meta->ty))
                        error_at(ident->loc,
                                 "function definition has incomplete parameter type");
                check_supported_function_abi(ty, ident);
            }

            // Register the declaration before parsing a body so recursion and
            // function-address expressions inside the definition see it.
            register_function_symbol(name, ty->return_ty, is_static,
                                     ty->params, ty->is_variadic, ty->has_prototype,
                                     is_definition);

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
            bind_predefined_func_name(name);

            Function *fn = calloc(1, sizeof(Function));
            fn->name = name;
            fn->params = param_head.param_next;
            fn->return_ty = ty->return_ty;
            fn->is_static = is_static;
            fn->is_variadic = ty->is_variadic;

            Type *saved_return_ty = current_return_ty;
            bool saved_variadic = current_function_variadic;
            current_return_ty = ty->return_ty;
            current_function_variadic = ty->is_variadic;
            Node *block = compound_stmt(&tok, tok);
            current_return_ty = saved_return_ty;
            current_function_variadic = saved_variadic;
            fn->body = block->body;
            fn->locals = locals;

            resolve_gotos();
            fn->gotos = current_gotos;
            fn->labels = current_labels;

            leave_scope();
            cur = cur->next = fn;
        } else {
            if (attrs.is_noreturn)
                error_at(ident->loc, "_Noreturn may only declare a function");
            // Global variable(s) (possibly with initializer)
            for (;;) {
                if (!is_extern && is_incomplete_object_type(ty) &&
                    !is_unknown_bound_array_with_complete_element(ty))
                    error_at(ident->loc, "variable has incomplete type");

                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);
                apply_object_alignment(var, ty, attrs.align, ident);
                ty = var->ty;

                if (equal(tok, "=") && object_has_initializer(var))
                    error_at(ident->loc, "redefinition of global '%s'", var->name);

                if (consume(&tok, tok, "=")) {
                    Token *after_string = NULL;
                    Token *string_tok = string_initializer_token(tok, &after_string);
                    if (string_tok && ty->kind == TY_ARRAY) {
                        if (!is_character_array(ty))
                            error_at(string_tok->loc,
                                     "global string initializer is supported only for character arrays");
                        prepare_string_array_type(var, &ty, string_tok);
                        var->init_data = build_string_array_image(ty, string_tok);
                        tok = after_string;
                    } else if (equal(tok, "{")) {
                        ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
                        var->ty = ty;
                    } else {
                        parse_static_scalar_initializer(var, &tok, tok, ty);
                    }
                }

                if (!consume(&tok, tok, ","))
                    break;
                ty = declarator(&tok, tok, basety, &ident);
            }
            tok = skip(tok, ";");
        }
    }

    // A file-scope tentative definition with incomplete array type is
    // completed as a one-element array if no later declaration supplied a
    // bound. Pure extern declarations remain incomplete and allocate nothing.
    for (Obj *var = globals; var; var = var->next) {
        if (var->is_function || var->is_extern)
            continue;
        if (is_unknown_bound_array_with_complete_element(var->ty))
            var->ty = array_of(var->ty->base, 1);
    }

    Program *prog = calloc(1, sizeof(Program));
    prog->globals = globals;
    prog->fns = head.next;
    return prog;
}
