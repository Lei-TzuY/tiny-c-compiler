from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path('.')

# Member metadata: anonymous struct/union members occupy real storage but have
# no direct identifier. Keep an explicit bit so lookup can promote nested names
# without inventing synthetic member names that would corrupt positional layout.
hdr_path = root / 'minicc.h'
hdr = hdr_path.read_text()
hdr = replace_once(
    hdr,
    '''struct Member {\n    Member *next;\n    char *name;\n    Type *ty;\n    int align;      // explicit _Alignas requirement, 0 = natural type alignment\n    int offset;\n};''',
    '''struct Member {\n    Member *next;\n    char *name;\n    Type *ty;\n    bool is_anonymous; // unnamed C11 struct/union member; nested names are promoted\n    int align;      // explicit _Alignas requirement, 0 = natural type alignment\n    int offset;\n};''',
    'Member metadata',
)
hdr_path.write_text(hdr)

parse_path = root / 'parse.c'
p = parse_path.read_text()

# Anonymous members use NULL names, so make the common token/name predicate safe
# and add a reusable recursive lookup path. The path represents the physical
# member chain that must be walked while the source spelling contains only the
# promoted name (e.g. outer.x through an unnamed inner record).
p = replace_once(
    p,
    '''static bool token_matches_name(Token *tok, const char *name) {\n    return tok->kind == TK_IDENT && strlen(name) == (size_t)tok->len &&\n           !strncmp(tok->loc, name, tok->len);\n}\n''',
    '''static bool token_matches_name(Token *tok, const char *name) {\n    return name && tok->kind == TK_IDENT && strlen(name) == (size_t)tok->len &&\n           !strncmp(tok->loc, name, tok->len);\n}\n\ntypedef struct MemberPath MemberPath;\nstruct MemberPath {\n    Member *member;\n    MemberPath *next;\n};\n\nstatic MemberPath *find_record_member_path_in_list(Member *members, Token *tok) {\n    // Prefer a direct member. C11 uniqueness constraints make the result\n    // unambiguous, but direct-first also keeps diagnostics deterministic.\n    for (Member *m = members; m; m = m->next) {\n        if (m->name && token_matches_name(tok, m->name)) {\n            MemberPath *path = calloc(1, sizeof(MemberPath));\n            path->member = m;\n            return path;\n        }\n    }\n\n    for (Member *m = members; m; m = m->next) {\n        if (!m->is_anonymous || !m->ty || m->ty->kind != TY_STRUCT)\n            continue;\n        MemberPath *sub = find_record_member_path_in_list(m->ty->members, tok);\n        if (!sub)\n            continue;\n        MemberPath *path = calloc(1, sizeof(MemberPath));\n        path->member = m;\n        path->next = sub;\n        return path;\n    }\n    return NULL;\n}\n\nstatic MemberPath *find_record_member_path(Type *ty, Token *tok) {\n    if (!ty || ty->kind != TY_STRUCT || ty->is_incomplete)\n        return NULL;\n    return find_record_member_path_in_list(ty->members, tok);\n}\n\nstatic void free_member_path(MemberPath *path) {\n    while (path) {\n        MemberPath *next = path->next;\n        free(path);\n        path = next;\n    }\n}\n\nstatic bool member_list_has_visible_name(Member *members, const char *name) {\n    for (Member *m = members; m; m = m->next) {\n        if (m->name && !strcmp(m->name, name))\n            return true;\n        if (m->is_anonymous && m->ty && m->ty->kind == TY_STRUCT &&\n            member_list_has_visible_name(m->ty->members, name))\n            return true;\n    }\n    return false;\n}\n\nstatic const char *anonymous_member_conflict(Member *existing, Type *candidate) {\n    if (!candidate || candidate->kind != TY_STRUCT)\n        return NULL;\n    for (Member *m = candidate->members; m; m = m->next) {\n        if (m->is_anonymous) {\n            const char *conflict = anonymous_member_conflict(existing, m->ty);\n            if (conflict)\n                return conflict;\n            continue;\n        }\n        if (m->name && member_list_has_visible_name(existing, m->name))\n            return m->name;\n    }\n    return NULL;\n}\n''',
    'member path helpers',
)

# Record whether the spelling itself used an untagged struct/union specifier.
# A typedef that happens to name an anonymous record is not an anonymous-member
# declaration in C11, so this must be syntax metadata rather than a Type flag.
p = replace_once(
    p,
    '''    bool is_inline;\n    bool is_noreturn;\n    int storage_class_count;\n''',
    '''    bool is_inline;\n    bool is_noreturn;\n    bool has_anonymous_record_specifier;\n    int storage_class_count;\n''',
    'DeclAttrs anonymous record syntax flag',
)

