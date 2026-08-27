from pathlib import Path

p = Path("parse.c")
s = p.read_text()

repls = []

repls.append((
'''typedef struct StructTag StructTag;
struct StructTag {
    StructTag *next;
    char *name;
    Type *ty;
};
''',
'''typedef enum {
    TAG_STRUCT,
    TAG_UNION,
    TAG_ENUM,
} TagKind;

typedef struct StructTag StructTag;
struct StructTag {
    StructTag *next;
    char *name;
    Type *ty;
    TagKind kind;
};
''',
"tag kind metadata"))

repls.append((
'''static StructTag *push_tag(const char *name, Type *ty) {
    StructTag *tag = calloc(1, sizeof(StructTag));
    tag->name = strdup(name);
    tag->ty = ty;
    tag->next = current_scope->tags;
    current_scope->tags = tag;
    return tag;
}
''',
'''static const char *tag_kind_name(TagKind kind) {
    switch (kind) {
    case TAG_STRUCT: return "struct";
    case TAG_UNION: return "union";
    case TAG_ENUM: return "enum";
    }
    return "tag";
}

static StructTag *push_tag(const char *name, Type *ty, TagKind kind) {
    StructTag *tag = calloc(1, sizeof(StructTag));
    tag->name = strdup(name);
    tag->ty = ty;
    tag->kind = kind;
    tag->next = current_scope->tags;
    current_scope->tags = tag;
    return tag;
}
''',
"typed tag insertion"))

old_record_head = '''static Type *record_decl(Token **rest, Token *tok, bool is_union) {
    const char *kind = is_union ? "union" : "struct";
    char *tag_name = NULL;
'''
new_record_head = '''static Type *record_decl(Token **rest, Token *tok, bool is_union) {
    const char *kind = is_union ? "union" : "struct";
    TagKind tag_kind = is_union ? TAG_UNION : TAG_STRUCT;
    char *tag_name = NULL;
'''
repls.append((old_record_head, new_record_head, "record tag kind"))

old_record_ref = '''        StructTag *tag = find_tag(tag_name);
        if (!tag) {
            Type *ty = new_record_type();
            tag = push_tag(tag_name, ty);
        }
        *rest = tok;
        return tag->ty;
'''
new_record_ref = '''        StructTag *tag = find_tag(tag_name);
        if (!tag) {
            Type *ty = new_record_type();
            tag = push_tag(tag_name, ty, tag_kind);
        } else if (tag->kind != tag_kind) {
            error_at(tok->loc, "%s %s conflicts with %s tag", kind, tag_name,
                     tag_kind_name(tag->kind));
        }
        *rest = tok;
        return tag->ty;
'''
repls.append((old_record_ref, new_record_ref, "record tag reference"))

old_record_def = '''        StructTag *tag = find_tag_in_scope(current_scope, tag_name);
        if (tag) {
            if (!tag->ty->is_incomplete)
                error_at(tok->loc, "redefinition of %s %s", kind, tag_name);
            ty = tag->ty;
        } else {
            ty = new_record_type();
            push_tag(tag_name, ty);
        }
'''
new_record_def = '''        StructTag *tag = find_tag_in_scope(current_scope, tag_name);
        if (tag) {
            if (tag->kind != tag_kind)
                error_at(tok->loc, "%s %s conflicts with %s tag", kind, tag_name,
                         tag_kind_name(tag->kind));
            if (!tag->ty->is_incomplete)
                error_at(tok->loc, "redefinition of %s %s", kind, tag_name);
            ty = tag->ty;
        } else {
            ty = new_record_type();
            push_tag(tag_name, ty, tag_kind);
        }
'''
repls.append((old_record_def, new_record_def, "record tag definition"))

old_enum_block = '''        if (equal(tok, "enum")) {
            tok = tok->next;
            if (tok->kind == TK_IDENT && !equal(tok, "{"))
                tok = tok->next;
            if (consume(&tok, tok, "{")) {
                int64_t val = 0;
                while (!equal(tok, "}")) {
                    if (tok->kind != TK_IDENT)
                        error_at(tok->loc, "expected identifier");
                    char *name = strndup(tok->loc, tok->len);
                    tok = tok->next;
                    if (consume(&tok, tok, "=")) {
                        if (tok->kind != TK_NUM)
                            error_at(tok->loc, "expected integer constant");
                        val = tok->val;
                        tok = tok->next;
                    }
                    push_enum_const(name, val++);
                    consume(&tok, tok, ",");
                }
                tok = skip(tok, "}");
            }
            ty = ty_int;
            continue;
        }
'''
new_enum_block = '''        if (equal(tok, "enum")) {
            ty = enum_decl(&tok, tok->next);
            continue;
        }
'''
repls.append((old_enum_block, new_enum_block, "enum declspec dispatch"))

for old, new, label in repls:
    if old not in s:
        raise SystemExit(f"expected parser block not found: {label}")
    s = s.replace(old, new, 1)

