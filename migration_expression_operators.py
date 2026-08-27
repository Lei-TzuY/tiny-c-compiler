from pathlib import Path

p = Path('parse.c')
s = p.read_text()

# Add shared operator semantic helpers after assignment compatibility.
anchor = '''static Node *new_checked_assign(Node *lhs, Node *rhs, Token *op) {
    add_type(lhs);
    if (!assignment_compatible(lhs->ty, rhs))
        error_at(op->loc, "incompatible types in assignment");
    return new_binary(ND_ASSIGN, lhs, rhs);
}

'''
assert s.count(anchor) == 1
helpers = anchor + r'''static Type *decay_value_type(Type *ty) {
    if (!ty)
        return NULL;
    if (ty->kind == TY_ARRAY)
        return pointer_to(ty->base);
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    return ty;
}

static bool is_scalar_expr(Node *node) {
    add_type(node);
    Type *ty = decay_value_type(node->ty);
    return ty && (is_numeric(ty) || ty->kind == TY_PTR);
}

static bool pointer_pair_compatible(Type *a, Type *b, bool relational_only) {
    a = decay_value_type(a);
    b = decay_value_type(b);
    if (!a || !b || a->kind != TY_PTR || b->kind != TY_PTR)
        return false;

    if (type_compatible(a->base, b->base)) {
        if (!relational_only)
            return true;
        return a->base && a->base->kind != TY_VOID && a->base->kind != TY_FUNC;
    }

    if (relational_only)
        return false;

    bool a_void = a->base && a->base->kind == TY_VOID;
    bool b_void = b->base && b->base->kind == TY_VOID;
    bool a_func = a->base && a->base->kind == TY_FUNC;
    bool b_func = b->base && b->base->kind == TY_FUNC;
    return !a_func && !b_func && (a_void || b_void);
}

static bool equality_operands_compatible(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);

    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return true;

    Type *lt = decay_value_type(lhs->ty);
    Type *rt = decay_value_type(rhs->ty);
    bool lp = lt && lt->kind == TY_PTR;
    bool rp = rt && rt->kind == TY_PTR;

    if (lp && is_null_pointer_constant(rhs))
        return true;
    if (rp && is_null_pointer_constant(lhs))
        return true;
    return lp && rp && pointer_pair_compatible(lt, rt, false);
}

static bool relational_operands_compatible(Node *lhs, Node *rhs) {
    add_type(lhs);
    add_type(rhs);
    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))
        return true;
    return pointer_pair_compatible(lhs->ty, rhs->ty, true);
}

static Type *conditional_result_type(Node *then, Node *els, Token *question) {
    add_type(then);
    add_type(els);

    if (is_numeric(then->ty) && is_numeric(els->ty))
        return get_common_type(then->ty, els->ty);

    if (then->ty->kind == TY_VOID && els->ty->kind == TY_VOID)
        return ty_void;

    if (then->ty->kind == TY_STRUCT && els->ty->kind == TY_STRUCT &&
        type_compatible(then->ty, els->ty))
        return then->ty;

    Type *tt = decay_value_type(then->ty);
    Type *et = decay_value_type(els->ty);
    bool tp = tt && tt->kind == TY_PTR;
    bool ep = et && et->kind == TY_PTR;

    if (tp && is_null_pointer_constant(els))
        return tt;
    if (ep && is_null_pointer_constant(then))
        return et;

    if (tp && ep) {
        if (type_compatible(tt->base, et->base))
            return tt;

        bool t_void = tt->base && tt->base->kind == TY_VOID;
        bool e_void = et->base && et->base->kind == TY_VOID;
        bool t_func = tt->base && tt->base->kind == TY_FUNC;
        bool e_func = et->base && et->base->kind == TY_FUNC;
        if (!t_func && !e_func && (t_void || e_void))
            return pointer_to(ty_void);
    }

    error_at(question->loc, "incompatible conditional operands");
}

'''
s = s.replace(anchor, helpers, 1)

# Conditional operator: scalar condition plus a real composite result type.
old = '''static Node *ternary(Token **rest, Token *tok) {
    Node *cond = logor(&tok, tok);
    if (!equal(tok, "?")) {
        *rest = tok;
        return cond;
    }
    Node *node = new_node(ND_TERNARY);
    node->cond = cond;
    tok = tok->next;
    node->then = expr(&tok, tok);
    tok = skip(tok, ":");
    node->els = ternary(rest, tok);
    return node;
}
'''
new = '''static Node *ternary(Token **rest, Token *tok) {
    Node *cond = logor(&tok, tok);
    if (!equal(tok, "?")) {
        *rest = tok;
        return cond;
    }

    Token *question = tok;
    if (!is_scalar_expr(cond))
        error_at(question->loc, "conditional expression requires scalar condition");

    Node *node = new_node(ND_TERNARY);
    node->cond = cond;
    tok = tok->next;
    node->then = expr(&tok, tok);
    tok = skip(tok, ":");
    node->els = ternary(rest, tok);
    node->ty = conditional_result_type(node->then, node->els, question);
    return node;
}
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

old = '''static Node *logor(Token **rest, Token *tok) {
    Node *node = logand(&tok, tok);
    while (equal(tok, "||"))
        node = new_binary(ND_LOGOR, node, logand(&tok, tok->next));
    *rest = tok;
    return node;
}