p = replace_once(
    p,
    '''        if (equal(tok, "union")) {\n            note_type_specifier(&specs, tok, &specs.n_named);\n            saw_non_signable_type = true;\n            ty = record_decl(&tok, tok->next, true);\n            continue;\n        }\n\n        if (equal(tok, "struct")) {\n            note_type_specifier(&specs, tok, &specs.n_named);\n            saw_non_signable_type = true;\n            ty = record_decl(&tok, tok->next, false);\n            continue;\n        }\n''',
    '''        if (equal(tok, "union")) {\n            bool anonymous_record_specifier = equal(tok->next, "{");\n            note_type_specifier(&specs, tok, &specs.n_named);\n            saw_non_signable_type = true;\n            ty = record_decl(&tok, tok->next, true);\n            if (attrs && anonymous_record_specifier)\n                attrs->has_anonymous_record_specifier = true;\n            continue;\n        }\n\n        if (equal(tok, "struct")) {\n            bool anonymous_record_specifier = equal(tok->next, "{");\n            note_type_specifier(&specs, tok, &specs.n_named);\n            saw_non_signable_type = true;\n            ty = record_decl(&tok, tok->next, false);\n            if (attrs && anonymous_record_specifier)\n                attrs->has_anonymous_record_specifier = true;\n            continue;\n        }\n''',
    'direct anonymous record specifier tracking',
)

# Materialize a no-declarator untagged struct/union as one physical anonymous
# member. Other no-declarator member declarations violate C11 6.7.2.1p2.
p = replace_once(
    p,
    '''        DeclAttrs attrs = {};\n        Type *basety = declspec_with_attrs(&tok, tok, &attrs);\n        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||\n            attrs.is_typedef || attrs.is_inline || attrs.is_noreturn)\n            error_at(tok->loc, "storage/function specifier is not allowed on a record member");\n        for (bool first = true; !consume(&tok, tok, ";"); first = false) {\n''',
    '''        DeclAttrs attrs = {};\n        Type *basety = declspec_with_attrs(&tok, tok, &attrs);\n        if (attrs.is_auto || attrs.is_static || attrs.is_extern || attrs.is_register ||\n            attrs.is_typedef || attrs.is_inline || attrs.is_noreturn)\n            error_at(tok->loc, "storage/function specifier is not allowed on a record member");\n\n        if (equal(tok, ";")) {\n            if (!attrs.has_anonymous_record_specifier || basety->kind != TY_STRUCT)\n                error_at(tok->loc,\n                         "record member declaration without a declarator must be an anonymous struct or union");\n            if (basety->has_flexible_array_member)\n                error_at(tok->loc,\n                         "anonymous record member cannot contain a flexible array member");\n\n            const char *conflict = anonymous_member_conflict(head.next, basety);\n            if (conflict)\n                error_at(tok->loc,\n                         "anonymous record member promotes duplicate name '%s'", conflict);\n\n            Member *m = calloc(1, sizeof(Member));\n            m->ty = basety;\n            m->is_anonymous = true;\n            m->align = validate_requested_alignment(basety, attrs.align, tok);\n            cur = cur->next = m;\n            tok = tok->next;\n            continue;\n        }\n\n        for (bool first = true; !consume(&tok, tok, ";"); first = false) {\n''',
    'anonymous member materialization',
)

# Named members must not collide with a name promoted by a preceding anonymous
# member. The old direct-only loop also dereferenced NULL anonymous names.
p = replace_once(
    p,
    '''            for (Member *prev = head.next; prev; prev = prev->next)\n                if (token_matches_name(ident, prev->name))\n                    error_at(ident->loc, "duplicate record member name");\n\n            Member *m = calloc(1, sizeof(Member));\n''',
    '''            MemberPath *duplicate =\n                find_record_member_path_in_list(head.next, ident);\n            if (duplicate)\n                error_at(ident->loc, "duplicate record member name");\n            free_member_path(duplicate);\n\n            Member *m = calloc(1, sizeof(Member));\n''',
    'promoted duplicate member check',
)

# Replace direct-only designated-initializer member lookup with the generic
# recursive path. One source `.x` may therefore append multiple physical member
# steps (anonymous container(s) followed by x).
p = replace_once(
    p,
    '''static Member *find_static_initializer_member(Type *ty, Token *tok) {\n    for (Member *m = ty->members; m; m = m->next)\n        if ((int)strlen(m->name) == tok->len &&\n            !strncmp(m->name, tok->loc, tok->len))\n            return m;\n    return NULL;\n}\n\n''',
    '',
    'remove direct-only initializer member lookup',
)

