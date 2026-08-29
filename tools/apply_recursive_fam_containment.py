from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


root = Path('.')

hdr_path = root / 'minicc.h'
hdr = hdr_path.read_text()
hdr = replace_once(
    hdr,
    '''    bool is_union;      // TY_STRUCT represents both records; true for union\n    bool has_flexible_array_member; // complete struct ends in a flexible array member\n    Type *base;       // Pointer or array\n''',
    '''    bool is_union;      // TY_STRUCT represents both records; true for union\n    bool has_flexible_array_member; // complete struct itself ends in a flexible array member\n    bool contains_flexible_array_member; // direct-FAM struct or union recursively containing one\n    Type *base;       // Pointer or array\n''',
    'Type flexible-array metadata',
)
hdr_path.write_text(hdr)

parse_path = root / 'parse.c'
p = parse_path.read_text()

# C11 permits a structure with a flexible array member to be a union member.
# The union then becomes a recursively restricted carrier: it may itself be a
# union member, but it may not be a structure member or an array element.
p = replace_once(
    p,
    '''        if (equal(tok, ";")) {\n            if (!attrs.has_anonymous_record_specifier || basety->kind != TY_STRUCT)\n                error_at(tok->loc,\n                         "record member declaration without a declarator must be an anonymous struct or union");\n            if (basety->has_flexible_array_member)\n                error_at(tok->loc,\n                         "anonymous record member cannot contain a flexible array member");\n\n            const char *conflict = anonymous_member_conflict(head.next, basety);\n''',
    '''        if (equal(tok, ";")) {\n            if (!attrs.has_anonymous_record_specifier || basety->kind != TY_STRUCT)\n                error_at(tok->loc,\n                         "record member declaration without a declarator must be an anonymous struct or union");\n            if (!is_union && basety->contains_flexible_array_member)\n                error_at(tok->loc,\n                         "record recursively containing a flexible array member cannot be embedded in a struct");\n\n            const char *conflict = anonymous_member_conflict(head.next, basety);\n''',
    'anonymous FAM carrier constraint',
)

p = replace_once(
    p,
    '''            } else {\n                if (is_incomplete_object_type(mty))\n                    error_at(ident->loc, "field has incomplete type");\n                if (mty->kind == TY_STRUCT && mty->has_flexible_array_member)\n                    error_at(ident->loc,\n                             "record containing a flexible array member cannot be embedded");\n            }\n''',
    '''            } else {\n                if (is_incomplete_object_type(mty))\n                    error_at(ident->loc, "field has incomplete type");\n                if (!is_union && mty->kind == TY_STRUCT &&\n                    mty->contains_flexible_array_member)\n                    error_at(ident->loc,\n                             "record recursively containing a flexible array member cannot be embedded in a struct");\n            }\n''',
    'named FAM carrier constraint',
)

p = replace_once(
    p,
    '''    ty->align = align;\n    ty->members = head.next;\n    ty->is_union = is_union;\n    ty->has_flexible_array_member = has_flexible_member;\n    ty->is_incomplete = false;\n    for (Type *q = ty->qual_next; q; q = q->qual_next) {\n        q->size = ty->size;\n        q->align = ty->align;\n        q->members = ty->members;\n        q->is_union = ty->is_union;\n        q->has_flexible_array_member = ty->has_flexible_array_member;\n        q->is_incomplete = false;\n    }\n''',
    '''    bool contains_flexible_member = has_flexible_member;\n    if (is_union) {\n        for (Member *m = head.next; m; m = m->next) {\n            if (m->ty && m->ty->kind == TY_STRUCT &&\n                m->ty->contains_flexible_array_member) {\n                contains_flexible_member = true;\n                break;\n            }\n        }\n    }\n\n    ty->align = align;\n    ty->members = head.next;\n    ty->is_union = is_union;\n    ty->has_flexible_array_member = has_flexible_member;\n    ty->contains_flexible_array_member = contains_flexible_member;\n    ty->is_incomplete = false;\n    for (Type *q = ty->qual_next; q; q = q->qual_next) {\n        q->size = ty->size;\n        q->align = ty->align;\n        q->members = ty->members;\n        q->is_union = ty->is_union;\n        q->has_flexible_array_member = ty->has_flexible_array_member;\n        q->contains_flexible_array_member = ty->contains_flexible_array_member;\n        q->is_incomplete = false;\n    }\n''',
    'record carrier propagation and qualified clone sync',
)