static Node *logand(Token **rest, Token *tok) {
    Node *node = bitor_expr(&tok, tok);
    while (equal(tok, "&&"))
        node = new_binary(ND_LOGAND, node, bitor_expr(&tok, tok->next));
    *rest = tok;
    return node;
}
'''
new = '''static Node *logor(Token **rest, Token *tok) {
    Node *node = logand(&tok, tok);
    while (equal(tok, "||")) {
        Token *op = tok;
        Node *rhs = logand(&tok, tok->next);
        if (!is_scalar_expr(node) || !is_scalar_expr(rhs))
            error_at(op->loc, "logical operator requires scalar operands");
        node = new_binary(ND_LOGOR, node, rhs);
    }
    *rest = tok;
    return node;
}

static Node *logand(Token **rest, Token *tok) {
    Node *node = bitor_expr(&tok, tok);
    while (equal(tok, "&&")) {
        Token *op = tok;
        Node *rhs = bitor_expr(&tok, tok->next);
        if (!is_scalar_expr(node) || !is_scalar_expr(rhs))
            error_at(op->loc, "logical operator requires scalar operands");
        node = new_binary(ND_LOGAND, node, rhs);
    }
    *rest = tok;
    return node;
}
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

old = '''static Node *equality(Token **rest, Token *tok) {
    Node *node = relational(&tok, tok);
    for (;;) {
        if (equal(tok, "==")) { node = new_binary(ND_EQ, node, relational(&tok, tok->next)); continue; }
        if (equal(tok, "!=")) { node = new_binary(ND_NE, node, relational(&tok, tok->next)); continue; }
        *rest = tok;
        return node;
    }
}
'''
new = '''static Node *equality(Token **rest, Token *tok) {
    Node *node = relational(&tok, tok);
    for (;;) {
        if (equal(tok, "==") || equal(tok, "!=")) {
            Token *op = tok;
            NodeKind kind = equal(tok, "==") ? ND_EQ : ND_NE;
            Node *rhs = relational(&tok, tok->next);
            if (!equality_operands_compatible(node, rhs))
                error_at(op->loc, "invalid equality operands");
            node = new_binary(kind, node, rhs);
            continue;
        }
        *rest = tok;
        return node;
    }
}
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

old = '''static Node *relational(Token **rest, Token *tok) {
    Node *node = shift(&tok, tok);
    for (;;) {
        if (equal(tok, "<"))  { node = new_binary(ND_LT, node, shift(&tok, tok->next)); continue; }
        if (equal(tok, "<=")) { node = new_binary(ND_LE, node, shift(&tok, tok->next)); continue; }
        if (equal(tok, ">"))  { node = new_binary(ND_LT, shift(&tok, tok->next), node); continue; }
        if (equal(tok, ">=")) { node = new_binary(ND_LE, shift(&tok, tok->next), node); continue; }
        *rest = tok;
        return node;
    }
}
'''
new = '''static Node *relational(Token **rest, Token *tok) {
    Node *node = shift(&tok, tok);
    for (;;) {
        if (equal(tok, "<") || equal(tok, "<=") ||
            equal(tok, ">") || equal(tok, ">=")) {
            Token *op = tok;
            bool reverse = equal(tok, ">") || equal(tok, ">=");
            bool inclusive = equal(tok, "<=") || equal(tok, ">=");
            Node *rhs = shift(&tok, tok->next);
            if (!relational_operands_compatible(node, rhs))
                error_at(op->loc, "invalid relational operands");
            node = reverse ? new_binary(inclusive ? ND_LE : ND_LT, rhs, node)
                           : new_binary(inclusive ? ND_LE : ND_LT, node, rhs);
            continue;
        }
        *rest = tok;
        return node;
    }
}
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

old = '''    if (equal(tok, "!"))  return new_unary(ND_NOT, unary(rest, tok->next));
'''
new = '''    if (equal(tok, "!")) {
        Token *op = tok;
        Node *operand = unary(rest, tok->next);
        if (!is_scalar_expr(operand))
            error_at(op->loc, "logical not requires scalar operand");
        return new_unary(ND_NOT, operand);
    }
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)
p.write_text(s)

# Ternary branches must be normalized to the selected common type, especially
# for mixed integer/floating branches.
c = Path('codegen.c')
cs = c.read_text()
old = '''        gen_expr(node->then);
        printf("  jmp .L.end.%d\\n", c);
        printf(".L.else.%d:\\n", c);
        gen_expr(node->els);
        printf(".L.end.%d:\\n", c);
