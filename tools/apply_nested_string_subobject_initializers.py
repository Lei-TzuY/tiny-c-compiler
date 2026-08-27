from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


p = Path("parse.c")
s = p.read_text()

anchor = '''static char *build_string_array_image(Type *ty, Token *str) {
    char *data = calloc(ty->array_len, 1);
    int copy = str->ty->array_len;
    if (copy > ty->array_len)
        copy = ty->array_len;
    memcpy(data, str->str, copy);
    return data;
}


// Append zero-initialization statements for an automatic aggregate subobject.
'''
replacement = '''static char *build_string_array_image(Type *ty, Token *str) {
    char *data = calloc(ty->array_len, 1);
    int copy = str->ty->array_len;
    if (copy > ty->array_len)
        copy = ty->array_len;
    memcpy(data, str->str, copy);
    return data;
}

static void validate_nested_string_array_type(Type *ty, Token *str) {
    if (!is_character_array(ty))
        error_at(str->loc, "string literal can initialize only a character array here");
    if (ty->array_len == 0)
        error_at(str->loc, "nested incomplete character-array initializer is not supported");

    int payload_len = str->ty->array_len - 1;
    if (ty->array_len < payload_len)
        error_at(str->loc, "initializer string is too long for character array");
}

static Node *append_auto_string_array_initializer(Node *tail, Node *lhs,
                                                   Type *ty, Token *str) {
    validate_nested_string_array_type(ty, str);

    for (int i = 0; i < ty->array_len; i++) {
        int value = 0;
        if (i < str->ty->array_len)
            value = (unsigned char)str->str[i];
        Node *elem = new_unary(ND_DEREF, new_add(lhs, new_num(i)));
        Node *a = new_initializer_assign(elem, new_num(value), str);
        tail = tail->next = new_unary(ND_EXPR_STMT, a);
    }
    return tail;
}


// Append zero-initialization statements for an automatic aggregate subobject.
'''
s = replace_once(s, anchor, replacement, "nested string helpers")

anchor = '''static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty, int offset) {
    if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT) {
'''
replacement = '''static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty, int offset) {
    Token *after_string = NULL;
    Token *string_tok = string_initializer_token(tok, &after_string);
    if (string_tok && ty->kind == TY_ARRAY) {
        validate_nested_string_array_type(ty, string_tok);
        reset_static_subobject(var, offset, ty->size);
        char *image = build_string_array_image(ty, string_tok);
        memcpy(var->init_image + offset, image, ty->size);
        free(image);
        *rest = after_string;
        return ty;
    }

    if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT) {
'''
s = replace_once(s, anchor, replacement, "static nested string dispatch")

old = '''                // Designated initializer: .member = expr
                if (consume(&tok, tok, ".")) {
                    if (ty->kind != TY_STRUCT)
                        error_at(tok->loc, "member designator requires a record initializer");
                    if (tok->kind != TK_IDENT) error_at(tok->loc, "expected member name in designated initializer");
                    char *mname = strndup(tok->loc, tok->len);
                    tok = skip(tok->next, "=");
                    Node *e = assign(&tok, tok);

                    Member *m = ty->members;
                    for (; m; m = m->next)
                        if (!strcmp(m->name, mname)) break;
                    if (!m) error_at(tok->loc, "unknown member in designated initializer");

                    int mi = record_member_index(ty, m);
                    if (mi >= 0) member_init[mi] = true;
                    Node *var_node = new_var_node(var);
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = var_node;
                    member_node->member = m;
                    Node *a = new_initializer_assign(member_node, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    if (ty->is_union)
                        initialized_union_members++;
                    cur_mem = m->next;
                    continue;
                }
'''
new = '''                // Designated initializer: .member = initializer
                if (consume(&tok, tok, ".")) {
                    if (ty->kind != TY_STRUCT)
                        error_at(tok->loc, "member designator requires a record initializer");
                    if (tok->kind != TK_IDENT)
                        error_at(tok->loc, "expected member name in designated initializer");
                    char *mname = strndup(tok->loc, tok->len);

                    Member *m = ty->members;
                    for (; m; m = m->next)
                        if (!strcmp(m->name, mname)) break;
                    if (!m)
                        error_at(tok->loc, "unknown member in designated initializer");
                    tok = skip(tok->next, "=");

                    int mi = record_member_index(ty, m);
                    if (mi >= 0) member_init[mi] = true;
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = new_var_node(var);
                    member_node->member = m;

                    Token *after_nested_string = NULL;
                    Token *nested_string = string_initializer_token(tok, &after_nested_string);
                    if (nested_string && m->ty->kind == TY_ARRAY) {
                        block_cur = append_auto_string_array_initializer(block_cur,
                                                                         member_node,
                                                                         m->ty,
                                                                         nested_string);
                        tok = after_nested_string;
                    } else {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(member_node, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }

                    if (ty->is_union)
                        initialized_union_members++;
                    cur_mem = m->next;
                    continue;
                }
'''
s = replace_once(s, old, new, "automatic member designator strings")

