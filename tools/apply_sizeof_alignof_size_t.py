from pathlib import Path

p = Path('parse.c')
s = p.read_text()

old = '''static Node *new_long(int64_t val) {
    Node *node = new_node(ND_NUM);
    node->val = val;
    node->ty = ty_long;
    return node;
}
'''
new = old + '''\nstatic Node *new_size_t_num(int64_t val) {
    Node *node = new_node(ND_NUM);
    node->val = val;
    // The x86-64 SysV target uses the LP64 data model, so size_t is
    // represented by unsigned long.
    node->ty = ty_ulong;
    return node;
}
'''
if old not in s:
    raise SystemExit('new_long anchor not found')
s = s.replace(old, new, 1)

repls = {
    'return new_num(ty->align);': 'return new_size_t_num(ty->align);',
    'return new_num(ty->size);': 'return new_size_t_num(ty->size);',
    'return new_num(n->ty->size);': 'return new_size_t_num(n->ty->size);',
}
for old, new in repls.items():
    if old not in s:
        raise SystemExit(f'anchor not found: {old}')
    s = s.replace(old, new, 1)

p.write_text(s)
