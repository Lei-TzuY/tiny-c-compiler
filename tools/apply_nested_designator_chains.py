from pathlib import Path


def func_end(src: str, signature: str) -> int:
    start = src.index(signature)
    brace = src.index('{', start)
    depth = 0
    in_str = False
    in_char = False
    escape = False
    i = brace
    while i < len(src):
        c = src[i]
        if escape:
            escape = False
        elif c == '\\' and (in_str or in_char):
            escape = True
        elif c == '"' and not in_char:
            in_str = not in_str
        elif c == "'" and not in_str:
            in_char = not in_char
        elif not in_str and not in_char:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise RuntimeError(f'unterminated function: {signature}')


p = Path('parse.c')
s = p.read_text()

# Add one shared parser for a C designator-list.  The parser resolves every
# array/member step against the current subobject type and records the resulting
# target type.  Static initializers map the same path to a byte offset while
# automatic initializers map it to an lvalue AST.
sig = 'static bool is_initializer_aggregate(Type *ty) {'
insert_at = func_end(s, sig)
helper = r'''

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
'''
s = s[:insert_at] + helper + s[insert_at:]

# Replace the static array initializer's one-level [idx] special case with the
# shared designator path.  Positional initialization retains brace elision.
static_fn = s.index('static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,\n                                            Type *ty, int offset) {')
array_start = s.index('            int index = next_index;', static_fn)
array_end_marker = '            next_index = index + 1;'
array_end = s.index(array_end_marker, array_start) + len(array_end_marker)
array_new = r'''            if (equal(tok, "[") || equal(tok, ".")) {
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
            next_index = index + 1;'''
s = s[:array_start] + array_new + s[array_end:]

# Replace the static record initializer's one-level .member branch.  A chain
# may now continue through record members and array elements before '='.
record_anchor = s.index('    Member *next_member = ty->members;', static_fn)
record_start = s.index('        if (equal(tok, "["))', record_anchor)
record_end_marker = '        next_member = member->next;'
record_end = s.index(record_end_marker, record_start) + len(record_end_marker)
record_new = r'''        if (equal(tok, ".") || equal(tok, "[")) {
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
        next_member = member->next;'''
s = s[:record_start] + record_new + s[record_end:]

# A designated automatic target uses ordinary initializer assignment once the
# path has been mapped to an lvalue.  Character arrays and braced aggregates
# keep their specialized initialization paths.
auto_sig = 'static void parse_automatic_aggregate_subobject(Node **tail, Node *lhs, Type *ty,\n                                                 Token **rest, Token *tok,\n                                                 Token *where) {'
auto_end = func_end(s, auto_sig)
auto_helper = r'''

static void parse_automatic_designated_initializer(Node **tail, Node *lhs, Type *ty,
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
'''
s = s[:auto_end] + auto_helper + s[auto_end:]

# Collapse the two top-level automatic designator special cases into one shared
# path.  The first designated top-level aggregate is zeroed exactly once so a
# later path into the same aggregate preserves earlier designated leaves.
auto_block_start = s.index('                // Designated initializer: .member = initializer')
auto_block_end = s.index('                // Positional initializer', auto_block_start)
auto_block = r'''                // Designated initializer-list. A chain such as
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

'''
s = s[:auto_block_start] + auto_block + s[auto_block_end:]

p.write_text(s)

# Register focused regression coverage.
p = Path('Makefile')
s = p.read_text()
anchor = '\tbash ./test/array_designators.sh\n'
if anchor not in s:
    raise SystemExit('Makefile array designator anchor missing')
s = s.replace(anchor, anchor + '\tbash ./test/nested_designators.sh\n', 1)
p.write_text(s)

