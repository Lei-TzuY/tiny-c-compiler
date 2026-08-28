from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


# Reuse one recursive automatic scalar initializer path everywhere a scalar
# subobject may appear. C11 permits the single scalar expression to be enclosed
# in braces (recursively), with an optional trailing comma at each brace level.
replace_once(
    "parse.c",
    '''    *rest = after;\n    return true;\n}\n\n\n// Append zero-initialization statements for an automatic aggregate subobject.\n''',
    '''    *rest = after;\n    return true;\n}\n\nstatic void append_automatic_scalar_initializer(Node **tail, Node *lhs,\n                                                Token **rest, Token *tok,\n                                                Token *where) {\n    if (equal(tok, "{")) {\n        Token *brace = tok;\n        tok = tok->next;\n        if (equal(tok, "}"))\n            error_at(brace->loc, "empty scalar initializer");\n\n        append_automatic_scalar_initializer(tail, lhs, &tok, tok, where);\n        if (equal(tok, ","))\n            tok = tok->next;\n        if (!equal(tok, "}"))\n            error_at(tok->loc, "excess elements in scalar initializer");\n        *rest = tok->next;\n        return;\n    }\n\n    Node *rhs = assign(&tok, tok);\n    Node *a = new_initializer_assign(lhs, rhs, where);\n    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);\n    *rest = tok;\n}\n\n\n// Append zero-initialization statements for an automatic aggregate subobject.\n''')

# Static scalar images already support one brace layer. Make that path recursive
# as well so global/static objects and scalar leaves obey the same C11 rule.
replace_once(
    "parse.c",
    '''    if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT) {\n        if (equal(tok, "{")) {\n            Token *brace = tok;\n            tok = tok->next;\n            if (equal(tok, "}"))\n                error_at(brace->loc, "empty scalar initializer");\n            parse_static_image_scalar(var, &tok, tok, ty, offset);\n            if (equal(tok, ","))\n                tok = tok->next;\n            *rest = skip(tok, "}");\n            return ty;\n        }\n        parse_static_image_scalar(var, rest, tok, ty, offset);\n        return ty;\n    }\n''',
    '''    if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT) {\n        if (equal(tok, "{")) {\n            Token *brace = tok;\n            tok = tok->next;\n            if (equal(tok, "}"))\n                error_at(brace->loc, "empty scalar initializer");\n            parse_static_image_initializer(var, &tok, tok, ty, offset);\n            if (equal(tok, ","))\n                tok = tok->next;\n            if (!equal(tok, "}"))\n                error_at(tok->loc, "excess elements in scalar initializer");\n            *rest = tok->next;\n            return ty;\n        }\n        parse_static_image_scalar(var, rest, tok, ty, offset);\n        return ty;\n    }\n''')

# Braced array scalar leaves in automatic aggregates.
replace_once(
    "parse.c",
    '''                if (is_initializer_aggregate(ty->base)) {\n                    parse_automatic_aggregate_subobject(tail, child, ty->base,\n                                                         &tok, tok, where);\n                    continue;\n                }\n\n                Node *rhs = assign(&tok, tok);\n                Node *a = new_initializer_assign(child, rhs, where);\n                *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);\n            }\n\n            if (infer_array) {\n''',
    '''                if (is_initializer_aggregate(ty->base)) {\n                    parse_automatic_aggregate_subobject(tail, child, ty->base,\n                                                         &tok, tok, where);\n                    continue;\n                }\n\n                append_automatic_scalar_initializer(tail, child, &tok, tok, where);\n            }\n\n            if (infer_array) {\n''')

# Braced record scalar leaves.
replace_once(
    "parse.c",
    '''                } else if (is_initializer_aggregate(next_member->ty)) {\n                    parse_automatic_aggregate_subobject(tail, child,\n                                                         next_member->ty,\n                                                         &tok, tok, where);\n                } else {\n                    Node *rhs = assign(&tok, tok);\n                    Node *a = new_initializer_assign(child, rhs, where);\n                    *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);\n                }\n\n                if (ty->is_union)\n''',
    '''                } else if (is_initializer_aggregate(next_member->ty)) {\n                    parse_automatic_aggregate_subobject(tail, child,\n                                                         next_member->ty,\n                                                         &tok, tok, where);\n                } else {\n                    append_automatic_scalar_initializer(tail, child, &tok, tok, where);\n                }\n\n                if (ty->is_union)\n''')

# Brace-elided array scalar leaves.
replace_once(
    "parse.c",
    '''            if (is_initializer_aggregate(ty->base)) {\n                parse_automatic_aggregate_subobject(tail, child, ty->base,\n                                                     &tok, tok, where);\n                continue;\n            }\n\n            Node *rhs = assign(&tok, tok);\n            Node *a = new_initializer_assign(child, rhs, where);\n            *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);\n        }\n    } else {\n''',
    '''            if (is_initializer_aggregate(ty->base)) {\n                parse_automatic_aggregate_subobject(tail, child, ty->base,\n                                                     &tok, tok, where);\n                continue;\n            }\n\n            append_automatic_scalar_initializer(tail, child, &tok, tok, where);\n        }\n    } else {\n''')

