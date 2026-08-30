from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"missing marker for {label}")
    return text.replace(old, new, 1)


# Extend the preprocessor with an ordered queue of command-line macro actions.
pp = Path("preprocess_v2.c")
text = pp.read_text()
text = replace_once(
    text,
    '''typedef struct Expansion Expansion;\nstruct Expansion {\n    Expansion *next;\n    Macro *macro;\n};\n\ntypedef struct {\n''',
    '''typedef struct Expansion Expansion;\nstruct Expansion {\n    Expansion *next;\n    Macro *macro;\n};\n\ntypedef enum {\n    CLI_MACRO_DEFINE,\n    CLI_MACRO_UNDEF,\n} CliMacroKind;\n\ntypedef struct CliMacroAction CliMacroAction;\nstruct CliMacroAction {\n    CliMacroAction *next;\n    CliMacroKind kind;\n    char *arg;\n};\n\nstatic void parse_define(char *start);\n\ntypedef struct {\n''',
    "CLI macro action types",
)
text = replace_once(
    text,
    '''static int preprocess_depth;\nstatic const char *current_pp_file;\nstatic int current_pp_line;\n''',
    '''static int preprocess_depth;\nstatic const char *current_pp_file;\nstatic int current_pp_line;\nstatic CliMacroAction *cli_macro_actions;\nstatic CliMacroAction *cli_macro_actions_tail;\n''',
    "CLI macro action storage",
)
text = replace_once(
    text,
    '''static bool is_ident2_pp(char c) {\n    return isalnum((unsigned char)c) || c == '_';\n}\n\nstatic char *trim_copy(const char *s) {\n''',
    '''static bool is_ident2_pp(char c) {\n    return isalnum((unsigned char)c) || c == '_';\n}\n\nstatic void queue_cli_macro_action(CliMacroKind kind, const char *arg) {\n    CliMacroAction *action = calloc(1, sizeof(CliMacroAction));\n    action->kind = kind;\n    action->arg = strdup(arg);\n    if (cli_macro_actions_tail)\n        cli_macro_actions_tail->next = action;\n    else\n        cli_macro_actions = action;\n    cli_macro_actions_tail = action;\n}\n\nvoid preprocess_v2_add_define(const char *definition) {\n    if (!definition || !*definition || !is_ident1_pp(*definition))\n        error("invalid macro name in -D option: %s", definition ? definition : "");\n\n    const char *p = definition + 1;\n    while (is_ident2_pp(*p))\n        p++;\n    if (*p && *p != '=' && *p != '(')\n        error("invalid macro name in -D option: %s", definition);\n\n    queue_cli_macro_action(CLI_MACRO_DEFINE, definition);\n}\n\nvoid preprocess_v2_add_undef(const char *name) {\n    if (!name || !*name || !is_ident1_pp(*name))\n        error("invalid macro name in -U option: %s", name ? name : "");\n    for (const char *p = name + 1; *p; p++)\n        if (!is_ident2_pp(*p))\n            error("invalid macro name in -U option: %s", name);\n\n    queue_cli_macro_action(CLI_MACRO_UNDEF, name);\n}\n\nstatic char *trim_copy(const char *s) {\n''',
    "CLI macro queue API",
)
text = replace_once(
    text,
    '''static void add_builtin_macro(const char *name, BuiltinMacroKind builtin) {\n    undef_macro(name);\n    Macro *m = calloc(1, sizeof(Macro));\n    m->name = strdup(name);\n    m->is_objlike = true;\n    m->builtin = builtin;\n    m->body = strdup("");\n    m->next = macros;\n    macros = m;\n}\n\n// Resolve a quoted include relative to the physical source file that\n''',
    '''static void add_builtin_macro(const char *name, BuiltinMacroKind builtin) {\n    undef_macro(name);\n    Macro *m = calloc(1, sizeof(Macro));\n    m->name = strdup(name);\n    m->is_objlike = true;\n    m->builtin = builtin;\n    m->body = strdup("");\n    m->next = macros;\n    macros = m;\n}\n\nstatic void apply_cli_macro_actions(void) {\n    for (CliMacroAction *action = cli_macro_actions; action; action = action->next) {\n        if (action->kind == CLI_MACRO_UNDEF) {\n            undef_macro(action->arg);\n            continue;\n        }\n\n        char *definition = strdup(action->arg);\n        char *eq = strchr(definition, '=');\n        if (eq) {\n            *eq = ' ';\n        } else {\n            size_t len = strlen(definition);\n            definition = realloc(definition, len + 3);\n            definition[len] = ' ';\n            definition[len + 1] = '1';\n            definition[len + 2] = '\\0';\n        }\n        parse_define(definition);\n        free(definition);\n    }\n}\n\n// Resolve a quoted include relative to the physical source file that\n''',
    "CLI macro action application",
)
text = replace_once(
    text,
    '''        add_builtin_macro("__LINE__", BUILTIN_MACRO_LINE);\n        add_builtin_macro("__FILE__", BUILTIN_MACRO_FILE);\n    }\n\n    CondStack *base_cond = cond_stack;\n''',
    '''        add_builtin_macro("__LINE__", BUILTIN_MACRO_LINE);\n        add_builtin_macro("__FILE__", BUILTIN_MACRO_FILE);\n        apply_cli_macro_actions();\n    }\n\n    CondStack *base_cond = cond_stack;\n''',
    "CLI macro replay",
)
pp.write_text(text)