old_designator = '''static InitializerDesignatorPath\nparse_initializer_designator_path(Token **rest, Token *tok, Type *root_ty) {\n    InitializerDesignatorPath path = {.first_index = -1};\n    Type *cur = root_ty;\n\n    while (equal(tok, "[") || equal(tok, ".")) {\n        InitializerDesignator *step = calloc(1, sizeof(InitializerDesignator));\n\n        if (equal(tok, "[")) {\n            Token *where = tok;\n            if (!cur || cur->kind != TY_ARRAY)\n                error_at(where->loc, "array designator requires an array subobject");\n            if (cur->array_len == 0 && path.depth > 0)\n                error_at(where->loc, "nested incomplete arrays are not supported");\n\n            tok = tok->next;\n            int index = parse_array_designator_index(&tok, tok, where);\n            tok = skip(tok, "]");\n            if (cur->array_len > 0 && index >= cur->array_len)\n                error_at(where->loc, "array designator index exceeds array bounds");\n\n            step->kind = INIT_DESIGNATOR_INDEX;\n            step->index = index;\n            step->result_ty = cur->base;\n            if (path.depth == 0)\n                path.first_index = index;\n            cur = cur->base;\n        } else {\n            Token *where = tok;\n            if (!cur || cur->kind != TY_STRUCT)\n                error_at(where->loc, "member designator requires a record subobject");\n            tok = tok->next;\n            if (tok->kind != TK_IDENT)\n                error_at(tok->loc, "expected member name in designated initializer");\n\n            Member *member = find_static_initializer_member(cur, tok);\n            if (!member)\n                error_at(tok->loc, "unknown member in designated initializer");\n            tok = tok->next;\n\n            step->kind = INIT_DESIGNATOR_MEMBER;\n            step->member = member;\n            step->result_ty = member->ty;\n            if (path.depth == 0)\n                path.first_member = member;\n            cur = member->ty;\n        }\n\n        if (!path.head)\n            path.head = step;\n        else\n            path.tail->next = step;\n        path.tail = step;\n        path.depth++;\n    }\n\n    if (!path.depth)\n        error_at(tok->loc, "expected initializer designator");\n\n    path.target_ty = cur;\n    *rest = skip(tok, "=");\n    return path;\n}\n'''
new_designator = '''static void append_initializer_designator_step(InitializerDesignatorPath *path,\n                                               InitializerDesignator *step) {\n    if (!path->head)\n        path->head = step;\n    else\n        path->tail->next = step;\n    path->tail = step;\n    path->depth++;\n}\n\nstatic InitializerDesignatorPath\nparse_initializer_designator_path(Token **rest, Token *tok, Type *root_ty) {\n    InitializerDesignatorPath path = {.first_index = -1};\n    Type *cur = root_ty;\n\n    while (equal(tok, "[") || equal(tok, ".")) {\n        if (equal(tok, "[")) {\n            Token *where = tok;\n            if (!cur || cur->kind != TY_ARRAY)\n                error_at(where->loc, "array designator requires an array subobject");\n            if (cur->array_len == 0 && path.depth > 0)\n                error_at(where->loc, "nested incomplete arrays are not supported");\n\n            tok = tok->next;\n            int index = parse_array_designator_index(&tok, tok, where);\n            tok = skip(tok, "]");\n            if (cur->array_len > 0 && index >= cur->array_len)\n                error_at(where->loc, "array designator index exceeds array bounds");\n\n            InitializerDesignator *step = calloc(1, sizeof(InitializerDesignator));\n            step->kind = INIT_DESIGNATOR_INDEX;\n            step->index = index;\n            step->result_ty = cur->base;\n            if (path.depth == 0)\n                path.first_index = index;\n            cur = cur->base;\n            append_initializer_designator_step(&path, step);\n            continue;\n        }\n\n        Token *where = tok;\n        if (!cur || cur->kind != TY_STRUCT)\n            error_at(where->loc, "member designator requires a record subobject");\n        tok = tok->next;\n        if (tok->kind != TK_IDENT)\n            error_at(tok->loc, "expected member name in designated initializer");\n\n        MemberPath *members = find_record_member_path(cur, tok);\n        if (!members)\n            error_at(tok->loc, "unknown member in designated initializer");\n        tok = tok->next;\n\n        for (MemberPath *mp = members; mp; mp = mp->next) {\n            InitializerDesignator *step = calloc(1, sizeof(InitializerDesignator));\n            step->kind = INIT_DESIGNATOR_MEMBER;\n            step->member = mp->member;\n            step->result_ty = mp->member->ty;\n            if (path.depth == 0)\n                path.first_member = mp->member;\n            cur = mp->member->ty;\n            append_initializer_designator_step(&path, step);\n        }\n        free_member_path(members);\n    }\n\n    if (!path.depth)\n        error_at(tok->loc, "expected initializer designator");\n\n    path.target_ty = cur;\n    *rest = skip(tok, "=");\n    return path;\n}\n'''
p = replace_once(p, old_designator, new_designator, 'promoted initializer designator path')