p = replace_once(
    p,
    '''        if (ty->kind == TY_STRUCT && ty->has_flexible_array_member)\n            error_at(bracket->loc,\n                     "array element type contains a flexible array member");\n''',
    '''        if (ty->kind == TY_STRUCT && ty->contains_flexible_array_member)\n            error_at(bracket->loc,\n                     "array element type contains a flexible array member");\n''',
    'array carrier constraint',
)

parse_path.write_text(p)

make_path = root / 'Makefile'
make = make_path.read_text()
make = replace_once(
    make,
    '\tbash ./test/incomplete_flexible_arrays.sh\n',
    '\tbash ./test/incomplete_flexible_arrays.sh\n\tbash ./test/flexible_array_containment.sh\n',
    'Makefile FAM containment regression',
)
make_path.write_text(make)

readme_path = root / 'README.md'
readme = readme_path.read_text()
readme = replace_once(
    readme,
    'anonymous struct/union members with recursively promoted names, and duplicate-member diagnostics including promoted-name collisions.',
    'anonymous struct/union members with recursively promoted names, duplicate-member diagnostics including promoted-name collisions, and C11 flexible-array containment rules propagated through nested unions.',
    'README FAM containment feature',
)
readme_path.write_text(readme)

(root / 'test' / 'flexible_array_containment.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-fam-containment.c
  ./minicc tmp-fam-containment.c > tmp-fam-containment.s
  cc -o tmp-fam-containment tmp-fam-containment.s
  set +e
  ./tmp-fam-containment
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(flexible-array containment): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-fam-containment-bad.c
  if ./minicc tmp-fam-containment-bad.c > /dev/null 2>tmp-fam-containment.err; then
    echo "FAIL(flexible-array containment): expected rejection"
    echo "$input"
    exit 1
  fi
}

# C11 allows a structure with a flexible array member to be a union member.
# Such unions remain complete ordinary object types and may nest through unions.
assert_run 0 'struct F{int n;int data[];};union U{struct F f;long raw;};int main(void){return sizeof(union U)!=8;}'
assert_run 0 'struct F{int n;int data[];};union U{struct F f;long raw;};union V{union U u;double d;};int main(void){return sizeof(union V)!=8;}'
assert_run 0 'struct F{int n;int data[];};union U{struct F f;long raw;};struct H{union U *p;};int main(void){return sizeof(struct H)!=8;}'
assert_run 0 'struct F;typedef const struct F CF;struct F{int n;int data[];};union U{CF f;long raw;};int main(void){return sizeof(union U)!=8;}'

# The same rule applies to anonymous record members: an anonymous FAM struct may
# live in a union, and the resulting union becomes a restricted carrier.
assert_run 0 'union U{struct{int n;int data[];};long raw;};int main(void){return sizeof(union U)!=8;}'
assert_run 0 'union U{struct{int n;int data[];};long raw;};union V{union{union U u;long x;};double d;};int main(void){return sizeof(union V)!=8;}'

# A direct-FAM structure, or any union recursively carrying one, may not become
# a member of a structure.
assert_reject 'struct F{int n;int data[];};struct H{struct F f;};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};struct H{union U u;};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};union V{union U u;int x;};struct H{union V v;};int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};struct H{union{struct F f;long raw;};};int main(void){return 0;}'
assert_reject 'struct H{union{struct{int n;int data[];} f;long raw;};};int main(void){return 0;}'

# Anonymous direct-FAM structs are likewise forbidden when the containing
# record is a structure rather than a union.
assert_reject 'struct H{struct{int n;int data[];};};int main(void){return 0;}'

# Restricted carriers may not be array elements, including recursively nested
# and qualified carrier unions.
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};union U a[2];int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};union V{union U u;int x;};union V a[2];int main(void){return 0;}'
assert_reject 'struct F{int n;int data[];};union U{struct F f;long raw;};typedef const union U CU;CU a[2];int main(void){return 0;}'

rm -f tmp-fam-containment.c tmp-fam-containment.s tmp-fam-containment \
      tmp-fam-containment-bad.c tmp-fam-containment.err

echo 'All recursive flexible-array containment tests passed!'
''')
