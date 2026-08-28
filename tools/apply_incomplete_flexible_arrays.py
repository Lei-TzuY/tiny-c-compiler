from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    s = s.replace(old, new, 1)
    p.write_text(s)


replace_once(
    "minicc.h",
    """    bool is_incomplete; // forward-declared struct/union with no body yet\n    bool is_union;      // TY_STRUCT represents both records; true for union\n    Type *base;       // Pointer or array\n""",
    """    bool is_incomplete; // forward-declared struct/union with no body yet\n    bool is_union;      // TY_STRUCT represents both records; true for union\n    bool has_flexible_array_member; // complete struct ends in a flexible array member\n    Type *base;       // Pointer or array\n""",
    "Type flexible-array metadata",
)

replace_once(
    "parse.c",
    """static bool is_incomplete_object_type(Type *ty) {\n    if (!ty)\n        return false;\n    if (ty->kind == TY_STRUCT)\n        return ty->is_incomplete;\n    if (ty->kind == TY_ARRAY)\n        return is_incomplete_object_type(ty->base);\n    return false;\n}\n""",
    """static bool is_incomplete_object_type(Type *ty) {\n    if (!ty)\n        return false;\n    if (ty->kind == TY_STRUCT)\n        return ty->is_incomplete;\n    if (ty->kind == TY_ARRAY)\n        return ty->array_len == 0 || is_incomplete_object_type(ty->base);\n    return false;\n}\n\nstatic bool is_unknown_bound_array_with_complete_element(Type *ty) {\n    return ty && ty->kind == TY_ARRAY && ty->array_len == 0 &&\n           !is_incomplete_object_type(ty->base);\n}\n""",
    "incomplete object classification",
)

replace_once(
    "parse.c",
    """    Member head = {};\n    Member *cur = &head;\n    while (!equal(tok, \"}\")) {\n""",
    """    Member head = {};\n    Member *cur = &head;\n    bool has_flexible_member = false;\n    while (!equal(tok, \"}\")) {\n""",
    "record flexible member state",
)

replace_once(
    "parse.c",
    """            Token *ident;\n            Type *mty = declarator(&tok, tok, basety, &ident);\n            if (is_incomplete_object_type(mty))\n                error_at(ident->loc, \"field has incomplete type\");\n\n            Member *m = calloc(1, sizeof(Member));\n""",
    """            Token *ident;\n            Type *mty = declarator(&tok, tok, basety, &ident);\n            bool flexible = mty->kind == TY_ARRAY && mty->array_len == 0;\n\n            if (flexible) {\n                if (is_union)\n                    error_at(ident->loc, \"flexible array member is not allowed in a union\");\n                if (!head.next)\n                    error_at(ident->loc,\n                             \"flexible array member requires a preceding named member\");\n                if (!equal(tok, \";\") || !equal(tok->next, \"}\"))\n                    error_at(ident->loc, \"flexible array member must be the last member\");\n                has_flexible_member = true;\n            } else {\n                if (is_incomplete_object_type(mty))\n                    error_at(ident->loc, \"field has incomplete type\");\n                if (mty->kind == TY_STRUCT && mty->has_flexible_array_member)\n                    error_at(ident->loc,\n                             \"record containing a flexible array member cannot be embedded\");\n            }\n\n            Member *m = calloc(1, sizeof(Member));\n""",
    "record member constraints",
)

replace_once(
    "parse.c",
    """    ty->align = align;\n    ty->members = head.next;\n    ty->is_union = is_union;\n    ty->is_incomplete = false;\n    for (Type *q = ty->qual_next; q; q = q->qual_next) {\n        q->size = ty->size;\n        q->align = ty->align;\n        q->members = ty->members;\n        q->is_union = ty->is_union;\n        q->is_incomplete = false;\n    }\n""",
    """    ty->align = align;\n    ty->members = head.next;\n    ty->is_union = is_union;\n    ty->has_flexible_array_member = has_flexible_member;\n    ty->is_incomplete = false;\n    for (Type *q = ty->qual_next; q; q = q->qual_next) {\n        q->size = ty->size;\n        q->align = ty->align;\n        q->members = ty->members;\n        q->is_union = ty->is_union;\n        q->has_flexible_array_member = ty->has_flexible_array_member;\n        q->is_incomplete = false;\n    }\n""",
    "record completion metadata",
)

