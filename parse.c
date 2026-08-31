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

typedef struct VmGuard VmGuard;
struct VmGuard {
    // Active variably-modified identifiers form a persistent chain. A goto may
    // target only a prefix of the source chain; otherwise it would enter the
    // scope of an identifier whose variably-modified declaration was skipped.
    VmGuard *parent;
    Obj *stack_save; // pre-allocation RSP checkpoint for a materialized VLA
    char *name;
};

typedef struct Scope Scope;
struct Scope {
    Scope *parent;
    VarScope *vars;
    StructTag *tags;
    TypeDef *typedefs;
    EnumConst *enum_consts;
    // First VLA in a lexical scope snapshots RSP here. All VLA allocations in
    // that scope are discarded together when the scope is exited.
    Obj *vla_stack_save;
    // Guard chain visible when this lexical scope was entered. Leaving the
    // block restores that exact declaration-scope frontier.
    VmGuard *vm_guard_entry;
};

static Scope *current_scope;
static VmGuard *current_vm_guard;

static bool type_compatible(Type *a, Type *b);
static Type *composite_redecl_type(Type *old_ty, Type *new_ty);
static Obj *find_global_symbol(const char *name);

static void enter_scope(void) {
    Scope *sc = calloc(1, sizeof(Scope));
    sc->parent = current_scope;
    sc->vm_guard_entry = current_vm_guard;
    current_scope = sc;
}

static void leave_scope(void) {
    Scope *leaving = current_scope;
    current_vm_guard = leaving->vm_guard_entry;
    current_scope = leaving->parent;
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
    return name && tok->kind == TK_IDENT && strlen(name) == (size_t)tok->len &&
           !strncmp(tok->loc, name, tok->len);
}

typedef struct MemberPath MemberPath;
struct MemberPath {
    Member *member;
    MemberPath *next;
};

static MemberPath *find_record_member_path_in_list(Member *members, Token *tok) {
    // Prefer a direct member. C11 uniqueness constraints make the result
    // unambiguous, but direct-first also keeps diagnostics deterministic.
    for (Member *m = members; m; m = m->next) {
        if (m->name && token_matches_name(tok, m->name)) {
            MemberPath *path = calloc(1, sizeof(MemberPath));
            path->member = m;
            return path;
        }
    }

    for (Member *m = members; m; m = m->next) {
        if (!m->is_anonymous || !m->ty || m->ty->kind != TY_STRUCT)
            continue;
        MemberPath *sub = find_record_member_path_in_list(m->ty->members, tok);
        if (!sub)
            continue;
        MemberPath *path = calloc(1, sizeof(MemberPath));
        path->member = m;
        path->next = sub;
        return path;
    }
    return NULL;
}

static MemberPath *find_record_member_path(Type *ty, Token *tok) {
    if (!ty || ty->kind != TY_STRUCT || ty->is_incomplete)
        return NULL;
    return find_record_member_path_in_list(ty->members, tok);
}

static void free_member_path(MemberPath *path) {
    while (path) {
        MemberPath *next = path->next;
        free(path);
        path = next;
    }
}

static bool member_list_has_visible_name(Member *members, const char *name) {
    for (Member *m = members; m; m = m->next) {
        if (m->name && !strcmp(m->name, name))
            return true;
        if (m->is_anonymous && m->ty && m->ty->kind == TY_STRUCT &&
            member_list_has_visible_name(m->ty->members, name))
            return true;
    }
    return false;
}

static const char *anonymous_member_conflict(Member *existing, Type *candidate) {
    if (!candidate || candidate->kind != TY_STRUCT)
        return NULL;
    for (Member *m = candidate->members; m; m = m->next) {
        if (m->is_anonymous) {
            const char *conflict = anonymous_member_conflict(existing, m->ty);
            if (conflict)
                return conflict;
            continue;
        }
        if (m->name && member_list_has_visible_name(existing, m->name))
            return m->name;
    }
    return NULL;
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

static bool push_typedef(Token *ident, Type *ty) {
    char *name = strndup(ident->loc, ident->len);
    if (find_var_name_in_scope(current_scope, name) ||
        find_enum_name_in_scope(current_scope, name))
        error_at(ident->loc, "typedef name conflicts with ordinary identifier");

    TypeDef *old = find_typedef_name_in_scope(current_scope, name);
    if (old) {
        if (!type_compatible(old->ty, ty))
            error_at(ident->loc, "conflicting typedef for '%s'", name);
        free(name);
        return false;
    }

    TypeDef *td = calloc(1, sizeof(TypeDef));
    td->name = name;
    td->ty = ty;
    td->next = current_scope->typedefs;
    current_scope->typedefs = td;
    return true;
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

typedef struct JumpMeta JumpMeta;
struct JumpMeta {
    JumpMeta *next;
    Node *node;
    VmGuard *guard;
};

static JumpMeta *current_goto_meta;
static JumpMeta *current_label_meta;

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
    bool is_thread_local;
    bool is_typedef;
    bool is_inline;
    bool is_noreturn;
    bool has_anonymous_record_specifier;
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
static Token *parse_static_assertion(Token *tok);
static Type *type_name(Token **rest, Token *tok);
static bool type_compatible(Type *a, Type *b);
static bool type_compatible_ignoring_top_qual(Type *a, Type *b);
static bool assignment_compatible(Type *dst, Node *rhs);
static bool is_scalar_expr(Node *node);
static Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at);
static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op);
static bool type_is_variably_modified(Type *ty);
static Node *vla_size_expression(Type *ty);

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
static Scope *current_break_scope;
static Scope *current_continue_scope;

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
    if (equal(tok, "auto") || equal(tok, "static") || equal(tok, "extern") ||
        equal(tok, "typedef")) return true;
    if (equal(tok, "const") || equal(tok, "volatile") || equal(tok, "restrict")) return true;
    if (equal(tok, "register") || equal(tok, "inline") ||
        equal(tok, "_Thread_local")) return true;
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
    case ND_COMPOUND_LITERAL:
        return node->ty && node->ty->kind != TY_FUNC && node->ty->kind != TY_VOID;
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

// `register` forbids applying unary & to the declared object. Member
// access still depends on the containing object, so `&r.member` must reject
// when `r` itself is register-qualified. Dereference breaks that chain:
// taking `&*p` or `&p->member` is valid even when the pointer object `p` was
// declared register, because the addressed object is the pointee.
static bool is_register_based_lvalue(Node *node) {
    if (!node)
        return false;
    if (node->kind == ND_VAR)
        return node->var && node->var->is_register;
    if (node->kind == ND_MEMBER)
        return is_register_based_lvalue(node->lhs);
    return false;
}

// Outside sizeof and unary &, an array expression undergoes the standard
// array-to-pointer conversion. For a register array that conversion requires
// the address that the storage-class contract intentionally makes unavailable.
// Diagnose the otherwise-undefined C11 case, matching strict host compilers.
// Member arrays inherit the restriction from a register aggregate root, while
// dereference deliberately breaks that chain (the array then belongs to the
// pointed-to object, not to the register pointer variable).
static bool is_register_array_designator(Node *node) {
    if (!node)
        return false;
    add_type(node);
    return node->ty && node->ty->kind == TY_ARRAY &&
           is_register_based_lvalue(node);
}

static void reject_register_array_decay(Node *node) {
    if (is_register_array_designator(node))
        error("register array cannot be converted to a pointer value");
}

static bool is_addressable_expr(Node *node) {
    add_type(node);

    if (node->kind == ND_MEMBER && node->member && node->member->is_bitfield)
        return false;

    // A function designator is not an lvalue in C, but unary & is explicitly
    // permitted on one. Both a named function and *function_pointer reach
    // here with TY_FUNC.
    if (node->ty->kind == TY_FUNC)
        return node->kind == ND_VAR || node->kind == ND_DEREF;
    if (!is_lvalue(node))
        return false;
    return !is_register_based_lvalue(node);
}

// The controlling expression of a C11 generic selection is not
// evaluated, but it is still in an ordinary value context. Array and function
// designators therefore decay to pointers, and top-level object qualifiers are
// removed by value conversion. Qualifiers nested below a pointer remain part of
// the controlling type and must still participate in association matching.
static Type *generic_control_type(Node *node) {
    add_type(node);
    reject_register_array_decay(node);
    Type *ty = node->ty;
    if (!ty)
        return NULL;
    if (ty->kind == TY_ARRAY)
        return pointer_to(ty->base);
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    if (ty->is_const || ty->is_volatile || ty->is_restrict)
        return ty->origin ? ty->origin : ty;
    return ty;
}

static Node *new_checked_addr(Node *operand, Token *op) {
    if (!is_addressable_expr(operand))
        error_at(op->loc, "address-of operand is not an lvalue or function designator");
    return new_unary(ND_ADDR, operand);
}

static Node *new_checked_deref(Node *operand, Token *op) {
    add_type(operand);
    reject_register_array_decay(operand);

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
    if (base->kind == TY_VOID || base->kind == TY_FUNC || base->is_incomplete)
        return NULL;
    if (base->size <= 0 &&
        !(base->kind == TY_ARRAY && type_is_variably_modified(base)))
        return NULL;
    return ty;
}

