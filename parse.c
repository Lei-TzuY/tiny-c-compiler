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

typedef struct StructTag StructTag;
struct StructTag {
    StructTag *next;
    char *name;
    Type *ty;
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

static StructTag *push_tag(const char *name, Type *ty) {
    StructTag *tag = calloc(1, sizeof(StructTag));
    tag->name = strdup(name);
    tag->ty = ty;
    tag->next = current_scope->tags;
    current_scope->tags = tag;
    return tag;
}

// ---- End Block Scope ----

static Obj *locals;
static Obj *globals;
static EnumConst *enum_consts;
static TypeDef *typedefs;

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
static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident);

static bool is_typename(Token *tok) {
    if (equal(tok, "int") || equal(tok, "char") || equal(tok, "void") ||
        equal(tok, "enum") || equal(tok, "struct") || equal(tok, "union") ||
        equal(tok, "short") || equal(tok, "long") || equal(tok, "unsigned") ||
        equal(tok, "_Bool") || equal(tok, "float") || equal(tok, "double"))
        return true;
    for (TypeDef *td = typedefs; td; td = td->next)
        if ((int)strlen(td->name) == tok->len &&
            !strncmp(tok->loc, td->name, tok->len))
            return true;
    return false;
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

static Node *new_add(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_ADD, lhs, rhs);

    if (lhs->ty->base && is_integer(rhs->ty))
        return new_binary(ND_ADD, lhs, new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size)));

    if (is_integer(lhs->ty) && rhs->ty->base)
        return new_binary(ND_ADD, rhs, new_binary(ND_MUL, lhs, new_long(rhs->ty->base->size)));

    error("invalid operands");
}

static Node *new_sub(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return new_binary(ND_SUB, lhs, rhs);

    if (lhs->ty->base && is_integer(rhs->ty))
        return new_binary(ND_SUB, lhs, new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size)));

    if (lhs->ty->base && rhs->ty->base) {
        Node *node = new_binary(ND_SUB, lhs, rhs);
        node->ty = ty_long;
        return new_binary(ND_DIV, node, new_long(lhs->ty->base->size));
    }

    error("invalid operands");
}

static Node *new_compound_assign(NodeKind kind, Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (kind == ND_ADD_EQ || kind == ND_SUB_EQ) {
        if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
            return new_binary(kind, lhs, rhs);

        if (lhs->ty->kind == TY_PTR && is_integer(rhs->ty)) {
            rhs = new_binary(ND_MUL, rhs, new_long(lhs->ty->base->size));
            return new_binary(kind, lhs, rhs);
        }

        error("invalid operands");
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
    if (!is_numeric(expr->ty) && expr->ty->kind != TY_PTR)
        error("invalid operand");
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
            tag = push_tag(tag_name, ty);
        }
        *rest = tok;
        return tag->ty;
    }

    Type *ty = NULL;
    if (tag_name) {
        StructTag *tag = find_tag_in_scope(current_scope, tag_name);
        if (tag) {
            if (!tag->ty->is_incomplete)
                error_at(tok->loc, "redefinition of %s %s", kind, tag_name);
            ty = tag->ty;
        } else {
            ty = new_record_type();
            push_tag(tag_name, ty);
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
            tok = tok->next;
            if (tok->kind == TK_IDENT && !equal(tok, "{"))
                tok = tok->next;
            if (consume(&tok, tok, "{")) {
                int64_t val = 0;
                while (!equal(tok, "}")) {
                    if (tok->kind != TK_IDENT)
                        error_at(tok->loc, "expected identifier");
                    char *name = strndup(tok->loc, tok->len);
                    tok = tok->next;
                    if (consume(&tok, tok, "=")) {
                        if (tok->kind != TK_NUM)
                            error_at(tok->loc, "expected integer constant");
                        val = tok->val;
                        tok = tok->next;
                    }
                    EnumConst *ec = calloc(1, sizeof(EnumConst));
                    ec->name = name;
                    ec->val = val++;
                    ec->next = enum_consts;
                    enum_consts = ec;
                    consume(&tok, tok, ",");
                }
                tok = skip(tok, "}");
            }
            ty = ty_int;
            continue;
        }

        // Check for typedef name
        if (tok->kind == TK_IDENT) {
            bool found = false;
            for (TypeDef *td = typedefs; td; td = td->next) {
                if ((int)strlen(td->name) == tok->len &&
                    !strncmp(tok->loc, td->name, tok->len)) {
                    tok = tok->next;
                    ty = td->ty;
                    found = true;
                    break;
                }
            }
            if (found) continue;
        }

        break;
    }

    *rest = tok;
    return ty ? ty : ty_int;
}

