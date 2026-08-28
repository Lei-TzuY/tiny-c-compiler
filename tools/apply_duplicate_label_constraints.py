from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    '''    // Labeled statement: ident ":"  stmt\n    if (is_label(tok)) {\n        Node *node = new_node(ND_LABEL);\n        node->label_name = strndup(tok->loc, tok->len);\n        node->unique_label = new_unique_name();\n        node->label_next = current_labels;\n        current_labels = node;\n        tok = skip(tok->next, ":");\n        node->lhs = stmt(rest, tok);\n        return node;\n    }\n''',
    '''    // Labeled statement: ident ":"  stmt. Labels have function scope in C,\n    // so the same label name may not be defined twice anywhere in one function,\n    // even when the definitions occur in different nested compound statements.\n    if (is_label(tok)) {\n        char *label_name = strndup(tok->loc, tok->len);\n        for (Node *label = current_labels; label; label = label->label_next)\n            if (!strcmp(label_name, label->label_name))\n                error_at(tok->loc, "duplicate label '%s'", label_name);\n\n        Node *node = new_node(ND_LABEL);\n        node->label_name = label_name;\n        node->unique_label = new_unique_name();\n        node->label_next = current_labels;\n        current_labels = node;\n        tok = skip(tok->next, ":");\n        node->lhs = stmt(rest, tok);\n        return node;\n    }\n''')

# Extend the existing control-flow context suite rather than introducing a new
# overlapping test harness.
test = Path("test/control_flow_context.sh")
text = test.read_text()
anchor = "assert_run 3 'int main(void){int i=0; while(i<3){switch(i){case 0:i++;continue;default:i++;break;}} return i;}'\n"
addition = anchor + \
    "assert_run 5 'int main(void){goto done; return 1; done: return 5;}'\n" + \
    "assert_run 6 'int main(void){int L=6; goto L; L: return L;}'\n" + \
    "assert_run 7 'int f(void){same:return 3;} int g(void){same:return 4;} int main(void){return f()+g();}'\n"
if text.count(anchor) != 1:
    raise SystemExit("control-flow positive insertion point not unique")
text = text.replace(anchor, addition, 1)

reject_anchor = "assert_reject_msg 'continue statement not within loop' 'int main(void){{{continue;}}}'\n"
reject_addition = reject_anchor + \
    "assert_reject_msg \"duplicate label 'L'\" 'int main(void){L:; L:; return 0;}'\n" + \
    "assert_reject_msg \"duplicate label 'L'\" 'int main(void){L:; {L:;} return 0;}'\n" + \
    "assert_reject_msg \"duplicate label 'done'\" 'int main(void){goto done; done:; {done:;} return 0;}'\n" + \
    "assert_reject_msg 'undefined label: missing' 'int main(void){goto missing; return 0;}'\n"
if text.count(reject_anchor) != 1:
    raise SystemExit("control-flow rejection insertion point not unique")
text = text.replace(reject_anchor, reject_addition, 1)
test.write_text(text)

readme = Path("README.md")
text = readme.read_text()
old = "- **Control-flow constraints**: `if`, `while`, `do-while`, and non-empty `for` controlling expressions must have scalar type (with ordinary array/function designator decay); `break` is accepted only inside loops or `switch`, while `continue` is accepted only inside loops, including correctly nested loop/switch combinations\n"
new = "- **Control-flow constraints**: `if`, `while`, `do-while`, and non-empty `for` controlling expressions must have scalar type (with ordinary array/function designator decay); `break` is accepted only inside loops or `switch`, while `continue` is accepted only inside loops, including correctly nested loop/switch combinations; ordinary labels have function scope, with undefined and duplicate label diagnostics for `goto`/labeled statements\n"
if text.count(old) != 1:
    raise SystemExit("README control-flow constraint line not unique")
readme.write_text(text.replace(old, new, 1))

print("duplicate label constraint migration applied")