replace_once(
    "parse.c",
    """        tok = skip(tok, \"]\");\n        ty = type_suffix(rest, tok, ty);\n        if (ty->kind == TY_FUNC)\n            error_at(tok->loc, \"array element type cannot be a function\");\n        return array_of(ty, len);\n""",
    """        tok = skip(tok, \"]\");\n        ty = type_suffix(rest, tok, ty);\n        if (ty->kind == TY_FUNC)\n            error_at(bracket->loc, \"array element type cannot be a function\");\n        if (ty->kind == TY_VOID)\n            error_at(bracket->loc, \"array element type cannot be void\");\n        if (is_incomplete_object_type(ty))\n            error_at(bracket->loc, \"array element type is incomplete\");\n        if (ty->kind == TY_STRUCT && ty->has_flexible_array_member)\n            error_at(bracket->loc,\n                     \"array element type contains a flexible array member\");\n        return array_of(ty, len);\n""",
    "array element constraints",
)

replace_once(
    "parse.c",
    """        Token *ident;\n        Type *ty = declarator(&tok, tok, basety, &ident);\n        if (!is_extern && is_incomplete_object_type(ty))\n            error_at(ident->loc, \"variable has incomplete type\");\n\n        char *name = strndup(ident->loc, ident->len);\n""",
    """        Token *ident;\n        Type *ty = declarator(&tok, tok, basety, &ident);\n        bool inferable_array = is_unknown_bound_array_with_complete_element(ty) &&\n                               equal(tok, \"=\");\n        if (!is_extern && is_incomplete_object_type(ty) && !inferable_array)\n            error_at(ident->loc, \"variable has incomplete type\");\n\n        char *name = strndup(ident->loc, ident->len);\n""",
    "block incomplete array declarations",
)

replace_once(
    "parse.c",
    """        if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC ||\n            ty->is_incomplete)\n            error_at(op->loc, \"invalid type for _Alignof\");\n""",
    """        if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC ||\n            is_incomplete_object_type(ty))\n            error_at(op->loc, \"invalid type for _Alignof\");\n""",
    "_Alignof incomplete arrays",
)

replace_once(
    "parse.c",
    """            // Global variable(s) (possibly with initializer)\n            for (;;) {\n                if (!is_extern && is_incomplete_object_type(ty))\n                    error_at(ident->loc, \"variable has incomplete type\");\n\n                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);\n""",
    """            // Global variable(s) (possibly with initializer)\n            for (;;) {\n                if (!is_extern && is_incomplete_object_type(ty) &&\n                    !is_unknown_bound_array_with_complete_element(ty))\n                    error_at(ident->loc, \"variable has incomplete type\");\n\n                Obj *var = register_global_symbol(ident, ty, is_static, is_extern);\n""",
    "file-scope incomplete arrays",
)

replace_once(
    "parse.c",
    """    Program *prog = calloc(1, sizeof(Program));\n    prog->globals = globals;\n""",
    """    // A file-scope tentative definition with incomplete array type is\n    // completed as a one-element array if no later declaration supplied a\n    // bound. Pure extern declarations remain incomplete and allocate nothing.\n    for (Obj *var = globals; var; var = var->next) {\n        if (var->is_function || var->is_extern)\n            continue;\n        if (is_unknown_bound_array_with_complete_element(var->ty))\n            var->ty = array_of(var->ty->base, 1);\n    }\n\n    Program *prog = calloc(1, sizeof(Program));\n    prog->globals = globals;\n""",
    "tentative incomplete array completion",
)

make = Path("Makefile")
s = make.read_text()
anchor = "\tbash ./test/incomplete_tags.sh\n"
if anchor not in s:
    raise SystemExit("Makefile incomplete_tags anchor missing")
s = s.replace(anchor, anchor + "\tbash ./test/incomplete_flexible_arrays.sh\n", 1)
make.write_text(s)

readme = Path("README.md")
s = readme.read_text()
anchor = "- Incomplete array types"
if anchor not in s:
    s += """\n\n- Incomplete array types are tracked explicitly. Local/static objects without an inferred bound are rejected; file-scope `extern T a[]` remains incomplete, tentative definitions are completed to one element at translation-unit end, and initializer-based bound inference remains supported. Flexible array members are accepted only as the final member of a non-union struct with at least one preceding named member, and such structs cannot be embedded or used as array element types.\n"""
readme.write_text(s)