anchor = '''static Type *declspec(Token **rest, Token *tok) {
'''
if anchor not in s:
    raise SystemExit("declspec anchor not found")

helpers = r'''static int64_t cast_const_integer(int64_t val, Type *ty) {
    if (!ty || !is_integer(ty))
        error("cast in integer constant expression must target an integer type");

    if (ty->kind == TY_BOOL)
        return val != 0;

    if (ty->size == 1)
        return ty->is_unsigned ? (uint8_t)val : (int8_t)val;
    if (ty->size == 2)
        return ty->is_unsigned ? (uint16_t)val : (int16_t)val;
    if (ty->size == 4)
        return ty->is_unsigned ? (uint32_t)val : (int32_t)val;
    return val;
}

static int64_t eval_const_expr(Node *node) {
    if (!node)
        error("expected integer constant expression");

    switch (node->kind) {
    case ND_NUM:
        if (node->ty && is_flonum(node->ty))
            error("floating value is not an integer constant expression");
        return node->val;
    case ND_ADD:
        return eval_const_expr(node->lhs) + eval_const_expr(node->rhs);
    case ND_SUB:
        return eval_const_expr(node->lhs) - eval_const_expr(node->rhs);
    case ND_MUL:
        return eval_const_expr(node->lhs) * eval_const_expr(node->rhs);
    case ND_DIV: {
        int64_t lhs = eval_const_expr(node->lhs);
        int64_t rhs = eval_const_expr(node->rhs);
        if (!rhs)
            error("division by zero in integer constant expression");
        return lhs / rhs;
    }
    case ND_MOD: {
        int64_t lhs = eval_const_expr(node->lhs);
        int64_t rhs = eval_const_expr(node->rhs);
        if (!rhs)
            error("modulo by zero in integer constant expression");
        return lhs % rhs;
    }
    case ND_BITAND:
        return eval_const_expr(node->lhs) & eval_const_expr(node->rhs);
    case ND_BITOR:
        return eval_const_expr(node->lhs) | eval_const_expr(node->rhs);
    case ND_BITXOR:
        return eval_const_expr(node->lhs) ^ eval_const_expr(node->rhs);
    case ND_BITNOT:
        return ~eval_const_expr(node->lhs);
    case ND_SHL:
    case ND_SHR: {
        int64_t lhs = eval_const_expr(node->lhs);
        int64_t rhs = eval_const_expr(node->rhs);
        if (rhs < 0 || rhs >= 64)
            error("invalid shift count in integer constant expression");
        return node->kind == ND_SHL ? (lhs << rhs) : (lhs >> rhs);
    }
    case ND_EQ:
        return eval_const_expr(node->lhs) == eval_const_expr(node->rhs);
    case ND_NE:
        return eval_const_expr(node->lhs) != eval_const_expr(node->rhs);
    case ND_LT:
        return eval_const_expr(node->lhs) < eval_const_expr(node->rhs);
    case ND_LE:
        return eval_const_expr(node->lhs) <= eval_const_expr(node->rhs);
    case ND_NOT:
        return !eval_const_expr(node->lhs);
    case ND_LOGAND: {
        int64_t lhs = eval_const_expr(node->lhs);
        return lhs ? !!eval_const_expr(node->rhs) : 0;
    }
    case ND_LOGOR: {
        int64_t lhs = eval_const_expr(node->lhs);
        return lhs ? 1 : !!eval_const_expr(node->rhs);
    }
    case ND_TERNARY:
        return eval_const_expr(node->cond) ? eval_const_expr(node->then)
                                           : eval_const_expr(node->els);
    case ND_CAST:
        return cast_const_integer(eval_const_expr(node->lhs), node->ty);
    default:
        error("not an integer constant expression");
    }
}

static Type *enum_decl(Token **rest, Token *tok) {
    char *tag_name = NULL;

    if (tok->kind == TK_IDENT) {
        tag_name = strndup(tok->loc, tok->len);
        tok = tok->next;
    }

    if (!equal(tok, "{")) {
        if (!tag_name)
            error_at(tok->loc, "expected enum tag or body");
        StructTag *tag = find_tag(tag_name);
        if (!tag)
            error_at(tok->loc, "unknown enum tag: %s", tag_name);
        if (tag->kind != TAG_ENUM)
            error_at(tok->loc, "enum %s conflicts with %s tag", tag_name,
                     tag_kind_name(tag->kind));
        *rest = tok;
        return ty_int;
    }

    if (tag_name) {
        StructTag *tag = find_tag_in_scope(current_scope, tag_name);
        if (tag) {
            if (tag->kind != TAG_ENUM)
                error_at(tok->loc, "enum %s conflicts with %s tag", tag_name,
                         tag_kind_name(tag->kind));
            error_at(tok->loc, "redefinition of enum %s", tag_name);
        }
        push_tag(tag_name, ty_int, TAG_ENUM);
    }

    tok = skip(tok, "{");
    int64_t val = 0;

    while (!equal(tok, "}")) {
        if (tok->kind != TK_IDENT)
            error_at(tok->loc, "expected enumerator name");

        char *name = strndup(tok->loc, tok->len);
        tok = tok->next;

        if (consume(&tok, tok, "=")) {
            Node *value = ternary(&tok, tok);
            val = eval_const_expr(value);
        }

        push_enum_const(name, val++);

        if (consume(&tok, tok, ","))
            continue;
        if (!equal(tok, "}"))
            error_at(tok->loc, "expected ',' or '}' in enum definition");
    }

    *rest = skip(tok, "}");
    return ty_int;
}

'''
s = s.replace(anchor, helpers + anchor, 1)

