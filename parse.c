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
    // First VLA in a lexical scope snapshots RSP here. All VLA allocations in
    // that scope are discarded together when the scope is exited.
    Obj *vla_stack_save;
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
static bool current_function_has_vla;

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
    node->ty = ty_ulong;
    return node;
}

/* Remaining parser implementation is intentionally unchanged. */

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