static Type *declarator(Token **rest, Token *tok, Type *ty, Token **ident) {
    while (consume(&tok, tok, "*"))
        ty = pointer_to(ty);

    // Function pointer: "(" "*"+ ident ")" "(" params ")"
    if (equal(tok, "(") && equal(tok->next, "*")) {
        tok = tok->next->next; // skip "(" and "*"
        // Additional pointer levels inside: int (**fp)(...)
        int extra_ptrs = 0;
        while (consume(&tok, tok, "*"))
            extra_ptrs++;

        if (tok->kind != TK_IDENT)
            error_at(tok->loc, "expected identifier in function pointer declarator");
        *ident = tok;
        tok = tok->next;
        tok = skip(tok, ")");
        tok = skip(tok, "(");

        // Skip parameter declarations (we don't store them)
        if (equal(tok, "void") && equal(tok->next, ")")) {
            tok = tok->next; // void param list = no params
        } else {
            while (!equal(tok, ")")) {
                if (!equal(tok, ",") || equal(tok, ")")) {
                    // Skip tokens until ',' or ')'
                    // Simple approach: skip type + optional name
                    if (is_typename(tok) || equal(tok, "const") || equal(tok, "volatile")) {
                        Type *dummy_ty = declspec(&tok, tok);
                        (void)dummy_ty;
                        while (consume(&tok, tok, "*")) {} // skip pointer stars
                        // Skip optional parameter name
                        if (tok->kind == TK_IDENT && !equal(tok->next, "("))
                            tok = tok->next;
                        // Skip array declarators in params: int arr[]
                        if (consume(&tok, tok, "[")) {
                            while (!equal(tok, "]")) tok = tok->next;
                            tok = skip(tok, "]");
                        }
                    } else {
                        tok = tok->next;
                    }
                }
                if (!equal(tok, ")"))
                    consume(&tok, tok, ",");
            }
        }
        tok = skip(tok, ")");

        // Build type: pointer_to(func_type(return_ty))
        Type *fty = func_type(ty); // ty is the return type (the base)
        ty = pointer_to(fty);
        for (int i = 0; i < extra_ptrs; i++)
            ty = pointer_to(ty);

        *rest = tok;
        return ty;
    }

    if (tok->kind != TK_IDENT)
        error_at(tok->loc, "expected a variable name");

    *ident = tok;
    tok = tok->next;

    // Multi-dimensional arrays: ident "[" num? "]" ("[" num? "]")*
    int sizes[16];
    int ndim = 0;
    while (consume(&tok, tok, "[")) {
        if (tok->kind == TK_NUM) {
            sizes[ndim++] = tok->val;
            tok = tok->next;
        } else {
            sizes[ndim++] = 0; // infer from initializer
        }
        tok = skip(tok, "]");
    }
    // Apply in reverse to build nested array types
    for (int i = ndim - 1; i >= 0; i--)
        ty = array_of(ty, sizes[i]);

    *rest = tok;
    return ty;
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
                    Node *a = new_binary(ND_ASSIGN, member_node, e);
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
                    Node *a = new_binary(ND_ASSIGN, lhs, e);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    cur_idx = idx + 1;
                    continue;
                }

                // Positional initializer
                Node *e = assign(&tok, tok);
                if (ty->kind == TY_ARRAY) {
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(cur_idx++)));
                    Node *a = new_binary(ND_ASSIGN, lhs, e);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                } else if (ty->kind == TY_STRUCT && cur_mem) {
                    Node *var_node = new_var_node(var);
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = var_node;
                    member_node->member = cur_mem;
                    Node *a = new_binary(ND_ASSIGN, member_node, e);
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
        Node *a = new_binary(ND_ASSIGN, vnode, rhs);
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
        Node *node = new_node(ND_RETURN);
        if (!equal(tok->next, ";"))
            node->lhs = expr(&tok, tok->next);
        else
            tok = tok->next;
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
            Token *ident;
            basety = declarator(&tok, tok, basety, &ident);
            TypeDef *td = calloc(1, sizeof(TypeDef));
            td->name = strndup(ident->loc, ident->len);
            td->ty = basety;
            td->next = typedefs; typedefs = td;
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

static Node *assign(Token **rest, Token *tok) {
    Node *node = ternary(&tok, tok);
    if (equal(tok, "="))
        node = new_binary(ND_ASSIGN, node, assign(&tok, tok->next));
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
    Node *node = new_node(ND_TERNARY);
    node->cond = cond;
    tok = tok->next;
    node->then = expr(&tok, tok);
    tok = skip(tok, ":");
    node->els = ternary(rest, tok);
    return node;
}

static Node *logor(Token **rest, Token *tok) {
    Node *node = logand(&tok, tok);
    while (equal(tok, "||"))
        node = new_binary(ND_LOGOR, node, logand(&tok, tok->next));
    *rest = tok;
    return node;
}

static Node *logand(Token **rest, Token *tok) {
    Node *node = bitor_expr(&tok, tok);
    while (equal(tok, "&&"))
        node = new_binary(ND_LOGAND, node, bitor_expr(&tok, tok->next));
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
        if (equal(tok, "==")) { node = new_binary(ND_EQ, node, relational(&tok, tok->next)); continue; }
        if (equal(tok, "!=")) { node = new_binary(ND_NE, node, relational(&tok, tok->next)); continue; }
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
        if (equal(tok, "<"))  { node = new_binary(ND_LT, node, shift(&tok, tok->next)); continue; }
        if (equal(tok, "<=")) { node = new_binary(ND_LE, node, shift(&tok, tok->next)); continue; }
        if (equal(tok, ">"))  { node = new_binary(ND_LT, shift(&tok, tok->next), node); continue; }
        if (equal(tok, ">=")) { node = new_binary(ND_LE, shift(&tok, tok->next), node); continue; }
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
        Type *ty = declspec(&tok, tok);
        while (consume(&tok, tok, "*"))
            ty = pointer_to(ty);
        tok = skip(tok, ")");
        Node *node = new_unary(ND_CAST, unary(rest, tok));
        node->ty = ty;
        return node;
    }

    if (equal(tok, "+"))  return unary(rest, tok->next);
    if (equal(tok, "-"))  return new_binary(ND_SUB, new_num(0), unary(rest, tok->next));
    if (equal(tok, "&"))  return new_unary(ND_ADDR, unary(rest, tok->next));
    if (equal(tok, "*"))  return new_unary(ND_DEREF, unary(rest, tok->next));
    if (equal(tok, "!"))  return new_unary(ND_NOT, unary(rest, tok->next));
    if (equal(tok, "~"))  return new_unary(ND_BITNOT, unary(rest, tok->next));
    if (equal(tok, "++")) return new_inc_dec(ND_PRE_INC, unary(rest, tok->next));
    if (equal(tok, "--")) return new_inc_dec(ND_PRE_DEC, unary(rest, tok->next));

    return postfix(rest, tok);
}