# Brace-elided record scalar leaves.
replace_once(
    "parse.c",
    '''            } else if (is_initializer_aggregate(m->ty)) {\n                parse_automatic_aggregate_subobject(tail, child, m->ty,\n                                                     &tok, tok, where);\n                initialized++;\n            } else {\n                Node *rhs = assign(&tok, tok);\n                Node *a = new_initializer_assign(child, rhs, where);\n                *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);\n                initialized++;\n            }\n\n            if (ty->is_union)\n''',
    '''            } else if (is_initializer_aggregate(m->ty)) {\n                parse_automatic_aggregate_subobject(tail, child, m->ty,\n                                                     &tok, tok, where);\n                initialized++;\n            } else {\n                append_automatic_scalar_initializer(tail, child, &tok, tok, where);\n                initialized++;\n            }\n\n            if (ty->is_union)\n''')

# Designated scalar targets such as `.x = {{1}}` and `[2] = {3}` share the
# scalar helper; aggregate designated targets keep the aggregate parser.
replace_once(
    "parse.c",
    '''    if (append_automatic_string_array_initializer(tail, lhs, ty, rest, tok))\n        return;\n\n    if (is_initializer_aggregate(ty) && equal(tok, "{")) {\n        parse_automatic_aggregate_subobject(tail, lhs, ty, rest, tok, where);\n        return;\n    }\n\n    Node *rhs = assign(&tok, tok);\n''',
    '''    if (append_automatic_string_array_initializer(tail, lhs, ty, rest, tok))\n        return;\n\n    if (!is_initializer_aggregate(ty)) {\n        append_automatic_scalar_initializer(tail, lhs, rest, tok, where);\n        return;\n    }\n\n    if (equal(tok, "{")) {\n        parse_automatic_aggregate_subobject(tail, lhs, ty, rest, tok, where);\n        return;\n    }\n\n    Node *rhs = assign(&tok, tok);\n''')

# Top-level automatic scalar declarations currently enter the aggregate-only
# brace parser and are rejected before assignment compatibility is checked.
replace_once(
    "parse.c",
    '''        // Brace-enclosed initializer: { expr, expr, ... }\n        if (equal(tok, "{")) {\n            Token *brace = tok;\n            tok = tok->next;\n\n            if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT)\n                error_at(brace->loc, "brace initializer requires an aggregate type");\n\n            int cur_idx = 0;\n''',
    '''        // Brace-enclosed initializer. Scalars contain one initializer\n        // recursively (plus optional trailing commas); aggregates use the full\n        // initializer-list machinery below.\n        if (equal(tok, "{")) {\n            if (!is_initializer_aggregate(ty)) {\n                Token *brace = tok;\n                Node *lhs = new_var_node(var);\n                append_automatic_scalar_initializer(&block_cur, lhs, &tok, tok, brace);\n                continue;\n            }\n\n            Token *brace = tok;\n            tok = tok->next;\n\n            int cur_idx = 0;\n''')

# Top-level aggregate scalar leaves have separate lowering paths.
replace_once(
    "parse.c",
    '''                        } else {\n                            Node *e = assign(&tok, tok);\n                            Node *a = new_initializer_assign(lhs, e, tok);\n                            block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);\n                        }\n''',
    '''                        } else {\n                            append_automatic_scalar_initializer(&block_cur, lhs,\n                                                                &tok, tok, brace);\n                        }\n''')

replace_once(
    "parse.c",
    '''                        } else {\n                            Node *e = assign(&tok, tok);\n                            Node *a = new_initializer_assign(member_node, e, tok);\n                            block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);\n                        }\n''',
    '''                        } else {\n                            append_automatic_scalar_initializer(&block_cur, member_node,\n                                                                &tok, tok, brace);\n                        }\n''')

# Automatic scalar compound literals use the same recursive scalar initializer.
replace_once(
    "parse.c",
    '''        } else {\n            tok = skip(tok, "{");\n            if (equal(tok, "}"))\n                error_at(tok->loc, "scalar compound literal requires an initializer");\n            Node *rhs = assign(&tok, tok);\n            Node *assign_node = new_initializer_assign(root, rhs, type_tok);\n            tail = tail->next = new_unary(ND_EXPR_STMT, assign_node);\n            if (equal(tok, ","))\n                tok = tok->next;\n            if (!equal(tok, "}"))\n                error_at(tok->loc, "excess elements in scalar compound literal");\n            tok = tok->next;\n        }\n\n        for (Node *stmt = head.next; stmt; stmt = stmt->next) {\n''',
    '''        } else {\n            append_automatic_scalar_initializer(&tail, root, &tok, tok, type_tok);\n        }\n\n        for (Node *stmt = head.next; stmt; stmt = stmt->next) {\n''')

