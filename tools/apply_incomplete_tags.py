from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"expected snippet not found in {path}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1))


# Type metadata: distinguish a forward-declared record from a complete one.
replace_once(
    "minicc.h",
    "    bool is_unsigned; // true for unsigned integer types\n    Type *base;       // Pointer or array\n",
    "    bool is_unsigned; // true for unsigned integer types\n    bool is_incomplete; // forward-declared struct/union with no body yet\n    Type *base;       // Pointer or array\n",
)

p = Path("parse.c")
text = p.read_text()

old_scope = '''struct Scope {
    Scope *parent;
    VarScope *vars;
};
'''
new_scope = '''struct Scope {
    Scope *parent;
    VarScope *vars;
    StructTag *tags;
};
'''
if old_scope not in text:
    raise SystemExit("scope layout snippet not found")
text = text.replace(old_scope, new_scope, 1)

text = text.replace(
    "static TypeDef *typedefs;\nstatic StructTag *struct_tags;\n",
    "static TypeDef *typedefs;\n",
    1,
)

scope_anchor = '''static void leave_scope(void) {
    current_scope = current_scope->parent;
}

// ---- End Block Scope ----
'''
scope_helpers = '''static void leave_scope(void) {
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
'''
if scope_anchor not in text:
    raise SystemExit("scope helper anchor not found")
text = text.replace(scope_anchor, scope_helpers, 1)

record_helpers = r'''static bool is_incomplete_object_type(Type *ty) {
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

'''
anchor = "static Type *declspec(Token **rest, Token *tok) {\n"
if anchor not in text:
    raise SystemExit("declspec anchor not found")
text = text.replace(anchor, record_helpers + anchor, 1)

start = text.find('        if (equal(tok, "union")) {')
end = text.find('        if (equal(tok, "enum")) {', start)
if start < 0 or end < 0:
    raise SystemExit("struct/union parser region not found")
replacement = '''        if (equal(tok, "union")) {
            ty = record_decl(&tok, tok->next, true);
            continue;
        }

        if (equal(tok, "struct")) {
            ty = record_decl(&tok, tok->next, false);
            continue;
        }

'''
text = text[:start] + replacement + text[end:]

# Reject actual object storage with incomplete record types while still allowing
# pointers and extern declarations.
local_decl_old = '''        Token *ident;
        Type *ty = declarator(&tok, tok, basety, &ident);

        Obj *var;
'''
local_decl_new = '''        Token *ident;
        Type *ty = declarator(&tok, tok, basety, &ident);
        if (!is_extern && is_incomplete_object_type(ty))
            error_at(ident->loc, "variable has incomplete type");

        Obj *var;
'''
if local_decl_old not in text:
    raise SystemExit("local declaration snippet not found")
text = text.replace(local_decl_old, local_decl_new, 1)

param_old = '''                    Type *param_basety = declspec(&tok, tok);
                    Token *pident;
                    Type *param_ty = declarator(&tok, tok, param_basety, &pident);

                    char *pname = strndup(pident->loc, pident->len);
'''
param_new = '''                    Type *param_basety = declspec(&tok, tok);
                    Token *pident;
                    Type *param_ty = declarator(&tok, tok, param_basety, &pident);
                    if (is_incomplete_object_type(param_ty))
                        error_at(pident->loc, "parameter has incomplete type");

                    char *pname = strndup(pident->loc, pident->len);
'''
if param_old not in text:
    raise SystemExit("parameter declaration snippet not found")
text = text.replace(param_old, param_new, 1)

global_old = '''        } else {
            // Global variable(s) (possibly with initializer)
            for (;;) {
'''
global_new = '''        } else {
            if (!is_extern && is_incomplete_object_type(ty))
                error_at(ident->loc, "variable has incomplete type");

            // Global variable(s) (possibly with initializer)
            for (;;) {
'''
if global_old not in text:
    raise SystemExit("global declaration snippet not found")
text = text.replace(global_old, global_new, 1)

sizeof_type_old = '''            while (consume(&tok, tok, "*"))
                ty = pointer_to(ty);
            *rest = skip(tok, ")");
            return new_num(ty->size);
'''
sizeof_type_new = '''            while (consume(&tok, tok, "*"))
                ty = pointer_to(ty);
            if (is_incomplete_object_type(ty))
                error_at(tok->loc, "invalid sizeof on incomplete type");
            *rest = skip(tok, ")");
            return new_num(ty->size);
'''
if sizeof_type_old not in text:
    raise SystemExit("sizeof(type) snippet not found")
text = text.replace(sizeof_type_old, sizeof_type_new, 1)

