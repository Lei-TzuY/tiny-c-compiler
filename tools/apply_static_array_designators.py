from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = r'''static int record_member_count(Type *ty) {
    int count = 0;
    for (Member *m = ty->members; m; m = m->next)
        count++;
    return count;
}
'''

helper = r'''static int record_member_count(Type *ty) {
    int count = 0;
    for (Member *m = ty->members; m; m = m->next)
        count++;
    return count;
}

// Array designators use an integer constant expression, not merely a numeric
// token. Evaluate with the shared type-aware constant-expression machinery so
// enum constants, casts, arithmetic, and unsigned range checks behave exactly
// like array bounds and case labels.
static int parse_array_designator_index(Token **rest, Token *tok, Token *where) {
    Node *index = ternary(&tok, tok);
    add_type(index);
    if (!is_integer(index->ty))
        error_at(where->loc, "array designator index must have integer type");

    int64_t raw = eval_const_expr(index);
    int64_t converted = cast_const_integer(raw, index->ty);
    if (index->ty->is_unsigned) {
        uint64_t value = (uint64_t)converted;
        if (value > INT32_MAX)
            error_at(where->loc, "array designator index is out of range");
        *rest = tok;
        return (int)value;
    }

    if (converted < 0 || converted > INT32_MAX)
        error_at(where->loc, "array designator index is out of range");
    *rest = tok;
    return (int)converted;
}

// Parse a static-storage-duration integer array initializer. The backing value
// vector is indexed by the actual designated subscript, so omitted elements are
// represented as zero and out-of-order/repeated designators retain C semantics.
static void parse_static_integer_array_initializer(Obj *var, Type **ty,
                                                   Token **rest, Token *tok) {
    Token *brace = tok;
    if ((*ty)->kind != TY_ARRAY || !is_integer((*ty)->base))
        error_at(brace->loc, "static brace initializer currently supports integer arrays");

    Type *elem_ty = (*ty)->base;
    tok = tok->next;
    int cap = (*ty)->array_len > 0 ? (*ty)->array_len : 16;
    if (cap < 1)
        cap = 16;
    int64_t *vals = calloc(cap, sizeof(int64_t));
    int cur_idx = 0;
    int max_idx = -1;
    bool first_elem = true;

    while (!equal(tok, "}")) {
        if (!first_elem) {
            tok = skip(tok, ",");
            if (equal(tok, "}"))
                break;
        }
        first_elem = false;

        if (equal(tok, "."))
            error_at(tok->loc, "member designator requires a record initializer");

        if (equal(tok, "[")) {
            Token *designator = tok;
            tok = tok->next;
            cur_idx = parse_array_designator_index(&tok, tok, designator);
            tok = skip(tok, "]");
            tok = skip(tok, "=");
        }

        if ((*ty)->array_len > 0 && cur_idx >= (*ty)->array_len)
            error_at(tok->loc, "array designator index exceeds array bounds");

        while (cur_idx >= cap) {
            int old_cap = cap;
            cap *= 2;
            vals = realloc(vals, cap * sizeof(int64_t));
            memset(vals + old_cap, 0, (cap - old_cap) * sizeof(int64_t));
        }

        vals[cur_idx] = parse_static_integer_initializer(&tok, tok, elem_ty);
        if (cur_idx > max_idx)
            max_idx = cur_idx;
        cur_idx++;
    }
    tok = skip(tok, "}");

    if ((*ty)->array_len == 0) {
        int inferred = max_idx + 1;
        if (inferred <= 0)
            error_at(brace->loc, "cannot infer array size from empty initializer");
        *ty = array_of(elem_ty, inferred);
        var->ty = *ty;
    }

    var->init_vals = vals;
    var->init_vals_count = max_idx + 1;
    *rest = tok;
}
'''

if s.count(anchor) != 1:
    raise SystemExit(f'record helper anchor count={s.count(anchor)}')
s = s.replace(anchor, helper, 1)

