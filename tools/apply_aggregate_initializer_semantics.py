from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = r'''static char *build_string_array_image(Type *ty, Token *str) {
    char *data = calloc(ty->array_len, 1);
    int copy = str->ty->array_len;
    if (copy > ty->array_len)
        copy = ty->array_len;
    memcpy(data, str->str, copy);
    return data;
}
'''
insert = anchor + r'''

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
        for (Member *m = ty->members; m; m = m->next) {
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
'''
if s.count(anchor) != 1:
    raise SystemExit(f'helper anchor count={s.count(anchor)}')
s = s.replace(anchor, insert, 1)

old_static = r'''                while (!equal(tok, "}")) {
                    if (cnt > 0) tok = skip(tok, ",");
                    if (equal(tok, "}")) break;
                    if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                    Type *elem_ty = (ty->kind == TY_ARRAY) ? ty->base : NULL;
                    vals[cnt++] = parse_static_integer_initializer(&tok, tok, elem_ty);
                }
'''
new_static = r'''                while (!equal(tok, "}")) {
                    if (cnt > 0) tok = skip(tok, ",");
                    if (equal(tok, "}")) break;
                    if (ty->kind == TY_ARRAY && ty->array_len > 0 && cnt >= ty->array_len)
                        error_at(tok->loc, "excess elements in array initializer");
                    if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                    Type *elem_ty = (ty->kind == TY_ARRAY) ? ty->base : NULL;
                    vals[cnt++] = parse_static_integer_initializer(&tok, tok, elem_ty);
                }
'''
if s.count(old_static) != 1:
    raise SystemExit(f'static initializer anchor count={s.count(old_static)}')
s = s.replace(old_static, new_static, 1)

