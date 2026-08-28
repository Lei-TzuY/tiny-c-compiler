from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "minicc.h",
    '''    ND_MEMBER,    // struct member (. and ->)\n    ND_COMMA,     // , (comma operator)\n    ND_GOTO,      // "goto"\n''',
    '''    ND_MEMBER,    // struct member (. and ->)\n    ND_COMMA,     // , (comma operator)\n    ND_COMPOUND_LITERAL, // (type-name){ initializer-list }\n    ND_GOTO,      // "goto"\n''',
    "compound literal node kind",
)

replace_once(
    "parse.c",
    '''    case ND_MEMBER:\n        return is_lvalue(node->lhs);\n    default:\n        return false;\n''',
    '''    case ND_MEMBER:\n        return is_lvalue(node->lhs);\n    case ND_COMPOUND_LITERAL:\n        return node->ty && node->ty->kind != TY_FUNC && node->ty->kind != TY_VOID;\n    default:\n        return false;\n''',
    "compound literal lvalue",
)

replace_once(
    "parse.c",
    '''    case ND_MEMBER: {\n        StaticAddress addr = eval_static_lvalue_address(node->lhs);\n        addr.addend += node->member->offset;\n        return addr;\n    }\n    default:\n        error("unsupported lvalue in static address initializer");\n''',
    '''    case ND_MEMBER: {\n        StaticAddress addr = eval_static_lvalue_address(node->lhs);\n        addr.addend += node->member->offset;\n        return addr;\n    }\n    case ND_COMPOUND_LITERAL:\n        if (!node->var || node->var->is_local || node->lhs)\n            error("automatic compound literal is not a static address constant");\n        return (StaticAddress){node->var->name, 0};\n    default:\n        error("unsupported lvalue in static address initializer");\n''',
    "static lvalue compound address",
)

replace_once(
    "parse.c",
    '''    case ND_ADDR:\n        return eval_static_lvalue_address(node->lhs);\n\n    case ND_ADD:\n''',
    '''    case ND_ADDR:\n        return eval_static_lvalue_address(node->lhs);\n\n    case ND_COMPOUND_LITERAL:\n        // An array compound literal at file scope undergoes the ordinary\n        // array-to-pointer conversion and denotes its anonymous static object.\n        if (!node->var || node->var->is_local || node->lhs ||\n            node->ty->kind != TY_ARRAY)\n            error("compound literal value is not a static address constant");\n        return (StaticAddress){node->var->name, 0};\n\n    case ND_ADD:\n''',
    "static array compound address",
)

helper = r'''static Node *compound_literal(Token **rest, Token *tok, Type *ty,
                              Token *type_tok) {
    if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC)
        error_at(type_tok->loc, "compound literal requires an object type");
    if (is_incomplete_object_type(ty))
        error_at(type_tok->loc,
                 "compound literal currently requires a complete object type");
    if (!equal(tok, "{"))
        error_at(tok->loc, "expected '{' after compound literal type name");

    Obj *var;
    Node *init_expr = NULL;

    if (current_return_ty) {
        var = create_lvar(new_unique_name());
        var->ty = ty;

        Node head = {};
        Node *tail = &head;
        Node *root = new_var_node(var);

        Token *after_string = NULL;
        Token *string_tok = string_initializer_token(tok, &after_string);
        if (string_tok && is_character_array(ty)) {
            append_automatic_string_array_initializer(&tail, root, ty, &tok, tok);
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            parse_automatic_aggregate_subobject(&tail, root, ty, &tok, tok,
                                                type_tok);
        } else {
            tok = skip(tok, "{");
            if (equal(tok, "}"))
                error_at(tok->loc, "scalar compound literal requires an initializer");
            Node *rhs = assign(&tok, tok);
            Node *assign_node = new_initializer_assign(root, rhs, type_tok);
            tail = tail->next = new_unary(ND_EXPR_STMT, assign_node);
            if (equal(tok, ","))
                tok = tok->next;
            if (!equal(tok, "}"))
                error_at(tok->loc, "excess elements in scalar compound literal");
            tok = tok->next;
        }

        for (Node *stmt = head.next; stmt; stmt = stmt->next) {
            if (stmt->kind != ND_EXPR_STMT || !stmt->lhs)
                error("invalid automatic compound literal initializer node");
            init_expr = init_expr ? new_binary(ND_COMMA, init_expr, stmt->lhs)
                                  : stmt->lhs;
        }
    } else {
        // File-scope compound literals have static storage duration. Keep the
        // anonymous object out of the ordinary identifier namespace but emit it
        // through the normal static-data path.
        var = calloc(1, sizeof(Obj));
        var->name = new_unique_name();
        var->ty = ty;
        var->is_local = false;
        var->is_static = true;
        var->next = globals;
        globals = var;

        Token *after_string = NULL;
        Token *string_tok = string_initializer_token(tok, &after_string);
        if (string_tok && is_character_array(ty)) {
            validate_string_array_initializer(ty, string_tok);
            var->init_data = build_string_array_image(ty, string_tok);
            tok = after_string;
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            Type *parsed = parse_static_image_initializer(var, &tok, tok, ty, 0);
            if (parsed != ty)
                error_at(type_tok->loc,
                         "compound literal array bound inference is not yet supported");
        } else {
            tok = skip(tok, "{");
            if (equal(tok, "}"))
                error_at(tok->loc, "scalar compound literal requires an initializer");
            parse_static_scalar_initializer(var, &tok, tok, ty);
            if (equal(tok, ","))
                tok = tok->next;
            if (!equal(tok, "}"))
                error_at(tok->loc, "excess elements in scalar compound literal");
            tok = tok->next;
        }
    }

    Node *node = new_node(ND_COMPOUND_LITERAL);
    node->var = var;
    node->lhs = init_expr;
    node->ty = ty;
    *rest = tok;
    return node;
}

'''
replace_once(
    "parse.c",
    '''static Node *unary(Token **rest, Token *tok) {\n''',
    helper + '''static Node *unary(Token **rest, Token *tok) {\n''',
    "compound literal parser helper",
)