old_static = r'''        // Static/extern: constant initializer only
        if (is_static || is_extern) {
            if (equal(tok, "{")) {
                tok = tok->next;
                int cap = 16, cnt = 0;
                int64_t *vals = calloc(cap, sizeof(int64_t));
                while (!equal(tok, "}")) {
                    if (cnt > 0) tok = skip(tok, ",");
                    if (equal(tok, "}")) break;
                    if (ty->kind == TY_ARRAY && ty->array_len > 0 && cnt >= ty->array_len)
                        error_at(tok->loc, "excess elements in array initializer");
                    if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                    Type *elem_ty = (ty->kind == TY_ARRAY) ? ty->base : NULL;
                    vals[cnt++] = parse_static_integer_initializer(&tok, tok, elem_ty);
                }
                tok = skip(tok, "}");
                if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                    ty = array_of(ty->base, cnt);
                    var->ty = ty;
                }
                var->init_vals = vals;
                var->init_vals_count = cnt;
            } else {
                parse_static_scalar_initializer(var, &tok, tok, ty);
            }
            continue;
        }
'''

new_static = r'''        // Static/extern: constant initializer only. Integer arrays share the
        // file-scope designated-initializer parser so block/static and global
        // objects cannot drift in their [constant-expression] semantics.
        if (is_static || is_extern) {
            if (equal(tok, "{")) {
                Token *brace = tok;

                // The historical fallback serialized record members as packed
                // 4-byte integers, ignoring real member offsets/padding. Refuse
                // that miscompile until typed static-record serialization lands.
                if (ty->kind == TY_STRUCT)
                    error_at(brace->loc, "static record brace initializers are not yet supported");

                if (ty->kind == TY_ARRAY) {
                    parse_static_integer_array_initializer(var, &ty, &tok, tok);
                    continue;
                }

                // Preserve scalar brace initialization as a single scalar
                // constant with an optional trailing comma.
                tok = tok->next;
                if (equal(tok, "}"))
                    error_at(brace->loc, "empty scalar initializer");
                parse_static_scalar_initializer(var, &tok, tok, ty);
                if (equal(tok, ","))
                    tok = tok->next;
                tok = skip(tok, "}");
                continue;
            }

            parse_static_scalar_initializer(var, &tok, tok, ty);
            continue;
        }
'''

if s.count(old_static) != 1:
    raise SystemExit(f'static initializer block count={s.count(old_static)}')
s = s.replace(old_static, new_static, 1)

old_auto = r'''                // Designated initializer: [index] = expr
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
'''

new_auto = r'''                // Designated initializer: [integer-constant-expression] = expr
                if (equal(tok, "[")) {
                    Token *designator = tok;
                    if (ty->kind != TY_ARRAY)
                        error_at(tok->loc, "array designator requires an array initializer");
                    tok = tok->next;
                    int idx = parse_array_designator_index(&tok, tok, designator);
                    tok = skip(tok, "]");
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
'''

if s.count(old_auto) != 1:
    raise SystemExit(f'automatic designator block count={s.count(old_auto)}')
s = s.replace(old_auto, new_auto, 1)

old_global = r'''                    } else if (equal(tok, "{")) {
                        tok = tok->next;
                        int cap = 16, cnt = 0;
                        int64_t *vals = calloc(cap, sizeof(int64_t));
                        while (!equal(tok, "}")) {
                            if (cnt > 0) tok = skip(tok, ",");
                            if (equal(tok, "}")) break;
                            if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                            Type *elem_ty = (ty->kind == TY_ARRAY) ? ty->base : NULL;
                    vals[cnt++] = parse_static_integer_initializer(&tok, tok, elem_ty);
                        }
                        tok = skip(tok, "}");

                        if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                            ty = array_of(ty->base, cnt);
                            var->ty = ty;
                        }

                        var->init_vals = vals;
                        var->init_vals_count = cnt;
'''

new_global = r'''                    } else if (equal(tok, "{")) {
                        Token *brace = tok;

                        // Do not silently serialize padded records as a dense
                        // list of .long values. Typed static-record data is a
                        // separate feature and should fail clearly for now.
                        if (ty->kind == TY_STRUCT)
                            error_at(brace->loc, "static record brace initializers are not yet supported");

                        if (ty->kind == TY_ARRAY) {
                            parse_static_integer_array_initializer(var, &ty, &tok, tok);
                        } else {
                            tok = tok->next;
                            if (equal(tok, "}"))
                                error_at(brace->loc, "empty scalar initializer");
                            parse_static_scalar_initializer(var, &tok, tok, ty);
                            if (equal(tok, ","))
                                tok = tok->next;
                            tok = skip(tok, "}");
                        }
'''

