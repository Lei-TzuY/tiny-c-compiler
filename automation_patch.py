from pathlib import Path

p = Path('type.c')
s = p.read_text()
old = """        if ((is_numeric(node->lhs->ty) && is_numeric(node->rhs->ty)) ||
            (is_object_pointer_operand(node->lhs->ty) &&
             is_object_pointer_operand(node->rhs->ty))) {
"""
new = """        if ((is_numeric(node->lhs->ty) && is_numeric(node->rhs->ty)) ||
            (is_object_pointer_operand(node->lhs->ty) &&
             is_object_pointer_operand(node->rhs->ty) &&
             pointer_equality_compatible(node->lhs->ty, node->rhs->ty))) {
"""
if old not in s:
    raise SystemExit('type.c relational comparison block did not match expected main')
p.write_text(s.replace(old, new, 1))

p = Path('test/comparison_scalar.sh')
s = p.read_text()
old = """  if ((p != 0) != 1) return 10;
  return 0;
"""
new = """  if ((p != 0) != 1) return 10;
  const int *cp = &a[1];
  if ((&a[0] < cp) != 1) return 11;
  return 0;
"""
if old not in s:
    raise SystemExit('comparison runtime block did not match expected main')
s = s.replace(old, new, 1)
old = """  'int f(void){return 0;} int main(void){int (*p)(void)=f; return p<=p;}' \\
  'int main(void){void *p=0; void *q=0; return p<q;}'
"""
new = """  'int f(void){return 0;} int main(void){int (*p)(void)=f; return p<=p;}' \\
  'int main(void){void *p=0; void *q=0; return p<q;}' \\
  'int main(void){int x=0; double y=0; return &x<&y;}' \\
  'int main(void){struct A{int x;} a; struct B{int x;} b; return &a<=&b;}' \\
  'int main(void){int x=0; int *p=&x; const int *cp=&x; int **pp=&p; const int **cpp=&cp; return pp<cpp;}'
"""
if old not in s:
    raise SystemExit('comparison rejection block did not match expected main')
p.write_text(s.replace(old, new, 1))
