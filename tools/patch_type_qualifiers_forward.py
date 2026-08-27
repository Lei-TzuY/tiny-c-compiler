from pathlib import Path

p = Path('tools/apply_type_qualifiers.py')
s = p.read_text()
old = '''static bool type_compatible(Type *a, Type *b);\nstatic bool type_compatible_ignoring_top_qual(Type *a, Type *b);\nstatic bool assignment_compatible(Type *dst, Node *rhs);\n'''
new = '''static bool type_compatible(Type *a, Type *b);\nstatic bool type_compatible_ignoring_top_qual(Type *a, Type *b);\nstatic bool assignment_compatible(Type *dst, Node *rhs);\nstatic Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at);\n'''
if s.count(old) != 1:
    raise SystemExit(f'forward-declaration migration anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))
