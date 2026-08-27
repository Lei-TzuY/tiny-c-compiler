from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = '''static Type *current_return_ty;\n'''
insert = r'''static Type *current_return_ty;

typedef struct CaseValue CaseValue;
struct CaseValue {
    int64_t val;
    CaseValue *next;
};

typedef struct SwitchContext SwitchContext;
struct SwitchContext {
    Type *ty;
    CaseValue *cases;
    bool has_default;
    SwitchContext *prev;
};

static SwitchContext *current_switch;
'''
if s.count(anchor) != 1:
    raise SystemExit(f'current_return_ty anchor count={s.count(anchor)}')
s = s.replace(anchor, insert, 1)

old = r'''    if (equal(tok, "switch")) {
        Node *node = new_node(ND_SWITCH);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        tok = skip(tok, ")");
        node->then = stmt(rest, tok);
        return node;
    }

    if (equal(tok, "case")) {
        if (tok->next->kind != TK_NUM)
            error_at(tok->next->loc, "expected integer constant after 'case'");
        Node *node = new_node(ND_CASE);
        node->val = tok->next->val;
        tok = skip(tok->next->next, ":");
        *rest = tok;
        return node;
    }

    if (equal(tok, "default")) {
        tok = skip(tok->next, ":");
        Node *node = new_node(ND_DEFAULT);
        *rest = tok;
        return node;
    }
'''
new = r'''    if (equal(tok, "switch")) {
        Token *switch_tok = tok;
        Node *node = new_node(ND_SWITCH);
        tok = skip(tok->next, "(");
        node->cond = expr(&tok, tok);
        add_type(node->cond);
        if (!is_integer(node->cond->ty))
            error_at(switch_tok->loc, "switch condition must have integer type");

        // The controlling expression undergoes integer promotion.  Using int
        // as the second operand requests exactly that promotion for the small
        // integer types supported by this LP64 target.
        node->ty = get_common_type(node->cond->ty, ty_int);
        tok = skip(tok, ")");

        SwitchContext ctx = {};
        ctx.ty = node->ty;
        ctx.prev = current_switch;
        current_switch = &ctx;
        node->then = stmt(rest, tok);
        current_switch = ctx.prev;
        return node;
    }

    if (equal(tok, "case")) {
        Token *case_tok = tok;
        if (!current_switch)
            error_at(case_tok->loc, "case label is not within a switch statement");

        Node *value = ternary(&tok, tok->next);
        add_type(value);
        if (!is_integer(value->ty))
            error_at(case_tok->loc, "case label does not reduce to an integer constant expression");

        int64_t val = eval_const_expr(value);
        val = cast_const_integer(val, current_switch->ty);

        for (CaseValue *cv = current_switch->cases; cv; cv = cv->next)
            if (cv->val == val)
                error_at(case_tok->loc, "duplicate case value");

        CaseValue *cv = calloc(1, sizeof(CaseValue));
        cv->val = val;
        cv->next = current_switch->cases;
        current_switch->cases = cv;

        tok = skip(tok, ":");
        Node *node = new_node(ND_CASE);
        node->val = val;
        *rest = tok;
        return node;
    }

    if (equal(tok, "default")) {
        Token *default_tok = tok;
        if (!current_switch)
            error_at(default_tok->loc, "default label is not within a switch statement");
        if (current_switch->has_default)
            error_at(default_tok->loc, "multiple default labels in one switch");
        current_switch->has_default = true;

        tok = skip(tok->next, ":");
        Node *node = new_node(ND_DEFAULT);
        *rest = tok;
        return node;
    }
'''
if s.count(old) != 1:
    raise SystemExit(f'switch/case block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('codegen.c')
s = p.read_text()
old = r'''    if (node->kind == ND_SWITCH) {
        int c = count();
        gen_expr(node->cond);

        bool has_default = false;
        int case_idx = 0;
        for (Node *n = node->then->body; n; n = n->next) {
            if (n->kind == ND_CASE) {
                printf("  cmp $%" PRId64 ", %%rax\n", n->val);
                printf("  je .L.case.%d.%d\n", c, case_idx++);
            } else if (n->kind == ND_DEFAULT) {
                has_default = true;
            }
        }
'''
new = r'''    if (node->kind == ND_SWITCH) {
        int c = count();
        gen_expr(node->cond);
        cast_value(node->cond->ty, node->ty);

        bool has_default = false;
        int case_idx = 0;
        for (Node *n = node->then->body; n; n = n->next) {
            if (n->kind == ND_CASE) {
                // Materialize the normalized case value in a full register.
                // This avoids x86-64 cmp-immediate sign-extension changing the
                // meaning of values such as UINT_MAX.
                printf("  movabs $%" PRId64 ", %%rdi\n", n->val);
                printf("  cmp %%rdi, %%rax\n");
                printf("  je .L.case.%d.%d\n", c, case_idx++);
            } else if (n->kind == ND_DEFAULT) {
                has_default = true;
            }
        }
'''
if s.count(old) != 1:
    raise SystemExit(f'codegen switch anchor count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('Makefile')
s = p.read_text()
anchor = '\tbash ./test/cast_constraints.sh\n'
if s.count(anchor) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(anchor)}')
s = s.replace(anchor, anchor + '\tbash ./test/switch_constraints.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
old = '- **Control flow**: `if/else`, `while`, `for` (including init declarations), `do-while`, `switch/case/default`, `break`, `continue`, `return`, `goto`/labels\n'
new = '- **Control flow**: `if/else`, `while`, `for` (including init declarations), `do-while`, `switch/case/default` with integer controlling expressions, integer-constant-expression cases, promoted case-value normalization, and duplicate case/default diagnostics, `break`, `continue`, `return`, `goto`/labels\n'
if s.count(old) != 1:
    raise SystemExit(f'README control-flow anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

Path('test/switch_constraints.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-switch.c
  ./minicc tmp-switch.c > tmp-switch.s
  cc -o tmp-switch tmp-switch.s
  set +e
  ./tmp-switch
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "switch constraint failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(switch constraint): $actual"
}

assert_fail() {
  input="$1"
  printf "%s\n" "$input" > tmp-switch-bad.c
  if ./minicc tmp-switch-bad.c > tmp-switch-bad.s 2>/dev/null; then
    echo "switch constraint unexpectedly accepted invalid program"
    echo "$input"
    exit 1
  fi
  echo "OK(switch constraint): rejected invalid program"
}

# Controlling expressions are integer-promoted and case labels accept the
# compiler's full integer constant-expression grammar rather than one token.
assert_run 7 'int main(){int x=3;switch(x){case 1+2:return 7;default:return 0;}}'
assert_run 8 'enum E{A=4};int main(){switch(4){case A:return 8;default:return 0;}}'
assert_run 9 'int main(){switch(5){case 1?5:6:return 9;default:return 0;}}'
assert_run 10 'int main(){switch(1){case (unsigned char)257:return 10;default:return 0;}}'
assert_run 11 'int main(){unsigned short x=65535;switch(x){case 65535:return 11;default:return 0;}}'

# Case values are converted to the promoted controlling type.  In particular,
# -1 must match UINT_MAX for an unsigned-int switch without cmp-immediate
# sign-extension corrupting the machine comparison.
assert_run 12 'int main(){unsigned int x=(unsigned int)-1;switch(x){case -1:return 12;default:return 0;}}'

# Nested switches maintain independent case/default namespaces.
assert_run 13 'int main(){int x=1;switch(x){case 1:switch(x){case 1:return 13;default:return 0;}default:return 0;}}'

# The controlling expression must have integer type.
assert_fail 'int main(){switch(1.5){case 1:return 0;}return 0;}'
assert_fail 'int main(){int x;int *p=&x;switch(p){case 0:return 0;}return 0;}'

# case/default labels are only valid while parsing a switch statement.
assert_fail 'int main(){case 1:return 0;}'
assert_fail 'int main(){default:return 0;}'

# case labels must be integer constant expressions.
assert_fail 'int main(){int x=1;switch(x){case x:return 0;}return 0;}'
assert_fail 'int main(){switch(1){case 1.5:return 0;}return 0;}'

# Duplicate values are diagnosed after constant folding and conversion to the
# promoted switch type.  A switch may contain at most one default label.
assert_fail 'int main(){switch(2){case 2:return 1;case 2:return 2;}return 0;}'
assert_fail 'int main(){switch(2){case 1+1:return 1;case 2:return 2;}return 0;}'
assert_fail 'int main(){unsigned int x=0;switch(x){case -1:return 1;case (unsigned int)-1:return 2;}return 0;}'
assert_fail 'int main(){switch(0){default:return 1;default:return 2;}}'

echo 'All switch-constraint tests passed!'
''')
