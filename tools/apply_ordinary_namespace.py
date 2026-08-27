from pathlib import Path

p = Path('parse.c')
s = p.read_text()

s = s.replace(
    'static Scope *current_scope;\n',
    'static Scope *current_scope;\n\n'
    'static bool type_compatible(Type *a, Type *b);\n'
    'static Type *composite_redecl_type(Type *old_ty, Type *new_ty);\n'
    'static Obj *find_global_symbol(const char *name);\n',
    1,
)

start = s.index('static bool token_matches_name(Token *tok, const char *name) {')
end = s.index('// ---- End Block Scope ----', start)
new_scope_helpers = r'''static bool token_matches_name(Token *tok, const char *name) {
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

'''
s = s[:start] + new_scope_helpers + s[end:]

old_find_var = r'''static Obj *find_var(Token *tok) {
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
}'''
new_find_var = r'''static Obj *find_var(Token *tok) {
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
}'''
if old_find_var not in s:
    raise RuntimeError('find_var anchor not found')
s = s.replace(old_find_var, new_find_var, 1)

start = s.index('static Obj *create_lvar(char *name) {')
end = s.index('static bool is_incomplete_object_type(Type *ty) {', start)
new_var_creators = r'''static Obj *create_lvar(char *name) {
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
            old->is_function != wants_function || !type_compatible(old->ty, ty))
            error("conflicting block-scope declaration of '%s'", name);
        old->ty = composite_redecl_type(old->ty, ty);
        return old;
    }

    Obj *var = find_global_symbol(name);
    if (var) {
        if (var->is_function != wants_function)
            error("'%s' redeclared as different kind of symbol", name);
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

'''
s = s[:start] + new_var_creators + s[end:]

old_enum = r'''        char *name = strndup(tok->loc, tok->len);
        tok = tok->next;

        if (consume(&tok, tok, "=")) {
            Node *value = ternary(&tok, tok);
            val = eval_const_expr(value);
        }

        push_enum_const(name, val++);'''
new_enum = r'''        Token *enumerator = tok;
        tok = tok->next;

        if (consume(&tok, tok, "=")) {
            Node *value = ternary(&tok, tok);
            val = eval_const_expr(value);
        }

        push_enum_const(enumerator, val++);'''
if old_enum not in s:
    raise RuntimeError('enum anchor not found')
s = s.replace(old_enum, new_enum, 1)

old_param = r'''        Obj *param = calloc(1, sizeof(Obj));
        param->ty = param_ty;
        if (name)
            param->name = strndup(name->loc, name->len);
        cur = cur->param_next = param;'''
new_param = r'''        if (name) {
            for (Obj *prev = head.param_next; prev; prev = prev->param_next)
                if (prev->name && token_matches_name(name, prev->name))
                    error_at(name->loc, "duplicate parameter name");
        }

        Obj *param = calloc(1, sizeof(Obj));
        param->ty = param_ty;
        if (name)
            param->name = strndup(name->loc, name->len);
        cur = cur->param_next = param;'''
if old_param not in s:
    raise RuntimeError('parameter anchor not found')
s = s.replace(old_param, new_param, 1)

old_local_create = r'''        Obj *var;
        if (is_static)
            var = create_static_lvar(strndup(ident->loc, ident->len));
        else if (is_extern)
            var = create_extern_ref(strndup(ident->loc, ident->len));
        else
            var = create_lvar(strndup(ident->loc, ident->len));
        var->ty = ty;'''
new_local_create = r'''        char *name = strndup(ident->loc, ident->len);
        Obj *var;
        if (ty->kind == TY_FUNC) {
            if (is_static)
                error_at(ident->loc, "block-scope function declaration cannot be static");
            var = create_extern_ref(name, ty);
        } else if (is_static) {
            var = create_static_lvar(name);
            var->ty = ty;
        } else if (is_extern) {
            var = create_extern_ref(name, ty);
        } else {
            var = create_lvar(name);
            var->ty = ty;
        }'''
if old_local_create not in s:
    raise RuntimeError('local declaration anchor not found')
s = s.replace(old_local_create, new_local_create, 1)