# File-scope scalar compound literals can reuse the recursive static image path.
replace_once(
    "parse.c",
    '''        } else {\n            tok = skip(tok, "{");\n            if (equal(tok, "}"))\n                error_at(tok->loc, "scalar compound literal requires an initializer");\n            parse_static_scalar_initializer(var, &tok, tok, ty);\n            if (equal(tok, ","))\n                tok = tok->next;\n            if (!equal(tok, "}"))\n                error_at(tok->loc, "excess elements in scalar compound literal");\n            tok = tok->next;\n        }\n    }\n\n    Node *node = new_node(ND_COMPOUND_LITERAL);\n''',
    '''        } else {\n            ty = parse_static_image_initializer(var, &tok, tok, ty, 0);\n            var->ty = ty;\n        }\n    }\n\n    Node *node = new_node(ND_COMPOUND_LITERAL);\n''')

Path("test/scalar_brace_initializers.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-scalar-brace.c
  ./minicc tmp-scalar-brace.c > tmp-scalar-brace.s
  cc -o tmp-scalar-brace tmp-scalar-brace.s
  set +e
  ./tmp-scalar-brace
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(scalar brace initializer): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-scalar-brace-bad.c
  if ./minicc tmp-scalar-brace-bad.c > /dev/null 2>tmp-scalar-brace.err; then
    echo "FAIL(scalar brace initializer): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Automatic scalar objects: one scalar initializer may be recursively braced,
# with an optional trailing comma at each brace level.
assert_run 5 'int main(void){int x={5};return x;}'
assert_run 8 'int main(void){int x={8,};return x;}'
assert_run 9 'int main(void){int x={{9}};return x;}'
assert_run 10 'int main(void){int x={{{10,},},};return x;}'
assert_run 4 'int main(void){int x=4;int *p={{&x}};return *p;}'
assert_run 1 'int main(void){_Bool x={{9}};return x;}'
assert_run 3 'int main(void){double x={{3.5}};return x>3.0 && x<4.0 ? 3 : 0;}'

# Static/file-scope scalar paths use the same recursive rule.
assert_run 6 'int x={{6}};int main(void){return x;}'
assert_run 7 'int main(void){static int x={{{7}}};return x;}'

# Scalar leaves inside automatic aggregates and designated initializers.
assert_run 9 'int main(void){int a[2]={{3},{{6,}}};return a[0]+a[1];}'
assert_run 11 'struct S{int x;};int main(void){struct S s={{{11}}};return s.x;}'
assert_run 12 'struct S{int x;};int main(void){struct S s={.x={{12,}}};return s.x;}'
assert_run 13 'int main(void){int a[2]={[1]={{{13}}}};return a[1];}'
assert_run 15 'struct I{int x;};struct O{struct I i;};int main(void){struct O o={.i.x={{15}}};return o.i.x;}'

# Integration with C99 compound literals and #113 unknown-bound inference.
assert_run 14 'struct S{int x;};int main(void){return (struct S){.x={{14}}}.x;}'
assert_run 5 'int main(void){return (int[]){{4},{{5}}}[1];}'
assert_run 17 'int main(void){return (int){{17}};}'
assert_run 16 'int *p=&(int){{16}};int main(void){return *p;}'

# A scalar still has exactly one underlying expression.
assert_reject 'int main(void){int x={};return x;}'
assert_reject 'int main(void){int x={1,2};return x;}'
assert_reject 'int main(void){int x={{1,2}};return x;}'
assert_reject 'int main(void){int x={{1},2};return x;}'
assert_reject 'int main(void){int a[1]={{{1,2}}};return a[0];}'
assert_reject 'struct S{int x;};int main(void){struct S s={.x={{1,2}}};return s.x;}'
assert_reject 'int main(void){int *p={1};return p!=0;}'
assert_reject 'int *p=&(int){{1,2}};int main(void){return *p;}'

rm -f tmp-scalar-brace.c tmp-scalar-brace.s tmp-scalar-brace \
      tmp-scalar-brace-bad.c tmp-scalar-brace.err

echo 'All scalar brace initializer tests passed!'
''')

makefile = Path("Makefile")
text = makefile.read_text()
needle = "\tbash ./test/aggregate_initializers.sh\n"
if text.count(needle) != 1:
    raise SystemExit("Makefile aggregate initializer test anchor not unique")
makefile.write_text(text.replace(needle, needle + "\tbash ./test/scalar_brace_initializers.sh\n", 1))

readme = Path("README.md")
text = readme.read_text()
old = "`{ }` brace-enclosed initializers for arrays and structs"
new = "`{ }` brace-enclosed initializers for arrays/records plus recursively braced C11 scalar initializers"
if text.count(old) != 1:
    raise SystemExit("README initializer wording not unique")
readme.write_text(text.replace(old, new, 1))

print("scalar brace initializer migration applied")
