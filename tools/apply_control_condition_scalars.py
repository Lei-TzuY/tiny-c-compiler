from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    s = s.replace(old, new, 1)
    p.write_text(s)


replace_once(
    "parse.c",
    """static bool assignment_compatible(Type *dst, Node *rhs);\nstatic Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at);\n""",
    """static bool assignment_compatible(Type *dst, Node *rhs);\nstatic bool is_scalar_expr(Node *node);\nstatic Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at);\n""",
    "scalar expression forward declaration",
)

replace_once(
    "parse.c",
    """static bool is_label(Token *tok) {\n    if (tok->kind != TK_IDENT) return false;\n    if (equal(tok->next, \":\")) {\n        if (equal(tok, \"case\") || equal(tok, \"default\"))\n            return false;\n        return true;\n    }\n    return false;\n}\n\nstatic Node *stmt(Token **rest, Token *tok) {\n""",
    """static bool is_label(Token *tok) {\n    if (tok->kind != TK_IDENT) return false;\n    if (equal(tok->next, \":\")) {\n        if (equal(tok, \"case\") || equal(tok, \"default\"))\n            return false;\n        return true;\n    }\n    return false;\n}\n\nstatic void require_scalar_condition(Node *cond, Token *keyword,\n                                     const char *construct) {\n    if (!is_scalar_expr(cond))\n        error_at(keyword->loc, \"%s condition must have scalar type\", construct);\n}\n\nstatic Node *stmt(Token **rest, Token *tok) {\n""",
    "condition helper",
)

replace_once(
    "parse.c",
    """    if (equal(tok, \"do\")) {\n        Node *node = new_node(ND_DO);\n        current_loop_depth++;\n        node->then = stmt(&tok, tok->next);\n        current_loop_depth--;\n        tok = skip(tok, \"while\");\n        tok = skip(tok, \"(\");\n        node->cond = expr(&tok, tok);\n        tok = skip(tok, \")\");\n""",
    """    if (equal(tok, \"do\")) {\n        Token *do_tok = tok;\n        Node *node = new_node(ND_DO);\n        current_loop_depth++;\n        node->then = stmt(&tok, tok->next);\n        current_loop_depth--;\n        tok = skip(tok, \"while\");\n        tok = skip(tok, \"(\");\n        node->cond = expr(&tok, tok);\n        require_scalar_condition(node->cond, do_tok, \"do-while\");\n        tok = skip(tok, \")\");\n""",
    "do while scalar condition",
)

replace_once(
    "parse.c",
    """    if (equal(tok, \"if\")) {\n        Node *node = new_node(ND_IF);\n        tok = skip(tok->next, \"(\");\n        node->cond = expr(&tok, tok);\n        tok = skip(tok, \")\");\n""",
    """    if (equal(tok, \"if\")) {\n        Token *if_tok = tok;\n        Node *node = new_node(ND_IF);\n        tok = skip(tok->next, \"(\");\n        node->cond = expr(&tok, tok);\n        require_scalar_condition(node->cond, if_tok, \"if\");\n        tok = skip(tok, \")\");\n""",
    "if scalar condition",
)

replace_once(
    "parse.c",
    """    if (equal(tok, \"while\")) {\n        Node *node = new_node(ND_WHILE);\n        tok = skip(tok->next, \"(\");\n        node->cond = expr(&tok, tok);\n        tok = skip(tok, \")\");\n""",
    """    if (equal(tok, \"while\")) {\n        Token *while_tok = tok;\n        Node *node = new_node(ND_WHILE);\n        tok = skip(tok->next, \"(\");\n        node->cond = expr(&tok, tok);\n        require_scalar_condition(node->cond, while_tok, \"while\");\n        tok = skip(tok, \")\");\n""",
    "while scalar condition",
)

replace_once(
    "parse.c",
    """    if (equal(tok, \"for\")) {\n        Node *node = new_node(ND_FOR);\n        tok = skip(tok->next, \"(\");\n""",
    """    if (equal(tok, \"for\")) {\n        Token *for_tok = tok;\n        Node *node = new_node(ND_FOR);\n        tok = skip(tok->next, \"(\");\n""",
    "for condition keyword",
)

