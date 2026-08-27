from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


p = Path('parse.c')
s = p.read_text()

anchor = '''static Member *find_static_initializer_member(Type *ty, Token *tok) {
    for (Member *m = ty->members; m; m = m->next)
        if ((int)strlen(m->name) == tok->len &&
            !strncmp(m->name, tok->loc, tok->len))
            return m;
    return NULL;
}

static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty, int offset) {
'''
replacement = '''static Member *find_static_initializer_member(Type *ty, Token *tok) {
    for (Member *m = ty->members; m; m = m->next)
        if ((int)strlen(m->name) == tok->len &&
            !strncmp(m->name, tok->loc, tok->len))
            return m;
    return NULL;
}

static bool is_initializer_aggregate(Type *ty) {
    return ty && (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT);
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
'''
s = replace_once(s, anchor, replacement, 'insert static brace-elision helpers')

old = '''            int index = next_index;
            if (equal(tok, "[")) {
                Token *designator = tok;
                tok = tok->next;
                index = parse_array_designator_index(&tok, tok, designator);
                tok = skip(tok, "]");
                tok = skip(tok, "=");
            }

            if (ty->array_len > 0 && index >= ty->array_len)
                error_at(tok->loc, "array designator index exceeds array bounds");

            int elem_offset = offset + index * ty->base->size;
            reset_static_subobject(var, elem_offset, ty->base->size);
            Type *elem_ty = parse_static_image_initializer(var, &tok, tok,
                                                           ty->base, elem_offset);
            if (elem_ty != ty->base)
                error_at(brace->loc, "nested incomplete arrays are not supported");
'''
new = '''            int index = next_index;
            bool designated = false;
            if (equal(tok, "[")) {
                designated = true;
                Token *designator = tok;
                tok = tok->next;
                index = parse_array_designator_index(&tok, tok, designator);
                tok = skip(tok, "]");
                tok = skip(tok, "=");
            }

            if (ty->array_len > 0 && index >= ty->array_len)
                error_at(tok->loc, "array designator index exceeds array bounds");

            Type *elem_ty = ty->base;
            int elem_offset = offset + index * elem_ty->size;
            reset_static_subobject(var, elem_offset, elem_ty->size);
            if (parse_static_string_array_initializer(var, &tok, tok,
                                                       elem_ty, elem_offset)) {
                // Character-array string initializer consumed as one subobject.
            } else if (!designated && is_initializer_aggregate(elem_ty) &&
                       !equal(tok, "{")) {
                parse_static_image_elided(var, &tok, tok, elem_ty,
                                          elem_offset, brace);
            } else {
                Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                              elem_ty, elem_offset);
                if (parsed != elem_ty)
                    error_at(brace->loc, "nested incomplete arrays are not supported");
            }
'''
s = replace_once(s, old, new, 'static array positional brace elision')

old = '''        Member *member = next_member;
        if (consume(&tok, tok, ".")) {
            if (tok->kind != TK_IDENT)
                error_at(tok->loc, "expected member name in designated initializer");
            member = find_static_initializer_member(ty, tok);
            if (!member)
                error_at(tok->loc, "unknown member in designated initializer");
            tok = skip(tok->next, "=");
        } else if (!member) {
            error_at(tok->loc, "excess elements in record initializer");
        }

        // All union members overlap at offset zero. Clear the complete union so
        // a designated pointer member cannot leave stale relocation/data bytes
        // from an earlier representation of the same object.
        if (ty->is_union)
            reset_static_subobject(var, offset, ty->size);
        else
            reset_static_subobject(var, offset + member->offset, member->ty->size);
        Type *member_ty = parse_static_image_initializer(var, &tok, tok,
                                                         member->ty,
                                                         offset + member->offset);
        if (member_ty != member->ty)
            error_at(brace->loc, "incomplete array record members are not supported");
'''
new = '''        Member *member = next_member;
        bool designated = false;
        if (consume(&tok, tok, ".")) {
            designated = true;
            if (tok->kind != TK_IDENT)
                error_at(tok->loc, "expected member name in designated initializer");
            member = find_static_initializer_member(ty, tok);
            if (!member)
                error_at(tok->loc, "unknown member in designated initializer");
            tok = skip(tok->next, "=");
        } else if (!member) {
            error_at(tok->loc, "excess elements in record initializer");
        }

        // All union members overlap at offset zero. Clear the complete union so
        // a designated pointer member cannot leave stale relocation/data bytes
        // from an earlier representation of the same object.
        if (ty->is_union)
            reset_static_subobject(var, offset, ty->size);
        else
            reset_static_subobject(var, offset + member->offset, member->ty->size);

        int member_offset = offset + member->offset;
        if (parse_static_string_array_initializer(var, &tok, tok,
                                                   member->ty, member_offset)) {
            // Character-array string initializer consumed as one subobject.
        } else if (!designated && is_initializer_aggregate(member->ty) &&
                   !equal(tok, "{")) {
            parse_static_image_elided(var, &tok, tok, member->ty,
                                      member_offset, brace);
        } else {
            Type *parsed = parse_static_image_initializer(var, &tok, tok,
                                                          member->ty, member_offset);
            if (parsed != member->ty)
                error_at(brace->loc, "incomplete array record members are not supported");
        }
'''
s = replace_once(s, old, new, 'static record positional brace elision')