p.write_text(s)

make = Path("Makefile")
m = make.read_text()
needle = '\tbash ./test/enum_scope.sh\n'
if needle not in m:
    raise SystemExit("Makefile enum scope line not found")
if '\tbash ./test/enum_constexpr_tags.sh\n' not in m:
    m = m.replace(needle, needle + '\tbash ./test/enum_constexpr_tags.sh\n', 1)
make.write_text(m)

Path("test/enum_constexpr_tags.sh").write_text(r'''#!/bin/bash
set -e

assert_enum() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-enum-ce.c
  "${MINICC:-./minicc}" tmp-enum-ce.c > tmp-enum-ce.s
  gcc -o tmp-enum-ce tmp-enum-ce.s
  set +e
  ./tmp-enum-ce
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(enum constexpr/tag): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(enum constexpr/tag): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-enum-ce-reject.c
  if "${MINICC:-./minicc}" tmp-enum-ce-reject.c > /dev/null 2>&1; then
    echo "FAIL(enum constexpr/tag): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(enum constexpr/tag): rejected invalid input"
}

assert_enum 8 'enum { A = 1 << 3 }; int main() { return A; }'
assert_enum 13 'enum { A = 3, B = A * 4 + 1 }; int main() { return B; }'
assert_enum 18 'enum { A = 1 << 4, B = A | 3, C = B ^ 1 }; int main() { return C; }'
assert_enum 3 'enum { A = ~0, B = !A, C = !0 }; int main() { return (A == -1) + (B == 0) + (C == 1); }'
assert_enum 4 'enum { A = 3 < 4, B = 5 == 5, C = A && B, D = 0 || C }; int main() { return A+B+C+D; }'
assert_enum 7 'enum { A = 0 ? 3 : 7 }; int main() { return A; }'
assert_enum 15 'enum { A = (2 + 3) * (8 - 5) }; int main() { return A; }'
assert_enum 9 'enum { A = sizeof(long) + sizeof(char) }; int main() { return A; }'
assert_enum 1 'enum { A = (char)257 }; int main() { return A; }'
assert_enum 1 'enum { A = 0 && (1/0), B = 1 || (1/0) }; int main() { return A+B; }'
assert_enum 6 'enum Color { RED = 6 }; int main() { enum Color x = RED; return x; }'
assert_enum 6 'enum Kind { OUT = 3 }; int main() { enum Kind a=OUT; { enum Kind { IN=5 }; enum Kind b=IN; if (b!=5) return 99; } enum Kind c=OUT; return a+c; }'
assert_enum 4 'struct T { int x; }; int main() { { enum T { A=7 }; enum T x=A; if (x!=7) return 99; } struct T y; y.x=4; return y.x; }'
assert_reject 'struct Clash; enum Clash { A=1 }; int main() { return 0; }'
assert_reject 'struct Clash; union Clash; int main() { return 0; }'
assert_reject 'int main() { enum Missing x; return 0; }'
assert_reject 'int x; enum { A = x }; int main() { return A; }'
assert_reject 'int f() { return 3; } enum { A = f() }; int main() { return A; }'

echo "All enum constant-expression/tag tests passed!"
''')

readme = Path("README.md")
r = readme.read_text()
old_scope = '- **Scope**: lexical block-level scoping for variables, record tags, typedef names, and enumeration constants, including ordinary-identifier shadowing\n'
new_scope = '- **Scope**: lexical block-level scoping for variables, the shared `struct`/`union`/`enum` tag namespace, typedef names, and enumeration constants, including ordinary-identifier shadowing\n'
if old_scope not in r:
    raise SystemExit("README scope line not found")
r = r.replace(old_scope, new_scope, 1)
old_types = '- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, `enum`, `typedef`, `unsigned`\n'
new_types = '- **Types**: `char` (1B), `short` (2B), `int` (4B), `long` (8B), `float` (4B), `double` (8B), `void`, pointers, arrays, `struct`, `union`, tagged `enum`, `typedef`, `unsigned`; enumerators accept integer constant expressions\n'
if old_types not in r:
    raise SystemExit("README types line not found")
r = r.replace(old_types, new_types, 1)
readme.write_text(r)

print("enum constexpr/tag migration applied")