'''
new = '''        gen_expr(node->then);
        cast_value(node->then->ty, node->ty);
        printf("  jmp .L.end.%d\\n", c);
        printf(".L.else.%d:\\n", c);
        gen_expr(node->els);
        cast_value(node->els->ty, node->ty);
        printf(".L.end.%d:\\n", c);
'''
assert cs.count(old) == 1
c.write_text(cs.replace(old, new, 1))

# Focused regression suite.
t = Path('test/expression_operators.sh')
t.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-exprop.c
  ./minicc tmp-exprop.c > tmp-exprop.s
  cc -o tmp-exprop tmp-exprop.s
  set +e
  ./tmp-exprop
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "expression operator failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(expression operator): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-exprop-bad.c
  if ./minicc tmp-exprop-bad.c > tmp-exprop-bad.s 2>/dev/null; then
    echo "expression operator unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(expression operator): rejected invalid program"
}

# Equality: arithmetic, compatible pointers, void*, null and function pointers.
assert_run 1 'int main(){int x=1;int *p=&x;return p==&x;}'
assert_run 1 'int main(){int x;int *p=&x;return p!=0;}'
assert_run 1 'int main(){int x;int *p=&x;void *v=p;return v==p;}'
assert_run 1 'int f(){return 1;} int main(){int (*p)()=f;return p==f;}'
assert_run 1 'int main(){double x=1.0;return x==1;}'

# Relational and logical operators require compatible scalar operands.
assert_run 1 'int main(){int a[2];return &a[0] < &a[1];}'
assert_run 1 'int main(){int x=1;int *p=&x;return p && 1;}'
assert_run 1 'int f(){return 1;} int main(){return f && 1;}'
assert_run 1 'int main(){int *p=0;return !p;}'

# Conditional operator computes a composite type and normalizes both branches.
assert_run 7 'int main(){int x=7;int *p=1 ? &x : 0;return *p;}'
assert_run 8 'int main(){int x=8;int *p=0 ? 0 : &x;return *p;}'
assert_run 3 'int main(){double x=1 ? 3 : 4.5;return (int)x;}'
assert_run 4 'int main(){double x=0 ? 3 : 4.5;return (int)x;}'
assert_run 6 'struct S{int x;}; int main(){struct S a;struct S b;struct S c;a.x=6;b.x=9;c=1?a:b;return c.x;}'
assert_run 5 'int f(int x){return x;} int g(int x){return x+1;} int main(){int (*p)(int)=1?f:g;return p(5);}'

# Invalid equality/relational operands.
assert_fail 'struct S{int x;}; int main(){struct S s;return s==s;}'
assert_fail 'int main(){int *p;double *q;return p==q;}'
assert_fail 'int main(){int *p;return p==1;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){return f==g;}'
assert_fail 'int main(){int *p;double *q;return p<q;}'
assert_fail 'int main(){int *p;return p<0;}'

# Structs are not scalar logical conditions/operands.
assert_fail 'struct S{int x;}; int main(){struct S s;return s&&1;}'
assert_fail 'struct S{int x;}; int main(){struct S s;return !s;}'
assert_fail 'struct S{int x;}; int main(){struct S s;return s?1:2;}'

# Conditional alternatives must have a valid common type.
assert_fail 'int main(){int x;double y;int *p=&x;double *q=&y;return (p?q:p)!=0;}'
assert_fail 'struct A{int x;};struct B{int x;};int main(){struct A a;struct B b;return (1?a:b).x;}'
assert_fail 'int f(int x){return x;} double g(double x){return x;} int main(){return (1?f:g)!=0;}'
assert_fail 'int main(){int *p;return (1?p:3)!=0;}'

echo 'All expression-operator semantic tests passed!'
''')

m = Path('Makefile')
ms = m.read_text()
anchor = '\tbash ./test/semantic_assignments.sh\n'
assert ms.count(anchor) == 1
m.write_text(ms.replace(anchor, anchor + '\tbash ./test/expression_operators.sh\n', 1))

r = Path('README.md')
rs = r.read_text()
anchor = 'and expression-level assignment/return/argument compatibility checking for numeric, pointer, function-pointer, `void *`, null-pointer, and record values'
assert rs.count(anchor) == 1
r.write_text(rs.replace(anchor, anchor + ', with typed equality/relational/logical/conditional operators and conditional-result normalization', 1))
