from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(s.replace(old, new, 1))


replace_once(
    "parse.c",
    '''static Node *new_checked_addr(Node *operand, Token *op) {
''',
    '''// The controlling expression of a C11 generic selection is not
// evaluated, but it is still in an ordinary value context. Array and function
// designators therefore decay to pointers, and top-level object qualifiers are
// removed by value conversion. Qualifiers nested below a pointer remain part of
// the controlling type and must still participate in association matching.
static Type *generic_control_type(Node *node) {
    add_type(node);
    Type *ty = node->ty;
    if (!ty)
        return NULL;
    if (ty->kind == TY_ARRAY)
        return pointer_to(ty->base);
    if (ty->kind == TY_FUNC)
        return pointer_to(ty);
    if (ty->is_const || ty->is_volatile || ty->is_restrict)
        return ty->origin ? ty->origin : ty;
    return ty;
}

static Node *new_checked_addr(Node *operand, Token *op) {
''',
    "generic controlling conversion helper",
)

replace_once(
    "parse.c",
    '''        Node *control = assign(&tok, tok);
        add_type(control);
        tok = skip(tok, ",");
''',
    '''        Node *control = assign(&tok, tok);
        Type *control_ty = generic_control_type(control);
        tok = skip(tok, ",");
''',
    "generic controlling type",
)

replace_once(
    "parse.c",
    '''                if (type_compatible(control->ty, assoc_ty)) {
''',
    '''                if (type_compatible(control_ty, assoc_ty)) {
''',
    "generic association match",
)

insert = r'''
# The controlling expression is in a value context even though it is not
# evaluated: arrays and function designators decay to pointers.
compile_and_run <<'EOF'
int main(void) {
  int a[2]={1,2};
  return _Generic(a, int *: 0, default: 1);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  const int a[2]={1,2};
  return _Generic(a, const int *: 0, int *: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  return _Generic("abc", char *: 0, default: 1);
}
EOF

compile_and_run <<'EOF'
int f(void){return 1;}
int main(void) {
  return _Generic(f, int (*)(void): 0, default: 1);
}
EOF

compile_and_run <<'EOF'
int f(void){return 1;}
int main(void) {
  int (*fp)(void)=f;
  return _Generic(*fp, int (*)(void): 0, default: 1);
}
EOF

# Value conversion removes only top-level qualifiers from the controlling
# expression. Qualified pointed-to types remain distinct.
compile_and_run <<'EOF'
int main(void) {
  const int x=0;
  return _Generic(x, int: 0, const int: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  volatile long x=0;
  return _Generic(x, long: 0, volatile long: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  int x=0;
  int *const p=&x;
  return _Generic(p, int *: 0, int *const: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  int x=0;
  int *restrict p=&x;
  return _Generic(p, int *: 0, int *restrict: 1, default: 2);
}
EOF

compile_and_run <<'EOF'
int main(void) {
  const int x=0;
  const int *p=&x;
  return _Generic(p, const int *: 0, int *: 1, default: 2);
}
EOF

'''
replace_once(
    "test/generic_selection.sh",
    '''reject() {
''',
    insert + '''reject() {
''',
    "generic controlling conversion regressions",
)

replace_once(
    "README.md",
    "- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, C11 `_Alignof(type-name)`, prefix/postfix `++/--`, all compound assignments",
    "- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, C11 `_Alignof(type-name)` and `_Generic` selection with ordinary controlling-expression value conversions, prefix/postfix `++/--`, all compound assignments",
    "README generic selection support",
)
