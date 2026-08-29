from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


p = Path('parse.c').read_text()
p = replace_once(
    p,
    '''        } else {\n            node->init = new_node(ND_EXPR_STMT);\n            node->init->lhs = expr(&tok, tok);\n            tok = skip(tok, ";");\n        }\n''',
    '''        } else {\n            node->init = new_node(ND_EXPR_STMT);\n            node->init->lhs = expr(&tok, tok);\n            reject_register_array_decay(node->init->lhs);\n            tok = skip(tok, ";");\n        }\n''',
    'for init expression conversion',
)
p = replace_once(
    p,
    '''        if (!equal(tok, ")"))\n            node->inc = expr(&tok, tok);\n        tok = skip(tok, ")");\n''',
    '''        if (!equal(tok, ")")) {\n            node->inc = expr(&tok, tok);\n            reject_register_array_decay(node->inc);\n        }\n        tok = skip(tok, ")");\n''',
    'for increment expression conversion',
)
Path('parse.c').write_text(p)

path = Path('test/register_addressability.sh')
t = path.read_text()
anchor = "assert_reject 'int main(void){register int a[2];a;return 0;}'\n"
replacement = anchor + \
    "assert_reject 'int main(void){register int a[2];for(a;;)break;return 0;}'\n" + \
    "assert_reject 'int main(void){register int a[2];for(;;a)break;return 0;}'\n"
t = replace_once(t, anchor, replacement, 'for-clause regressions')
path.write_text(t)