if s.count(old_global) != 1:
    raise SystemExit(f'global initializer block count={s.count(old_global)}')
s = s.replace(old_global, new_global, 1)
p.write_text(s)

# Wire focused regression coverage into make test.
p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/aggregate_initializers.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/array_designators.sh\n', 1)
p.write_text(s)

# Document the now-shared designator semantics.
p = Path('README.md')
s = p.read_text()
needle = 'including bounds-checked aggregate initialization with implicit zero-fill for omitted aggregate subobjects\n'
replacement = 'including bounds-checked aggregate initialization with implicit zero-fill for omitted aggregate subobjects and integer-constant-expression array designators for automatic/static integer arrays\n'
if s.count(needle) != 1:
    raise SystemExit(f'README anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))

Path('test/array_designators.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-array-designator.c
  ./minicc tmp-array-designator.c > tmp-array-designator.s
  cc -o tmp-array-designator tmp-array-designator.s
  set +e
  ./tmp-array-designator
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "array designator failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(array designator): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-array-designator-bad.c
  if ./minicc tmp-array-designator-bad.c > tmp-array-designator-bad.s 2>/dev/null; then
    echo "array designator unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(array designator): rejected invalid program"
}

# Static/global integer arrays support designated holes and preserve zero-fill.
assert_run 7 'int a[5]={[3]=7};int main(){return a[0]+a[1]+a[2]+a[3]+a[4];}'
assert_run 9 'int main(){static int a[5]={[4]=9};return a[0]+a[4];}'
assert_run 1 'int a[]={[4]=9};int main(){return sizeof(a)/sizeof(int)==5;}'
assert_run 1 'int a[]={[4]=7,[1]=2};int main(){return sizeof(a)/sizeof(int)==5 && a[1]==2 && a[4]==7 && a[3]==0;}'
assert_run 1 'int a[5]={[2]=4,5,6};int main(){return a[0]==0 && a[2]==4 && a[3]==5 && a[4]==6;}'
assert_run 1 'enum { K=1 };int a[5]={[K+2]=8};int main(){return a[3]==8 && a[2]==0;}'
assert_run 7 'int a[3]={[1]=2,[1]=7};int main(){return a[1];}'
assert_run 44 'unsigned char a[3]={[1]=300};int main(){return a[1];}'
assert_run 1 'long a[3]={[2]=4294967297L};int main(){return a[2]==4294967297L && a[0]==0;}'
assert_run 1 'unsigned int a[2]={[1]=4294967295U};int main(){return a[1]==4294967295U;}'
assert_run 1 'int a[3]={[2]=5,};int main(){return a[0]==0 && a[2]==5;}'

# Automatic arrays use the same full integer-constant-expression index parser.
assert_run 1 'enum { K=2 };int main(){int a[5]={[K+1]=9};return a[3]==9 && a[0]==0;}'
assert_run 1 'int main(){int a[6]={[1+2*2]=7};return a[5]==7 && a[4]==0;}'
assert_run 1 'int main(){int a[4]={[(int)2]=6};return a[2]==6 && a[1]==0;}'

# Designator indices are constrained integer constant expressions and fixed
# arrays reject indices outside their declared bound.
assert_fail 'int a[3]={[3]=1};int main(){return 0;}'
assert_fail 'int a[3]={[-1]=1};int main(){return 0;}'
assert_fail 'int a[3]={[1.5]=1};int main(){return 0;}'
assert_fail 'int x=1;int a[3]={[x]=1};int main(){return 0;}'
assert_fail 'int a[3]={.x=1};int main(){return 0;}'
assert_fail 'int a[] = {}; int main(){return 0;}'
assert_fail 'int a[]={[2147483648ULL]=1};int main(){return 0;}'

# Until typed static-record serialization exists, reject the historical packed
# integer fallback rather than silently placing members at incorrect offsets.
assert_fail 'struct S{char c;long x;};struct S s={1,2};int main(){return 0;}'

echo 'All array-designator tests passed!'
''')