Path('test/nested_designators.sh').write_text(r'''#!/bin/bash
set -eu

run_case() {
  src="$1"
  cat > tmp-nested-designators.c <<EOF
$src
EOF
  ./minicc tmp-nested-designators.c > tmp-nested-designators.s
  cc -o tmp-nested-designators tmp-nested-designators.s
  ./tmp-nested-designators
  echo "OK(nested designator): $src"
}

reject_case() {
  src="$1"
  cat > tmp-nested-designators-bad.c <<EOF
$src
EOF
  if ./minicc tmp-nested-designators-bad.c >/dev/null 2>&1; then
    echo "expected nested designator rejection: $src"
    exit 1
  fi
  echo "OK(reject nested designator): $src"
}

# Static/global chains.
run_case 'int a[2][3] = {[1][2] = 7}; int main(void) { return !(a[0][0] == 0 && a[1][0] == 0 && a[1][2] == 7); }'
run_case 'struct I { int x; int y; }; struct O { int h; struct I inner; int t; }; struct O o = {.inner.y = 9, .h = 2}; int main(void) { return !(o.h == 2 && o.inner.x == 0 && o.inner.y == 9 && o.t == 0); }'
run_case 'struct S { int a[3]; int z; }; struct S s = {.a[1] = 5, .z = 7}; int main(void) { return !(s.a[0] == 0 && s.a[1] == 5 && s.a[2] == 0 && s.z == 7); }'
run_case 'struct P { int x; int y; }; struct P a[2] = {[1].x = 4, [1].y = 6}; int main(void) { return !(a[0].x == 0 && a[1].x == 4 && a[1].y == 6); }'
run_case 'struct I { int x; int y; }; struct O { struct I v[2]; }; struct O o = {.v[1].y = 12}; int main(void) { return !(o.v[0].x == 0 && o.v[1].x == 0 && o.v[1].y == 12); }'
run_case 'int g = 33; struct I { int *p; }; struct O { struct I inner; }; struct O o = {.inner.p = &g}; int main(void) { return *o.inner.p == 33 ? 0 : 1; }'
run_case 'struct S { char rows[2][4]; }; struct S s = {.rows[1] = "hi"}; int main(void) { return !(s.rows[0][0] == 0 && s.rows[1][0] == 104 && s.rows[1][1] == 105 && s.rows[1][2] == 0); }'
run_case 'union U { long a; int b; }; struct W { union U u; int z; }; struct W w = {.u.b = 17, .z = 3}; int main(void) { return !(w.u.b == 17 && w.z == 3); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; struct O o = {.inner.x = 3, .inner.y = 4}; int main(void) { return !(o.inner.x == 3 && o.inner.y == 4); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; struct O o = {.inner.x = 3, .inner.x = 8}; int main(void) { return o.inner.x == 8 ? 0 : 1; }'
run_case 'enum { R = 1, C = 2 }; int a[2][3] = {[R][C] = 19}; int main(void) { return a[1][2] == 19 ? 0 : 1; }'
run_case 'int f(void) { static struct S { int a[2]; int z; } s = {.a[1] = 7, .z = 8}; return s.a[1] + s.z; } int main(void) { return f() == 15 ? 0 : 1; }'

# Automatic/local chains use the same parsed path, but lower it to lvalue ASTs.
run_case 'int main(void) { int a[2][3] = {[1][2] = 7}; return !(a[0][0] == 0 && a[1][0] == 0 && a[1][2] == 7); }'
run_case 'struct I { int x; int y; }; struct O { int h; struct I inner; int t; }; int main(void) { struct O o = {.inner.y = 9, .h = 2}; return !(o.h == 2 && o.inner.x == 0 && o.inner.y == 9 && o.t == 0); }'
run_case 'struct P { int x; int y; }; int main(void) { struct P a[2] = {[1].x = 4, [1].y = 6}; return !(a[0].x == 0 && a[1].x == 4 && a[1].y == 6); }'
run_case 'struct I { int x; int y; }; struct O { struct I v[2]; }; int main(void) { struct O o = {.v[1].y = 12}; return !(o.v[0].x == 0 && o.v[1].x == 0 && o.v[1].y == 12); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner.x = 3, .inner.y = 4}; return !(o.inner.x == 3 && o.inner.y == 4); }'
run_case 'struct S { char rows[2][4]; }; int main(void) { struct S s = {.rows[1] = "hi"}; return !(s.rows[0][0] == 0 && s.rows[1][0] == 104 && s.rows[1][1] == 105 && s.rows[1][2] == 0); }'
run_case 'int g = 21; struct I { int *p; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner.p = &g}; return *o.inner.p == 21 ? 0 : 1; }'

# Constraint and range diagnostics at any point in a chain.
reject_case 'int a[2][3] = {[2][0] = 1}; int main(void) { return 0; }'
reject_case 'int a[2][3] = {[0][3] = 1}; int main(void) { return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; struct O o = {.inner.missing = 1}; int main(void) { return 0; }'
reject_case 'struct S { int x; }; struct S s = {.x[0] = 1}; int main(void) { return 0; }'
reject_case 'int a[2] = {[0].x = 1}; int main(void) { return 0; }'
reject_case 'struct S { int x; }; struct S s = {[0] = 1}; int main(void) { return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; struct O o = {.inner[0] = 1}; int main(void) { return 0; }'
reject_case 'int n = 1; int a[2][2] = {[n][0] = 1}; int main(void) { return 0; }'
reject_case 'struct S { int a[2]; }; struct S s = {.a = 1}; int main(void) { return 0; }'

rm -f tmp-nested-designators.c tmp-nested-designators.s tmp-nested-designators \
      tmp-nested-designators-bad.c

echo 'All nested designated-initializer chain tests passed!'
''')

p = Path('README.md')
s = p.read_text()
line = ('\nDesignated aggregate initializers support nested designator lists such as '
        '`[1][2]`, `[1].field`, `.inner.x`, and `.rows[1]` for both static '
        'storage and automatic objects.\n')
if 'Designated aggregate initializers support nested designator lists' not in s:
    s += line
p.write_text(s)