anchor = '''// declaration = declspec (declarator ("=" (expr | "{" initializer "}"))?)
//               ("," declarator ("=" (expr | "{" initializer "}"))?)* ";"
'''
helper = '''// Parse one nested automatic aggregate subobject, with or without its own
// braces. Zero the complete subobject first, then overwrite explicitly supplied
// positional leaves. In unbraced mode the helper consumes only separators that
// belong inside the subobject and leaves the next enclosing comma untouched.
static void parse_automatic_aggregate_subobject(Node **tail, Node *lhs, Type *ty,
                                                 Token **rest, Token *tok,
                                                 Token *where) {
    if (!is_initializer_aggregate(ty))
        error_at(where->loc, "internal error: automatic aggregate initializer expected");
    if (ty->kind == TY_ARRAY && ty->array_len == 0)
        error_at(where->loc, "nested incomplete arrays are not supported");

    append_zero_initializer(tail, lhs, ty, where);
    bool braced = consume(&tok, tok, "{");

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
                error_at(tok->loc, "designators in nested aggregate initializers are not yet supported");

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
                error_at(tok->loc, "designators in nested aggregate initializers are not yet supported");

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

    if (braced) {
        if (equal(tok, ","))
            tok = tok->next;
        *rest = skip(tok, "}");
    } else {
        *rest = tok;
    }
}

'''
s = replace_once(s, anchor, helper + anchor, 'insert automatic aggregate helper')

old = '''                    if (!append_automatic_string_array_initializer(&block_cur,
                                                                    member_node,
                                                                    m->ty,
                                                                    &tok, tok)) {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(member_node, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }
'''
new = '''                    if (!append_automatic_string_array_initializer(&block_cur,
                                                                    member_node,
                                                                    m->ty,
                                                                    &tok, tok)) {
                        if (is_initializer_aggregate(m->ty) && equal(tok, "{")) {
                            parse_automatic_aggregate_subobject(&block_cur, member_node,
                                                                m->ty, &tok, tok, brace);
                        } else {
                            Node *e = assign(&tok, tok);
                            Node *a = new_initializer_assign(member_node, e, tok);
                            block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                        }
                    }
'''
s = replace_once(s, old, new, 'automatic designated member braces')

old = '''                    if (!append_automatic_string_array_initializer(&block_cur, lhs,
                                                                    ty->base,
                                                                    &tok, tok)) {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(lhs, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }
'''
new = '''                    if (!append_automatic_string_array_initializer(&block_cur, lhs,
                                                                    ty->base,
                                                                    &tok, tok)) {
                        if (is_initializer_aggregate(ty->base) && equal(tok, "{")) {
                            parse_automatic_aggregate_subobject(&block_cur, lhs,
                                                                ty->base, &tok, tok, brace);
                        } else {
                            Node *e = assign(&tok, tok);
                            Node *a = new_initializer_assign(lhs, e, tok);
                            block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                        }
                    }
'''
s = replace_once(s, old, new, 'automatic designated array braces')

old = '''                    if (!append_automatic_string_array_initializer(&block_cur, lhs,
                                                                    ty->base,
                                                                    &tok, tok)) {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(lhs, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }
                } else {
'''
new = '''                    if (!append_automatic_string_array_initializer(&block_cur, lhs,
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
'''
s = replace_once(s, old, new, 'automatic positional array elision')

old = '''                    if (!append_automatic_string_array_initializer(&block_cur,
                                                                    member_node,
                                                                    cur_mem->ty,
                                                                    &tok, tok)) {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(member_node, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }
'''
new = '''                    if (!append_automatic_string_array_initializer(&block_cur,
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
'''
s = replace_once(s, old, new, 'automatic positional record elision')
p.write_text(s)