replace_once(
    "parse.c",
    """        if (!equal(tok, \";\"))\n            node->cond = expr(&tok, tok);\n        tok = skip(tok, \";\");\n""",
    """        if (!equal(tok, \";\")) {\n            node->cond = expr(&tok, tok);\n            require_scalar_condition(node->cond, for_tok, \"for\");\n        }\n        tok = skip(tok, \";\");\n""",
    "for scalar condition",
)

make = Path("Makefile")
s = make.read_text()
anchor = "\tbash ./test/control_flow_context.sh\n"
if anchor not in s:
    raise SystemExit("Makefile control_flow_context anchor missing")
s = s.replace(anchor, anchor + "\tbash ./test/control_condition_scalars.sh\n", 1)
make.write_text(s)

readme = Path("README.md")
s = readme.read_text()
old = "- **Control-flow constraints**: `break` is accepted only inside loops or `switch`, while `continue` is accepted only inside loops, including correctly nested loop/switch combinations"
new = "- **Control-flow constraints**: `if`, `while`, `do-while`, and non-empty `for` controlling expressions must have scalar type (with ordinary array/function designator decay); `break` is accepted only inside loops or `switch`, while `continue` is accepted only inside loops, including correctly nested loop/switch combinations"
if old not in s:
    raise SystemExit("README control-flow constraint anchor missing")
s = s.replace(old, new, 1)
readme.write_text(s)

Path("test/control_condition_scalars.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-cond.c
  ./minicc tmp-control-cond.c > tmp-control-cond.s
  cc -o tmp-control-cond tmp-control-cond.s
  set +e
  ./tmp-control-cond
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(control condition): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(control condition): $actual"
}

assert_reject_msg() {
  pattern="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-cond-reject.c
  if ./minicc tmp-control-cond-reject.c > /dev/null 2>tmp-control-cond.err; then
    echo "FAIL(control condition): expected rejection"
    echo "$input"
    exit 1
  fi
  if ! grep -q "$pattern" tmp-control-cond.err; then
    echo "FAIL(control condition): missing diagnostic '$pattern'"
    cat tmp-control-cond.err
    exit 1
  fi
  echo "OK(control condition): rejected with $pattern"
}

# Arithmetic, pointer, array, and function designators are valid scalar conditions.
assert_run 7 'int main(void){ int x=0; if(3) x=7; return x; }'
assert_run 5 'int main(void){ double x=0.25; if(x) return 5; return 1; }'
assert_run 6 'int main(void){ int x=1; int *p=&x; if(p) return 6; return 1; }'
assert_run 4 'int main(void){ int a[2]={1,2}; if(a) return 4; return 1; }'
assert_run 3 'int f(void){return 1;} int main(void){ if(f) return 3; return 1; }'
assert_run 4 'int main(void){ int x=0; int *p=&x; while(p){x=4;p=0;} return x; }'
assert_run 2 'int main(void){ double x=1.0; int n=0; do {n++;x=0.0;} while(x); return n+1; }'
assert_run 3 'int main(void){ int a[1]={1}; int n=0; for(;a && n<3;n++){} return n; }'
assert_run 4 'int main(void){ int n=0; for(;;){n=4;break;} return n; }'

# Records and void expressions are not scalar controlling expressions.
assert_reject_msg 'if condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; if(s) return 1; return 0;}'
assert_reject_msg 'if condition must have scalar type' 'union U{int x;double y;}; int main(void){union U u={1}; if(u) return 1; return 0;}'
assert_reject_msg 'if condition must have scalar type' 'int main(void){if((void)0) return 1; return 0;}'
assert_reject_msg 'while condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; while(s) break; return 0;}'
assert_reject_msg 'while condition must have scalar type' 'int main(void){while((void)0){} return 0;}'
assert_reject_msg 'do-while condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; do {} while(s); return 0;}'
assert_reject_msg 'for condition must have scalar type' 'struct S{int x;}; int main(void){struct S s={1}; for(;s;) break; return 0;}'
assert_reject_msg 'for condition must have scalar type' 'int main(void){for(;(void)0;){} return 0;}'

echo 'control-condition scalar tests passed'
''')