Path("test/incomplete_flexible_arrays.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-incomplete-array.c
  ./minicc tmp-incomplete-array.c > tmp-incomplete-array.s
  cc -o tmp-incomplete-array tmp-incomplete-array.s
  set +e
  ./tmp-incomplete-array
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(incomplete/flexible array): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(incomplete/flexible array): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-incomplete-array-reject.c
  if ./minicc tmp-incomplete-array-reject.c > /dev/null 2>&1; then
    echo "FAIL(incomplete/flexible array): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(incomplete/flexible array): rejected"
}

# A valid flexible array member contributes alignment/offset but no payload size.
assert_run 0 'struct S { int n; int data[]; }; int main(void){ struct S s={7}; return sizeof(struct S)!=4 || _Alignof(struct S)!=4 || s.n!=7; }'
assert_run 0 'struct S { char tag; double values[]; }; int main(void){ return sizeof(struct S)!=8 || _Alignof(struct S)!=8; }'
# A preceding named member may appear in the same member declaration.
assert_run 0 'struct S { int n, data[]; }; int main(void){ return sizeof(struct S)!=4; }'
# Pointers to flexible-array records and pointers to incomplete arrays remain valid.
assert_run 0 'struct S { int n; int data[]; }; struct S *p; int (*q)[]; int main(void){ return sizeof(p)!=8 || sizeof(q)!=8; }'

# Unknown outer bounds are still inferred from ordinary automatic/static/global initializers.
assert_run 0 'int main(void){ int a[]={1,2,3}; return sizeof(a)!=12 || a[2]!=3; }'
assert_run 0 'int main(void){ static int a[]={4,5}; return sizeof(a)!=8 || a[1]!=5; }'
assert_run 0 'int main(void){ char s[]="abc"; return sizeof(s)!=4 || s[3]!=0; }'
assert_run 0 'int a[][2]={{1,2},{3,4}}; int main(void){ return sizeof(a)!=16 || a[1][1]!=4; }'

# The first parameter array dimension still adjusts to a pointer before completeness checks.
assert_run 0 'int pick(int a[]){ return a[1]; } int main(void){ int a[2]={2,7}; return pick(a)-7; }'
# File-scope extern incomplete arrays compose with a later complete declaration.
assert_run 0 'extern int a[]; int a[3]={1,2,3}; int main(void){ return sizeof(a)!=12 || a[2]!=3; }'

# A leftover tentative incomplete array is completed to one element for emission.
printf '%s\n' 'int tentative[]; int main(void){ tentative[0]=9; return tentative[0]-9; }' > tmp-tentative-array.c
./minicc tmp-tentative-array.c > tmp-tentative-array.s
if ! awk '/^tentative:/{seen=1; next} seen && /\.zero[[:space:]]+4/{ok=1; exit} END{exit !ok}' tmp-tentative-array.s; then
  echo 'FAIL(incomplete/flexible array): tentative incomplete array was not completed to one element'
  exit 1
fi
cc -o tmp-tentative-array tmp-tentative-array.s
./tmp-tentative-array
printf '%s\n' 'OK(incomplete/flexible array): tentative array completed to one element'

# Incomplete arrays are not zero-sized ordinary block objects.
assert_reject 'int main(void){ int a[]; return 0; }'
assert_reject 'int main(void){ static int a[]; return 0; }'
# Array elements must be complete object types.
assert_reject 'void a[3]; int main(void){ return 0; }'
assert_reject 'struct S; struct S a[2]; int main(void){ return 0; }'
assert_reject 'int a[2][]; int main(void){ return 0; }'
# _Alignof, like sizeof, requires a complete object type.
assert_reject 'int main(void){ return _Alignof(int[]); }'

# Flexible array member constraints.
assert_reject 'struct S { int data[]; }; int main(void){ return 0; }'
assert_reject 'struct S { int n; int data[]; int tail; }; int main(void){ return 0; }'
assert_reject 'struct S { int n; int data[], tail; }; int main(void){ return 0; }'
assert_reject 'union U { int n; int data[]; }; int main(void){ return 0; }'
# A record containing a flexible array member cannot itself be embedded or arrayed.
assert_reject 'struct S { int n; int data[]; }; struct T { struct S s; }; int main(void){ return 0; }'
assert_reject 'struct S { int n; int data[]; }; struct S a[2]; int main(void){ return 0; }'

# Existing positive-bound/constant-expression constraints remain enforced.
assert_reject 'int a[0]; int main(void){ return 0; }'
assert_reject 'int main(void){ int n=3; int a[n]; return 0; }'

echo 'incomplete/flexible array tests passed'
''')