# Export the command-line macro queue API.
hdr = Path("preprocess_v2.h")
h = hdr.read_text()
h = replace_once(
    h,
    '''char *preprocess_v2(char *input);\nchar *preprocess_v2_source(char *input, const char *source_name);\n''',
    '''char *preprocess_v2(char *input);\nchar *preprocess_v2_source(char *input, const char *source_name);\nvoid preprocess_v2_add_define(const char *definition);\nvoid preprocess_v2_add_undef(const char *name);\n''',
    "preprocessor public API",
)
hdr.write_text(h)

# Teach the driver attached and separated -D/-U forms, preserving argv order.
main = Path("main.c")
m = main.read_text()
m = replace_once(
    m,
    '''            "  -fsyntax-only    Check preprocessing, syntax and semantics only\\n"\n            "  -o <file>        Write output to <file>\\n"\n''',
    '''            "  -fsyntax-only    Check preprocessing, syntax and semantics only\\n"\n            "  -D<macro>[=<value>]  Define a preprocessor macro (default value: 1)\\n"\n            "  -U<macro>        Undefine a preprocessor macro\\n"\n            "  -o <file>        Write output to <file>\\n"\n''',
    "driver help",
)
m = replace_once(
    m,
    '''        if (!end_options && !strcmp(arg, "-fsyntax-only")) {\n            saw_syntax_only = true;\n            opts.mode = DRIVER_SYNTAX_ONLY;\n            continue;\n        }\n\n        if (!end_options && !strcmp(arg, "-o")) {\n''',
    '''        if (!end_options && !strcmp(arg, "-fsyntax-only")) {\n            saw_syntax_only = true;\n            opts.mode = DRIVER_SYNTAX_ONLY;\n            continue;\n        }\n\n        if (!end_options && !strcmp(arg, "-D")) {\n            if (++i >= argc)\n                error("%s: missing argument after '-D'", argv[0]);\n            preprocess_v2_add_define(argv[i]);\n            continue;\n        }\n\n        if (!end_options && !strncmp(arg, "-D", 2) && arg[2]) {\n            preprocess_v2_add_define(arg + 2);\n            continue;\n        }\n\n        if (!end_options && !strcmp(arg, "-U")) {\n            if (++i >= argc)\n                error("%s: missing argument after '-U'", argv[0]);\n            preprocess_v2_add_undef(argv[i]);\n            continue;\n        }\n\n        if (!end_options && !strncmp(arg, "-U", 2) && arg[2]) {\n            preprocess_v2_add_undef(arg + 2);\n            continue;\n        }\n\n        if (!end_options && !strcmp(arg, "-o")) {\n''',
    "driver option parsing",
)
main.write_text(m)

