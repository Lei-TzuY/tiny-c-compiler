from pathlib import Path

# Parse case/default as true labeled statements.  This preserves the statement
# following the label in the AST, which is required when labels occur below the
# top level of a switch body (inside if/loop/block/labeled statements).
p = Path('parse.c')
s = p.read_text()
old = '''        tok = skip(tok, ":");
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
new = '''        tok = skip(tok, ":");
        Node *node = new_node(ND_CASE);
        node->val = val;
        node->unique_label = new_unique_name();
        node->lhs = stmt(rest, tok);
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
        node->unique_label = new_unique_name();
        node->lhs = stmt(rest, tok);
        return node;
    }
'''
if s.count(old) != 1:
    raise SystemExit(f'parse case/default anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

# Codegen: recursively discover case/default labels belonging to this switch,
# skipping nested switches, and emit labels wherever their statement actually
# appears in the control-flow tree.
p = Path('codegen.c')
s = p.read_text()
anchor = '''static void gen_stmt(Node *node) {
'''
helper = '''static void emit_switch_dispatch(Node *node, Node **default_case) {
    if (!node)
        return;

    // A nested switch owns its own case/default labels.
    if (node->kind == ND_SWITCH)
        return;

    if (node->kind == ND_CASE) {
        printf("  movabs $%" PRId64 ", %%rdi\\n", node->val);
        printf("  cmp %%rdi, %%rax\\n");
        printf("  je %s\\n", node->unique_label);
        emit_switch_dispatch(node->lhs, default_case);
        return;
    }

    if (node->kind == ND_DEFAULT) {
        *default_case = node;
        emit_switch_dispatch(node->lhs, default_case);
        return;
    }

    if (node->kind == ND_BLOCK) {
        for (Node *n = node->body; n; n = n->next)
            emit_switch_dispatch(n, default_case);
        return;
    }

    if (node->kind == ND_IF) {
        emit_switch_dispatch(node->then, default_case);
        emit_switch_dispatch(node->els, default_case);
        return;
    }

    if (node->kind == ND_WHILE || node->kind == ND_DO || node->kind == ND_FOR) {
        emit_switch_dispatch(node->then, default_case);
        return;
    }

    if (node->kind == ND_LABEL) {
        emit_switch_dispatch(node->lhs, default_case);
        return;
    }
}

static void gen_stmt(Node *node) {
'''
if s.count(anchor) != 1:
    raise SystemExit(f'gen_stmt anchor count={s.count(anchor)}')
s = s.replace(anchor, helper, 1)

# Case/default labels are ordinary labeled statements during body emission.
anchor = '''    if (node->kind == ND_LABEL) {
        printf("%s:\\n", node->unique_label);
        gen_stmt(node->lhs);
        return;
    }

'''
replacement = anchor + '''    if (node->kind == ND_CASE || node->kind == ND_DEFAULT) {
        printf("%s:\\n", node->unique_label);
        if (node->lhs)
            gen_stmt(node->lhs);
        return;
    }

'''
if s.count(anchor) != 1:
    raise SystemExit(f'label codegen anchor count={s.count(anchor)}')
s = s.replace(anchor, replacement, 1)

old = '''    if (node->kind == ND_SWITCH) {
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
                printf("  movabs $%" PRId64 ", %%rdi\\n", n->val);
                printf("  cmp %%rdi, %%rax\\n");
                printf("  je .L.case.%d.%d\\n", c, case_idx++);
            } else if (n->kind == ND_DEFAULT) {
                has_default = true;
            }
        }
        if (has_default)
            printf("  jmp .L.default.%d\\n", c);
        else
            printf("  jmp .L.end.%d\\n", c);

        char brk_buf[32];
        sprintf(brk_buf, ".L.end.%d", c);
        char *old_brk = brk_label;
        brk_label = brk_buf;

        case_idx = 0;
        for (Node *n = node->then->body; n; n = n->next) {
            if (n->kind == ND_CASE)
                printf(".L.case.%d.%d:\\n", c, case_idx++);
            else if (n->kind == ND_DEFAULT)
                printf(".L.default.%d:\\n", c);
            else
                gen_stmt(n);
        }

        printf(".L.end.%d:\\n", c);
        brk_label = old_brk;
        return;
    }
