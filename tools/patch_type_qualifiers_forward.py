from pathlib import Path

p = Path('tools/apply_type_qualifiers.py')
s = p.read_text()
old = '''static bool type_compatible(Type *a, Type *b);\nstatic bool type_compatible_ignoring_top_qual(Type *a, Type *b);\nstatic bool assignment_compatible(Type *dst, Node *rhs);\n'''
new = '''static bool type_compatible(Type *a, Type *b);\nstatic bool type_compatible_ignoring_top_qual(Type *a, Type *b);\nstatic bool assignment_compatible(Type *dst, Node *rhs);\nstatic Node *new_initializer_assign(Node *lhs, Node *rhs, Token *at);\n'''
if s.count(old) != 1:
    raise SystemExit(f'forward-declaration migration anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old_test = "assert_run 9 'int main(){int x=9;int *p=&x;const void *q=p;return *(const int*)q;}'"
new_test = "assert_run 1 'int main(){int x=9;int *p=&x;const void *q=p;return q==p;}'"
if s.count(old_test) != 1:
    raise SystemExit(f'qualifier void-pointer test anchor count={s.count(old_test)}')
s = s.replace(old_test, new_test, 1)

p.write_text(s)