sizeof_expr_old = '''        Node *n = unary(rest, tok);
        add_type(n);
        return new_num(n->ty->size);
'''
sizeof_expr_new = '''        Node *n = unary(rest, tok);
        add_type(n);
        if (is_incomplete_object_type(n->ty))
            error_at(tok->loc, "invalid sizeof on incomplete type");
        return new_num(n->ty->size);
'''
if sizeof_expr_old not in text:
    raise SystemExit("sizeof(expr) snippet not found")
text = text.replace(sizeof_expr_old, sizeof_expr_new, 1)

member_old = '''            add_type(node);
            if (node->ty->kind != TY_STRUCT) error_at(tok->loc, "not a struct");
            Member *mem = node->ty->members;
'''
member_new = '''            add_type(node);
            if (node->ty->kind != TY_STRUCT) error_at(tok->loc, "not a struct");
            if (node->ty->is_incomplete) error_at(tok->loc, "incomplete struct type");
            Member *mem = node->ty->members;
'''
if member_old not in text:
    raise SystemExit("member access snippet not found")
text = text.replace(member_old, member_new, 1)

arrow_old = '''            if (node->ty->kind != TY_PTR || node->ty->base->kind != TY_STRUCT)
                error_at(tok->loc, "not a pointer to struct");
            Node *deref = new_unary(ND_DEREF, node);
'''
arrow_new = '''            if (node->ty->kind != TY_PTR || node->ty->base->kind != TY_STRUCT)
                error_at(tok->loc, "not a pointer to struct");
            if (node->ty->base->is_incomplete)
                error_at(tok->loc, "incomplete struct type");
            Node *deref = new_unary(ND_DEREF, node);
'''
if arrow_old not in text:
    raise SystemExit("arrow access snippet not found")
text = text.replace(arrow_old, arrow_new, 1)

p.write_text(text)

# Regression coverage for forward declarations, completion-in-place, recursive
# records, unions, tag shadowing, and rejected incomplete object operations.
Path("test/incomplete_tags.sh").write_text(r'''#!/bin/bash
set -e

assert_record() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-record.c
  "${MINICC:-./minicc}" tmp-record.c > tmp-record.s
  gcc -o tmp-record tmp-record.s
  set +e
  ./tmp-record
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(record): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(record): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-record-reject.c
  if "${MINICC:-./minicc}" tmp-record-reject.c > /dev/null 2>&1; then
    echo "FAIL(record): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(record): rejected invalid incomplete-type use"
}

assert_record 7 'typedef struct FILE FILE; struct FILE { int fd; }; int main() { FILE f; f.fd=7; return f.fd; }'
assert_record 9 'typedef struct Node Node; struct Node { Node *next; int value; }; int main() { Node a; Node b; a.next=&b; b.value=9; return a.next->value; }'
assert_record 5 'struct Node { struct Node *next; int value; }; int main() { struct Node a; struct Node b; a.next=&b; b.value=5; return a.next->value; }'
assert_record 6 'struct B; struct A { struct B *b; }; struct B { struct A *a; int x; }; int main() { struct A a; struct B b; a.b=&b; b.a=&a; b.x=6; return a.b->x; }'
assert_record 4 'union U; union U { int x; char c; }; int main() { union U u; u.x=4; return u.x; }'
assert_record 8 'struct S { int x; }; int main() { struct S a; a.x=3; { struct S { int y; }; struct S b; b.y=5; a.x += b.y; } return a.x; }'
assert_record 8 'struct Opaque; int main() { return sizeof(struct Opaque*) == 8 ? 8 : 0; }'
assert_record 3 'struct S; extern struct S ext; struct S { int x; }; int main() { struct S s; s.x=3; return s.x; }'

assert_reject 'struct S; int main() { struct S value; return 0; }'
assert_reject 'struct S; int main() { return sizeof(struct S); }'
assert_reject 'struct S; struct T { struct S field; }; int main() { return 0; }'
assert_reject 'struct S { int x; }; struct S { int y; }; int main() { return 0; }'

echo "All incomplete record/tag scope tests passed!"
''')

replace_once(
    "Makefile",
    "\tbash ./test/float_abi.sh\n",
    "\tbash ./test/float_abi.sh\n\tbash ./test/incomplete_tags.sh\n",
)

# Small documentation update.
readme = Path("README.md")
rtext = readme.read_text()
needle = "- **Floating point**: scalar `float`/`double` literals"
pos = rtext.find(needle)
if pos >= 0:
    line_end = rtext.find("\n", pos)
    insert = "\n- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required."
    rtext = rtext[:line_end] + insert + rtext[line_end:]
    readme.write_text(rtext)

print("incomplete record and tag-scope migration applied")