static Node *pointer_stride_expression(Type *ptr) {
    if (!ptr || ptr->kind != TY_PTR || !ptr->base)
        error("internal error: pointer stride requested for non-pointer type");
    if (ptr->base->kind == TY_ARRAY && type_is_variably_modified(ptr->base))
        return vla_size_expression(ptr->base);
    return new_size_t_num(ptr->base->size);
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
                                new_binary(ND_MUL, rhs,
                                           pointer_stride_expression(lp)));
        node->ty = lp;
        return node;
    }

    if (is_integer(lhs->ty) && rp) {
        Node *node = new_binary(ND_ADD, rhs,
                                new_binary(ND_MUL, lhs,
                                           pointer_stride_expression(rp)));
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
                                new_binary(ND_MUL, rhs,
                                           pointer_stride_expression(lp)));
        node->ty = lp;
        return node;
    }

    if (lp && rp) {
        if (!type_compatible_ignoring_top_qual(lp->base, rp->base))
            error("incompatible pointer subtraction");

        Node *diff = new_binary(ND_SUB, lhs, rhs);
        diff->ty = ty_long;
        Node *node = new_binary(ND_DIV, diff, pointer_stride_expression(lp));
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
            rhs = new_binary(ND_MUL, rhs, pointer_stride_expression(ptr));
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
    Type *ptr = pointer_arithmetic_type(expr->ty);
    if (!is_numeric(expr->ty) && !ptr)
        error("invalid increment/decrement operand");
    Node *node = new_unary(kind, expr);
    if (ptr && ptr->base->kind == TY_ARRAY &&
        type_is_variably_modified(ptr->base))
        node->rhs = pointer_stride_expression(ptr);
    return node;
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

static Node *new_vla_stack_node(NodeKind kind, Obj *slot) {
    Node *node = new_node(kind);
    node->var = slot;
    return node;
}

static VmGuard *push_vm_guard(Token *ident) {
    VmGuard *guard = calloc(1, sizeof(VmGuard));
    guard->parent = current_vm_guard;
    if (ident)
        guard->name = strndup(ident->loc, ident->len);
    current_vm_guard = guard;
    return guard;
}

static void note_jump_meta(JumpMeta **list, Node *node) {
    JumpMeta *meta = calloc(1, sizeof(JumpMeta));
    meta->node = node;
    meta->guard = current_vm_guard;
    meta->next = *list;
    *list = meta;
}

static VmGuard *jump_guard_for(JumpMeta *list, Node *node) {
    for (JumpMeta *meta = list; meta; meta = meta->next)
        if (meta->node == node)
            return meta->guard;
    return NULL;
}

// A target is legal only when every variably-modified identifier active at the
// target is already active at the goto statement. In the persistent guard
// chain that means target must be an ancestor (prefix) of source.
static bool vm_guard_target_is_active(VmGuard *source, VmGuard *target) {
    if (!target)
        return true;
    for (VmGuard *guard = source; guard; guard = guard->parent)
        if (guard == target)
            return true;
    return false;
}

// Walk declarations exited by a legal goto. The final checkpoint encountered
// is the oldest exited dynamic allocation, which restores RSP to exactly the
// target frontier while retaining all VLAs that are still active there.
static Obj *vm_guard_restore_between(VmGuard *source, VmGuard *target) {
    Obj *restore = NULL;
    for (VmGuard *guard = source; guard && guard != target; guard = guard->parent)
        if (guard->stack_save)
            restore = guard->stack_save;
    return restore;
}

// Return the outermost VLA stack snapshot among scopes exited when control
// transfers from `from` to (but not including) `target`.
static Obj *vla_restore_between(Scope *from, Scope *target) {
    Obj *restore = NULL;
    for (Scope *sc = from; sc && sc != target; sc = sc->parent)
        if (sc->vla_stack_save)
            restore = sc->vla_stack_save;
    return restore;
}

static Node *vla_size_expression(Type *ty) {
    if (!ty || ty->kind != TY_ARRAY || !type_is_variably_modified(ty))
        return new_size_t_num(ty ? ty->size : 0);
    if (ty->vla_size)
        return new_var_node(ty->vla_size);

    Node *count = NULL;
    if (ty->is_vla) {
        if (!ty->vla_len)
            error("sizeof cannot be applied to an unspecified parameter VLA bound");
        count = ty->vla_len;
    } else {
        count = new_size_t_num(ty->array_len);
    }

    Node *bytes = new_binary(ND_MUL, count,
                             vla_size_expression(ty->base));
    add_type(bytes);
    return bytes;
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
static Obj *create_extern_ref(char *name, Type *ty, bool is_thread_local) {
    if (find_typedef_name_in_scope(current_scope, name) ||
        find_enum_name_in_scope(current_scope, name))
        error("extern declaration of '%s' conflicts with ordinary identifier", name);

    bool wants_function = ty->kind == TY_FUNC;
    if (wants_function && is_thread_local)
        error("_Thread_local may only declare an object");
    VarScope *same_scope = find_var_name_in_scope(current_scope, name);
    if (same_scope) {
        Obj *old = same_scope->var;
        if (old->is_local || strcmp(old->name, name) ||
            old->is_function != wants_function)
            error("conflicting block-scope declaration of '%s'", name);
        if (wants_function)
            check_oldstyle_definition_redeclaration(old, ty, false, name);
        if (!wants_function && old->is_thread_local != is_thread_local)
            error("inconsistent _Thread_local redeclaration of '%s'", name);
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
        if (!wants_function && var->is_thread_local != is_thread_local)
            error("inconsistent _Thread_local redeclaration of '%s'", name);
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
        var->is_thread_local = is_thread_local;
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

static bool type_is_variably_modified(Type *ty) {
    if (!ty)
        return false;
    if (ty->kind == TY_ARRAY) {
        if (ty->is_vla)
            return true;
        return type_is_variably_modified(ty->base);
    }
    if (ty->kind == TY_PTR)
        return type_is_variably_modified(ty->base);
    return false;
}

static Type *vla_of(Type *base, Node *bound) {
    Type *ty = calloc(1, sizeof(Type));
    ty->kind = TY_ARRAY;
    ty->size = 0;
    ty->align = base && base->align > 0 ? base->align : 1;
    ty->base = base;
    ty->array_len = -1;
    ty->is_vla = true;
    ty->vla_len = bound;
    return ty;
}


// Materialize every runtime byte stride reachable through an automatic
// variably-modified declarator. Inner dimensions are saved before outer ones so
// later indexing, sizeof and pointer arithmetic never re-evaluate a bound.
static void append_vm_size_materialization(Type *ty, Node **tail) {
    if (!ty)
        return;
    if (ty->kind == TY_PTR) {
        append_vm_size_materialization(ty->base, tail);
        return;
    }
    if (ty->kind != TY_ARRAY)
        return;

    append_vm_size_materialization(ty->base, tail);
    if (!type_is_variably_modified(ty) || ty->vla_size)
        return;
    if (ty->is_vla && !ty->vla_len)
        return; // prototype-scope [*] has no runtime stride to materialize

    Obj *size = create_lvar(new_unique_name());
    size->ty = ty_ulong;
    ty->vla_size = size;

    Node *count = ty->is_vla ? ty->vla_len : new_size_t_num(ty->array_len);
    Node *bytes = new_binary(ND_MUL, count, vla_size_expression(ty->base));
    Node *assign_size = new_binary(ND_ASSIGN, new_var_node(size), bytes);
    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, assign_size);
}

// Function parameter VLA bound expressions were parsed against temporary
// prototype-scope metadata objects. Rebind only those exact Obj identities to
// the actual callee local parameter slots before generating entry-time strides.
static void rebind_param_bound_expr(Node *node, Obj **meta, Obj **actual, int nparam) {
    for (; node; node = node->next) {
        if (node->kind == ND_VAR && node->var) {
            for (int i = 0; i < nparam; i++) {
                if (node->var == meta[i]) {
                    node->var = actual[i];
                    break;
                }
            }
        }
        rebind_param_bound_expr(node->lhs, meta, actual, nparam);
        rebind_param_bound_expr(node->rhs, meta, actual, nparam);
        rebind_param_bound_expr(node->cond, meta, actual, nparam);
        rebind_param_bound_expr(node->then, meta, actual, nparam);
        rebind_param_bound_expr(node->els, meta, actual, nparam);
        rebind_param_bound_expr(node->init, meta, actual, nparam);
        rebind_param_bound_expr(node->inc, meta, actual, nparam);
        rebind_param_bound_expr(node->args, meta, actual, nparam);
    }
}

static void rebind_param_vla_type(Type *ty, Obj **meta, Obj **actual, int nparam) {
    if (!ty)
        return;
    if (ty->kind == TY_ARRAY) {
        if (ty->vla_len)
            rebind_param_bound_expr(ty->vla_len, meta, actual, nparam);
        rebind_param_vla_type(ty->base, meta, actual, nparam);
    } else if (ty->kind == TY_PTR) {
        rebind_param_vla_type(ty->base, meta, actual, nparam);
    }
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

static int parse_bitfield_width(Token **rest, Token *tok, Type *ty,
                                Token *where) {
    if (!is_integer(ty))
        error_at(where->loc, "bit-field has non-integer type");

    Node *width_expr = ternary(&tok, tok);
    add_type(width_expr);
    if (!is_integer(width_expr->ty))
        error_at(where->loc, "bit-field width must be an integer constant expression");
    int64_t width = eval_const_expr(width_expr);
    int max_width = ty->kind == TY_BOOL ? 1 : ty->size * 8;
    if (width < 0)
        error_at(where->loc, "negative width in bit-field");
    if (width > max_width)
        error_at(where->loc, "bit-field width exceeds its type");
    *rest = tok;
    return (int)width;
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

    Token *body = tok;
    tok = skip(tok, "{");
    if (equal(tok, "}"))
        error_at(body->loc, "%s definition requires at least one member", kind);

    Member head = {};
    Member *cur = &head;
    bool has_flexible_member = false;
    while (!equal(tok, "}")) {
        if (equal(tok, "_Static_assert")) {
            tok = parse_static_assertion(tok);
            continue;
        }

        DeclAttrs attrs = {};
        Type *basety = declspec_with_attrs(&tok, tok, &attrs);
        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||
            attrs.is_thread_local || attrs.is_typedef || attrs.is_inline || attrs.is_noreturn)
            error_at(tok->loc, "storage/function specifier is not allowed on a record member");

        if (equal(tok, ";")) {
            if (!attrs.has_anonymous_record_specifier || basety->kind != TY_STRUCT)
                error_at(tok->loc,
                         "record member declaration without a declarator must be an anonymous struct or union");
            if (!is_union && basety->contains_flexible_array_member)
                error_at(tok->loc,
                         "record recursively containing a flexible array member cannot be embedded in a struct");

            const char *conflict = anonymous_member_conflict(head.next, basety);
            if (conflict)
                error_at(tok->loc,
                         "anonymous record member promotes duplicate name '%s'", conflict);

            Member *m = calloc(1, sizeof(Member));
            m->ty = basety;
            m->is_anonymous = true;
            m->align = validate_requested_alignment(basety, attrs.align, tok);
            cur = cur->next = m;
            tok = tok->next;
            continue;
        }

        for (bool first = true; !consume(&tok, tok, ";"); first = false) {
            if (!first)
                tok = skip(tok, ",");

            Token *ident = NULL;
            Type *mty = basety;
            Token *member_at = tok;
            bool is_bitfield = false;
            int bit_width = 0;

            // struct-declarator permits an omitted declarator for an unnamed
            // bit-field: `unsigned : 3`. Otherwise parse the ordinary member
            // declarator first and then its optional `: constant-expression`.
            if (!equal(tok, ":"))
                mty = declarator(&tok, tok, basety, &ident);

            if (equal(tok, ":")) {
                Token *colon = tok;
                tok = tok->next;
                bit_width = parse_bitfield_width(&tok, tok, mty, colon);
                is_bitfield = true;
                if (attrs.align)
                    error_at(member_at->loc, "_Alignas is not allowed on a bit-field");
                if (bit_width == 0 && ident)
                    error_at(ident->loc, "zero-width bit-field must be unnamed");
            }

            if (!is_bitfield) {
                if (type_is_variably_modified(mty))
                    error_at(ident ? ident->loc : member_at->loc,
                             "record member cannot have variably modified type");
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
                    if (!is_union && mty->kind == TY_STRUCT &&
                        mty->contains_flexible_array_member)
                        error_at(ident->loc,
                                 "record recursively containing a flexible array member cannot be embedded in a struct");
                }
            }

            if (ident) {
                MemberPath *duplicate =
                    find_record_member_path_in_list(head.next, ident);
                if (duplicate)
                    error_at(ident->loc, "duplicate record member name");
                free_member_path(duplicate);
            }

            Member *m = calloc(1, sizeof(Member));
            if (ident)
                m->name = strndup(ident->loc, ident->len);
            m->ty = mty;
            m->is_bitfield = is_bitfield;
            m->bit_width = bit_width;
            m->align = is_bitfield ? 0 : validate_requested_alignment(mty, attrs.align, ident);
            cur = cur->next = m;
        }
    }
    tok = skip(tok, "}");

    int align = 1;
    if (is_union) {
        int size = 0;
        for (Member *m = head.next; m; m = m->next) {
            if (m->is_bitfield) {
                m->offset = 0;
                m->bit_offset = 0;
                if (!m->name || m->bit_width == 0)
                    continue;
                if (m->ty->size > size)
                    size = m->ty->size;
                int ma = m->ty->align > 0 ? m->ty->align : 1;
                if (ma > align)
                    align = ma;
                continue;
            }

            if (m->ty->size > size)
                size = m->ty->size;
            int ma = m->align > 0 ? m->align : (m->ty->align > 0 ? m->ty->align : 1);
            if (ma > align)
                align = ma;
            m->offset = 0;
        }
        ty->size = align_up(size, align);
    } else {
        int bitpos = 0;
        for (Member *m = head.next; m; m = m->next) {
            if (m->is_bitfield) {
                int unit_bits = m->ty->size * 8;
                if (m->bit_width == 0) {
                    bitpos = align_up(bitpos, unit_bits);
                    m->offset = bitpos / 8;
                    m->bit_offset = 0;
                    continue;
                }

                int unit_start = (bitpos / unit_bits) * unit_bits;
                if (bitpos + m->bit_width > unit_start + unit_bits) {
                    bitpos = align_up(bitpos, unit_bits);
                    unit_start = bitpos;
                }
                m->offset = unit_start / 8;
                m->bit_offset = bitpos - unit_start;
                bitpos += m->bit_width;

                if (m->name) {
                    int ma = m->ty->align > 0 ? m->ty->align : 1;
                    if (ma > align)
                        align = ma;
                }
                continue;
            }

            int offset = (bitpos + 7) / 8;
            int ma = m->align > 0 ? m->align : (m->ty->align > 0 ? m->ty->align : 1);
            offset = align_up(offset, ma);
            m->offset = offset;
            bitpos = (offset + m->ty->size) * 8;
            if (ma > align)
                align = ma;
        }
        ty->size = align_up((bitpos + 7) / 8, align);
    }

    bool contains_flexible_member = has_flexible_member;
    if (is_union) {
        for (Member *m = head.next; m; m = m->next) {
            if (m->ty && m->ty->kind == TY_STRUCT &&
                m->ty->contains_flexible_array_member) {
                contains_flexible_member = true;
                break;
            }
        }
    }

    ty->align = align;
    ty->members = head.next;
    ty->is_union = is_union;
    ty->has_flexible_array_member = has_flexible_member;
    ty->contains_flexible_array_member = contains_flexible_member;
    ty->is_incomplete = false;
    for (Type *q = ty->qual_next; q; q = q->qual_next) {
        q->size = ty->size;
        q->align = ty->align;
        q->members = ty->members;
        q->is_union = ty->is_union;
        q->has_flexible_array_member = ty->has_flexible_array_member;
        q->contains_flexible_array_member = ty->contains_flexible_array_member;
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

static int64_t signed_const_min(Type *ty) {
    if (!ty || !is_integer(ty) || ty->is_unsigned)
        error("signed integer type required in integer constant expression");
    if (ty->size == 1) return INT8_MIN;
    if (ty->size == 2) return INT16_MIN;
    if (ty->size == 4) return INT32_MIN;
    return INT64_MIN;
}

static int64_t signed_const_max(Type *ty) {
    if (!ty || !is_integer(ty) || ty->is_unsigned)
        error("signed integer type required in integer constant expression");
    if (ty->size == 1) return INT8_MAX;
    if (ty->size == 2) return INT16_MAX;
    if (ty->size == 4) return INT32_MAX;
    return INT64_MAX;
}

static int64_t checked_signed_add(int64_t lhs, int64_t rhs, Type *ty) {
    int64_t min = signed_const_min(ty);
    int64_t max = signed_const_max(ty);
    if ((rhs > 0 && lhs > max - rhs) ||
        (rhs < 0 && lhs < min - rhs))
        error("signed overflow in integer constant expression");
    return lhs + rhs;
}

static int64_t checked_signed_sub(int64_t lhs, int64_t rhs, Type *ty) {
    int64_t min = signed_const_min(ty);
    int64_t max = signed_const_max(ty);
    if ((rhs < 0 && lhs > max + rhs) ||
        (rhs > 0 && lhs < min + rhs))
        error("signed overflow in integer constant expression");
    return lhs - rhs;
}

static int64_t checked_signed_mul(int64_t lhs, int64_t rhs, Type *ty) {
    int64_t min = signed_const_min(ty);
    int64_t max = signed_const_max(ty);

    if (!lhs || !rhs)
        return 0;
    if (lhs == -1) {
        if (rhs == min)
            error("signed overflow in integer constant expression");
        return -rhs;
    }
    if (rhs == -1) {
        if (lhs == min)
            error("signed overflow in integer constant expression");
        return -lhs;
    }

    if (lhs > 0) {
        if (rhs > 0) {
            if (lhs > max / rhs)
                error("signed overflow in integer constant expression");
        } else if (rhs < min / lhs) {
            error("signed overflow in integer constant expression");
        }
    } else if (rhs > 0) {
        if (lhs < min / rhs)
            error("signed overflow in integer constant expression");
    } else if (lhs < max / rhs) {
        error("signed overflow in integer constant expression");
    }

    return lhs * rhs;
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
        if (node->ty->is_unsigned) {
            uint64_t bits = 0 - (uint64_t)val;
            return cast_const_integer((int64_t)bits, node->ty);
        }
        if (val == signed_const_min(node->ty))
            error("signed overflow in integer constant expression");
        return -val;
    }

    case ND_ADD:
    case ND_SUB:
    case ND_MUL: {
        if (!is_integer(node->ty))
            error("non-integer arithmetic in integer constant expression");
        Type *ty = const_binary_type(node);
        int64_t lhs = cast_const_integer(eval_const_expr(node->lhs), ty);
        int64_t rhs = cast_const_integer(eval_const_expr(node->rhs), ty);

        if (ty->is_unsigned) {
            uint64_t bits;
            if (node->kind == ND_ADD)
                bits = (uint64_t)lhs + (uint64_t)rhs;
            else if (node->kind == ND_SUB)
                bits = (uint64_t)lhs - (uint64_t)rhs;
            else
                bits = (uint64_t)lhs * (uint64_t)rhs;
            return cast_const_integer((int64_t)bits, ty);
        }

        int64_t val;
        if (node->kind == ND_ADD)
            val = checked_signed_add(lhs, rhs, ty);
        else if (node->kind == ND_SUB)
            val = checked_signed_sub(lhs, rhs, ty);
        else
            val = checked_signed_mul(lhs, rhs, ty);
        return cast_const_integer(val, ty);
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

        if (rhs == -1 && lhs == signed_const_min(ty))
            error("signed overflow in integer constant expression");

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

        if (node->kind == ND_SHL) {
            if (left_ty->is_unsigned)
                return cast_const_integer((int64_t)((uint64_t)lhs << count), left_ty);
            if (lhs < 0)
                error("invalid signed left shift in integer constant expression");
            int64_t max = signed_const_max(left_ty);
            if (count && lhs > (max >> count))
                error("signed overflow in integer constant expression");
            return cast_const_integer(lhs << count, left_ty);
        }
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

// C11 enumerator identifiers have type int, and every enumerator value
// must be representable as int. Evaluate using the expression's actual signedness
// first so large unsigned constants cannot masquerade as negative int64_t values.
static int64_t eval_enum_value(Node *node, Token *at) {
    add_type(node);
    if (!node->ty || !is_integer(node->ty))
        error_at(at->loc, "enumerator value must be an integer constant expression");

    int64_t raw = eval_const_expr(node);
    if (node->ty->is_unsigned) {
        uint64_t value = (uint64_t)cast_const_integer(raw, node->ty);
        if (value > INT32_MAX)
            error_at(at->loc, "enumerator value is not representable as int");
        return (int64_t)value;
    }

    int64_t value = cast_const_integer(raw, node->ty);
    if (value < INT32_MIN || value > INT32_MAX)
        error_at(at->loc, "enumerator value is not representable as int");
    return value;
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

    Token *body = tok;
    tok = skip(tok, "{");
    if (equal(tok, "}"))
        error_at(body->loc, "enum definition requires at least one enumerator");
    int64_t next_val = 0;
    bool implicit_value_valid = true;

    while (!equal(tok, "}")) {
        if (tok->kind != TK_IDENT)
            error_at(tok->loc, "expected enumerator name");

        Token *enumerator = tok;
        tok = tok->next;

        int64_t val;
        if (consume(&tok, tok, "=")) {
            Node *value = ternary(&tok, tok);
            val = eval_enum_value(value, enumerator);
        } else {
            if (!implicit_value_valid)
                error_at(enumerator->loc,
                         "implicit enumerator value is not representable as int");
            val = next_val;
        }

        push_enum_const(enumerator, val);
        if (val == INT32_MAX) {
            implicit_value_valid = false;
        } else {
            next_val = val + 1;
            implicit_value_valid = true;
        }

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
                                        bool saw_signed, bool saw_unsigned,
                                        Token *end) {
    if (!state->first)
        error_at(end->loc, "declaration requires a type specifier");

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
        Token *thread_tok = tok;
        if (consume(&tok, tok, "_Thread_local")) {
            if (!attrs)
                error_at(thread_tok->loc,
                         "_Thread_local is not allowed in this declaration context");
            if (attrs->is_thread_local)
                error_at(thread_tok->loc, "duplicate _Thread_local storage-class specifier");
            attrs->is_thread_local = true;
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
        storage_tok = tok;
        if (consume(&tok, tok, "typedef")) {
            note_storage_class(attrs, storage_tok);
            attrs->is_typedef = true;
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
            bool anonymous_record_specifier = equal(tok->next, "{");
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, true);
            if (attrs && anonymous_record_specifier)
                attrs->has_anonymous_record_specifier = true;
            continue;
        }

        if (equal(tok, "struct")) {
            bool anonymous_record_specifier = equal(tok->next, "{");
            note_type_specifier(&specs, tok, &specs.n_named);
            saw_non_signable_type = true;
            ty = record_decl(&tok, tok->next, false);
            if (attrs && anonymous_record_specifier)
                attrs->has_anonymous_record_specifier = true;
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
    validate_type_specifier_set(&specs, saw_signed, saw_unsigned, tok);
    if (specs.n_double == 1 && specs.n_long == 1)
        ty = ty_ldouble;
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

    enter_scope();
    Obj head = {};
    Obj *cur = &head;

    // `(void)` is the strict zero-parameter prototype, unlike old-style `()`.
    if (equal(tok, "void") && equal(tok->next, ")")) {
        tok = tok->next;
        fty->has_prototype = true;
        *rest = skip(tok, ")");
        leave_scope();
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
        if (param_attrs.is_thread_local ||
            (param_attrs.storage_class_count && !param_attrs.is_register))
            error_at(param_spec->loc,
                     "only register storage class is allowed on a parameter");
        if (param_attrs.is_inline || param_attrs.is_noreturn)
            error_at(param_spec->loc,
                     "function specifier is not allowed on a parameter");
        if (param_attrs.align)
            error_at(param_spec->loc, "_Alignas is not allowed on a parameter");
        Token *name = NULL;
        Type *declared_param_ty =
            declarator_impl(&tok, tok, basety, &name, true, true);
        bool param_vla_star = declared_param_ty->kind == TY_ARRAY &&
                              declared_param_ty->is_vla &&
                              declared_param_ty->vla_len == NULL;
        Type *param_ty = adjust_param_type(declared_param_ty);

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
            leave_scope();
            return fty;
        }

        if (name) {
            for (Obj *prev = head.param_next; prev; prev = prev->param_next)
                if (prev->name && token_matches_name(name, prev->name))
                    error_at(name->loc, "duplicate parameter name");
        }

        Obj *param = calloc(1, sizeof(Obj));
        param->ty = param_ty;
        param->is_register = param_attrs.is_register;
        param->param_vla_star = param_vla_star;
        if (name) {
            param->name = strndup(name->loc, name->len);
            bind_var_in_current_scope(param->name, param, false);
        }
        cur = cur->param_next = param;
    }

    fty->params = head.param_next;
    *rest = skip(tok, ")");
    leave_scope();
    return fty;
}

static bool array_bound_is_runtime(Node *node) {
    if (!node)
        return false;
    switch (node->kind) {
    case ND_NUM:
        return false;
    case ND_POS:
    case ND_NEG:
    case ND_BITNOT:
    case ND_NOT:
    case ND_CAST:
        return array_bound_is_runtime(node->lhs);
    case ND_ADD:
    case ND_SUB:
    case ND_MUL:
    case ND_DIV:
    case ND_MOD:
    case ND_BITAND:
    case ND_BITOR:
    case ND_BITXOR:
    case ND_SHL:
    case ND_SHR:
    case ND_EQ:
    case ND_NE:
    case ND_LT:
    case ND_LE:
    case ND_LOGAND:
    case ND_LOGOR:
        return array_bound_is_runtime(node->lhs) ||
               array_bound_is_runtime(node->rhs);
    case ND_TERNARY:
        return array_bound_is_runtime(node->cond) ||
               array_bound_is_runtime(node->then) ||
               array_bound_is_runtime(node->els);
    default:
        return true;
    }
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
        bool star_bound = false;

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
            if (equal(tok, "*")) {
                if (param_static)
                    error_at(tok->loc,
                             "static parameter array declarator requires an explicit bound");
                star_bound = true;
                tok = tok->next;
            }
            if (param_static && equal(tok, "]"))
                error_at(bracket->loc,
                         "static parameter array declarator requires an explicit bound");
        } else if (equal(tok, "*")) {
            error_at(tok->loc,
                     "'*' VLA bound is only allowed in function parameter prototype scope");
        }

        Node *bound = NULL;
        int len = 0;
        bool runtime_bound = star_bound;
        if (!star_bound && !equal(tok, "]")) {
            // Array size syntax is an assignment-expression (C11 6.7.6.2), so VLA
            // bounds may contain assignments and compound assignments.
            bound = assign(&tok, tok);
            add_type(bound);
            if (!is_integer(bound->ty))
                error_at(bracket->loc, "array bound must have integer type");

            runtime_bound = array_bound_is_runtime(bound);
            if (!runtime_bound) {
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
        }
        tok = skip(tok, "]");
        ty = type_suffix(rest, tok, ty, false);
        if (ty->kind == TY_FUNC)
            error_at(bracket->loc, "array element type cannot be a function");
        if (ty->kind == TY_VOID)
            error_at(bracket->loc, "array element type cannot be void");
        if (is_incomplete_object_type(ty))
            error_at(bracket->loc, "array element type is incomplete");
        if (ty->kind == TY_STRUCT && ty->contains_flexible_array_member)
            error_at(bracket->loc,
                     "array element type contains a flexible array member");
        Type *arr = runtime_bound ? vla_of(ty, bound) : array_of(ty, len);
        if (allow_parameter_array_syntax) {
            arr->param_array_const = param_const;
            arr->param_array_volatile = param_volatile;
            arr->param_array_restrict = param_restrict;
        }
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
    long double fval;
} ConstNumber;

static ConstNumber eval_const_number(Node *node);

static long double const_number_as_floating(ConstNumber v) {
    if (v.is_fp)
        return v.fval;

    if (!v.ty || !is_integer(v.ty))
        error("arithmetic constant expression required");

    int64_t val = cast_const_integer(v.ival, v.ty);
    if (v.ty->is_unsigned)
        return (long double)(uint64_t)val;
    return (long double)val;
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
        long double x = const_number_as_floating(v);
        out.is_fp = true;
        if (ty->kind == TY_FLOAT)
            out.fval = (long double)(float)x;
        else if (ty->kind == TY_DOUBLE)
            out.fval = (long double)(double)x;
        else
            out.fval = x;
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

    long double x = v.fval;
    if (ty->is_unsigned) {
        if (!(x >= 0.0) || x >= 18446744073709551616.0L)
            error("floating-to-unsigned conversion is out of range in constant expression");
        out.ival = cast_const_integer((int64_t)(uint64_t)x, ty);
        return out;
    }

    if (x < (long double)INT64_MIN || x >= 9223372036854775808.0L)
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
            double a = const_number_as_floating(lhs);
            double b = const_number_as_floating(rhs);
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
                                         ? (long double)(float)node->fval
                                         : node->ty->kind == TY_DOUBLE
                                               ? (long double)(double)node->fval
                                               : node->fval};
    case ND_NEG: {
        ConstNumber v = const_number_cast(eval_const_number(node->lhs), node->ty);
        v.fval = node->ty->kind == TY_FLOAT ? (long double)(float)-v.fval
                 : node->ty->kind == TY_DOUBLE ? (long double)(double)-v.fval
                 : -v.fval;
        return v;
    }
    case ND_ADD:
    case ND_SUB:
    case ND_MUL:
    case ND_DIV: {
        long double a = const_number_as_floating(eval_const_number(node->lhs));
        long double b = const_number_as_floating(eval_const_number(node->rhs));
        long double r = node->kind == ND_ADD ? a + b
                   : node->kind == ND_SUB ? a - b
                   : node->kind == ND_MUL ? a * b
                                          : a / b;
        if (node->ty->kind == TY_FLOAT)
            r = (long double)(float)r;
        else if (node->ty->kind == TY_DOUBLE)
            r = (long double)(double)r;
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

static long double parse_const_floating(Token **rest, Token *tok, Type *target) {
    Node *node = assign(&tok, tok);
    add_type(node);
    if (!is_numeric(node->ty))
        error("static floating initializer requires an arithmetic constant expression");

    ConstNumber value = const_number_cast(eval_const_number(node), target);
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
        if (node->var->is_thread_local)
            error("address of thread-local object is not a static address constant");
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
    case ND_COMPOUND_LITERAL:
        if (!node->var || node->var->is_local || node->lhs)
            error("automatic compound literal is not a static address constant");
        return (StaticAddress){node->var->name, 0};
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
        if (node->var->is_thread_local)
            error("thread-local object is not a static address constant");
        if (node->var->is_local)
            error("automatic object is not a static address constant");
        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_FUNC)
            error("object value is not a static address constant");
        return (StaticAddress){node->var->name, 0};

    case ND_ADDR:
        return eval_static_lvalue_address(node->lhs);

    case ND_COMPOUND_LITERAL:
        // An array compound literal at file scope undergoes the ordinary
        // array-to-pointer conversion and denotes its anonymous static object.
        if (!node->var || node->var->is_local || node->lhs ||
            node->ty->kind != TY_ARRAY)
            error("compound literal value is not a static address constant");
        return (StaticAddress){node->var->name, 0};

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
        var->finit_val = parse_const_floating(rest, tok, ty);
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

static void append_automatic_scalar_initializer(Node **tail, Node *lhs,
                                                Token **rest, Token *tok,
                                                Token *where) {
    if (equal(tok, "{")) {
        Token *brace = tok;
        tok = tok->next;
        if (equal(tok, "}"))
            error_at(brace->loc, "empty scalar initializer");

        append_automatic_scalar_initializer(tail, lhs, &tok, tok, where);
        if (equal(tok, ","))
            tok = tok->next;
        if (!equal(tok, "}"))
            error_at(tok->loc, "excess elements in scalar initializer");
        *rest = tok->next;
        return;
    }

    Node *rhs = assign(&tok, tok);
    Node *a = new_initializer_assign(lhs, rhs, where);
    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
    *rest = tok;
}


static bool is_initializable_record_member(Member *m) {
    return m && !(m->is_bitfield && !m->name);
}

static Member *next_initializable_record_member(Member *m) {
    while (m && !is_initializable_record_member(m))
        m = m->next;
    return m;
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
            Member *m = next_initializable_record_member(ty->members);
            if (m) {
                Node *member = new_node(ND_MEMBER);
                member->lhs = lhs;
                member->member = m;
                append_zero_initializer(tail, member, m->ty, where);
            }
            return;
        }

        for (Member *m = ty->members; m; m = m->next) {
            if (!is_initializable_record_member(m))
                continue;
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

typedef struct StaticUnionSelection StaticUnionSelection;
struct StaticUnionSelection {
    StaticUnionSelection *next;
    Obj *var;
    Type *ty;
    int offset;
    Member *member;
};

static StaticUnionSelection *static_union_selections;

static void invalidate_static_union_selections(Obj *var, int offset, int size) {
    StaticUnionSelection head = {};
    StaticUnionSelection *tail = &head;
    for (StaticUnionSelection *sel = static_union_selections; sel;) {
        StaticUnionSelection *next = sel->next;
        bool contained = sel->var == var && sel->offset >= offset &&
                         sel->offset < offset + size;
        if (contained) {
            free(sel);
        } else {
            tail = tail->next = sel;
            sel->next = NULL;
        }
        sel = next;
    }
    static_union_selections = head.next;
}

// Designators may enter the same union member repeatedly, e.g. `.s.a` then
// `.s.b`. Preserve earlier writes while that selected member stays active, but
// clear the complete overlapping representation (including relocations) when a
// later designator switches the union to another member. Offset plus Type
// identifies each physical union subobject within one static object image.
static void select_static_union_member(Obj *var, Type *ty, int offset,
                                       Member *member) {
    for (StaticUnionSelection *sel = static_union_selections; sel; sel = sel->next) {
        if (sel->var == var && sel->ty == ty && sel->offset == offset) {
            if (sel->member == member)
                return;
            break;
        }
    }

    reset_static_subobject(var, offset, ty->size);
    invalidate_static_union_selections(var, offset, ty->size);

    StaticUnionSelection *sel = calloc(1, sizeof(StaticUnionSelection));
    sel->var = var;
    sel->ty = ty;
    sel->offset = offset;
    sel->member = member;
    sel->next = static_union_selections;
    static_union_selections = sel;
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

static void write_static_bitfield(Obj *var, int offset, Member *member,
                                  int64_t val) {
    int bytes = member->ty->size;
    int width = member->bit_width;
    ensure_static_image(var, offset + bytes);

    uint64_t unit = 0;
    for (int i = 0; i < bytes; i++)
        unit |= (uint64_t)(unsigned char)var->init_image[offset + i] << (i * 8);

    uint64_t mask = width == 64 ? UINT64_MAX : ((UINT64_C(1) << width) - 1);
    uint64_t shifted = mask << member->bit_offset;
    unit = (unit & ~shifted) |
           ((((uint64_t)val) & mask) << member->bit_offset);

    for (int i = 0; i < bytes; i++)
        var->init_image[offset + i] = (char)(unit >> (i * 8));
}

static void parse_static_bitfield_initializer(Obj *var, Token **rest, Token *tok,
                                              Member *member, int offset) {
    if (equal(tok, "{")) {
        Token *brace = tok;
        tok = tok->next;
        if (equal(tok, "}"))
            error_at(brace->loc, "empty scalar initializer");
        parse_static_bitfield_initializer(var, &tok, tok, member, offset);
        if (equal(tok, ","))
            tok = tok->next;
        *rest = skip(tok, "}");
        return;
    }

    int64_t val = parse_static_integer_initializer(&tok, tok, member->ty);
    write_static_bitfield(var, offset, member, val);
    *rest = tok;
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
        long double val = parse_const_floating(rest, tok, ty);
        if (ty->kind == TY_FLOAT) {
            float f = (float)val;
            memcpy(var->init_image + offset, &f, sizeof(f));
        } else if (ty->kind == TY_DOUBLE) {
            double d = (double)val;
            memcpy(var->init_image + offset, &d, sizeof(d));
        } else {
            unsigned char raw[16] = {0};
            memcpy(raw, &val, sizeof(val));
            memcpy(var->init_image + offset, raw, 16);
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
    Member *last_member;
    int depth;
} InitializerDesignatorPath;

static void append_initializer_designator_step(InitializerDesignatorPath *path,
                                               InitializerDesignator *step) {
    if (!path->head)
        path->head = step;
    else
        path->tail->next = step;
    path->tail = step;
    path->depth++;
}

static InitializerDesignatorPath
parse_initializer_designator_path(Token **rest, Token *tok, Type *root_ty) {
    InitializerDesignatorPath path = {.first_index = -1};
    Type *cur = root_ty;

    while (equal(tok, "[") || equal(tok, ".")) {
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

            InitializerDesignator *step = calloc(1, sizeof(InitializerDesignator));
            step->kind = INIT_DESIGNATOR_INDEX;
            step->index = index;
            step->result_ty = cur->base;
            if (path.depth == 0)
                path.first_index = index;
            path.last_member = NULL;
            cur = cur->base;
            append_initializer_designator_step(&path, step);
            continue;
        }

        Token *where = tok;
        if (!cur || cur->kind != TY_STRUCT)
            error_at(where->loc, "member designator requires a record subobject");
        tok = tok->next;
        if (tok->kind != TK_IDENT)
            error_at(tok->loc, "expected member name in designated initializer");

        MemberPath *members = find_record_member_path(cur, tok);
        if (!members)
            error_at(tok->loc, "unknown member in designated initializer");
        tok = tok->next;

        for (MemberPath *mp = members; mp; mp = mp->next) {
            InitializerDesignator *step = calloc(1, sizeof(InitializerDesignator));
            step->kind = INIT_DESIGNATOR_MEMBER;
            step->member = mp->member;
            step->result_ty = mp->member->ty;
            if (path.depth == 0)
                path.first_member = mp->member;
            path.last_member = mp->member;
            cur = mp->member->ty;
            append_initializer_designator_step(&path, step);
        }
        free_member_path(members);
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
            if (cur->is_union)
                select_static_union_member(var, cur, offset, step->member);
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
        if (!is_initializable_record_member(m))
            continue;
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
            select_static_union_member(var, ty, offset, m);

        int child_offset = offset + m->offset;
        if (m->is_bitfield) {
            parse_static_bitfield_initializer(var, &tok, tok, m, child_offset);
            initialized++;
        } else {
            if (!ty->is_union)
                reset_static_subobject(var, child_offset, m->ty->size);
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
            parse_static_image_initializer(var, &tok, tok, ty, offset);
            if (equal(tok, ","))
                tok = tok->next;
            if (!equal(tok, "}"))
                error_at(tok->loc, "excess elements in scalar initializer");
            *rest = tok->next;
            return ty;
        }
        parse_static_image_scalar(var, rest, tok, ty, offset);
        return ty;
    }

    Token *brace = tok;
    if (!equal(tok, "{"))
        error_at(tok->loc, "nested static aggregate initializer requires braces");
    tok = tok->next;
    if (equal(tok, "}"))
        error_at(brace->loc, "empty aggregate initializer is not valid in C11");

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
                Member *target_member = path.last_member;
                int target_offset = apply_static_designator_path(var, ty, offset, &path);
                bool target_bitfield = target_member && target_member->is_bitfield;
                if (!target_bitfield)
                    reset_static_subobject(var, target_offset, target_ty->size);
                free_initializer_designator_path(&path);

                if (target_bitfield) {
                    parse_static_bitfield_initializer(var, &tok, tok,
                                                      target_member, target_offset);
                } else if (parse_static_string_array_initializer(var, &tok, tok,
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
    Member *next_member = next_initializable_record_member(ty->members);
    bool first = true;
    int initialized_members = 0;
    while (!equal(tok, "}")) {
        if (!first) {
            tok = skip(tok, ",");
            if (equal(tok, "}"))
                break;
        }
        first = false;

        if (ty->is_union && initialized_members && !equal(tok, "."))
            error_at(tok->loc, "excess elements in union initializer");

        if (equal(tok, ".") || equal(tok, "[")) {
            InitializerDesignatorPath path =
                parse_initializer_designator_path(&tok, tok, ty);
            if (!path.first_member)
                error_at(brace->loc, "record initializer designator must start with a member");

            Member *member = path.first_member;
            Member *target_member = path.last_member;
            Type *target_ty = path.target_ty;
            int target_offset = apply_static_designator_path(var, ty, offset, &path);
            bool target_bitfield = target_member && target_member->is_bitfield;
            if (!target_bitfield)
                reset_static_subobject(var, target_offset, target_ty->size);
            free_initializer_designator_path(&path);

            if (target_bitfield) {
                parse_static_bitfield_initializer(var, &tok, tok,
                                                  target_member, target_offset);
            } else if (parse_static_string_array_initializer(var, &tok, tok,
                                                              target_ty, target_offset)) {
                // String literal consumed as the designated character array.
            } else {
                Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                              target_ty, target_offset);
                if (parsed != target_ty)
                    error_at(brace->loc, "incomplete array record members are not supported");
            }

            initialized_members++;
            next_member = next_initializable_record_member(member->next);
            continue;
        }

        Member *member = next_member;
        if (!member)
            error_at(tok->loc, "excess elements in record initializer");

        // All union members overlap at offset zero. Selecting a positional
        // member participates in the same active-member state as designators.
        if (ty->is_union)
            select_static_union_member(var, ty, offset, member);

        int member_offset = offset + member->offset;
        if (member->is_bitfield) {
            parse_static_bitfield_initializer(var, &tok, tok, member, member_offset);
        } else {
            if (!ty->is_union)
                reset_static_subobject(var, member_offset, member->ty->size);
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
        }
        initialized_members++;
        next_member = next_initializable_record_member(member->next);
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

    bool infer_array = ty->kind == TY_ARRAY && ty->array_len == 0;
    if (infer_array && (lhs->kind != ND_VAR || !lhs->var))
        error_at(where->loc, "nested incomplete arrays are not supported");

    // Automatic aggregates are normally zero-initialized before explicit
    // writes. An outermost unknown-bound array has no size yet, so defer its
    // zero-fill until the initializer determines the completed array type.
    Node *before_init = *tail;
    if (!infer_array)
        append_zero_initializer(tail, lhs, ty, where);
    bool braced = consume(&tok, tok, "{");
    if (infer_array && !braced)
        error_at(where->loc, "unknown-bound array initializer requires braces");
    if (braced && equal(tok, "}"))
        error_at(where->loc, "empty aggregate initializer is not valid in C11");

    // A braced nested initializer is a real initializer-list, so it may contain
    // designators at any entry.  Reuse the same designator-path parser used by
    // top-level automatic initializers and then lower the resolved path to an
    // lvalue rooted at this nested subobject.
    if (braced) {
        if (ty->kind == TY_ARRAY) {
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
                    if (index > max_index)
                        max_index = index;
                    next_index = index + 1;
                    continue;
                }

                if (ty->array_len > 0 && next_index >= ty->array_len)
                    error_at(tok->loc, "excess elements in array initializer");

                int index = next_index++;
                if (index > max_index)
                    max_index = index;
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

                append_automatic_scalar_initializer(tail, child, &tok, tok, where);
            }

            if (infer_array) {
                if (max_index < 0)
                    error_at(where->loc, "cannot infer array size from empty initializer");
                ty = array_of(ty->base, max_index + 1);
                lhs->var->ty = ty;
                lhs->ty = ty;

                Node zero_head = {};
                Node *zero_cur = &zero_head;
                append_zero_initializer(&zero_cur, lhs, ty, where);
                zero_cur->next = before_init->next;
                before_init->next = zero_head.next;
            }
        } else {
            Member *next_member = next_initializable_record_member(ty->members);
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
                    next_member = next_initializable_record_member(member->next);
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
                    append_automatic_scalar_initializer(tail, child, &tok, tok, where);
                }

                if (ty->is_union)
                    initialized_union_members++;
                next_member = next_initializable_record_member(next_member->next);
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

            append_automatic_scalar_initializer(tail, child, &tok, tok, where);
        }
    } else {
        int initialized = 0;
        for (Member *m = ty->members; m; m = m->next) {
            if (!is_initializable_record_member(m))
                continue;
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
                append_automatic_scalar_initializer(tail, child, &tok, tok, where);
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

    if (!is_initializer_aggregate(ty)) {
        append_automatic_scalar_initializer(tail, lhs, rest, tok, where);
        return;
    }

    if (equal(tok, "{")) {
        parse_automatic_aggregate_subobject(tail, lhs, ty, rest, tok, where);
        return;
    }

    Node *rhs = assign(&tok, tok);
    Node *a = new_initializer_assign(lhs, rhs, where);
    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
    *rest = tok;
}


static Token *parse_typedef_declaration(Token *tok, Type *basety,
                                        DeclAttrs *attrs, Node **runtime_tail) {
    if (attrs->align)
        error_at(tok->loc, "_Alignas is not allowed on a typedef declaration");
    if (attrs->is_thread_local)
        error_at(tok->loc, "_Thread_local is not allowed on a typedef declaration");
    if (attrs->is_inline || attrs->is_noreturn)
        error_at(tok->loc, "function specifier is not allowed on a typedef declaration");
    if (equal(tok, ";"))
        error_at(tok->loc, "typedef declaration requires a declarator");

    for (;;) {
        Token *ident;
        Type *ty = declarator(&tok, tok, basety, &ident);
        bool is_vm_typedef = type_is_variably_modified(ty);
        if (is_vm_typedef) {
            // C11 6.7.6.2 permits variably-modified typedef names only at
            // ordinary block scope.  Materialize every dynamic byte extent at
            // the typedef declaration itself: later objects and sizeof(type)
            // reuse those saved values and must not re-evaluate the bounds.
            if (!runtime_tail)
                error_at(ident->loc,
                         "variably modified typedef requires block scope");
            append_vm_size_materialization(ty, runtime_tail);
        }
        if (equal(tok, "="))
            error_at(tok->loc, "typedef declaration cannot have an initializer");
        bool introduced = push_typedef(ident, ty);
        if (is_vm_typedef && introduced)
            push_vm_guard(ident);
        if (!consume(&tok, tok, ","))
            break;
    }
    return skip(tok, ";");
}

// declaration = declspec (declarator ("=" (expr | "{" initializer "}"))?)
//               ("," declarator ("=" (expr | "{" initializer "}"))?)* ";"
static Node *declaration(Token **rest, Token *tok) {
    DeclAttrs attrs = {};
    Type *basety = declspec_with_attrs(&tok, tok, &attrs);
    if (attrs.is_typedef) {
        Node typedef_head = {};
        Node *typedef_cur = &typedef_head;
        *rest = parse_typedef_declaration(tok, basety, &attrs, &typedef_cur);
        if (!typedef_head.next)
            return new_node(ND_EXPR_STMT);
        if (!typedef_head.next->next)
            return typedef_head.next;
        Node *block = new_node(ND_BLOCK);
        block->body = typedef_head.next;
        return block;
    }
    bool is_static = attrs.is_static;
    bool is_extern = attrs.is_extern;
    if (is_static && is_extern)
        error_at(tok->loc, "declaration cannot be both static and extern");
    if (attrs.is_thread_local && (attrs.is_auto || attrs.is_register))
        error_at(tok->loc,
                 "_Thread_local may be combined only with static or extern storage class");
    if (attrs.is_thread_local && !is_static && !is_extern)
        error_at(tok->loc,
                 "block-scope _Thread_local declaration requires static or extern");
    if (attrs.align && attrs.is_register)
        error_at(tok->loc, "_Alignas is not allowed on a register object");
    if (equal(tok, ";")) {
        if (attrs.storage_class_count || attrs.is_thread_local)
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
        bool is_vm_type = type_is_variably_modified(ty);
        bool is_vm_array_object = ty->kind == TY_ARRAY && is_vm_type;
        if (is_vm_type && (is_static || is_extern || attrs.is_thread_local))
            error_at(ident->loc,
                     "variably modified declaration requires automatic storage duration");
        bool inferable_array = is_unknown_bound_array_with_complete_element(ty) &&
                               equal(tok, "=");
        if (!is_extern && is_incomplete_object_type(ty) && !inferable_array)
            error_at(ident->loc, "variable has incomplete type");

        char *name = strndup(ident->loc, ident->len);
        Obj *var;
        if (ty->kind == TY_FUNC) {
            if (attrs.is_thread_local)
                error_at(ident->loc, "_Thread_local may only declare an object");
            if (attrs.is_auto || attrs.is_register || is_static)
                error_at(ident->loc,
                         "block-scope function declaration may only use extern storage class");
            var = create_extern_ref(name, ty, false);
        } else if (is_static) {
            var = create_static_lvar(name);
            var->ty = ty;
        } else if (is_extern) {
            var = create_extern_ref(name, ty, attrs.is_thread_local);
        } else {
            var = create_lvar(name);
            var->ty = ty;
        }
        apply_object_alignment(var, ty, attrs.align, ident);
        var->is_register = attrs.is_register;
        var->is_thread_local = attrs.is_thread_local;

        VmGuard *vm_guard = NULL;
        if (is_vm_type) {
            append_vm_size_materialization(ty, &block_cur);
            // The identifier's variably-modified scope begins after its
            // declarator. Labels cannot occur inside a declaration, so this is
            // the control-flow frontier observed by every later statement.
            vm_guard = push_vm_guard(ident);
        }

        if (is_vm_array_object) {
            if (equal(tok, "="))
                error_at(tok->loc, "variable length array may not be initialized");
            if (!ty->vla_size)
                error_at(ident->loc, "automatic variably modified array has no runtime extent");

            // Every dynamic VLA declaration gets its own pre-allocation
            // checkpoint. The first checkpoint in a lexical block also remains
            // the block-wide unwind target used by normal exit/break/continue.
            Obj *save = create_lvar(new_unique_name());
            save->ty = ty_ulong;
            block_cur = block_cur->next = new_vla_stack_node(ND_VLA_SAVE, save);
            if (!current_scope->vla_stack_save)
                current_scope->vla_stack_save = save;
            if (!vm_guard)
                error_at(ident->loc, "internal error: VLA is missing VM guard metadata");
            vm_guard->stack_save = save;

            var->is_vla = true;
            var->vla_size = ty->vla_size;

            Node *alloc = new_node(ND_VLA_ALLOC);
            alloc->var = var;
            block_cur = block_cur->next = alloc;
            continue;
        }

        if (!equal(tok, "="))
            continue;
        if (is_extern)
            error_at(tok->loc,
                     "block-scope extern declaration cannot have an initializer");
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

        // Brace-enclosed initializer. Scalars contain one initializer
        // recursively (plus optional trailing commas); aggregates use the full
        // initializer-list machinery below.
        if (equal(tok, "{")) {
            if (!is_initializer_aggregate(ty)) {
                Token *brace = tok;
                Node *lhs = new_var_node(var);
                append_automatic_scalar_initializer(&block_cur, lhs, &tok, tok, brace);
                continue;
            }

            Token *brace = tok;
            tok = tok->next;
            if (equal(tok, "}"))
                error_at(brace->loc, "empty aggregate initializer is not valid in C11");

            int cur_idx = 0;
            int max_idx = -1;
            int elem_cap = ty->kind == TY_ARRAY && ty->array_len > 0 ? ty->array_len : 8;
            bool *elem_init = ty->kind == TY_ARRAY ? calloc(elem_cap, sizeof(bool)) : NULL;
            int member_count = ty->kind == TY_STRUCT ? record_member_count(ty) : 0;
            bool *member_init = member_count ? calloc(member_count, sizeof(bool)) : NULL;
            Member *cur_mem = (ty->kind == TY_STRUCT)
                                  ? next_initializable_record_member(ty->members)
                                  : NULL;
            Member *active_union_member = NULL;
            Node *before_init = block_cur;
            int initialized_union_members = 0;

            while (!equal(tok, "}")) {
                if (equal(tok, ",")) tok = tok->next;
                if (equal(tok, "}")) break;
                if (ty->kind == TY_STRUCT && ty->is_union &&
                    initialized_union_members && !equal(tok, "."))
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
                        if (ty->is_union && active_union_member != member) {
                            for (int i = 0; i < member_count; i++)
                                member_init[i] = false;
                            was_initialized = false;
                            Node *top = new_node(ND_MEMBER);
                            top->lhs = new_var_node(var);
                            top->member = member;
                            append_zero_initializer(&block_cur, top, member->ty, brace);
                            active_union_member = member;
                        } else {
                            was_initialized = member_init[mi];
                        }
                        member_init[mi] = true;
                        cur_mem = next_initializable_record_member(member->next);
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
                            append_automatic_scalar_initializer(&block_cur, lhs,
                                                                &tok, tok, brace);
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
                            append_automatic_scalar_initializer(&block_cur, member_node,
                                                                &tok, tok, brace);
                        }
                    }
                    if (ty->is_union)
                        initialized_union_members++;
                    cur_mem = next_initializable_record_member(cur_mem->next);
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
                Member *m = next_initializable_record_member(ty->members);
                if (!initialized_union_members && m) {
                    Node *member = new_node(ND_MEMBER);
                    member->lhs = new_var_node(var);
                    member->member = m;
                    append_zero_initializer(&zero_cur, member, m->ty, brace);
                }
            } else {
                int mi = 0;
                for (Member *m = ty->members; m; m = m->next, mi++) {
                    if (!is_initializable_record_member(m)) continue;
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

static void require_statement_after_label(Token *tok) {
    if (equal(tok, "_Static_assert") || is_decl_start(tok))
        error_at(tok->loc, "label must be followed by a statement, not a declaration");
}

static void require_control_substatement(Token *tok, const char *construct) {
    if (equal(tok, "_Static_assert") || is_decl_start(tok))
        error_at(tok->loc, "%s body must be a statement, not a declaration", construct);
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
        Node *node = new_node(ND_BREAK);
        node->var = vla_restore_between(current_scope, current_break_scope);
        return node;
    }

    if (equal(tok, "continue")) {
        if (current_loop_depth == 0)
            error_at(tok->loc, "continue statement not within loop");
        *rest = skip(tok->next, ";");
        Node *node = new_node(ND_CONTINUE);
        node->var = vla_restore_between(current_scope, current_continue_scope);
        return node;
    }

    if (equal(tok, "goto")) {
        tok = tok->next;
        if (tok->kind != TK_IDENT)
            error_at(tok->loc, "expected label name after 'goto'");
        Node *node = new_node(ND_GOTO);
        node->label_name = strndup(tok->loc, tok->len);
        node->goto_next = current_gotos;
        current_gotos = node;
        note_jump_meta(&current_goto_meta, node);
        *rest = skip(tok->next, ";");
        return node;
    }

    if (equal(tok, "do")) {
        Token *do_tok = tok;
        Node *node = new_node(ND_DO);
        Token *body_tok = tok->next;
        require_control_substatement(body_tok, "do");
        Scope *saved_break_scope = current_break_scope;
        Scope *saved_continue_scope = current_continue_scope;
        current_break_scope = current_scope;
        current_continue_scope = current_scope;
        current_loop_depth++;
        node->then = stmt(&tok, body_tok);
        current_loop_depth--;
        current_break_scope = saved_break_scope;
        current_continue_scope = saved_continue_scope;
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
        node->ty = integer_promotion_for_node(node->cond);
        tok = skip(tok, ")");
        require_control_substatement(tok, "switch");

        SwitchContext ctx = {};
        ctx.ty = node->ty;
        ctx.prev = current_switch;
        Scope *saved_break_scope = current_break_scope;
        current_break_scope = current_scope;
        current_switch = &ctx;
        node->then = stmt(rest, tok);
        current_switch = ctx.prev;
        current_break_scope = saved_break_scope;
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
        require_statement_after_label(tok);
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
        require_statement_after_label(tok);
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
        require_control_substatement(tok, "if");
        node->then = stmt(&tok, tok);
        if (equal(tok, "else")) {
            require_control_substatement(tok->next, "else");
            node->els = stmt(&tok, tok->next);
        }
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
        require_control_substatement(tok, "while");
        Scope *saved_break_scope = current_break_scope;
        Scope *saved_continue_scope = current_continue_scope;
        current_break_scope = current_scope;
        current_continue_scope = current_scope;
        current_loop_depth++;
        node->then = stmt(&tok, tok);
        current_loop_depth--;
        current_break_scope = saved_break_scope;
        current_continue_scope = saved_continue_scope;
        *rest = tok;
        return node;
    }

    if (equal(tok, "for")) {
        Token *for_tok = tok;
        Node *node = new_node(ND_FOR);
        tok = skip(tok->next, "(");
        Scope *outer_for_scope = current_scope;
        enter_scope();
        Scope *for_scope = current_scope;

        if (equal(tok, ";")) {
            tok = skip(tok, ";");
        } else if (is_decl_start(tok)) {
            node->init = declaration(&tok, tok);
        } else {
            node->init = new_node(ND_EXPR_STMT);
            node->init->lhs = expr(&tok, tok);
            reject_register_array_decay(node->init->lhs);
            tok = skip(tok, ";");
        }

        if (!equal(tok, ";")) {
            node->cond = expr(&tok, tok);
            require_scalar_condition(node->cond, for_tok, "for");
        }
        tok = skip(tok, ";");

        if (!equal(tok, ")")) {
            node->inc = expr(&tok, tok);
            reject_register_array_decay(node->inc);
        }
        tok = skip(tok, ")");
        require_control_substatement(tok, "for");

        Scope *saved_break_scope = current_break_scope;
        Scope *saved_continue_scope = current_continue_scope;
        current_break_scope = outer_for_scope;
        current_continue_scope = for_scope;
        current_loop_depth++;
        node->then = stmt(rest, tok);
        current_loop_depth--;
        current_break_scope = saved_break_scope;
        current_continue_scope = saved_continue_scope;
        node->var = for_scope->vla_stack_save;
        leave_scope();
        return node;
    }

    if (equal(tok, "{")) {
        enter_scope();
        Scope *block_scope = current_scope;
        Node head = {};
        Node *cur = &head;
        tok = tok->next;
        while (!equal(tok, "}")) {
            Node *n = stmt(&tok, tok);
            if (n->kind != ND_EXPR_STMT || n->lhs)
                cur = cur->next = n;
        }
        *rest = skip(tok, "}");
        if (block_scope->vla_stack_save)
            cur = cur->next = new_vla_stack_node(ND_VLA_RESTORE,
                                                 block_scope->vla_stack_save);
        Node *node = new_node(ND_BLOCK);
        node->body = head.next;
        leave_scope();
        return node;
    }

    // Labeled statement: ident ":"  stmt. Labels have function scope in C,
    // so the same label name may not be defined twice anywhere in one function,
    // even when the definitions occur in different nested compound statements.
    if (is_label(tok)) {
        char *label_name = strndup(tok->loc, tok->len);
        for (Node *label = current_labels; label; label = label->label_next)
            if (!strcmp(label_name, label->label_name))
                error_at(tok->loc, "duplicate label '%s'", label_name);

        Node *node = new_node(ND_LABEL);
        node->label_name = label_name;
        node->unique_label = new_unique_name();
        node->label_next = current_labels;
        current_labels = node;
        note_jump_meta(&current_label_meta, node);
        tok = skip(tok->next, ":");
        require_statement_after_label(tok);
        node->lhs = stmt(rest, tok);
        return node;
    }

    // Declaration (storage classes, qualifiers and alignment specifiers may
    // appear in any declaration-specifier order).
    if (is_decl_start(tok))
        return declaration(rest, tok);

    Node *node = new_node(ND_EXPR_STMT);
    if (!equal(tok, ";")) {
        node->lhs = expr(&tok, tok);
        reject_register_array_decay(node->lhs);
    }
    *rest = skip(tok, ";");
    return node;
}

// expr = assign ("," assign)*   (comma operator)
static Node *expr(Token **rest, Token *tok) {
    Node *node = assign(&tok, tok);

    while (equal(tok, ",")) {
        reject_register_array_decay(node);
        Node *rhs = assign(&tok, tok->next);
        reject_register_array_decay(rhs);
        node = new_binary(ND_COMMA, node, rhs);
    }

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
    reject_register_array_decay(rhs);
    Type *src = rhs->ty;

    if (!dst || !src || dst->kind == TY_ARRAY || dst->kind == TY_FUNC)
        return false;
    if (is_numeric(dst) && is_numeric(src))
        return true;

    // _Bool accepts any scalar value after the standard value conversions.
    // Array and function designators therefore contribute pointer values here.
    if (dst->kind == TY_BOOL &&
        (src->kind == TY_PTR || src->kind == TY_ARRAY || src->kind == TY_FUNC))
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
    reject_register_array_decay(node);
    Type *ty = decay_value_type(node->ty);
    return ty && (is_numeric(ty) || ty->kind == TY_PTR);
}

static bool cast_compatible(Type *dst, Node *expr) {
    add_type(expr);
    reject_register_array_decay(expr);

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
    reject_register_array_decay(lhs);
    reject_register_array_decay(rhs);

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
    reject_register_array_decay(lhs);
    reject_register_array_decay(rhs);
    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return true;
    return pointer_pair_compatible(lhs->ty, rhs->ty, true);
}

static Type *conditional_result_type(Node *then, Node *els, Token *question) {
    add_type(then);
    add_type(els);
    reject_register_array_decay(then);
    reject_register_array_decay(els);

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
        if (equal(tok, "+")) {
            Node *rhs = mul(&tok, tok->next);
            reject_register_array_decay(node);
            reject_register_array_decay(rhs);
            node = new_add(node, rhs);
            continue;
        }
        if (equal(tok, "-")) {
            Node *rhs = mul(&tok, tok->next);
            reject_register_array_decay(node);
            reject_register_array_decay(rhs);
            node = new_sub(node, rhs);
            continue;
        }
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

static Node *compound_literal(Token **rest, Token *tok, Type *ty,
                              Token *type_tok) {
    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)
        error_at(type_tok->loc, "compound literal requires an object type");
    if (is_incomplete_object_type(ty) &&
        !is_unknown_bound_array_with_complete_element(ty))
        error_at(type_tok->loc,
                 "compound literal requires a complete object type or an unknown-bound array with complete element type");
    if (!equal(tok, "{"))
        error_at(tok->loc, "expected '{' after compound literal type name");

    Obj *var;
    Node *init_expr = NULL;

    if (current_return_ty) {
        var = create_lvar(new_unique_name());
        var->ty = ty;

        Node head = {};
        Node *tail = &head;
        Node *root = new_var_node(var);

        Token *after_string = NULL;
        Token *string_tok = string_initializer_token(tok, &after_string);
        if (string_tok && is_character_array(ty)) {
            prepare_string_array_type(var, &ty, string_tok);
            append_automatic_string_array_initializer(&tail, root, ty, &tok, tok);
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            parse_automatic_aggregate_subobject(&tail, root, ty, &tok, tok,
                                                type_tok);
            ty = var->ty;
        } else {
            append_automatic_scalar_initializer(&tail, root, &tok, tok, type_tok);
        }

        for (Node *stmt = head.next; stmt; stmt = stmt->next) {
            if (stmt->kind != ND_EXPR_STMT || !stmt->lhs)
                error("invalid automatic compound literal initializer node");
            init_expr = init_expr ? new_binary(ND_COMMA, init_expr, stmt->lhs)
                                  : stmt->lhs;
        }
    } else {
        // File-scope compound literals have static storage duration. Keep the
        // anonymous object out of the ordinary identifier namespace but emit it
        // through the normal static-data path.
        var = calloc(1, sizeof(Obj));
        var->name = new_unique_name();
        var->ty = ty;
        var->is_local = false;
        var->is_static = true;
        var->next = globals;
        globals = var;

        Token *after_string = NULL;
        Token *string_tok = string_initializer_token(tok, &after_string);
        if (string_tok && is_character_array(ty)) {
            prepare_string_array_type(var, &ty, string_tok);
            var->init_data = build_string_array_image(ty, string_tok);
            tok = after_string;
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
            var->ty = ty;
        } else {
            ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
            var->ty = ty;
        }
    }

    Node *node = new_node(ND_COMPOUND_LITERAL);
    node->var = var;
    node->lhs = init_expr;
    node->ty = ty;
    *rest = tok;
    return node;
}

static Node *unary(Token **rest, Token *tok) {
    if (equal(tok, "(") && is_typename(tok->next)) {
        Token *cast_tok = tok;
        tok = tok->next;
        Type *ty = type_name(&tok, tok);
        tok = skip(tok, ")");
        if (equal(tok, "{"))
            return postfix(rest, cast_tok);
        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||
            (ty->kind != TY_VOID && !is_numeric(ty) && ty->kind != TY_PTR))
            error_at(cast_tok->loc, "cast specifies non-scalar type");
        Node *operand = unary(rest, tok);
        if (!cast_compatible(ty, operand))
            error_at(cast_tok->loc, "invalid cast operand type");
        Node *node = new_unary(ND_CAST, operand);
        node->ty = ty;
        return node;
    }

    if (equal(tok, "+"))  return new_unary(ND_POS, unary(rest, tok->next));
    if (equal(tok, "-"))  return new_unary(ND_NEG, unary(rest, tok->next));
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
        reject_register_array_decay(arg);

        // Unprototyped calls and variadic tails have no declared parameter to
        // inspect, so classify aggregate actuals directly before codegen.
        if (arg->ty && arg->ty->kind == TY_STRUCT &&
            !supported_record_abi(arg->ty))
            error_at(arg_tok->loc, "unsupported record argument ABI for x86-64 backend");

        if (expected) {
            if (!assignment_compatible(expected->ty, arg))
                error_at(tok->loc, "incompatible argument type");
            if ((is_numeric(arg->ty) && is_numeric(expected->ty)) ||
                (expected->ty->kind == TY_BOOL &&
                 (arg->ty->kind == TY_PTR || arg->ty->kind == TY_ARRAY ||
                  arg->ty->kind == TY_FUNC)))
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

static Node *apply_record_member_path(Node *base, MemberPath *path) {
    for (MemberPath *mp = path; mp; mp = mp->next) {
        Node *member = new_node(ND_MEMBER);
        member->lhs = base;
        member->member = mp->member;
        base = member;
    }
    return base;
}

static Node *postfix(Token **rest, Token *tok) {
    Node *node;
    if (equal(tok, "(") && is_typename(tok->next)) {
        Token *type_tok = tok;
        Token *cur = tok->next;
        Type *ty = type_name(&cur, cur);
        cur = skip(cur, ")");
        if (!equal(cur, "{"))
            error_at(type_tok->loc, "expected compound literal initializer");
        node = compound_literal(&tok, cur, ty, type_tok);
    } else {
        node = primary(&tok, tok);
    }

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
            reject_register_array_decay(node);
            reject_register_array_decay(idx);
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
            MemberPath *path = find_record_member_path(node->ty, tok);
            if (!path) error_at(tok->loc, "unknown member");
            node = apply_record_member_path(node, path);
            free_member_path(path);
            tok = tok->next;
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
            MemberPath *path = find_record_member_path(deref->ty, tok);
            if (!path) error_at(tok->loc, "unknown member");
            node = apply_record_member_path(deref, path);
            free_member_path(path);
            tok = tok->next;
            continue;
        }

        break;
    }
    *rest = tok;
    return node;
}

static Node *primary(Token **rest, Token *tok) {
    if (equal(tok, "__builtin_offsetof")) {
        Token *builtin = tok;
        tok = skip(tok->next, "(");
        Type *cur_ty = type_name(&tok, tok);
        if (!cur_ty || cur_ty->kind != TY_STRUCT || cur_ty->is_incomplete)
            error_at(builtin->loc, "offsetof requires a complete struct or union type");
        tok = skip(tok, ",");

        int64_t offset = 0;
        for (;;) {
            if (tok->kind != TK_IDENT)
                error_at(tok->loc, "offsetof requires a member designator");
            if (!cur_ty || cur_ty->kind != TY_STRUCT || cur_ty->is_incomplete)
                error_at(tok->loc, "member designator does not name a record subobject");

            MemberPath *path = find_record_member_path(cur_ty, tok);
            if (!path)
                error_at(tok->loc, "unknown member in offsetof");
            for (MemberPath *mp = path; mp; mp = mp->next) {
                offset += mp->member->offset;
                cur_ty = mp->member->ty;
            }
            free_member_path(path);
            tok = tok->next;

            while (equal(tok, "[")) {
                Token *bracket = tok;
                if (!cur_ty || cur_ty->kind != TY_ARRAY || !cur_ty->base ||
                    cur_ty->array_len <= 0 || cur_ty->base->size <= 0)
                    error_at(bracket->loc,
                             "offsetof array designator requires a complete array type");
                tok = tok->next;
                Node *index_expr = ternary(&tok, tok);
                add_type(index_expr);
                if (!is_integer(index_expr->ty))
                    error_at(bracket->loc, "offsetof array index must have integer type");

                int64_t raw = eval_const_expr(index_expr);
                uint64_t index;
                if (index_expr->ty->is_unsigned) {
                    index = (uint64_t)cast_const_integer(raw, index_expr->ty);
                } else {
                    int64_t signed_index = cast_const_integer(raw, index_expr->ty);
                    if (signed_index < 0)
                        error_at(bracket->loc, "offsetof array index must be nonnegative");
                    index = (uint64_t)signed_index;
                }
                if (index >= (uint64_t)cur_ty->array_len)
                    error_at(bracket->loc, "offsetof array index exceeds array bounds");
                if (index > (uint64_t)INT64_MAX / (uint64_t)cur_ty->base->size)
                    error_at(bracket->loc, "offsetof result is out of range");
                offset += (int64_t)(index * (uint64_t)cur_ty->base->size);
                cur_ty = cur_ty->base;
                tok = skip(tok, "]");
            }

            if (!equal(tok, "."))
                break;
            tok = tok->next;
        }

        *rest = skip(tok, ")");
        return new_size_t_num(offset);
    }

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
        bool ld = ty->kind == TY_LDOUBLE;
        bool record = ty->kind == TY_STRUCT && supported_record_abi(ty);
        if (!gp && !fp && !ld && !record)
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
        Type *control_ty = generic_control_type(control);
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
                if (type_compatible(control_ty, assoc_ty)) {
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
            if (ty->kind == TY_ARRAY && type_is_variably_modified(ty))
                return vla_size_expression(ty);
            return new_size_t_num(ty->size);
        }
        Node *n = unary(rest, tok);
        add_type(n);
        if (n->kind == ND_MEMBER && n->member && n->member->is_bitfield)
            error_at(tok->loc, "sizeof may not be applied to a bit-field");
        if (invalid_sizeof_type(n->ty))
            error_at(tok->loc, "invalid operand type for sizeof");
        if (n->ty->kind == TY_ARRAY && type_is_variably_modified(n->ty))
            return vla_size_expression(n->ty);
        return new_size_t_num(n->ty->size);
    }

    if (tok->kind == TK_IDENT) {
        // Check for an enumeration constant visible in lexical scope.
        EnumConst *ec = find_enum_const(tok);
        if (ec) {
            *rest = tok->next;
            return new_num(ec->val);
        }

        // Direct function calls keep a named callee for codegen. C99 and
        // later require a visible declaration at the call site; a definition or
        // declaration appearing later in the translation unit cannot retroactively
        // supply the old implicit-function declaration. A function-pointer object
        // falls through to ND_VAR and the ordinary postfix-call path.
        if (equal(tok->next, "(")) {
            Obj *fn = find_var(tok);
            if (!fn) {
                if (find_typedef(tok))
                    error_at(tok->loc, "typedef name is not callable");
                error_at(tok->loc, "call to undeclared function");
            }
            if (fn->is_function) {
                Node *node = new_node(ND_FUNCALL);
                node->funcname = strndup(tok->loc, tok->len);

                Type *fty = fn->ty;
                node->ty = fty->return_ty;
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
    if (current_scope->vla_stack_save)
        cur = cur->next = new_vla_stack_node(ND_VLA_RESTORE,
                                             current_scope->vla_stack_save);

    *rest = skip(tok, "}");
    Node *node = new_node(ND_BLOCK);
    node->body = head.next;
    return node;
}

static void resolve_gotos(void) {
    for (Node *g = current_gotos; g; g = g->goto_next) {
        Node *target = NULL;
        for (Node *l = current_labels; l; l = l->label_next) {
            if (!strcmp(g->label_name, l->label_name)) {
                target = l;
                break;
            }
        }
        if (!target)
            error("undefined label: %s", g->label_name);

        VmGuard *source_guard = jump_guard_for(current_goto_meta, g);
        VmGuard *target_guard = jump_guard_for(current_label_meta, target);
        if (!vm_guard_target_is_active(source_guard, target_guard))
            error("goto to label '%s' enters scope of a variably modified identifier",
                  g->label_name);

        g->unique_label = target->unique_label;
        g->var = vm_guard_restore_between(source_guard, target_guard);
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
        // A variable-length bound is evaluated at runtime and is not part of
        // the compatible array element type. Treat either VLA extent like an
        // unknown bound while still recursively checking the element type.
        return type_compatible_impl(a->base, b->base, false) &&
               (a->is_vla || b->is_vla || !a->array_len || !b->array_len ||
                a->array_len == b->array_len);
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
                                   bool is_extern, bool has_storage_class,
                                   bool is_thread_local) {
    char *name = strndup(ident->loc, ident->len);
    Obj *var = find_global_symbol(name);
    if (var) {
        if (var->is_function)
            error_at(ident->loc, "'%s' redeclared as different kind of symbol", name);
        if (!type_compatible(var->ty, ty))
            error_at(ident->loc, "conflicting types for '%s'", name);
        if (var->is_thread_local != is_thread_local)
            error_at(ident->loc,
                     "inconsistent _Thread_local redeclaration of '%s'", name);
        if (is_static && !var->is_static)
            error_at(ident->loc, "static declaration of '%s' follows non-static declaration", name);
        // For file-scope objects, a declaration with no storage-class
        // specifier has external linkage. Unlike an explicit `extern`, it does
        // not inherit a prior internal linkage declaration.
        if (!has_storage_class && var->is_static)
            error_at(ident->loc,
                     "non-static declaration of '%s' follows static declaration", name);

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
    var->is_thread_local = is_thread_local;
    var->next = globals;
    globals = var;
    bind_var_in_current_scope(var->name, var, false);
    return var;
}

// Register a function symbol as a global Obj so it can be used as a value
// (e.g. function pointer assignment: fp = add;). Redeclarations are checked
// against the complete recursive function type before metadata is refreshed.
// Return the canonical symbol so a definition can inherit the effective linkage
// established by an earlier declaration.
static Obj *register_function_symbol(char *name, Type *return_ty, bool is_static,
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
        return var;
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
    return fn_obj;
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

        DeclAttrs attrs = {};
        Type *basety = declspec_with_attrs(&tok, tok, &attrs);
        if (attrs.is_typedef) {
            tok = parse_typedef_declaration(tok, basety, &attrs, NULL);
            continue;
        }
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
            if (attrs.storage_class_count || attrs.is_thread_local)
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
            if (attrs.is_thread_local)
                error_at(ident->loc, "_Thread_local may only declare an object");
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
                for (Obj *meta = ty->params; meta; meta = meta->param_next) {
                    if (is_incomplete_object_type(meta->ty))
                        error_at(ident->loc,
                                 "function definition has incomplete parameter type");
                    if (meta->param_vla_star)
                        error_at(ident->loc,
                                 "[*] VLA bound is only allowed in function prototype scope");
                }
                check_supported_function_abi(ty, ident);
            }

            // Register the declaration before parsing a body so recursion and
            // function-address expressions inside the definition see it.
            Obj *fn_symbol = register_function_symbol(
                name, ty->return_ty, is_static, ty->params, ty->is_variadic,
                ty->has_prototype, is_definition);

            // Prototype only: the recursive declarator has already consumed
            // the complete parameter list.
            if (consume(&tok, tok, ";"))
                continue;

            locals = NULL;
            current_gotos = NULL;
            current_labels = NULL;
            current_goto_meta = NULL;
            current_label_meta = NULL;
            current_vm_guard = NULL;
            current_break_scope = NULL;
            current_continue_scope = NULL;
            enter_scope();

            Obj param_head = {};
            Obj *pcur = &param_head;
            Obj *meta_params[64] = {};
            Obj *actual_params[64] = {};
            int nparam = 0;
            for (Obj *meta = ty->params; meta; meta = meta->param_next) {
                if (!meta->name)
                    error_at(ident->loc, "parameter name omitted in function definition");
                if (nparam >= 64)
                    error_at(ident->loc, "too many function parameters");
                Obj *var = create_lvar(meta->name);
                var->ty = meta->ty;
                var->is_register = meta->is_register;
                meta_params[nparam] = meta;
                actual_params[nparam] = var;
                nparam++;
                pcur = pcur->param_next = var;
            }

            Node param_vm_head = {};
            Node *param_vm_cur = &param_vm_head;
            for (int i = 0; i < nparam; i++) {
                rebind_param_vla_type(actual_params[i]->ty, meta_params,
                                      actual_params, nparam);
                append_vm_size_materialization(actual_params[i]->ty,
                                               &param_vm_cur);
            }

            tok = skip(tok, "{");
            bind_predefined_func_name(name);

            Function *fn = calloc(1, sizeof(Function));
            fn->name = name;
            fn->params = param_head.param_next;
            fn->return_ty = ty->return_ty;
            fn->is_static = fn_symbol->is_static;
            fn->is_variadic = ty->is_variadic;

            Type *saved_return_ty = current_return_ty;
            bool saved_variadic = current_function_variadic;
            current_return_ty = ty->return_ty;
            current_function_variadic = ty->is_variadic;
            Node *block = compound_stmt(&tok, tok);
            current_return_ty = saved_return_ty;
            current_function_variadic = saved_variadic;
            if (param_vm_head.next) {
                param_vm_cur->next = block->body;
                fn->body = param_vm_head.next;
            } else {
                fn->body = block->body;
            }
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
                if (type_is_variably_modified(ty))
                    error_at(ident->loc,
                             "variably modified object type is not allowed at file scope");
                if (!is_extern && is_incomplete_object_type(ty) &&
                    !is_unknown_bound_array_with_complete_element(ty))
                    error_at(ident->loc, "variable has incomplete type");

                Obj *var = register_global_symbol(ident, ty, is_static, is_extern,
                                                  attrs.storage_class_count != 0,
                                                  attrs.is_thread_local);
                apply_object_alignment(var, ty, attrs.align, ident);
                ty = var->ty;

                if (equal(tok, "=") && object_has_initializer(var))
                    error_at(ident->loc, "redefinition of global '%s'", var->name);

                if (consume(&tok, tok, "=")) {
                    // A file-scope declaration with an initializer is a
                    // definition even when it is spelled with `extern`.
                    var->is_extern = false;
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