old = '''                    tok = skip(tok, "]");
                    tok = skip(tok, "=");
                    if (ty->array_len > 0 && idx >= ty->array_len)
                        error_at(tok->loc, "array designator index exceeds array bounds");
                    while (idx >= elem_cap) {
                        int old_cap = elem_cap;
                        elem_cap *= 2;
                        elem_init = realloc(elem_init, elem_cap * sizeof(bool));
                        memset(elem_init + old_cap, 0, (elem_cap - old_cap) * sizeof(bool));
                    }
                    Node *e = assign(&tok, tok);

                    elem_init[idx] = true;
                    if (idx > max_idx) max_idx = idx;
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(idx)));
                    Node *a = new_initializer_assign(lhs, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    cur_idx = idx + 1;
                    continue;
'''
new = '''                    tok = skip(tok, "]");
                    tok = skip(tok, "=");
                    if (ty->array_len > 0 && idx >= ty->array_len)
                        error_at(tok->loc, "array designator index exceeds array bounds");
                    while (idx >= elem_cap) {
                        int old_cap = elem_cap;
                        elem_cap *= 2;
                        elem_init = realloc(elem_init, elem_cap * sizeof(bool));
                        memset(elem_init + old_cap, 0, (elem_cap - old_cap) * sizeof(bool));
                    }

                    elem_init[idx] = true;
                    if (idx > max_idx) max_idx = idx;
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(idx)));
                    Token *after_nested_string = NULL;
                    Token *nested_string = string_initializer_token(tok, &after_nested_string);
                    if (nested_string && ty->base->kind == TY_ARRAY) {
                        block_cur = append_auto_string_array_initializer(block_cur, lhs,
                                                                         ty->base,
                                                                         nested_string);
                        tok = after_nested_string;
                    } else {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(lhs, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }
                    cur_idx = idx + 1;
                    continue;
'''
s = replace_once(s, old, new, "automatic array designator strings")

old = '''                // Positional initializer
                Node *e = assign(&tok, tok);
                if (ty->kind == TY_ARRAY) {
                    if (ty->array_len > 0 && cur_idx >= ty->array_len)
                        error_at(tok->loc, "excess elements in array initializer");
                    while (cur_idx >= elem_cap) {
                        int old_cap = elem_cap;
                        elem_cap *= 2;
                        elem_init = realloc(elem_init, elem_cap * sizeof(bool));
                        memset(elem_init + old_cap, 0, (elem_cap - old_cap) * sizeof(bool));
                    }
                    elem_init[cur_idx] = true;
                    if (cur_idx > max_idx) max_idx = cur_idx;
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(cur_idx++)));
                    Node *a = new_initializer_assign(lhs, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                } else {
                    if (!cur_mem)
                        error_at(tok->loc, "excess elements in record initializer");
                    int mi = record_member_index(ty, cur_mem);
                    if (mi >= 0) member_init[mi] = true;
                    Node *var_node = new_var_node(var);
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = var_node;
                    member_node->member = cur_mem;
                    Node *a = new_initializer_assign(member_node, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    if (ty->is_union)
                        initialized_union_members++;
                    cur_mem = cur_mem->next;
                }
'''
new = '''                // Positional initializer
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
                    Token *after_nested_string = NULL;
                    Token *nested_string = string_initializer_token(tok, &after_nested_string);
                    if (nested_string && ty->base->kind == TY_ARRAY) {
                        block_cur = append_auto_string_array_initializer(block_cur, lhs,
                                                                         ty->base,
                                                                         nested_string);
                        tok = after_nested_string;
                    } else {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(lhs, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }
                } else {
                    if (!cur_mem)
                        error_at(tok->loc, "excess elements in record initializer");
                    int mi = record_member_index(ty, cur_mem);
                    if (mi >= 0) member_init[mi] = true;
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = new_var_node(var);
                    member_node->member = cur_mem;

                    Token *after_nested_string = NULL;
                    Token *nested_string = string_initializer_token(tok, &after_nested_string);
                    if (nested_string && cur_mem->ty->kind == TY_ARRAY) {
                        block_cur = append_auto_string_array_initializer(block_cur,
                                                                         member_node,
                                                                         cur_mem->ty,
                                                                         nested_string);
                        tok = after_nested_string;
                    } else {
                        Node *e = assign(&tok, tok);
                        Node *a = new_initializer_assign(member_node, e, tok);
                        block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    }
                    if (ty->is_union)
                        initialized_union_members++;
                    cur_mem = cur_mem->next;
                }
'''
s = replace_once(s, old, new, "automatic positional strings")
p.write_text(s)