replace_once(
    "parse.c",
    '''        tok = tok->next;\n        Type *ty = type_name(&tok, tok);\n        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||\n            (ty->kind != TY_VOID && !is_numeric(ty) && ty->kind != TY_PTR))\n            error_at(cast_tok->loc, "cast specifies non-scalar type");\n        tok = skip(tok, ")");\n        Node *operand = unary(rest, tok);\n''',
    '''        tok = tok->next;\n        Type *ty = type_name(&tok, tok);\n        tok = skip(tok, ")");\n        if (equal(tok, "{"))\n            return postfix(rest, cast_tok);\n        if (ty->kind == TY_ARRAY || ty->kind == TY_FUNC ||\n            (ty->kind != TY_VOID && !is_numeric(ty) && ty->kind != TY_PTR))\n            error_at(cast_tok->loc, "cast specifies non-scalar type");\n        Node *operand = unary(rest, tok);\n''',
    "cast versus compound literal disambiguation",
)

replace_once(
    "parse.c",
    '''static Node *postfix(Token **rest, Token *tok) {\n    Node *node = primary(&tok, tok);\n\n    for (;;) {\n''',
    '''static Node *postfix(Token **rest, Token *tok) {\n    Node *node;\n    if (equal(tok, "(") && is_typename(tok->next)) {\n        Token *type_tok = tok;\n        Token *cur = tok->next;\n        Type *ty = type_name(&cur, cur);\n        cur = skip(cur, ")");\n        if (!equal(cur, "{"))\n            error_at(type_tok->loc, "expected compound literal initializer");\n        node = compound_literal(&tok, cur, ty, type_tok);\n    } else {\n        node = primary(&tok, tok);\n    }\n\n    for (;;) {\n''',
    "compound literal postfix primary",
)

replace_once(
    "codegen.c",
    '''static void gen_addr(Node *node) {\n    if (node->kind == ND_VAR) {\n''',
    '''static void gen_addr(Node *node) {\n    if (node->kind == ND_COMPOUND_LITERAL) {\n        if (node->lhs)\n            gen_expr(node->lhs);\n        if (!node->var)\n            error("compound literal missing backing object");\n        if (node->var->is_local)\n            printf("  lea %d(%%rbp), %%rax\\n", node->var->offset);\n        else\n            printf("  lea %s(%%rip), %%rax\\n", node->var->name);\n        return;\n    }\n    if (node->kind == ND_VAR) {\n''',
    "compound literal address generation",
)

replace_once(
    "codegen.c",
    '''    if (node->kind == ND_VAR) {\n        gen_addr(node);\n        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_STRUCT &&\n            node->ty->kind != TY_FUNC)\n            load(node->ty);\n        return;\n    }\n\n    if (node->kind == ND_ADDR) {\n''',
    '''    if (node->kind == ND_VAR || node->kind == ND_COMPOUND_LITERAL) {\n        gen_addr(node);\n        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_STRUCT &&\n            node->ty->kind != TY_FUNC)\n            load(node->ty);\n        return;\n    }\n\n    if (node->kind == ND_ADDR) {\n''',
    "compound literal expression generation",
)