Path('test/brace_elision.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-brace-elision.c
  ./minicc tmp-brace-elision.c > tmp-brace-elision.s
  cc -o tmp-brace-elision tmp-brace-elision.s
  set +e
  ./tmp-brace-elision
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "brace elision failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(brace elision): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-brace-elision-bad.c
  if ./minicc tmp-brace-elision-bad.c > tmp-brace-elision-bad.s 2>/dev/null; then
    echo "brace elision unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(brace elision): rejected invalid program"
}

# Static/global positional brace elision.
assert_run 1 'int a[2][2]={1,2,3,4};int main(){return a[0][0]==1&&a[0][1]==2&&a[1][0]==3&&a[1][1]==4;}'
assert_run 1 'int a[][2]={1,2,3,4};int main(){return sizeof(a)/sizeof(a[0])==2&&a[1][1]==4;}'
assert_run 1 'struct S{int a[2];int b;};struct S s={1,2,3};int main(){return s.a[0]==1&&s.a[1]==2&&s.b==3;}'
assert_run 1 'struct I{int x;int y;};struct O{struct I i;int z;};struct O o={1,2,3};int main(){return o.i.x==1&&o.i.y==2&&o.z==3;}'
assert_run 1 'int a[2][2]={1};int main(){return a[0][0]==1&&a[0][1]==0&&a[1][0]==0&&a[1][1]==0;}'
assert_run 1 'union U{struct P{int x;int y;} p;long z;};union U u={1,2};int main(){return u.p.x==1&&u.p.y==2;}'
assert_run 1 'int main(){static int a[2][2]={5,6,7,8};return a[0][1]==6&&a[1][0]==7;}'
assert_run 1 'int x=3,y=4;struct S{int *p[2];int n;};struct S s={&x,&y,9};int main(){return *s.p[0]==3&&*s.p[1]==4&&s.n==9;}'
assert_run 1 'struct S{char rows[2][3];int n;};struct S s={"ab","c",7};int main(){return s.rows[0][1]==98&&s.rows[1][0]==99&&s.n==7;}'

# Automatic aggregates: elided and explicit nested braces share the same
# recursive subobject initializer and preserve implicit zero-fill.
assert_run 1 'int main(){int a[2][2]={1,2,3,4};return a[0][1]==2&&a[1][0]==3;}'
assert_run 1 'int main(){int a[2][2]={{1,2},{3,4}};return a[0][0]==1&&a[1][1]==4;}'
assert_run 1 'int main(){struct S{int a[2];int b;};struct S s={1,2,3};return s.a[1]==2&&s.b==3;}'
assert_run 1 'int main(){struct I{int x;int y;};struct O{struct I i;int z;};struct O o={1,2,3};return o.i.y==2&&o.z==3;}'
assert_run 1 'int main(){int a[2][2]={1};return a[0][0]==1&&a[0][1]==0&&a[1][1]==0;}'
assert_run 1 'int main(){union U{struct P{int x;int y;} p;long z;};union U u={1,2};return u.p.x==1&&u.p.y==2;}'
assert_run 1 'int main(){int x=3,y=4;struct S{int *p[2];int n;};struct S s={&x,&y,8};return *s.p[0]==3&&*s.p[1]==4&&s.n==8;}'
assert_run 1 'int main(){struct S{char rows[2][3];int n;};struct S s={"ab","c",6};return s.rows[0][1]==98&&s.rows[1][1]==0&&s.n==6;}'

# Fixed aggregate bounds still reject values that remain after all subobjects
# have been consumed.
assert_fail 'int a[1][2]={1,2,3};int main(){return 0;}'
assert_fail 'int main(){int a[1][2]={1,2,3};return 0;}'
assert_fail 'struct S{int a[1];int b;};struct S s={1,2,3};int main(){return 0;}'
assert_fail 'int main(){struct S{int a[1];int b;};struct S s={1,2,3};return 0;}'

echo 'All aggregate brace-elision tests passed!'
''')

p = Path('Makefile')
s = p.read_text()
s = replace_once(s,
                 '\tbash ./test/aggregate_initializers.sh\n\tbash ./test/array_designators.sh\n',
                 '\tbash ./test/aggregate_initializers.sh\n\tbash ./test/brace_elision.sh\n\tbash ./test/array_designators.sh\n',
                 'Makefile brace-elision test')
p.write_text(s)

p = Path('README.md')
s = p.read_text()
s = replace_once(s,
                 'including bounds-checked aggregate initialization with implicit zero-fill for omitted aggregate subobjects',
                 'including bounds-checked aggregate initialization with implicit zero-fill for omitted aggregate subobjects and positional brace elision across nested arrays/records',
                 'README brace-elision support')
p.write_text(s)