old_direct = '''        if (equal(tok->next, "(")) {\n            Obj *fn = find_var(tok);\n            if (!fn || fn->is_function) {'''
new_direct = '''        if (equal(tok->next, "(")) {\n            Obj *fn = find_var(tok);\n            if (!fn && find_typedef(tok))\n                error_at(tok->loc, "typedef name is not callable");\n            if (!fn || fn->is_function) {'''
if old_direct not in s:
    raise RuntimeError('direct call anchor not found')
s = s.replace(old_direct, new_direct, 1)

old_compound_start = '''static Node *compound_stmt(Token **rest, Token *tok) {\n    enter_scope();\n    Node head = {};'''
new_compound_start = '''static Node *compound_stmt(Token **rest, Token *tok) {\n    // The caller creates the function-definition scope before binding parameters.\n    // Keep the outermost compound statement in that same scope so a declaration\n    // cannot redeclare a parameter; nested `{ ... }` statements still create\n    // ordinary child block scopes in stmt().\n    Node head = {};'''
if old_compound_start not in s:
    raise RuntimeError('compound start anchor not found')
s = s.replace(old_compound_start, new_compound_start, 1)
old_compound_end = '''    Node *node = new_node(ND_BLOCK);\n    node->body = head.next;\n    leave_scope();\n    return node;\n}'''
new_compound_end = '''    Node *node = new_node(ND_BLOCK);\n    node->body = head.next;\n    return node;\n}'''
if old_compound_end not in s:
    raise RuntimeError('compound end anchor not found')
s = s.replace(old_compound_end, new_compound_end, 1)

# File-scope objects/functions are ordinary-name bindings in the root lexical
# scope. Compatible redeclarations reuse the same binding.
old_obj_return = '''        if (!is_extern)\n            var->is_extern = false;\n        return var;'''
new_obj_return = '''        if (!is_extern)\n            var->is_extern = false;\n        bind_var_in_current_scope(var->name, var, true);\n        return var;'''
if old_obj_return not in s:
    raise RuntimeError('global redecl return anchor not found')
s = s.replace(old_obj_return, new_obj_return, 1)
old_obj_new = '''    var->is_extern = is_extern;\n    var->next = globals;\n    globals = var;\n    return var;'''
new_obj_new = '''    var->is_extern = is_extern;\n    var->next = globals;\n    globals = var;\n    bind_var_in_current_scope(var->name, var, false);\n    return var;'''
if old_obj_new not in s:
    raise RuntimeError('global new anchor not found')
s = s.replace(old_obj_new, new_obj_new, 1)

old_fn_redecl = '''        var->ty = composite_redecl_type(var->ty, fty);\n        var->is_static = var->is_static || is_static;\n        var->is_defined = var->is_defined || is_definition;\n        return;'''
new_fn_redecl = '''        var->ty = composite_redecl_type(var->ty, fty);\n        var->is_static = var->is_static || is_static;\n        var->is_defined = var->is_defined || is_definition;\n        bind_var_in_current_scope(var->name, var, true);\n        return;'''
if old_fn_redecl not in s:
    raise RuntimeError('function redecl anchor not found')
s = s.replace(old_fn_redecl, new_fn_redecl, 1)
old_fn_new = '''    fn_obj->is_defined = is_definition;\n    fn_obj->next = globals;\n    globals = fn_obj;\n}'''
new_fn_new = '''    fn_obj->is_defined = is_definition;\n    fn_obj->next = globals;\n    globals = fn_obj;\n    bind_var_in_current_scope(fn_obj->name, fn_obj, false);\n}'''
if old_fn_new not in s:
    raise RuntimeError('function new anchor not found')
s = s.replace(old_fn_new, new_fn_new, 1)

p.write_text(s)

m = Path('Makefile')
ms = m.read_text()
needle = '\tbash ./test/enum_scope.sh\n'
if 'ordinary_namespace.sh' not in ms:
    if needle not in ms:
        raise RuntimeError('Makefile anchor not found')
    ms = ms.replace(needle, needle + '\tbash ./test/ordinary_namespace.sh\n', 1)
m.write_text(ms)