old = r'''        // Brace-enclosed initializer: { expr, expr, ... }
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
                    Node *a = new_initializer_assign(member_node, e, tok);
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
                    Node *a = new_initializer_assign(lhs, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                    cur_idx = idx + 1;
                    continue;
                }

                // Positional initializer
                Node *e = assign(&tok, tok);
                if (ty->kind == TY_ARRAY) {
                    Node *lhs = new_unary(ND_DEREF, new_add(new_var_node(var), new_num(cur_idx++)));
                    Node *a = new_initializer_assign(lhs, e, tok);
                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);
                } else if (ty->kind == TY_STRUCT && cur_mem) {
                    Node *var_node = new_var_node(var);
                    Node *member_node = new_node(ND_MEMBER);
                    member_node->lhs = var_node;
                    member_node->member = cur_mem;
                    Node *a = new_initializer_assign(member_node, e, tok);
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
'''
new = r'''        // Brace-enclosed initializer: { expr, expr, ... }
        if (equal(tok, "{")) {
            Token *brace = tok;
            tok = tok->next;

            if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT)
                error_at(brace->loc, "brace initializer requires an aggregate type");

            int cur_idx = 0;
            int max_idx = -1;
            int elem_cap = ty->kind == TY_ARRAY && ty->array_len > 0 ? ty->array_len : 8;
            bool *elem_init = ty->kind == TY_ARRAY ? calloc(elem_cap, sizeof(bool)) : NULL;
            int member_count = ty->kind == TY_STRUCT ? record_member_count(ty) : 0;
            bool *member_init = member_count ? calloc(member_count, sizeof(bool)) : NULL;
            Member *cur_mem = (ty->kind == TY_STRUCT) ? ty->members : NULL;
            Node *before_init = block_cur;

            while (!equal(tok, "}")) {
                if (equal(tok, ",")) tok = tok->next;
                if (equal(tok, "}")) break;

                // Designated initializer: .member = expr
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
                    cur_mem = m->next;
                    continue;
                }

                // Designated initializer: [index] = expr
                if (consume(&tok, tok, "[")) {
                    if (ty->kind != TY_ARRAY)
                        error_at(tok->loc, "array designator requires an array initializer");
                    if (tok->kind != TK_NUM || tok->is_float)
                        error_at(tok->loc, "expected integer array index in designated initializer");
                    int64_t raw_idx = tok->val;
                    if (raw_idx < 0 || raw_idx > INT32_MAX)
                        error_at(tok->loc, "array designator index is out of range");
                    int idx = (int)raw_idx;
                    tok = skip(tok->next, "]");
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
                }

                // Positional initializer
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
                    cur_mem = cur_mem->next;
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
            } else {
                int mi = 0;
                for (Member *m = ty->members; m; m = m->next, mi++) {
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
'''
if s.count(old) != 1:
    raise SystemExit(f'local brace block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/static_address_initializers.sh\n'
if needle not in s:
    # tolerate current ordering by appending after the string-array suite
    needle = '\tbash ./test/string_array_initializers.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/aggregate_initializers.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = '- **Declarations**:'
idx = s.find(needle)
if idx < 0:
    raise SystemExit('README declarations line missing')
end = s.find('\n', idx)
line = s[idx:end]
if 'implicit zero-fill for omitted aggregate subobjects' not in line:
    line += ', including bounds-checked aggregate initialization with implicit zero-fill for omitted aggregate subobjects'
    s = s[:idx] + line + s[end:]
p.write_text(s)

Path('test/aggregate_initializers.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-agginit.c
  ./minicc tmp-agginit.c > tmp-agginit.s
  cc -o tmp-agginit tmp-agginit.s
  set +e
  ./tmp-agginit
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "aggregate initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(aggregate initializer): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-agginit-bad.c
  if ./minicc tmp-agginit-bad.c > tmp-agginit-bad.s 2>/dev/null; then
    echo "aggregate initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(aggregate initializer): rejected invalid program"
}

# Omitted automatic array elements receive static-style zero initialization.
assert_run 1 'int main(){int a[4]={7};return a[0]==7&&a[1]==0&&a[2]==0&&a[3]==0;}'
assert_run 1 'int main(){long a[3]={1,2};return a[2]==0;}'
assert_run 1 'int main(){double a[3]={1.5};return a[1]==0.0&&a[2]==0.0;}'
assert_run 1 'int main(){int *a[3]={0};return a[1]==0&&a[2]==0;}'

# Designators leave holes zeroed and incomplete arrays infer the largest index.
assert_run 1 'int main(){int a[5]={[3]=9};return a[0]==0&&a[1]==0&&a[2]==0&&a[3]==9&&a[4]==0;}'
assert_run 1 'int main(){int a[5]={[2]=3,4};return a[0]==0&&a[1]==0&&a[2]==3&&a[3]==4&&a[4]==0;}'
assert_run 1 'int main(){int a[]={[4]=7,[1]=2};return sizeof(a)==20&&a[0]==0&&a[1]==2&&a[4]==7;}'

# Omitted record members, including nested aggregates, are recursively zeroed.
assert_run 1 'struct S{int x;long y;int *p;};int main(){struct S s={5};return s.x==5&&s.y==0&&s.p==0;}'
assert_run 1 'struct S{int x;double y;};int main(){struct S s={.y=2.5};return s.x==0&&s.y==2.5;}'
assert_run 1 'struct I{int a;int b;};struct O{struct I i;int x;};int main(){struct O o={.x=3};return o.i.a==0&&o.i.b==0&&o.x==3;}'
assert_run 1 'struct S{int a[3];int x;};int main(){struct S s={.x=4};return s.a[0]==0&&s.a[1]==0&&s.a[2]==0&&s.x==4;}'

# Fixed-size aggregate initializers reject writes beyond the declared object.
assert_fail 'int main(){int a[2]={1,2,3};return 0;}'
assert_fail 'int main(){int a[2]={[2]=1};return 0;}'
assert_fail 'struct S{int a;int b;};int main(){struct S s={1,2,3};return 0;}'
assert_fail 'int main(){static int a[2]={1,2,3};return 0;}'

# Designator categories must match the aggregate being initialized.
assert_fail 'struct S{int a;};int main(){struct S s={[0]=1};return 0;}'
assert_fail 'int main(){int a[2]={.x=1};return 0;}'

# An incomplete array needs at least one element to determine its size.
assert_fail 'int main(){int a[]={};return 0;}'

echo 'All aggregate-initializer tests passed!'
''')
