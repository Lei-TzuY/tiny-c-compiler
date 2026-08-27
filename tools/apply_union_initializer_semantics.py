from pathlib import Path

# minicc.h: preserve the record kind after parsing so all later semantic passes
# can distinguish struct layout/initialization rules from union rules.
p = Path('minicc.h')
s = p.read_text()
old = '''    bool is_unsigned; // true for unsigned integer types\n    bool is_incomplete; // forward-declared struct/union with no body yet\n    Type *base;       // Pointer or array\n'''
new = '''    bool is_unsigned; // true for unsigned integer types\n    bool is_incomplete; // forward-declared struct/union with no body yet\n    bool is_union;      // TY_STRUCT represents both records; true for union\n    Type *base;       // Pointer or array\n'''
if s.count(old) != 1:
    raise SystemExit(f'minicc Type anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

p = Path('parse.c')
s = p.read_text()

old = '''static Type *new_record_type(void) {\n    Type *ty = calloc(1, sizeof(Type));\n    ty->kind = TY_STRUCT;\n    ty->align = 1;\n    ty->is_incomplete = true;\n    return ty;\n}\n'''
new = '''static Type *new_record_type(bool is_union) {\n    Type *ty = calloc(1, sizeof(Type));\n    ty->kind = TY_STRUCT;\n    ty->align = 1;\n    ty->is_incomplete = true;\n    ty->is_union = is_union;\n    return ty;\n}\n'''
if s.count(old) != 1:
    raise SystemExit(f'new_record_type anchor count={s.count(old)}')
s = s.replace(old, new, 1)
s = s.replace('new_record_type();', 'new_record_type(is_union);')

old = '''    ty->align = align;\n    ty->members = head.next;\n    ty->is_incomplete = false;\n    for (Type *q = ty->qual_next; q; q = q->qual_next) {\n        q->size = ty->size;\n        q->align = ty->align;\n        q->members = ty->members;\n        q->is_incomplete = false;\n    }\n'''
new = '''    ty->align = align;\n    ty->members = head.next;\n    ty->is_union = is_union;\n    ty->is_incomplete = false;\n    for (Type *q = ty->qual_next; q; q = q->qual_next) {\n        q->size = ty->size;\n        q->align = ty->align;\n        q->members = ty->members;\n        q->is_union = ty->is_union;\n        q->is_incomplete = false;\n    }\n'''
if s.count(old) != 1:
    raise SystemExit(f'record completion anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Implicit zero initialization of a union initializes only its first named
# member. Recursing through every overlapping member is both unnecessary and,
# for automatic objects, can overwrite an earlier explicit union initializer.
old = '''    if (ty->kind == TY_STRUCT) {\n        for (Member *m = ty->members; m; m = m->next) {\n            Node *member = new_node(ND_MEMBER);\n            member->lhs = lhs;\n            member->member = m;\n            append_zero_initializer(tail, member, m->ty, where);\n        }\n        return;\n    }\n'''
new = '''    if (ty->kind == TY_STRUCT) {\n        if (ty->is_union) {\n            Member *m = ty->members;\n            if (m) {\n                Node *member = new_node(ND_MEMBER);\n                member->lhs = lhs;\n                member->member = m;\n                append_zero_initializer(tail, member, m->ty, where);\n            }\n            return;\n        }\n\n        for (Member *m = ty->members; m; m = m->next) {\n            Node *member = new_node(ND_MEMBER);\n            member->lhs = lhs;\n            member->member = m;\n            append_zero_initializer(tail, member, m->ty, where);\n        }\n        return;\n    }\n'''
if s.count(old) != 1:
    raise SystemExit(f'zero initializer anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Static aggregate images already preserve the whole union storage as zeroed
# bytes. Permit exactly one initializer element, defaulting to the first member
# or selecting a member with .designator, and reject a second overlapping write.
old = '''    ensure_static_image(var, offset + ty->size);\n    Member *next_member = ty->members;\n    bool first = true;\n    while (!equal(tok, "}")) {\n        if (!first) {\n            tok = skip(tok, ",");\n            if (equal(tok, "}"))\n                break;\n        }\n        first = false;\n\n        if (equal(tok, "["))\n            error_at(tok->loc, "array designator requires an array initializer");\n\n        Member *member = next_member;\n        if (consume(&tok, tok, ".")) {\n            if (tok->kind != TK_IDENT)\n                error_at(tok->loc, "expected member name in designated initializer");\n            member = find_static_initializer_member(ty, tok);\n            if (!member)\n                error_at(tok->loc, "unknown member in designated initializer");\n            tok = skip(tok->next, "=");\n        } else if (!member) {\n            error_at(tok->loc, "excess elements in record initializer");\n        }\n\n        reset_static_subobject(var, offset + member->offset, member->ty->size);\n        Type *member_ty = parse_static_image_initializer(var, &tok, tok,\n                                                         member->ty,\n                                                         offset + member->offset);\n        if (member_ty != member->ty)\n            error_at(brace->loc, "incomplete array record members are not supported");\n        next_member = member->next;\n    }\n\n    *rest = skip(tok, "}");\n    return ty;\n'''
new = '''    ensure_static_image(var, offset + ty->size);\n    Member *next_member = ty->members;\n    bool first = true;\n    int initialized_members = 0;\n    while (!equal(tok, "}")) {\n        if (!first) {\n            tok = skip(tok, ",");\n            if (equal(tok, "}"))\n                break;\n        }\n        first = false;\n\n        if (ty->is_union && initialized_members)\n            error_at(tok->loc, "excess elements in union initializer");\n\n        if (equal(tok, "["))\n            error_at(tok->loc, "array designator requires an array initializer");\n\n        Member *member = next_member;\n        if (consume(&tok, tok, ".")) {\n            if (tok->kind != TK_IDENT)\n                error_at(tok->loc, "expected member name in designated initializer");\n            member = find_static_initializer_member(ty, tok);\n            if (!member)\n                error_at(tok->loc, "unknown member in designated initializer");\n            tok = skip(tok->next, "=");\n        } else if (!member) {\n            error_at(tok->loc, "excess elements in record initializer");\n        }\n\n        // All union members overlap at offset zero. Clear the complete union so\n        // a designated pointer member cannot leave stale relocation/data bytes\n        // from an earlier representation of the same object.\n        if (ty->is_union)\n            reset_static_subobject(var, offset, ty->size);\n        else\n            reset_static_subobject(var, offset + member->offset, member->ty->size);\n        Type *member_ty = parse_static_image_initializer(var, &tok, tok,\n                                                         member->ty,\n                                                         offset + member->offset);\n        if (member_ty != member->ty)\n            error_at(brace->loc, "incomplete array record members are not supported");\n        initialized_members++;\n        next_member = member->next;\n    }\n\n    *rest = skip(tok, "}");\n    return ty;\n'''
if s.count(old) != 1:
    raise SystemExit(f'static record initializer anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Automatic record initialization needs the same one-active-member rule. Track
# whether a union already consumed an initializer, regardless of positional vs
# designated spelling.
old = '''            Member *cur_mem = (ty->kind == TY_STRUCT) ? ty->members : NULL;\n            Node *before_init = block_cur;\n\n            while (!equal(tok, "}")) {\n                if (equal(tok, ",")) tok = tok->next;\n                if (equal(tok, "}")) break;\n\n                // Designated initializer: .member = expr\n'''
new = '''            Member *cur_mem = (ty->kind == TY_STRUCT) ? ty->members : NULL;\n            Node *before_init = block_cur;\n            int initialized_union_members = 0;\n\n            while (!equal(tok, "}")) {\n                if (equal(tok, ",")) tok = tok->next;\n                if (equal(tok, "}")) break;\n                if (ty->kind == TY_STRUCT && ty->is_union && initialized_union_members)\n                    error_at(tok->loc, "excess elements in union initializer");\n\n                // Designated initializer: .member = expr\n'''
if s.count(old) != 1:
    raise SystemExit(f'automatic loop anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);\n                    cur_mem = m->next;\n                    continue;\n                }\n'''
new = '''                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);\n                    if (ty->is_union)\n                        initialized_union_members++;\n                    cur_mem = m->next;\n                    continue;\n                }\n'''
if s.count(old) != 1:
    raise SystemExit(f'automatic designated member anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''                    Node *a = new_initializer_assign(member_node, e, tok);\n                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);\n                    cur_mem = cur_mem->next;\n                }\n'''
new = '''                    Node *a = new_initializer_assign(member_node, e, tok);\n                    block_cur = block_cur->next = new_unary(ND_EXPR_STMT, a);\n                    if (ty->is_union)\n                        initialized_union_members++;\n                    cur_mem = cur_mem->next;\n                }\n'''
if s.count(old) != 1:
    raise SystemExit(f'automatic positional member anchor count={s.count(old)}')
s = s.replace(old, new, 1)

# Do not zero every overlapping union member after an explicit initializer. If
# no member was explicitly initialized (the compiler's existing {} extension),
# initialize only the first member recursively.
old = '''            } else {\n                int mi = 0;\n                for (Member *m = ty->members; m; m = m->next, mi++) {\n                    if (mi < member_count && member_init[mi]) continue;\n                    Node *member = new_node(ND_MEMBER);\n                    member->lhs = new_var_node(var);\n                    member->member = m;\n                    append_zero_initializer(&zero_cur, member, m->ty, brace);\n                }\n            }\n'''
new = '''            } else if (ty->is_union) {\n                if (!initialized_union_members && ty->members) {\n                    Member *m = ty->members;\n                    Node *member = new_node(ND_MEMBER);\n                    member->lhs = new_var_node(var);\n                    member->member = m;\n                    append_zero_initializer(&zero_cur, member, m->ty, brace);\n                }\n            } else {\n                int mi = 0;\n                for (Member *m = ty->members; m; m = m->next, mi++) {\n                    if (mi < member_count && member_init[mi]) continue;\n                    Node *member = new_node(ND_MEMBER);\n                    member->lhs = new_var_node(var);\n                    member->member = m;\n                    append_zero_initializer(&zero_cur, member, m->ty, brace);\n                }\n            }\n'''
if s.count(old) != 1:
    raise SystemExit(f'automatic zero record anchor count={s.count(old)}')
s = s.replace(old, new, 1)

p.write_text(s)

# Focused regression coverage.
Path('test/union_initializers.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-union-init.c
  ./minicc tmp-union-init.c > tmp-union-init.s
  cc -o tmp-union-init tmp-union-init.s
  set +e
  ./tmp-union-init
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "union initializer failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(union initializer): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-union-init-bad.c
  if ./minicc tmp-union-init-bad.c > tmp-union-init-bad.s 2>/dev/null; then
    echo "union initializer unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(union initializer): rejected invalid program"
}

# Positional union initialization selects exactly the first member.
assert_run 7 'int main(){union U{int x; long y;}; union U u={7}; return u.x;}'
assert_run 1 'int main(){union U{char c; long x;}; return sizeof(union U)==8;}'

# A member designator selects a non-first member without later implicit zeroing
# overwriting the shared storage.
assert_run 9 'int main(){union U{int x; long y;}; union U u={.y=9}; return u.y;}'
assert_run 13 'int main(){union U{int x; long y;}; union U u={.x=13}; return u.x;}'

# Static/global union images follow the same active-member rule and preserve
# full-size zeroed storage/padding.
assert_run 11 'union U{int x; long y;}; union U u={11}; int main(){return u.x;}'
assert_run 17 'union U{int x; long y;}; union U u={.y=17}; int main(){return u.y;}'
assert_run 19 'int main(){union U{int x; long y;}; static union U u={.y=19}; return u.y;}'
assert_run 1 'union U{char c; long x;}; union U u={.c=3}; int main(){return sizeof(u)==8 && u.c==3;}'

# Relocations inside a selected static union member use offset zero correctly.
assert_run 1 'int g=5; union U{int *p; long x;}; union U u={.p=&g}; int main(){return u.p==&g;}'
assert_run 1 'int f(){return 7;} union U{int (*fp)(); long x;}; union U u={.fp=f}; int main(){return u.fp()==7;}'
assert_run 1 'union U{char *p; long x;}; union U u={.p="ok"}; int main(){return u.p[0]==111 && u.p[1]==107;}'

# Union metadata survives qualifiers/forward completion.
assert_run 23 'union U; typedef const union U CU; union U{int x; long y;}; int main(){union U u={.y=23}; CU *p=&u; return p->y;}'

# A union initializer contains at most one initializer element. The previous
# struct-like implementation silently accepted these and overwrote offset zero.
assert_fail 'int main(){union U{int x; int y;}; union U u={1,2}; return u.x;}'
assert_fail 'union U{int x; int y;}; union U u={.x=1,.y=2}; int main(){return 0;}'
assert_fail 'int main(){union U{int x; int y;}; union U u={.y=1,2}; return 0;}'
assert_fail 'union U{int x; int y;}; static union U u={1,2}; int main(){return 0;}'

# Existing struct semantics remain multi-member.
assert_run 3 'int main(){struct S{int x;int y;}; struct S s={1,2}; return s.x+s.y;}'
assert_run 7 'struct S{int x;int y;}; struct S s={3,4}; int main(){return s.x+s.y;}'

echo 'All union-initializer tests passed!'
''')

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/aggregate_static_relocations.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/union_initializers.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = '- Static aggregate initializers use zero-filled byte images plus per-offset linker relocations, supporting pointer/function/string addresses inside arrays and records, nested aggregates, designators, and record padding.\n'
replacement = needle + '\n- Union types retain their record kind through semantic analysis; automatic/static union initializers select exactly one member (the first by default or a designated member), preserve overlapping storage correctly, and reject excess initializer elements.\n'
if s.count(needle) != 1:
    raise SystemExit(f'README anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))