r = Path('README.md')
rs = r.read_text()
note = '\nOrdinary identifiers (objects/functions, typedef names, and enumerators) now obey one lexical namespace with same-scope conflict diagnostics and correct cross-kind shadowing.\n'
if note.strip() not in rs:
    rs += note
r.write_text(rs)

Path('test/ordinary_namespace.sh').write_text(r'''#!/bin/bash
set -eu

run_case() {
  src="$1"
  printf '%s\n' "$src" > tmp-ordinary.c
  ./minicc tmp-ordinary.c > tmp-ordinary.s
  cc -o tmp-ordinary tmp-ordinary.s
  ./tmp-ordinary
  echo "OK(ordinary namespace): $src"
}

reject_case() {
  src="$1"
  printf '%s\n' "$src" > tmp-ordinary-bad.c
  if ./minicc tmp-ordinary-bad.c >/dev/null 2>&1; then
    echo "expected ordinary-namespace rejection: $src"
    exit 1
  fi
  echo "OK(reject ordinary namespace): $src"
}

# Legal shadowing and compatible redeclarations.
run_case 'typedef int T; typedef int T; int main(void) { T x=5; return x==5 ? 0 : 1; }'
run_case 'typedef int T; int main(void) { enum { T=7 }; return T==7 ? 0 : 1; }'
run_case 'int X=4; int main(void) { typedef char X; X y=1; return sizeof(y)==1 ? 0 : 1; }'
run_case 'enum { X=3 }; int main(void) { typedef char X; X y=1; return sizeof(y)==1 ? 0 : 1; }'
run_case 'int main(void) { int x=1; { int x=2; if (x!=2) return 1; } return x==1 ? 0 : 1; }'
run_case 'int g=7; int main(void) { extern int g; extern int g; return g==7 ? 0 : 1; }'
run_case 'int helper(int); int main(void) { int helper(int); return helper(3)==4 ? 0 : 1; } int helper(int x) { return x+1; }'
run_case 'int f(int x) { { int x=3; return x; } } int main(void) { return f(1)==3 ? 0 : 1; }'

# Same-scope ordinary identifiers conflict across all kinds.
reject_case 'int main(void) { int x; int x; return 0; }'
reject_case 'int main(void) { typedef int T; int T; return 0; }'
reject_case 'int main(void) { int T; typedef int T; return 0; }'
reject_case 'int main(void) { enum { X=1 }; int X; return 0; }'
reject_case 'int main(void) { int X; enum { X=1 }; return 0; }'
reject_case 'int main(void) { typedef int X; enum { X=1 }; return 0; }'
reject_case 'int main(void) { enum { X=1 }; typedef int X; return 0; }'
reject_case 'enum { X=1, X=2 }; int main(void) { return 0; }'
reject_case 'typedef int X; int X; int main(void) { return 0; }'
reject_case 'int X; typedef int X; int main(void) { return 0; }'
reject_case 'enum { X=1 }; int X; int main(void) { return 0; }'
reject_case 'int X; enum { X=1 }; int main(void) { return 0; }'
reject_case 'typedef int F; int F(void); int main(void) { return 0; }'
reject_case 'int F(void); typedef int F; int main(void) { return 0; }'
reject_case 'enum { F=1 }; int F(void); int main(void) { return 0; }'

# Nearest ordinary binding blocks outer names of every other kind.
reject_case 'int X=3; int main(void) { typedef int X; return X; }'
reject_case 'typedef int T; int main(void) { enum { T=1 }; T x; return 0; }'
reject_case 'int main(void) { typedef int F; return F(); }'

# Parameter and block-linkage constraints.
reject_case 'int f(int x, int x); int main(void) { return 0; }'
reject_case 'int f(int x, int x) { return x; } int main(void) { return 0; }'
reject_case 'int f(int x) { int x; return x; } int main(void) { return 0; }'
reject_case 'int main(void) { int x; extern int x; return 0; }'
reject_case 'int g; int main(void) { extern long g; return 0; }'
reject_case 'int main(void) { static int f(void); return 0; }'

rm -f tmp-ordinary.c tmp-ordinary.s tmp-ordinary tmp-ordinary-bad.c

echo 'All ordinary identifier namespace tests passed!'
''')