# Member-expression lookup lowers the same physical path into nested ND_MEMBER
# nodes so codegen/static-address evaluation naturally sum all anonymous offsets.
p = replace_once(
    p,
    '''static Node *postfix(Token **rest, Token *tok) {\n''',
    '''static Node *apply_record_member_path(Node *base, MemberPath *path) {\n    for (MemberPath *mp = path; mp; mp = mp->next) {\n        Node *member = new_node(ND_MEMBER);\n        member->lhs = base;\n        member->member = mp->member;\n        base = member;\n    }\n    return base;\n}\n\nstatic Node *postfix(Token **rest, Token *tok) {\n''',
    'member-expression path lowering helper',
)

old_dot = '''        if (equal(tok, ".")) {\n            tok = tok->next;\n            if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name");\n            add_type(node);\n            if (node->ty->kind != TY_STRUCT) error_at(tok->loc, "not a struct");\n            if (node->ty->is_incomplete) error_at(tok->loc, "incomplete struct type");\n            Member *mem = node->ty->members;\n            for (; mem; mem = mem->next)\n                if ((int)strlen(mem->name) == tok->len &&\n                    !strncmp(mem->name, tok->loc, tok->len)) break;\n            if (!mem) error_at(tok->loc, "unknown member");\n            Node *n = new_node(ND_MEMBER);\n            n->lhs = node; n->member = mem;\n            tok = tok->next; node = n;\n            continue;\n        }\n'''
new_dot = '''        if (equal(tok, ".")) {\n            tok = tok->next;\n            if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name");\n            add_type(node);\n            if (node->ty->kind != TY_STRUCT) error_at(tok->loc, "not a struct");\n            if (node->ty->is_incomplete) error_at(tok->loc, "incomplete struct type");\n            MemberPath *path = find_record_member_path(node->ty, tok);\n            if (!path) error_at(tok->loc, "unknown member");\n            node = apply_record_member_path(node, path);\n            free_member_path(path);\n            tok = tok->next;\n            continue;\n        }\n'''
p = replace_once(p, old_dot, new_dot, 'dot anonymous member promotion')

old_arrow = '''        if (equal(tok, "->")) {\n            tok = tok->next;\n            if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name");\n            add_type(node);\n            if (node->ty->kind != TY_PTR || node->ty->base->kind != TY_STRUCT)\n                error_at(tok->loc, "not a pointer to struct");\n            if (node->ty->base->is_incomplete)\n                error_at(tok->loc, "incomplete struct type");\n            Node *deref = new_unary(ND_DEREF, node);\n            add_type(deref);\n            Member *mem = deref->ty->members;\n            for (; mem; mem = mem->next)\n                if ((int)strlen(mem->name) == tok->len &&\n                    !strncmp(mem->name, tok->loc, tok->len)) break;\n            if (!mem) error_at(tok->loc, "unknown member");\n            Node *n = new_node(ND_MEMBER);\n            n->lhs = deref; n->member = mem;\n            tok = tok->next; node = n;\n            continue;\n        }\n'''
new_arrow = '''        if (equal(tok, "->")) {\n            tok = tok->next;\n            if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name");\n            add_type(node);\n            if (node->ty->kind != TY_PTR || node->ty->base->kind != TY_STRUCT)\n                error_at(tok->loc, "not a pointer to struct");\n            if (node->ty->base->is_incomplete)\n                error_at(tok->loc, "incomplete struct type");\n            Node *deref = new_unary(ND_DEREF, node);\n            add_type(deref);\n            MemberPath *path = find_record_member_path(deref->ty, tok);\n            if (!path) error_at(tok->loc, "unknown member");\n            node = apply_record_member_path(deref, path);\n            free_member_path(path);\n            tok = tok->next;\n            continue;\n        }\n'''
p = replace_once(p, old_arrow, new_arrow, 'arrow anonymous member promotion')

parse_path.write_text(p)

