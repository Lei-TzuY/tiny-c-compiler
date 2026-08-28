from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    '''    bind_var_in_current_scope(fn_obj->name, fn_obj, false);\n}\n\n// program = (function | global-var | typedef)*\n''',
    '''    bind_var_in_current_scope(fn_obj->name, fn_obj, false);\n}\n\n// C99 defines __func__ inside every function as if the implementation inserted\n// `static const char __func__[] = "function-name";` immediately after the\n// opening brace. Model it as one compiler-generated static object bound in the\n// function scope so array extent, pointer identity, and const element semantics\n// all follow ordinary variable rules.\nstatic void bind_predefined_func_name(const char *name) {\n    Obj *var = calloc(1, sizeof(Obj));\n    var->name = new_unique_name();\n    var->ty = array_of(qualify_type(ty_char, true, false), strlen(name) + 1);\n    var->is_local = false;\n    var->is_static = true;\n    var->is_string_literal = true;\n    var->init_data = strdup(name);\n    var->next = globals;\n    globals = var;\n    bind_var_in_current_scope("__func__", var, false);\n}\n\n// program = (function | global-var | typedef)*\n''')

replace_once(
    "parse.c",
    '''            tok = skip(tok, "{");\n\n            Function *fn = calloc(1, sizeof(Function));\n''',
    '''            tok = skip(tok, "{");\n            bind_predefined_func_name(name);\n\n            Function *fn = calloc(1, sizeof(Function));\n''')

replace_once(
    "Makefile",
    '''\tbash ./test/generic_selection.sh\n\tbash ./test/gnu_stack.sh\n''',
    '''\tbash ./test/generic_selection.sh\n\tbash ./test/predefined_func.sh\n\tbash ./test/gnu_stack.sh\n''')

replace_once(
    "README.md",
    '''- **Lexical literals**: ordinary character/string literals support standard simple escapes plus one-to-three-digit octal and variable-length hexadecimal escapes, with byte-range diagnostics and adjacent string literal concatenation\n''',
    '''- **Lexical literals**: ordinary character/string literals support standard simple escapes plus one-to-three-digit octal and variable-length hexadecimal escapes, with byte-range diagnostics and adjacent string literal concatenation; every function provides the C99 predefined `__func__` identifier as a function-local `static const char[]` object\n''')