replace_once(
    "Makefile",
    '''\tbash ./test/constant_expressions.sh\n\tbash ./test/static_integer_initializers.sh\n''',
    '''\tbash ./test/constant_expressions.sh\n\tbash ./test/compound_literals.sh\n\tbash ./test/static_integer_initializers.sh\n''',
    "compound literal test target",
)

replace_once(
    "README.md",
    '''- Static/global integer scalar and array initializers accept type-aware integer constant expressions, including enum constants, casts, shifts, short-circuit logic, and ternary expressions. Signed integer constant-expression arithmetic diagnoses overflow and invalid signed left shifts instead of wrapping, while unsigned arithmetic retains modulo semantics.\n''',
    '''- Static/global integer scalar and array initializers accept type-aware integer constant expressions, including enum constants, casts, shifts, short-circuit logic, and ternary expressions. Signed integer constant-expression arithmetic diagnoses overflow and invalid signed left shifts instead of wrapping, while unsigned arithmetic retains modulo semantics.\n\n- C99 compound literals are supported for complete object types. Block-scope literals use anonymous automatic objects and remain modifiable lvalues (subject to qualifiers), while file-scope literals use anonymous static storage; scalar, fixed-size array, struct/union, nested, designated, string-array, address-taking, member/index, and by-value record uses share the ordinary initializer and ABI machinery. Unknown-bound array compound literals are diagnosed until reusable bound-inference support is added.\n''',
    "README compound literals",
)

Path("test/compound_literals.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-compound.c
  ./minicc tmp-compound.c > tmp-compound.s
  cc -o tmp-compound tmp-compound.s
  set +e
  ./tmp-compound
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "compound literal test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(compound literal): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-compound.c
  if ./minicc tmp-compound.c > tmp-compound.s 2>/dev/null; then
    echo "compound literal test unexpectedly accepted invalid input"
    echo "$input"
    exit 1
  fi
  echo "OK(compound literal): rejected invalid input"
}

# Scalar literals are genuine modifiable lvalues with automatic storage.
assert_run 3 'int main(){return (int){3};}'
assert_run 7 'int main(){return ((int){3}=7);}'
assert_run 9 'int main(){int *p=&(int){4}; *p=9; return *p;}'
assert_run 12 'int main(){int i=1; int *p=&(int){i++}; return *p*10+i;}'
assert_run 4 'int main(){return sizeof((int){9});}'

# Aggregate, designated, nested, union, string-array and postfix uses.
assert_run 5 'struct S{int x;int y;}; int main(){return (struct S){1,5}.y;}'
assert_run 9 'struct S{int x;int y;}; int main(){struct S *p=&(struct S){.y=7,.x=2}; return p->x+p->y;}'
assert_run 6 'struct S{int x;}; int main(){return ((struct S){.x=1}.x=6);}'
assert_run 2 'int main(){return (int[3]){1,2,3}[1];}'
assert_run 7 'int main(){return (int[4]){[2]=7}[2];}'
assert_run 8 'struct R{int a[2];}; int main(){return (struct R){.a={3,8}}.a[1];}'
assert_run 11 'union U{int x;long y;}; int main(){return (union U){.x=11}.x;}'
assert_run 98 'int main(){return (char[4]){"abc"}[1];}'
assert_run 13 'struct P{int *p;}; int main(){int x=13; return *(struct P){.p=&x}.p;}'

# Compound literal record values participate in the existing SysV ABI.
assert_run 7 'struct S{int x;int y;}; int sum(struct S s){return s.x+s.y;} int main(){return sum((struct S){3,4});}'
assert_run 6 'struct S{int x;}; struct S id(struct S s){return s;} int main(){return id((struct S){6}).x;}'

# File-scope literals have anonymous static storage and are address constants.
assert_run 7 'int *p=&(int){7}; int main(){return *p;}'
assert_run 6 'struct S{int x;}; struct S *p=&(struct S){.x=6}; int main(){return p->x;}'
assert_run 6 'int *p=(int[3]){2,4,6}; int main(){return p[2];}'
assert_run 99 'char *p=(char[4]){"abc"}; int main(){return p[2];}'

# Qualifiers and invalid forms keep ordinary C lvalue/constant rules.
assert_reject 'int main(){(const int){3}=4; return 0;}'
assert_reject 'int main(){int x=1; return *(&(0,x));}'
assert_reject 'int main(){return (void){0};}'
assert_reject 'struct S; int main(){return ((struct S){0},0);}'
assert_reject 'int main(){return (int[]){1,2}[0];}'
assert_reject 'int main(){return (int){1,2};}'
assert_reject 'int x=(int){3}; int main(){return x;}'
assert_reject 'int main(){static int *p=&(int){5}; return *p;}'

echo 'All compound literal tests passed!'
''')
