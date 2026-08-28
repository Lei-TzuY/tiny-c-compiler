from pathlib import Path

p = Path('preprocess_v2.c')
text = p.read_text()
old = 'static Macro *macros;\nstatic CondStack *cond_stack;\n'
new = 'static Macro *macros;\nstatic CondStack *cond_stack;\nstatic int preprocess_depth;\n'
if old not in text:
    raise SystemExit('global anchor not found')
text = text.replace(old, new, 1)

old = 'char *preprocess_v2(char *input) {\n    CondStack *base_cond = cond_stack;\n'
new = '''char *preprocess_v2(char *input) {\n    bool outermost = preprocess_depth++ == 0;\n    if (outermost) {\n        add_macro(strdup("__STDC__"), true, false, NULL, 0, strdup("1"));\n        add_macro(strdup("__STDC_VERSION__"), true, false, NULL, 0, strdup("201112L"));\n        add_macro(strdup("__STDC_HOSTED__"), true, false, NULL, 0, strdup("1"));\n    }\n\n    CondStack *base_cond = cond_stack;\n'''
if old not in text:
    raise SystemExit('entry anchor not found')
text = text.replace(old, new, 1)

old = '    if (cond_stack != base_cond)\n        error("unterminated conditional directive");\n    return out.data;\n}\n'
new = '    if (cond_stack != base_cond)\n        error("unterminated conditional directive");\n    preprocess_depth--;\n    return out.data;\n}\n'
if old not in text:
    raise SystemExit('exit anchor not found')
text = text.replace(old, new, 1)
p.write_text(text)