# Wire regression coverage into the standard suite.
make_path = root / 'Makefile'
make = make_path.read_text()
make = replace_once(
    make,
    '\tbash ./test/record_static_assert.sh\n',
    '\tbash ./test/record_static_assert.sh\n\tbash ./test/anonymous_record_members.sh\n',
    'Makefile anonymous member test',
)
make_path.write_text(make)

readme_path = root / 'README.md'
readme = readme_path.read_text()
readme = replace_once(
    readme,
    'block-scoped tags, C11 non-empty struct/union/enum definition bodies, and duplicate-member diagnostics within each record.',
    'block-scoped tags, C11 non-empty struct/union/enum definition bodies, anonymous struct/union members with recursively promoted names, and duplicate-member diagnostics including promoted-name collisions.',
    'README record feature',
)
readme_path.write_text(readme)

# Focused runtime and rejection coverage. These cases exercise direct/pointer
# access, recursive promotion, automatic/static/compound-literal designators,
# positional brace elision, ABI lowering, alignment, invalid no-declarator
# declarations, promoted-name collisions, and FAM containment constraints.
test_path = root / 'test' / 'anonymous_record_members.sh'
test_path.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-anon-member.c
  ./minicc tmp-anon-member.c > tmp-anon-member.s
  cc -o tmp-anon-member tmp-anon-member.s
  set +e
  ./tmp-anon-member
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(anonymous record member): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-anon-member-bad.c
  if ./minicc tmp-anon-member-bad.c > /dev/null 2>tmp-anon-member.err; then
    echo "FAIL(anonymous record member): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Physical anonymous subobjects preserve layout while their names are promoted.
assert_run 9 'struct S{struct{int x;int y;};int z;};int main(void){struct S s={2,3,4};return s.x+s.y+s.z;}'
assert_run 7 'struct S{struct{int x;int y;};};int main(void){struct S s={3,4};struct S *p=&s;return p->x+p->y;}'
assert_run 8 'union U{struct{int x;int y;};long q;};int main(void){union U u={{3,5}};return u.x+u.y;}'
assert_run 6 'struct S{union{struct{int x;};long y;};};int main(void){struct S s={.x=6};return s.x;}'
assert_run 8 'struct S{_Alignas(8) struct{char c;};char d;};int main(void){return _Alignof(struct S);}'

# Promoted designators share the existing nested-designator machinery. Multiple
# paths into one anonymous aggregate must not zero earlier writes.
assert_run 10 'struct S{struct{int x;int y;};int z;};int main(void){struct S s={.x=2,.y=3,.z=5};return s.x+s.y+s.z;}'
assert_run 12 'struct S{union{int x;long y;};int z;};int main(void){struct S s={.x=7,.z=5};return s.x+s.z;}'
assert_run 11 'struct S{struct{int x;int y;};};static struct S s={.x=5,.y=6};int main(void){return s.x+s.y;}'
assert_run 9 'struct S{struct{int x;int y;};};int main(void){return ((struct S){.x=4,.y=5}).x+((struct S){.x=4,.y=5}).y;}'

# Anonymous members remain real ABI-visible subobjects rather than flattened
# duplicate layout entries.
assert_run 7 'struct S{struct{int x;int y;};};int sum(struct S s){return s.x+s.y;}int main(void){struct S s={3,4};return sum(s);}'
assert_run 8 'struct S{char c;struct{int x;};};int main(void){return sizeof(struct S);}'

# C11 6.7.2.1p2: no-declarator member declarations are valid only for an
# untagged struct/union specifier written directly in the declaration.
assert_reject 'struct S{int;};int main(void){return 0;}'
assert_reject 'struct I{int x;};struct O{struct I;};int main(void){return 0;}'
assert_reject 'typedef struct{int x;} I;struct O{I;};int main(void){return 0;}'
assert_reject 'struct O{enum E{A};};int main(void){return 0;}'

# Promoted names inhabit the containing record member namespace recursively.
assert_reject 'struct O{struct{int x;};int x;};int main(void){return 0;}'
assert_reject 'struct O{int x;struct{int x;};};int main(void){return 0;}'
assert_reject 'struct O{struct{int x;};union{long x;int y;};};int main(void){return 0;}'
assert_reject 'struct O{struct{union{int x;long y;};};int x;};int main(void){return 0;}'

# A structure containing a flexible-array member cannot itself be embedded as
# an anonymous record member under the existing C11 FAM containment rule.
assert_reject 'struct O{struct{int n;int a[];};};int main(void){return 0;}'

rm -f tmp-anon-member.c tmp-anon-member.s tmp-anon-member \
      tmp-anon-member-bad.c tmp-anon-member.err

echo 'All C11 anonymous record-member tests passed!'
''')
