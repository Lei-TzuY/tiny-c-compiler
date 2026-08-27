from pathlib import Path

parse_path = Path("parse.c")
src = parse_path.read_text()

sig = "static void parse_automatic_aggregate_subobject(Node **tail, Node *lhs, Type *ty,"
start = src.index(sig)
brace = src.index("{", start)
depth = 0
end = None
for i in range(brace, len(src)):
    c = src[i]
    if c == "{":
        depth += 1
    elif c == "}":
        depth -= 1
        if depth == 0:
            end = i + 1
            break
if end is None:
    raise RuntimeError("could not find parse_automatic_aggregate_subobject end")

new_func = r'''static void parse_automatic_aggregate_subobject(Node **tail, Node *lhs, Type *ty,
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
}'''

src = src[:start] + new_func + src[end:]

prototype = r'''static void parse_automatic_designated_initializer(Node **tail, Node *lhs,
                                                    Type *ty, Token **rest,
                                                    Token *tok, Token *where);

'''
insert_at = src.index(sig)
if prototype.strip() not in src:
    src = src[:insert_at] + prototype + src[insert_at:]

parse_path.write_text(src)

make_path = Path("Makefile")
make = make_path.read_text()
needle = "\tbash ./test/nested_designators.sh\n"
addition = needle + "\tbash ./test/nested_brace_designators.sh\n"
if "nested_brace_designators.sh" not in make:
    if needle not in make:
        raise RuntimeError("Makefile nested-designator anchor not found")
    make = make.replace(needle, addition, 1)
make_path.write_text(make)

readme_path = Path("README.md")
readme = readme_path.read_text()
note = "\nNested braced aggregate initializer-lists accept member/array designators at every level, including positional continuation after a designator for automatic objects.\n"
if note.strip() not in readme:
    readme += note
readme_path.write_text(readme)

# Focused regression suite.
test_path = Path("test/nested_brace_designators.sh")
test_path.write_text(r'''#!/bin/bash
set -eu

run_case() {
  src="$1"
  cat > tmp-nested-brace-designators.c <<EOF
$src
EOF
  ./minicc tmp-nested-brace-designators.c > tmp-nested-brace-designators.s
  cc -o tmp-nested-brace-designators tmp-nested-brace-designators.s
  ./tmp-nested-brace-designators
  echo "OK(nested brace designator): $src"
}

reject_case() {
  src="$1"
  cat > tmp-nested-brace-designators-bad.c <<EOF
$src
EOF
  if ./minicc tmp-nested-brace-designators-bad.c >/dev/null 2>&1; then
    echo "expected nested-brace designator rejection: $src"
    exit 1
  fi
  echo "OK(reject nested brace designator): $src"
}

# Static paths were already recursive; keep them covered while automatic
# nested-brace parsing is brought to the same language surface.
run_case 'struct I { int x; int y; }; struct O { struct I inner; int z; }; struct O o = {.inner = {.y = 4, .x = 3}, .z = 5}; int main(void) { return !(o.inner.x == 3 && o.inner.y == 4 && o.z == 5); }'
run_case 'int a[2][3] = {[1] = {[2] = 7, [0] = 4}}; int main(void) { return !(a[0][0] == 0 && a[1][0] == 4 && a[1][1] == 0 && a[1][2] == 7); }'
run_case 'int f(void) { static struct I { int x; int y; } a[2] = {[1] = {.y = 8, .x = 6}}; return a[1].x + a[1].y; } int main(void) { return f() == 14 ? 0 : 1; }'

# Automatic nested braced initializer-lists.
run_case 'struct I { int x; int y; }; struct O { struct I inner; int z; }; int main(void) { struct O o = {.inner = {.y = 4, .x = 3}, .z = 5}; return !(o.inner.x == 3 && o.inner.y == 4 && o.z == 5); }'
run_case 'int main(void) { int a[2][3] = {[1] = {[2] = 7, [0] = 4}}; return !(a[0][0] == 0 && a[1][0] == 4 && a[1][1] == 0 && a[1][2] == 7); }'
run_case 'int main(void) { int a[2][3] = {{[1] = 2}, {[2] = 7}}; return !(a[0][0] == 0 && a[0][1] == 2 && a[1][0] == 0 && a[1][2] == 7); }'
run_case 'int main(void) { int a[1][3] = {{[1] = 5, 6}}; return !(a[0][0] == 0 && a[0][1] == 5 && a[0][2] == 6); }'
run_case 'struct I { int x; int y; int z; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.y = 2, 3}}; return !(o.inner.x == 0 && o.inner.y == 2 && o.inner.z == 3); }'
run_case 'struct I { int x; int y; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.x = 1, .x = 4, .y = 7}}; return !(o.inner.x == 4 && o.inner.y == 7); }'
run_case 'struct S { char rows[2][4]; }; int main(void) { struct S s = {.rows = {[1] = "hi"}}; return !(s.rows[0][0] == 0 && s.rows[1][0] == 104 && s.rows[1][1] == 105 && s.rows[1][2] == 0); }'
run_case 'struct P { int x; int y; }; int main(void) { struct P a[2] = {{.y = 2, .x = 1}, {.x = 3}}; return !(a[0].x == 1 && a[0].y == 2 && a[1].x == 3 && a[1].y == 0); }'
run_case 'int g = 21; struct I { int *p; int n; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.p = &g, .n = 2}}; return !(*o.inner.p == 21 && o.inner.n == 2); }'
run_case 'union U { long l; int i; }; struct W { union U u; int z; }; int main(void) { struct W w = {.u = {.l = 17}, .z = 3}; return !(w.u.l == 17 && w.z == 3); }'
run_case 'struct I { int x; int y; }; struct M { struct I inner; int m; }; struct O { struct M mid; }; int main(void) { struct O o = {.mid = {.inner = {.y = 9}, .m = 4}}; return !(o.mid.inner.x == 0 && o.mid.inner.y == 9 && o.mid.m == 4); }'
run_case 'struct I { int x; int y; int z; }; struct O { struct I inner; int tail; }; int main(void) { struct O o = {.inner = {.y = 5}, .tail = 8}; return !(o.inner.x == 0 && o.inner.y == 5 && o.inner.z == 0 && o.tail == 8); }'
run_case 'enum { R = 1, C = 2 }; int main(void) { int a[2][3] = {[R] = {[C] = 19}}; return a[1][2] == 19 ? 0 : 1; }'

# Nested path diagnostics must still be enforced inside the inner braces.
reject_case 'int main(void) { int a[1][2] = {{[2] = 1}}; return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.missing = 1}}; return 0; }'
reject_case 'int main(void) { int a[1][2] = {{.x = 1}}; return 0; }'
reject_case 'struct I { int x; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {[0] = 1}}; return 0; }'
reject_case 'int main(void) { int n = 1; int a[1][2] = {{[n] = 1}}; return 0; }'
reject_case 'union U { int a; long b; }; struct O { union U u; }; int main(void) { struct O o = {.u = {.a = 1, .b = 2}}; return 0; }'
reject_case 'int main(void) { int a[1][3] = {{[2] = 7, 8}}; return 0; }'
reject_case 'struct I { int x; int y; }; struct O { struct I inner; }; int main(void) { struct O o = {.inner = {.y = 2, 3}}; return 0; }'

rm -f tmp-nested-brace-designators.c tmp-nested-brace-designators.s \
      tmp-nested-brace-designators tmp-nested-brace-designators-bad.c

echo 'All nested-brace designated initializer tests passed!'
''')