'''
new = '''    if (node->kind == ND_SWITCH) {
        int c = count();
        gen_expr(node->cond);
        cast_value(node->cond->ty, node->ty);

        Node *default_case = NULL;
        emit_switch_dispatch(node->then, &default_case);
        if (default_case)
            printf("  jmp %s\\n", default_case->unique_label);
        else
            printf("  jmp .L.end.%d\\n", c);

        char brk_buf[32];
        sprintf(brk_buf, ".L.end.%d", c);
        char *old_brk = brk_label;
        brk_label = brk_buf;

        gen_stmt(node->then);

        printf(".L.end.%d:\\n", c);
        brk_label = old_brk;
        return;
    }
'''
if s.count(old) != 1:
    raise SystemExit(f'old switch codegen block count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

# Regression suite.
Path('test/nested_switch_labels.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-nested-switch.c
  ./minicc tmp-nested-switch.c > tmp-nested-switch.s
  cc -o tmp-nested-switch tmp-nested-switch.s
  set +e
  ./tmp-nested-switch
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "nested switch label failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(nested switch label): $actual"
}

# Labels may occur in nested compound statements.
assert_run 7 'int main(){int x=2;switch(x){{case 2:return 7;}default:return 1;}}'
assert_run 5 'int main(){int x=3;switch(x){{{case 3:return 5;}}}return 1;}'

# Dispatch to a case inside an if bypasses the if condition, as C labels do.
assert_run 9 'int main(){switch(1){if(0)case 1:return 9;return 2;}}'
assert_run 8 'int main(){switch(2){if(1)return 1;else case 2:return 8;}}'

# The same rule applies inside loop bodies: dispatch enters at the label.
assert_run 6 'int main(){switch(1){while(0){case 1:return 6;}return 2;}}'
assert_run 4 'int main(){switch(1){for(;0;){case 1:return 4;}return 2;}}'
assert_run 3 'int main(){switch(1){do{case 1:return 3;}while(0);return 2;}}'

# Consecutive case labels remain aliases for the same following statement.
assert_run 11 'int main(){switch(1){case 1:case 2:return 11;default:return 3;}}'
assert_run 11 'int main(){switch(2){case 1:case 2:return 11;default:return 3;}}'

# Generic labels can wrap case/default labeled statements.
assert_run 12 'int main(){switch(1){outer:case 1:return 12;default:return 2;}}'
assert_run 13 'int main(){switch(9){outer:default:return 13;case 1:return 2;}}'

# Nested switches own independent labels; the outer dispatch must not collect
# labels from the inner switch subtree.
assert_run 14 'int main(){int x=2;switch(x){case 1:switch(2){case 2:return 1;}case 2:return 14;default:return 3;}}'

# Fallthrough still follows source order after a nested label statement.
assert_run 7 'int main(){int y=0;switch(1){{case 1:y=3;}y+=4;break;default:y=9;}return y;}'

# A nested default is a valid dispatch target too.
assert_run 15 'int main(){switch(7){if(0){default:return 15;}case 1:return 2;}}'

echo 'All nested switch-label tests passed!'
''')

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/switch_constraints.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
p.write_text(s.replace(needle, needle + '\tbash ./test/nested_switch_labels.sh\n', 1))

p = Path('README.md')
s = p.read_text()
needle = '- **Control flow**: `if/else`, `while`, `for` (including init declarations), `do-while`, `switch/case/default`, `break`, `continue`, `return`, `goto`/labels\n'
replacement = '- **Control flow**: `if/else`, `while`, `for` (including init declarations), `do-while`, `switch/case/default` with integer-constant case semantics and nested labeled statements, `break`, `continue`, `return`, `goto`/labels\n'
if s.count(needle) != 1:
    raise SystemExit(f'README control-flow anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))