# Add focused regression coverage.
p = Path("test/nested_string_initializers.sh")
p.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-nested-string.c
  ./minicc tmp-nested-string.c > tmp-nested-string.s
  cc -o tmp-nested-string tmp-nested-string.s
  set +e
  ./tmp-nested-string
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "nested string initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(nested string initializer): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-nested-string-bad.c
  if ./minicc tmp-nested-string-bad.c > tmp-nested-string-bad.s 2>/dev/null; then
    echo "nested string initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(nested string initializer): rejected invalid program"
}

# Static/global aggregate character-array subobjects.
assert_run 1 'struct S{char name[4];int n;};struct S s={"abc",7};int main(){return s.name[0]==97&&s.name[2]==99&&s.name[3]==0&&s.n==7;}'
assert_run 1 'char rows[2][4]={"ab","xyz"};int main(){return rows[0][0]==97&&rows[0][2]==0&&rows[1][2]==122&&rows[1][3]==0;}'
assert_run 1 'struct S{char name[5];int n;};struct S s={.n=9,.name="hi"};int main(){return s.name[0]==104&&s.name[2]==0&&s.n==9;}'
assert_run 1 'int main(){struct S{char name[4];int n;};static struct S s={"ok",5};return s.name[1]==107&&s.name[2]==0&&s.n==5;}'
assert_run 1 'union U{char text[4];long x;};union U u={.text="abc"};int main(){return u.text[0]==97&&u.text[3]==0;}'
assert_run 1 'char rows[3][4]={[1]="xy"};int main(){return rows[0][0]==0&&rows[1][0]==120&&rows[1][2]==0&&rows[2][0]==0;}'
assert_run 1 'struct S{char name[3];int n;};struct S s={"abc",1};int main(){return s.name[0]==97&&s.name[2]==99&&s.n==1;}'
assert_run 1 'struct S{char name[4];int n;};struct S s={{"abc"},7};int main(){return s.name[1]==98&&s.name[3]==0&&s.n==7;}'

# Automatic aggregate character-array subobjects use element assignments and
# preserve aggregate zero-fill semantics for omitted rows/members.
assert_run 1 'int main(){struct S{char name[4];int n;};struct S s={"abc",7};return s.name[0]==97&&s.name[3]==0&&s.n==7;}'
assert_run 1 'int main(){char rows[2][4]={"ab","cd"};return rows[0][2]==0&&rows[1][0]==99&&rows[1][2]==0;}'
assert_run 1 'int main(){struct S{char name[5];int n;};struct S s={.n=4,.name="xy"};return s.name[1]==121&&s.name[2]==0&&s.n==4;}'
assert_run 1 'int main(){char rows[3][4]={[2]="z"};return rows[0][0]==0&&rows[1][0]==0&&rows[2][0]==122&&rows[2][1]==0;}'
assert_run 1 'int main(){union U{char text[4];long x;};union U u={.text="hey"};return u.text[0]==104&&u.text[3]==0;}'
assert_run 1 'int main(){struct S{char name[4];int n;};struct S s={{"abc"},2};return s.name[2]==99&&s.name[3]==0&&s.n==2;}'

# Pointer-from-string aggregate leaves remain scalar pointer initialization.
assert_run 1 'char *p[2]={"ab","cd"};int main(){return p[0][1]==98&&p[1][0]==99;}'
assert_run 1 'int main(){char *p[2]={"ab","cd"};return p[0][0]==97&&p[1][1]==100;}'

# String payload may omit the terminator only when the destination has exactly
# the payload width; genuinely overlong and non-character-array cases reject.
assert_fail 'struct S{char name[3];};struct S s={"abcd"};int main(){return 0;}'
assert_fail 'int main(){struct S{char name[3];};struct S s={"abcd"};return 0;}'
assert_fail 'struct S{int data[2];};struct S s={"x"};int main(){return 0;}'
assert_fail 'int main(){int rows[1][2]={"x"};return 0;}'

echo 'All nested string initializer tests passed!'
''')

p = Path("Makefile")
s = p.read_text()
s = replace_once(s, '\tbash ./test/call_arguments.sh\n\tbash ./test/string_array_initializers.sh\n',
                 '\tbash ./test/call_arguments.sh\n\tbash ./test/nested_string_initializers.sh\n\tbash ./test/string_array_initializers.sh\n',
                 "Makefile nested string test")
p.write_text(s)

p = Path("README.md")
s = p.read_text()
s = replace_once(s,
                 'character-array initialization from string literals with safe length inference/zero-fill',
                 'character-array initialization from string literals with safe length inference/zero-fill, including character-array subobjects nested inside arrays, structs, and unions',
                 "README nested string support")
p.write_text(s)