static Node *postfix(Token **rest, Token *tok) {
    Node *node = primary(&tok, tok);

    for (;;) {
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
            Type *ty = declspec(&tok, tok);
            while (consume(&tok, tok, "*"))
                ty = pointer_to(ty);
            if (is_incomplete_object_type(ty))
                error_at(tok->loc, "invalid sizeof on incomplete type");
            *rest = skip(tok, ")");
            return new_num(ty->size);
        }
        Node *n = unary(rest, tok);
        add_type(n);
        if (is_incomplete_object_type(n->ty))
            error_at(tok->loc, "invalid sizeof on incomplete type");
        return new_num(n->ty->size);
    }

    if (tok->kind == TK_IDENT) {
        // Check for enum constant
        for (EnumConst *ec = enum_consts; ec; ec = ec->next) {
            if (strlen(ec->name) == (size_t)tok->len &&
                !strncmp(tok->loc, ec->name, tok->len)) {
                *rest = tok->next;
                return new_num(ec->val);
            }
        }

        // Function call
        if (equal(tok->next, "(")) {
            // Check if this is a variable (function pointer) or a direct call
            Obj *var = find_var(tok);

            if (var && !var->is_function) {
                // Indirect call through function pointer variable. The current
                // declarator keeps the return type even though it does not yet
                // retain a full function-pointer parameter prototype.
                Node *node = new_node(ND_FUNCALL);
                node->funcname = NULL; // NULL = indirect call
                node->lhs = new_var_node(var); // callee expression
                if (var->ty->kind == TY_PTR && var->ty->base &&
                    var->ty->base->kind == TY_FUNC)
                    node->ty = var->ty->base->return_ty;
                tok = skip(tok->next, "(");

                Node head = {};
                Node *cur = &head;
                while (!equal(tok, ")")) {
                    if (cur != &head) tok = skip(tok, ",");
                    cur = cur->next = assign(&tok, tok);
                }
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
            Node head = {};
            Node *cur = &head;
            while (!equal(tok, ")")) {
                if (cur != &head)
                    tok = skip(tok, ",");

                Node *arg = assign(&tok, tok);
                add_type(arg);

                if (expected) {
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

// Register a function symbol as a global Obj so it can be used as a value
// (e.g. function pointer assignment: fp = add;)
static void register_function_symbol(char *name, Type *return_ty, bool is_static,
                                     Obj *params, bool is_variadic) {
    // A later definition refreshes metadata from an earlier prototype.
    for (Obj *var = globals; var; var = var->next) {
        if (!strcmp(var->name, name) && var->is_function) {
            var->ty = func_type(return_ty);
            var->func_params = params;
            var->func_variadic = is_variadic;
            var->is_static = is_static;
            return;
        }
    }

    Obj *fn_obj = calloc(1, sizeof(Obj));
    fn_obj->name = name;
    fn_obj->ty = func_type(return_ty);
    fn_obj->func_params = params;
    fn_obj->func_variadic = is_variadic;
    fn_obj->is_local = false;
    fn_obj->is_function = true;
    fn_obj->is_static = is_static;
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
                Token *ident;
                basety = declarator(&tok, tok, basety, &ident);
                TypeDef *td = calloc(1, sizeof(TypeDef));
                td->name = strndup(ident->loc, ident->len);
                td->ty = basety;
                td->next = typedefs; typedefs = td;
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

        if (consume(&tok, tok, "(")) {
            // Function definition or prototype
            char *name = strndup(ident->loc, ident->len);

            locals = NULL;
            current_gotos = NULL;
            current_labels = NULL;
            enter_scope();

            Obj param_head = {};
            Obj *pcur = &param_head;

            bool is_variadic = false;
            // Parse void parameter list
            if (equal(tok, "void") && equal(tok->next, ")")) {
                tok = tok->next;
            } else {
                while (!equal(tok, ")")) {
                    if (pcur != &param_head)
                        tok = skip(tok, ",");
                    if (equal(tok, "...")) {
                        tok = tok->next;
                        is_variadic = true;
                        break;
                    }
                    // Skip qualifiers
                    consume(&tok, tok, "const");
                    consume(&tok, tok, "volatile");
                    consume(&tok, tok, "register");

                    Type *param_basety = declspec(&tok, tok);
                    Token *pident;
                    Type *param_ty = declarator(&tok, tok, param_basety, &pident);
                    if (is_incomplete_object_type(param_ty))
                        error_at(pident->loc, "parameter has incomplete type");

                    char *pname = strndup(pident->loc, pident->len);
                    Obj *var = create_lvar(pname);
                    var->ty = param_ty;
                    pcur = pcur->param_next = var;
                }
            }
            tok = skip(tok, ")");

            // Register function symbol for calls and function-pointer usage.
            register_function_symbol(name, basety, is_static,
                                     param_head.param_next, is_variadic);

            // Function prototype
            if (consume(&tok, tok, ";")) {
                leave_scope();
                continue;
            }

            tok = skip(tok, "{");

            Function *fn = calloc(1, sizeof(Function));
            fn->name = name;
            fn->params = param_head.param_next;
            fn->return_ty = basety;
            fn->is_static = is_static;
            fn->is_variadic = is_variadic;

            Node *block = compound_stmt(&tok, tok);
            fn->body = block->body;
            fn->locals = locals;

            resolve_gotos();
            fn->gotos = current_gotos;
            fn->labels = current_labels;

            leave_scope();
            cur = cur->next = fn;
        } else {
            if (!is_extern && is_incomplete_object_type(ty))
                error_at(ident->loc, "variable has incomplete type");

            // Global variable(s) (possibly with initializer)
            for (;;) {
                Obj *var = calloc(1, sizeof(Obj));
                var->name = strndup(ident->loc, ident->len);
                var->ty = ty;
                var->is_local = false;
                var->is_static = is_static;
                var->is_extern = is_extern;
                var->next = globals;
                globals = var;

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
