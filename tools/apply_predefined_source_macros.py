from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"anchor not found in {path}")
    p.write_text(text.replace(old, new, 1))

replace_once(
    "preprocess_v2.c",
    '''typedef struct Macro Macro;\nstruct Macro {\n''',
    '''typedef enum {\n    BUILTIN_MACRO_NONE,\n    BUILTIN_MACRO_LINE,\n    BUILTIN_MACRO_FILE,\n} BuiltinMacroKind;\n\ntypedef struct Macro Macro;\nstruct Macro {\n''',
)
replace_once(
    "preprocess_v2.c",
    '''    bool is_variadic;\n    char **params;\n''',
    '''    bool is_variadic;\n    BuiltinMacroKind builtin;\n    char **params;\n''',
)
replace_once(
    "preprocess_v2.c",
    '''static Macro *macros;\nstatic CondStack *cond_stack;\nstatic int preprocess_depth;\n''',
    '''static Macro *macros;\nstatic CondStack *cond_stack;\nstatic int preprocess_depth;\nstatic const char *current_pp_file;\nstatic int current_pp_line;\n''',
)
replace_once(
    "preprocess_v2.c",
    '''static void add_macro(char *name, bool is_objlike, bool is_variadic,\n                      char **params, int num_params, char *body) {\n    undef_macro(name);\n    Macro *m = calloc(1, sizeof(Macro));\n    m->name = name;\n    m->is_objlike = is_objlike;\n    m->is_variadic = is_variadic;\n    m->params = params;\n    m->num_params = num_params;\n    m->body = body;\n    m->next = macros;\n    macros = m;\n}\n''',
    '''static void add_macro(char *name, bool is_objlike, bool is_variadic,\n                      char **params, int num_params, char *body) {\n    undef_macro(name);\n    Macro *m = calloc(1, sizeof(Macro));\n    m->name = name;\n    m->is_objlike = is_objlike;\n    m->is_variadic = is_variadic;\n    m->params = params;\n    m->num_params = num_params;\n    m->body = body;\n    m->next = macros;\n    macros = m;\n}\n\nstatic void add_builtin_macro(const char *name, BuiltinMacroKind builtin) {\n    undef_macro(name);\n    Macro *m = calloc(1, sizeof(Macro));\n    m->name = strdup(name);\n    m->is_objlike = true;\n    m->builtin = builtin;\n    m->body = strdup(\"\");\n    m->next = macros;\n    macros = m;\n}\n''',
)
replace_once(
    "preprocess_v2.c",
    '''        Macro *m = find_macro(ident);\n        int64_t result = 0;\n        if (m && m->is_objlike && e->depth < 64)\n            result = eval_pp_expr_depth(m->body, e->depth + 1);\n        free(ident);\n        return result;\n''',
    '''        Macro *m = find_macro(ident);\n        int64_t result = 0;\n        if (m && m->builtin == BUILTIN_MACRO_LINE) {\n            result = current_pp_line;\n        } else if (m && m->builtin == BUILTIN_MACRO_FILE) {\n            error(\"__FILE__ expands to a string and is not valid in #if arithmetic\");\n        } else if (m && m->is_objlike && e->depth < 64) {\n            result = eval_pp_expr_depth(m->body, e->depth + 1);\n        }\n        free(ident);\n        return result;\n''',
)
replace_once(
    "preprocess_v2.c",
    '''static void copy_quoted(StrBuf *out, const char **pp, char quote) {\n''',
    '''static char *quote_pp_string(const char *text) {\n    StrBuf out;\n    sb_init(&out, strlen(text) + 8);\n    sb_putc(&out, '\"');\n    for (const char *p = text; *p; p++) {\n        if (*p == '\\\\' || *p == '\"')\n            sb_putc(&out, '\\\\');\n        sb_putc(&out, *p);\n    }\n    sb_putc(&out, '\"');\n    return out.data;\n}\n\nstatic void copy_quoted(StrBuf *out, const char **pp, char quote) {\n''',
)
replace_once(
    "preprocess_v2.c",
    '''        if (!m || expansion_contains(stack, m)) {\n            sb_putn(&out, start, (size_t)(p - start));\n            free(ident);\n            continue;\n        }\n\n        Expansion frame = {.next = stack, .macro = m};\n''',
    '''        if (!m || expansion_contains(stack, m)) {\n            sb_putn(&out, start, (size_t)(p - start));\n            free(ident);\n            continue;\n        }\n\n        if (m->builtin == BUILTIN_MACRO_LINE) {\n            char buf[32];\n            snprintf(buf, sizeof(buf), \"%d\", current_pp_line);\n            sb_puts(&out, buf);\n            free(ident);\n            continue;\n        }\n        if (m->builtin == BUILTIN_MACRO_FILE) {\n            char *quoted = quote_pp_string(current_pp_file ? current_pp_file : \"<stdin>\");\n            sb_puts(&out, quoted);\n            free(quoted);\n            free(ident);\n            continue;\n        }\n\n        Expansion frame = {.next = stack, .macro = m};\n''',
)
replace_once(
    "preprocess_v2.c",
    '''char *preprocess_v2(char *input) {\n    bool outermost = preprocess_depth++ == 0;\n''',
    '''char *preprocess_v2_source(char *input, const char *source_name) {\n    const char *saved_file = current_pp_file;\n    int saved_line = current_pp_line;\n    bool outermost = preprocess_depth++ == 0;\n''',
)
replace_once(
    "preprocess_v2.c",
    '''        add_macro(strdup(\"__STDC_HOSTED__\"), true, false, NULL, 0, strdup(\"1\"));\n    }\n\n    CondStack *base_cond = cond_stack;\n''',
    '''        add_macro(strdup(\"__STDC_HOSTED__\"), true, false, NULL, 0, strdup(\"1\"));\n        add_builtin_macro(\"__LINE__\", BUILTIN_MACRO_LINE);\n        add_builtin_macro(\"__FILE__\", BUILTIN_MACRO_FILE);\n    }\n\n    CondStack *base_cond = cond_stack;\n''',
)
replace_once(
    "preprocess_v2.c",
    '''    char *p = spliced;\n    while (*p) {\n        char *line_start = p;\n''',
    '''    char *p = spliced;\n    int line_no = 0;\n    while (*p) {\n        line_no++;\n        current_pp_file = source_name ? source_name : \"<stdin>\";\n        current_pp_line = line_no;\n        char *line_start = p;\n''',
)
replace_once(
    "preprocess_v2.c",
    '''                    char *sub = preprocess_v2((char *)content);\n''',
    '''                    char *sub = preprocess_v2_source((char *)content, hname);\n''',
)
replace_once(
    "preprocess_v2.c",
    '''    preprocess_depth--;\n    return out.data;\n}\n''',
    '''    preprocess_depth--;\n    current_pp_file = saved_file;\n    current_pp_line = saved_line;\n    return out.data;\n}\n\nchar *preprocess_v2(char *input) {\n    return preprocess_v2_source(input, \"<stdin>\");\n}\n''',
)
replace_once(
    "preprocess_v2.h",
    '''char *preprocess_v2(char *input);\n''',
    '''char *preprocess_v2(char *input);\nchar *preprocess_v2_source(char *input, const char *source_name);\n''',
)
replace_once(
    "main.c",
    '''    char *user_input = read_file(argv[1]);\n    char *preprocessed = preprocess_v2(user_input);\n''',
    '''    char *user_input = read_file(argv[1]);\n    const char *source_name = !strcmp(argv[1], \"-\") ? \"<stdin>\" : argv[1];\n    char *preprocessed = preprocess_v2_source(user_input, source_name);\n''',
)