# Extend CLI regression coverage.
test = Path("test/driver_cli.sh")
t = test.read_text()
t = replace_once(
    t,
    '''grep -F -- '-fsyntax-only' tmp-driver-help.txt >/dev/null || fail '--help missing -fsyntax-only'\ngrep -F -- '-o <file>' tmp-driver-help.txt >/dev/null || fail '--help missing -o'\n''',
    '''grep -F -- '-fsyntax-only' tmp-driver-help.txt >/dev/null || fail '--help missing -fsyntax-only'\ngrep -F -- '-D<macro>' tmp-driver-help.txt >/dev/null || fail '--help missing -D'\ngrep -F -- '-U<macro>' tmp-driver-help.txt >/dev/null || fail '--help missing -U'\ngrep -F -- '-o <file>' tmp-driver-help.txt >/dev/null || fail '--help missing -o'\n''',
    "driver help tests",
)
macro_tests = r'''
# Command-line macro definitions must participate in preprocessing before the
# source file. Attached and separated forms are both supported, and a missing
# explicit replacement defaults to 1.
cat > tmp-driver-macros.c <<'EOF'
#ifndef FEATURE
#error FEATURE missing
#endif
#ifndef FLAG
#error FLAG missing
#endif
int feature = FEATURE;
int flag = FLAG;
EOF
./minicc -E -DFEATURE=7 -DFLAG tmp-driver-macros.c > tmp-driver-macros.i
grep -F 'int feature = 7;' tmp-driver-macros.i >/dev/null || fail '-Dname=value did not expand'
grep -F 'int flag = 1;' tmp-driver-macros.i >/dev/null || fail '-Dname did not default to 1'
./minicc -E -D FEATURE=8 -D FLAG tmp-driver-macros.c > tmp-driver-macros-separated.i
grep -F 'int feature = 8;' tmp-driver-macros-separated.i >/dev/null || fail 'separated -D did not expand'

# Function-like command-line macros use the same replacement machinery as
# source #define directives.
cat > tmp-driver-function-macro.c <<'EOF'
int main(void) { return SCALE(4) == 12 ? 0 : 1; }
EOF
./minicc '-DSCALE(x)=((x)*3)' -o tmp-driver-function-macro.s tmp-driver-function-macro.c
cc -o tmp-driver-function-macro tmp-driver-function-macro.s
./tmp-driver-function-macro

# -D and -U are replayed in their original argv order after the predefined
# macros are installed and before the source is processed.
cat > tmp-driver-macro-order.c <<'EOF'
#if VALUE != 3
#error wrong VALUE ordering
#endif
int main(void) { return VALUE == 3 ? 0 : 1; }
EOF
./minicc -DVALUE=1 -UVALUE -DVALUE=3 -o tmp-driver-macro-order.s tmp-driver-macro-order.c
cc -o tmp-driver-macro-order tmp-driver-macro-order.s
./tmp-driver-macro-order

# Source definitions occur after command-line actions and therefore may
# redefine a command-line macro in the normal preprocessing stream.
cat > tmp-driver-source-redefine.c <<'EOF'
#define VALUE 9
#if VALUE != 9
#error source definition did not win
#endif
int main(void) { return 0; }
EOF
./minicc -DVALUE=3 -fsyntax-only tmp-driver-source-redefine.c

# Command-line macros are inherited by recursively processed includes, while
# command actions themselves are only replayed once at the outermost source.
cat > tmp-driver-macro-header.h <<'EOF'
#if FEATURE != 11
#error include did not inherit FEATURE
#endif
#define HEADER_VALUE FEATURE
EOF
cat > tmp-driver-macro-include.c <<'EOF'
#include "tmp-driver-macro-header.h"
int main(void) { return HEADER_VALUE == 11 ? 0 : 1; }
EOF
./minicc -DFEATURE=11 -o tmp-driver-macro-include.s tmp-driver-macro-include.c
cc -o tmp-driver-macro-include tmp-driver-macro-include.s
./tmp-driver-macro-include

# Because command actions are replayed after predefined macros are installed,
# -U can intentionally suppress a predefined macro as normal compiler drivers do.
cat > tmp-driver-undef-stdc.c <<'EOF'
#ifdef __STDC__
#error __STDC__ should have been undefined
#endif
int main(void) { return 0; }
EOF
./minicc -U__STDC__ -fsyntax-only tmp-driver-undef-stdc.c

'''
t = replace_once(
    t,
    '''# Syntax-only mode must run the complete front end without producing assembly or\n''',
    macro_tests + '''# Syntax-only mode must run the complete front end without producing assembly or\n''',
    "driver macro tests",
)
t = replace_once(
    t,
    '''assert_reject 'unknown option' ./minicc -Z tmp-driver-cli.c\nassert_reject "missing argument after '-o'" ./minicc -o\n''',
    '''assert_reject 'unknown option' ./minicc -Z tmp-driver-cli.c\nassert_reject "missing argument after '-D'" ./minicc -D\nassert_reject "missing argument after '-U'" ./minicc -U\nassert_reject 'invalid macro name in -D option' ./minicc -D9BAD=1 tmp-driver-cli.c\nassert_reject 'invalid macro name in -U option' ./minicc -UBAD=1 tmp-driver-cli.c\nassert_reject "missing argument after '-o'" ./minicc -o\n''',
    "driver macro diagnostics",
)
t = replace_once(
    t,
    '''      tmp-driver-syntax-output.s \\\n      tmp-driver-help.txt tmp-driver-version.txt tmp-driver-cli.out tmp-driver-cli.err \\\n''',
    '''      tmp-driver-syntax-output.s \\\n      tmp-driver-macros.c tmp-driver-macros.i tmp-driver-macros-separated.i \\\n      tmp-driver-function-macro.c tmp-driver-function-macro.s tmp-driver-function-macro \\\n      tmp-driver-macro-order.c tmp-driver-macro-order.s tmp-driver-macro-order \\\n      tmp-driver-source-redefine.c tmp-driver-macro-header.h tmp-driver-macro-include.c \\\n      tmp-driver-macro-include.s tmp-driver-macro-include tmp-driver-undef-stdc.c \\\n      tmp-driver-help.txt tmp-driver-version.txt tmp-driver-cli.out tmp-driver-cli.err \\\n''',
    "driver cleanup",
)
test.write_text(t)
