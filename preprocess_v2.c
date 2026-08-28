#include "minicc.h"
#include "preprocess_v2.h"

typedef enum {
    BUILTIN_MACRO_NONE,
    BUILTIN_MACRO_LINE,
    BUILTIN_MACRO_FILE,
} BuiltinMacroKind;

typedef struct Macro Macro;
struct Macro {
    Macro *next;
    char *name;
    bool is_objlike;
    bool is_variadic;
    BuiltinMacroKind builtin;
    char **params;
    int num_params;
    char *body;
};

typedef struct CondStack CondStack;
struct CondStack {
    CondStack *next;
    bool parent_active;
    bool active;
    bool branch_taken;
    bool seen_else;
};

typedef struct Expansion Expansion;
struct Expansion {
    Expansion *next;
    Macro *macro;
};

typedef struct {
    char *data;
    size_t len;
    size_t cap;
} StrBuf;

static Macro *macros;
static CondStack *cond_stack;
static int preprocess_depth;
static const char *current_pp_file;
static int current_pp_line;

static void sb_init(StrBuf *sb, size_t cap) {
    sb->cap = cap < 64 ? 64 : cap;
    sb->len = 0;
    sb->data = calloc(1, sb->cap);
}

static void sb_reserve(StrBuf *sb, size_t extra) {
    if (sb->len + extra + 1 <= sb->cap)
        return;
    while (sb->len + extra + 1 > sb->cap)
        sb->cap *= 2;
    sb->data = realloc(sb->data, sb->cap);
}

static void sb_putn(StrBuf *sb, const char *s, size_t n) {
    sb_reserve(sb, n);
    memcpy(sb->data + sb->len, s, n);
    sb->len += n;
    sb->data[sb->len] = '\0';
}

static void sb_puts(StrBuf *sb, const char *s) {
    sb_putn(sb, s, strlen(s));
}

static void sb_putc(StrBuf *sb, char c) {
    sb_reserve(sb, 1);
    sb->data[sb->len++] = c;
    sb->data[sb->len] = '\0';
}

static bool is_ident1_pp(char c) {
    return isalpha((unsigned char)c) || c == '_';
}

static bool is_ident2_pp(char c) {
    return isalnum((unsigned char)c) || c == '_';
}

static char *trim_copy(const char *s) {
    while (isspace((unsigned char)*s))
        s++;
    const char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)end[-1]))
        end--;
    return strndup(s, (size_t)(end - s));
}

static char *splice_lines(const char *input) {
    StrBuf out;
    sb_init(&out, strlen(input) + 1);
    for (const char *p = input; *p;) {
        if (p[0] == '\\' && p[1] == '\n') {
            p += 2;
            continue;
        }
        if (p[0] == '\\' && p[1] == '\r' && p[2] == '\n') {
            p += 3;
            continue;
        }
        sb_putc(&out, *p++);
    }
    return out.data;
}

static Macro *find_macro(const char *name) {
    for (Macro *m = macros; m; m = m->next)
        if (!strcmp(m->name, name))
            return m;
    return NULL;
}

static void free_macro_payload(Macro *m) {
    if (!m)
        return;
    free(m->name);
    for (int i = 0; i < m->num_params; i++)
        free(m->params[i]);
    free(m->params);
    free(m->body);
}

static void undef_macro(const char *name) {
    Macro **pp = &macros;
    while (*pp) {
        Macro *m = *pp;
        if (!strcmp(m->name, name)) {
            *pp = m->next;
            free_macro_payload(m);
            free(m);
            continue;
        }
        pp = &m->next;
    }
}

static void add_macro(char *name, bool is_objlike, bool is_variadic,
                      char **params, int num_params, char *body) {
    undef_macro(name);
    Macro *m = calloc(1, sizeof(Macro));
    m->name = name;
    m->is_objlike = is_objlike;
    m->is_variadic = is_variadic;
    m->params = params;
    m->num_params = num_params;
    m->body = body;
    m->next = macros;
    macros = m;
}

static void add_builtin_macro(const char *name, BuiltinMacroKind builtin) {
    undef_macro(name);
    Macro *m = calloc(1, sizeof(Macro));
    m->name = strdup(name);
    m->is_objlike = true;
    m->builtin = builtin;
    m->body = strdup("");
    m->next = macros;
    macros = m;
}

static char *read_file_content(char *path) {
    FILE *fp = fopen(path, "r");
    if (!fp)
        return NULL;
    if (fseek(fp, 0, SEEK_END) != 0) {
        fclose(fp);
        return NULL;
    }
    long size = ftell(fp);
    if (size < 0) {
        fclose(fp);
        return NULL;
    }
    rewind(fp);
    char *buf = malloc((size_t)size + 1);
    size_t nread = fread(buf, 1, (size_t)size, fp);
    fclose(fp);
    if (nread != (size_t)size) {
        free(buf);
        return NULL;
    }
    buf[size] = '\0';
    return buf;
}

static char *get_builtin_header(char *name) {
    if (!strcmp(name, "stdio.h")) {
        return "typedef struct FILE FILE;\n"
               "extern FILE *stdin, *stdout, *stderr;\n"
               "int printf(const char *fmt, ...);\n"
               "int sprintf(char *str, const char *fmt, ...);\n"
               "int fprintf(FILE *stream, const char *fmt, ...);\n"
               "int puts(const char *s);\n"
               "int putchar(int c);\n";
    }
    if (!strcmp(name, "stdlib.h")) {
        return "void *malloc(unsigned long size);\n"
               "void *calloc(unsigned long nmemb, unsigned long size);\n"
               "void *realloc(void *ptr, unsigned long size);\n"
               "void free(void *ptr);\n"
               "void exit(int status);\n"
               "int atoi(const char *nptr);\n";
    }
    if (!strcmp(name, "stdbool.h")) {
        return "#define bool _Bool\n"
               "#define true 1\n"
               "#define false 0\n"
               "#define __bool_true_false_are_defined 1\n";
    }
    if (!strcmp(name, "stdnoreturn.h")) {
        return "#define noreturn _Noreturn\n";
    }
    if (!strcmp(name, "stdarg.h")) {
        return "typedef struct __minicc_va_list {\n"
               "  unsigned int gp_offset;\n"
               "  unsigned int fp_offset;\n"
               "  void *overflow_arg_area;\n"
               "  void *reg_save_area;\n"
               "} va_list;\n"
               "#define va_start(ap, last) __builtin_va_start(&(ap))\n"
               "#define va_arg(ap, type) __builtin_va_arg(&(ap), type)\n"
               "#define va_copy(dest, src) ((dest) = (src))\n"
               "#define __va_copy(dest, src) va_copy(dest, src)\n"
               "#define va_end(ap) ((void)0)\n";
    }
    return NULL;
}

static bool is_cond_active(void) {
    return !cond_stack || cond_stack->active;
}

static void push_cond(bool cond) {
    CondStack *cs = calloc(1, sizeof(CondStack));
    cs->parent_active = is_cond_active();
    cs->active = cs->parent_active && cond;
    cs->branch_taken = cond;
    cs->next = cond_stack;
    cond_stack = cs;
}

static void handle_elif(bool cond) {
    if (!cond_stack)
        error("stray #elif");
    if (cond_stack->seen_else)
        error("#elif after #else");
    bool select = !cond_stack->branch_taken && cond;
    cond_stack->active = cond_stack->parent_active && select;
    if (cond)
        cond_stack->branch_taken = true;
}

static void handle_else(void) {
    if (!cond_stack)
        error("stray #else");
    if (cond_stack->seen_else)
        error("duplicate #else");
    cond_stack->seen_else = true;
    cond_stack->active = cond_stack->parent_active && !cond_stack->branch_taken;
    cond_stack->branch_taken = true;
}

static void handle_endif(void) {
    if (!cond_stack)
        error("stray #endif");
    CondStack *old = cond_stack;
    cond_stack = old->next;
    free(old);
}

// ---- #if expression evaluator ------------------------------------------------

typedef struct {
    const char *p;
    int depth;
    bool suppress_eval;
} PPExpr;

static int64_t pp_conditional(PPExpr *e);

static void pp_skip_space(PPExpr *e) {
    while (isspace((unsigned char)*e->p))
        e->p++;
}

static bool pp_consume(PPExpr *e, const char *op) {
    pp_skip_space(e);
    size_t n = strlen(op);
    if (strncmp(e->p, op, n))
        return false;
    e->p += n;
    return true;
}

static char *pp_read_ident(PPExpr *e) {
    pp_skip_space(e);
    if (!is_ident1_pp(*e->p))
        return NULL;
    const char *start = e->p++;
    while (is_ident2_pp(*e->p))
        e->p++;
    return strndup(start, (size_t)(e->p - start));
}

static int64_t eval_pp_expr_depth(const char *text, int depth);

static int64_t pp_primary(PPExpr *e) {
    pp_skip_space(e);
    const char *saved = e->p;
    char *ident = pp_read_ident(e);
    if (ident && !strcmp(ident, "defined")) {
        free(ident);
        bool paren = pp_consume(e, "(");
        char *name = pp_read_ident(e);
        if (!name)
            error("expected identifier after defined");
        if (paren && !pp_consume(e, ")"))
            error("expected ')' after defined");
        bool result = find_macro(name) != NULL;
        free(name);
        return result;
    }
    if (ident) {
        Macro *m = find_macro(ident);
        int64_t result = 0;
        if (m && m->builtin == BUILTIN_MACRO_LINE) {
            result = current_pp_line;
        } else if (m && m->builtin == BUILTIN_MACRO_FILE) {
            error("__FILE__ expands to a string and is not valid in #if arithmetic");
        } else if (m && m->is_objlike && e->depth < 64) {
            result = eval_pp_expr_depth(m->body, e->depth + 1);
        }
        free(ident);
        return result;
    }
    e->p = saved;

    if (pp_consume(e, "(")) {
        int64_t val = pp_conditional(e);
        if (!pp_consume(e, ")"))
            error("expected ')' in #if expression");
        return val;
    }

    pp_skip_space(e);
    if (isdigit((unsigned char)*e->p)) {
        char *end;
        unsigned long long val = strtoull(e->p, &end, 0);
        if (end == e->p)
            error("invalid number in #if expression");
        e->p = end;
        while (*e->p == 'u' || *e->p == 'U' || *e->p == 'l' || *e->p == 'L')
            e->p++;
        return (int64_t)val;
    }
    error("invalid #if expression near '%s'", e->p);
}

static int64_t pp_unary(PPExpr *e) {
    if (pp_consume(e, "!")) return !pp_unary(e);
    if (pp_consume(e, "~")) return ~pp_unary(e);
    if (pp_consume(e, "+")) return +pp_unary(e);
    if (pp_consume(e, "-")) return -pp_unary(e);
    return pp_primary(e);
}

static int64_t pp_mul(PPExpr *e) {
    int64_t val = pp_unary(e);
    for (;;) {
        if (pp_consume(e, "*")) val *= pp_unary(e);
        else if (pp_consume(e, "/")) {
            int64_t rhs = pp_unary(e);
            if (!e->suppress_eval) {
                if (!rhs) error("division by zero in #if expression");
                val /= rhs;
            }
        } else if (pp_consume(e, "%")) {
            int64_t rhs = pp_unary(e);
            if (!e->suppress_eval) {
                if (!rhs) error("division by zero in #if expression");
                val %= rhs;
            }
        } else return val;
    }
}

static int64_t pp_add(PPExpr *e) {
    int64_t val = pp_mul(e);
    for (;;) {
        if (pp_consume(e, "+")) val += pp_mul(e);
        else if (pp_consume(e, "-")) val -= pp_mul(e);
        else return val;
    }
}

static int64_t pp_shift(PPExpr *e) {
    int64_t val = pp_add(e);
    for (;;) {
        if (pp_consume(e, "<<")) val <<= pp_add(e);
        else if (pp_consume(e, ">>")) val >>= pp_add(e);
        else return val;
    }
}

static int64_t pp_rel(PPExpr *e) {
    int64_t val = pp_shift(e);
    for (;;) {
        if (pp_consume(e, "<=")) val = val <= pp_shift(e);
        else if (pp_consume(e, ">=")) val = val >= pp_shift(e);
        else if (pp_consume(e, "<")) val = val < pp_shift(e);
        else if (pp_consume(e, ">")) val = val > pp_shift(e);
        else return val;
    }
}

static int64_t pp_eq(PPExpr *e) {
    int64_t val = pp_rel(e);
    for (;;) {
        if (pp_consume(e, "==")) val = val == pp_rel(e);
        else if (pp_consume(e, "!=")) val = val != pp_rel(e);
        else return val;
    }
}

static int64_t pp_bitand(PPExpr *e) {
    int64_t val = pp_eq(e);
    for (;;) {
        pp_skip_space(e);
        if (e->p[0] == '&' && e->p[1] != '&') {
            e->p++;
            val &= pp_eq(e);
        } else return val;
    }
}

static int64_t pp_bitxor(PPExpr *e) {
    int64_t val = pp_bitand(e);
    while (pp_consume(e, "^"))
        val ^= pp_bitand(e);
    return val;
}

static int64_t pp_bitor(PPExpr *e) {
    int64_t val = pp_bitxor(e);
    for (;;) {
        pp_skip_space(e);
        if (e->p[0] == '|' && e->p[1] != '|') {
            e->p++;
            val |= pp_bitxor(e);
        } else return val;
    }
}

static int64_t pp_logand(PPExpr *e) {
    int64_t val = pp_bitor(e);
    while (pp_consume(e, "&&")) {
        bool saved = e->suppress_eval;
        if (!saved && !val)
            e->suppress_eval = true;
        int64_t rhs = pp_bitor(e);
        e->suppress_eval = saved;
        if (!saved)
            val = val && rhs;
    }
    return val;
}

static int64_t pp_logor(PPExpr *e) {
    int64_t val = pp_logand(e);
    while (pp_consume(e, "||")) {
        bool saved = e->suppress_eval;
        if (!saved && val)
            e->suppress_eval = true;
        int64_t rhs = pp_logand(e);
        e->suppress_eval = saved;
        if (!saved)
            val = val || rhs;
    }
    return val;
}

static int64_t pp_conditional(PPExpr *e) {
    int64_t cond = pp_logor(e);
    if (!pp_consume(e, "?"))
        return cond;

    bool saved = e->suppress_eval;
    if (!saved && !cond)
        e->suppress_eval = true;
    int64_t then_val = pp_conditional(e);
    e->suppress_eval = saved;

    if (!pp_consume(e, ":"))
        error("expected ':' in #if conditional expression");

    if (!saved && cond)
        e->suppress_eval = true;
    int64_t else_val = pp_conditional(e);
    e->suppress_eval = saved;

    if (saved)
        return 0;
    return cond ? then_val : else_val;
}

static int64_t eval_pp_expr_depth(const char *text, int depth) {
    PPExpr e = {.p = text, .depth = depth};
    int64_t val = pp_conditional(&e);
    pp_skip_space(&e);
    if (*e.p)
        error("unexpected token in #if expression near '%s'", e.p);
    return val;
}

static int64_t eval_pp_expr(const char *text) {
    return eval_pp_expr_depth(text, 0);
}

// ---- Macro expansion ---------------------------------------------------------

static bool expansion_contains(Expansion *stack, Macro *m) {
    for (; stack; stack = stack->next)
        if (stack->macro == m)
            return true;
    return false;
}

static char *expand_text(const char *text, Expansion *stack, bool *in_block_comment);

static int macro_param_index(Macro *m, const char *start, size_t len) {
    for (int i = 0; i < m->num_params; i++)
        if (strlen(m->params[i]) == len && !strncmp(m->params[i], start, len))
            return i;
    if (m->is_variadic && len == strlen("__VA_ARGS__") &&
        !strncmp(start, "__VA_ARGS__", len))
        return m->num_params;
    return -1;
}

static bool ident_is_pasted(const char *body, const char *start, const char *end) {
    const char *p = start;
    while (p > body && isspace((unsigned char)p[-1])) p--;
    bool left = p - body >= 2 && p[-1] == '#' && p[-2] == '#';
    p = end;
    while (*p && isspace((unsigned char)*p)) p++;
    bool right = p[0] == '#' && p[1] == '#';
    return left || right;
}

static char *stringify_arg(const char *arg) {
    char *trimmed = trim_copy(arg);
    StrBuf out;
    sb_init(&out, strlen(trimmed) + 8);
    sb_putc(&out, '"');

    bool pending_space = false;
    char quote = 0;
    for (const char *p = trimmed; *p; p++) {
        char c = *p;
        if (!quote && isspace((unsigned char)c)) {
            pending_space = true;
            continue;
        }
        if (pending_space && out.len > 1) {
            sb_putc(&out, ' ');
            pending_space = false;
        }
        if (c == '"' || c == '\\')
            sb_putc(&out, '\\');
        sb_putc(&out, c);
        if (quote) {
            if (c == '\\' && p[1]) {
                p++;
                if (*p == '"' || *p == '\\')
                    sb_putc(&out, '\\');
                sb_putc(&out, *p);
                continue;
            }
            if (c == quote)
                quote = 0;
        } else if (c == '"' || c == '\'') {
            quote = c;
        }
    }
    sb_putc(&out, '"');
    free(trimmed);
    return out.data;
}

static char *apply_token_paste(const char *text) {
    StrBuf out;
    sb_init(&out, strlen(text) + 1);
    const char *p = text;

    while (*p) {
        if (p[0] == '#' && p[1] == '#') {
            while (out.len && isspace((unsigned char)out.data[out.len - 1]))
                out.data[--out.len] = '\0';
            p += 2;
            while (*p && isspace((unsigned char)*p))
                p++;
            continue;
        }
        sb_putc(&out, *p++);
    }
    return out.data;
}

static char *join_variadic_args(char **args, int start, int argc) {
    StrBuf out;
    sb_init(&out, 32);
    for (int i = start; i < argc; i++) {
        if (i > start)
            sb_puts(&out, ", ");
        sb_puts(&out, args[i]);
    }
    return out.data;
}

static char *substitute_func_macro(Macro *m, char **raw_args, char **expanded_args) {
    StrBuf out;
    sb_init(&out, strlen(m->body) + 64);
    const char *p = m->body;

    while (*p) {
        if (p[0] == '#' && p[1] == '#') {
            sb_puts(&out, "##");
            p += 2;
            continue;
        }

        if (*p == '#') {
            const char *hash = p++;
            while (*p == ' ' || *p == '\t') p++;
            if (is_ident1_pp(*p)) {
                const char *start = p++;
                while (is_ident2_pp(*p)) p++;
                int idx = macro_param_index(m, start, (size_t)(p - start));
                if (idx >= 0) {
                    char *s = stringify_arg(raw_args[idx]);
                    sb_puts(&out, s);
                    free(s);
                    continue;
                }
            }
            p = hash;
        }

        if (is_ident1_pp(*p)) {
            const char *start = p++;
            while (is_ident2_pp(*p)) p++;
            int idx = macro_param_index(m, start, (size_t)(p - start));
            if (idx >= 0) {
                bool pasted = ident_is_pasted(m->body, start, p);
                sb_puts(&out, pasted ? raw_args[idx] : expanded_args[idx]);
            } else {
                sb_putn(&out, start, (size_t)(p - start));
            }
            continue;
        }

        sb_putc(&out, *p++);
    }

    char *pasted = apply_token_paste(out.data);
    free(out.data);
    return pasted;
}

static char *quote_pp_string(const char *text) {
    StrBuf out;
    sb_init(&out, strlen(text) + 8);
    sb_putc(&out, '"');
    for (const char *p = text; *p; p++) {
        if (*p == '\\' || *p == '"')
            sb_putc(&out, '\\');
        sb_putc(&out, *p);
    }
    sb_putc(&out, '"');
    return out.data;
}

static void copy_quoted(StrBuf *out, const char **pp, char quote) {
    const char *p = *pp;
    sb_putc(out, *p++);
    while (*p) {
        sb_putc(out, *p);
        if (*p == '\\' && p[1]) {
            p++;
            sb_putc(out, *p++);
            continue;
        }
        if (*p++ == quote)
            break;
    }
    *pp = p;
}

static char **parse_macro_args(const char **pp, int *argc_out) {
    const char *p = *pp;
    if (*p != '(')
        return NULL;
    p++;

    int cap = 4;
    int argc = 0;
    char **args = calloc(cap, sizeof(char *));
    StrBuf cur;
    sb_init(&cur, 32);
    int depth = 1;
    char quote = 0;

    while (*p && depth > 0) {
        if (quote) {
            sb_putc(&cur, *p);
            if (*p == '\\' && p[1]) {
                p++;
                sb_putc(&cur, *p++);
                continue;
            }
            if (*p == quote)
                quote = 0;
            p++;
            continue;
        }
        if (*p == '"' || *p == '\'') {
            quote = *p;
            sb_putc(&cur, *p++);
            continue;
        }
        if (*p == '(') {
            depth++;
            sb_putc(&cur, *p++);
            continue;
        }
        if (*p == ')') {
            depth--;
            if (depth == 0) {
                p++;
                break;
            }
            sb_putc(&cur, *p++);
            continue;
        }
        if (*p == ',' && depth == 1) {
            if (argc == cap) {
                cap *= 2;
                args = realloc(args, cap * sizeof(char *));
            }
            args[argc++] = strdup(cur.data);
            cur.len = 0;
            cur.data[0] = '\0';
            p++;
            continue;
        }
        sb_putc(&cur, *p++);
    }

    if (depth != 0)
        error("unterminated function-like macro invocation");

    char *trimmed = trim_copy(cur.data);
    if (argc > 0 || *trimmed) {
        if (argc == cap) {
            cap *= 2;
            args = realloc(args, cap * sizeof(char *));
        }
        args[argc++] = strdup(cur.data);
    }
    free(trimmed);
    free(cur.data);
    *pp = p;
    *argc_out = argc;
    return args;
}

static char *expand_text(const char *text, Expansion *stack, bool *in_block_comment) {
    StrBuf out;
    sb_init(&out, strlen(text) + 64);
    const char *p = text;

    while (*p) {
        if (*in_block_comment) {
            const char *end = strstr(p, "*/");
            if (!end) {
                sb_puts(&out, p);
                break;
            }
            sb_putn(&out, p, (size_t)(end + 2 - p));
            p = end + 2;
            *in_block_comment = false;
            continue;
        }
        if (p[0] == '/' && p[1] == '*') {
            *in_block_comment = true;
            sb_putn(&out, p, 2);
            p += 2;
            continue;
        }
        if (p[0] == '/' && p[1] == '/') {
            sb_puts(&out, p);
            break;
        }
        if (*p == '"' || *p == '\'') {
            copy_quoted(&out, &p, *p);
            continue;
        }
        if (!is_ident1_pp(*p)) {
            sb_putc(&out, *p++);
            continue;
        }

        const char *start = p++;
        while (is_ident2_pp(*p))
            p++;
        char *ident = strndup(start, (size_t)(p - start));
        Macro *m = find_macro(ident);

        if (!m || expansion_contains(stack, m)) {
            sb_putn(&out, start, (size_t)(p - start));
            free(ident);
            continue;
        }

        if (m->builtin == BUILTIN_MACRO_LINE) {
            char buf[32];
            snprintf(buf, sizeof(buf), "%d", current_pp_line);
            sb_puts(&out, buf);
            free(ident);
            continue;
        }
        if (m->builtin == BUILTIN_MACRO_FILE) {
            char *quoted = quote_pp_string(current_pp_file ? current_pp_file : "<stdin>");
            sb_puts(&out, quoted);
            free(quoted);
            free(ident);
            continue;
        }

        Expansion frame = {.next = stack, .macro = m};
        if (m->is_objlike) {
            bool nested_comment = false;
            char *expanded = expand_text(m->body, &frame, &nested_comment);
            sb_puts(&out, expanded);
            free(expanded);
            free(ident);
            continue;
        }

        const char *after_name = p;
        while (*after_name == ' ' || *after_name == '\t')
            after_name++;
        if (*after_name != '(') {
            sb_putn(&out, start, (size_t)(p - start));
            free(ident);
            continue;
        }

        int argc = 0;
        const char *after_call = after_name;
        char **args = parse_macro_args(&after_call, &argc);
        if ((!m->is_variadic && argc != m->num_params) ||
            (m->is_variadic && argc < m->num_params))
            error("macro '%s' argument count mismatch", m->name);

        int slots = m->num_params + (m->is_variadic ? 1 : 0);
        char **raw = calloc(slots ? slots : 1, sizeof(char *));
        char **expanded = calloc(slots ? slots : 1, sizeof(char *));

        for (int i = 0; i < m->num_params; i++)
            raw[i] = strdup(args[i]);
        if (m->is_variadic)
            raw[m->num_params] = join_variadic_args(args, m->num_params, argc);

        for (int i = 0; i < slots; i++) {
            bool arg_comment = false;
            expanded[i] = expand_text(raw[i], stack, &arg_comment);
        }

        char *subst = substitute_func_macro(m, raw, expanded);
        bool nested_comment = false;
        char *rescanned = expand_text(subst, &frame, &nested_comment);
        sb_puts(&out, rescanned);

        for (int i = 0; i < argc; i++)
            free(args[i]);
        free(args);
        for (int i = 0; i < slots; i++) {
            free(raw[i]);
            free(expanded[i]);
        }
        free(raw);
        free(expanded);
        free(subst);
        free(rescanned);
        free(ident);
        p = after_call;
    }

    return out.data;
}

static char *read_directive_ident(char **pp) {
    char *p = *pp;
    while (*p == ' ' || *p == '\t') p++;
    if (!is_ident1_pp(*p))
        return NULL;
    char *start = p++;
    while (is_ident2_pp(*p)) p++;
    *pp = p;
    return strndup(start, (size_t)(p - start));
}

static void parse_define(char *start) {
    char *name = read_directive_ident(&start);
    if (!name)
        error("expected macro name after #define");

    bool is_objlike = true;
    bool is_variadic = false;
    char **params = NULL;
    int num_params = 0;

    // Function-like macros require '(' immediately after the macro name.
    if (*start == '(') {
        is_objlike = false;
        start++;
        int cap = 4;
        params = calloc(cap, sizeof(char *));

        while (*start && *start != ')') {
            while (*start == ' ' || *start == '\t') start++;
            if (!strncmp(start, "...", 3)) {
                is_variadic = true;
                start += 3;
                while (*start == ' ' || *start == '\t') start++;
                if (*start != ')')
                    error("'...' must be the final macro parameter");
                break;
            }

            char *param = read_directive_ident(&start);
            if (!param)
                error("expected parameter name in macro '%s'", name);
            if (num_params == cap) {
                cap *= 2;
                params = realloc(params, cap * sizeof(char *));
            }
            params[num_params++] = param;
            while (*start == ' ' || *start == '\t') start++;
            if (*start == ',') {
                start++;
                continue;
            }
            if (*start != ')')
                error("expected ',' or ')' in macro '%s'", name);
        }
        if (*start != ')')
            error("unterminated macro parameter list for '%s'", name);
        start++;
    }

    while (*start == ' ' || *start == '\t') start++;
    add_macro(name, is_objlike, is_variadic, params, num_params, strdup(start));
}

char *preprocess_v2_source(char *input, const char *source_name) {
    const char *saved_file = current_pp_file;
    int saved_line = current_pp_line;
    bool outermost = preprocess_depth++ == 0;
    if (outermost) {
        add_macro(strdup("__STDC__"), true, false, NULL, 0, strdup("1"));
        add_macro(strdup("__STDC_VERSION__"), true, false, NULL, 0, strdup("201112L"));
        add_macro(strdup("__STDC_HOSTED__"), true, false, NULL, 0, strdup("1"));
        add_builtin_macro("__LINE__", BUILTIN_MACRO_LINE);
        add_builtin_macro("__FILE__", BUILTIN_MACRO_FILE);
    }

    CondStack *base_cond = cond_stack;
    char *spliced = splice_lines(input);
    StrBuf out;
    sb_init(&out, strlen(spliced) * 2 + 1024);
    bool in_block_comment = false;

    char *p = spliced;
    int line_no = 0;
    int line_offset = 0;
    char *logical_file = strdup(source_name ? source_name : "<stdin>");
    while (*p) {
        line_no++;
        current_pp_file = logical_file;
        current_pp_line = line_no + line_offset;
        char *line_start = p;
        while (*p && *p != '\n') p++;
        size_t line_len = (size_t)(p - line_start);
        if (*p == '\n') p++;

        char *line = strndup(line_start, line_len);
        char *start = line;
        while (*start == ' ' || *start == '\t') start++;

        if (!in_block_comment && *start == '#') {
            start++;
            while (*start == ' ' || *start == '\t') start++;
            char *kw_start = start;
            while (is_ident2_pp(*start)) start++;
            char *directive = strndup(kw_start, (size_t)(start - kw_start));
            while (*start == ' ' || *start == '\t') start++;

            if (!strcmp(directive, "ifdef")) {
                char *name = read_directive_ident(&start);
                if (!name) error("expected identifier after #ifdef");
                push_cond(find_macro(name) != NULL);
                free(name);
            } else if (!strcmp(directive, "ifndef")) {
                char *name = read_directive_ident(&start);
                if (!name) error("expected identifier after #ifndef");
                push_cond(find_macro(name) == NULL);
                free(name);
            } else if (!strcmp(directive, "if")) {
                bool parent_active = is_cond_active();
                push_cond(parent_active ? eval_pp_expr(start) != 0 : false);
            } else if (!strcmp(directive, "elif")) {
                bool should_eval = cond_stack && cond_stack->parent_active &&
                                   !cond_stack->branch_taken && !cond_stack->seen_else;
                handle_elif(should_eval ? eval_pp_expr(start) != 0 : false);
            } else if (!strcmp(directive, "else")) {
                handle_else();
            } else if (!strcmp(directive, "endif")) {
                handle_endif();
            } else if (is_cond_active() && !strcmp(directive, "define")) {
                parse_define(start);
            } else if (is_cond_active() && !strcmp(directive, "undef")) {
                char *name = read_directive_ident(&start);
                if (!name) error("expected identifier after #undef");
                undef_macro(name);
                free(name);
            } else if (is_cond_active() && !strcmp(directive, "include")) {
                // C11 6.10.2: if the directive does not directly contain a
                // header-name token, macro-expand the remaining preprocessing
                // tokens and interpret the result as the header name.
                char *expanded_include = NULL;
                char *include_operand = start;
                if (*include_operand != '"' && *include_operand != '<') {
                    bool directive_comment = false;
                    expanded_include = expand_text(include_operand, NULL, &directive_comment);
                    include_operand = expanded_include;
                    while (*include_operand == ' ' || *include_operand == '\t')
                        include_operand++;
                }

                char quote = *include_operand;
                if (quote != '"' && quote != '<')
                    error("#include requires a header name");
                char end_quote = quote == '"' ? '"' : '>';
                char *hname = include_operand + 1;
                char *end_h = strchr(hname, end_quote);
                if (!end_h)
                    error("unterminated #include");
                *end_h = '\0';

                char *owned = NULL;
                const char *content = NULL;
                if (quote == '"')
                    owned = read_file_content(hname);
                content = owned ? owned : get_builtin_header(hname);
                if (!content)
                    error("cannot include %s", hname);
                char *sub = preprocess_v2_source((char *)content, hname);
                sb_puts(&out, sub);
                if (out.len && out.data[out.len - 1] != '\n')
                    sb_putc(&out, '\n');
                free(sub);
                free(owned);
                free(expanded_include);
            } else if (is_cond_active() && !strcmp(directive, "line")) {
                // C11 #line operands are macro-expanded before interpretation.
                bool directive_comment = false;
                char *expanded = expand_text(start, NULL, &directive_comment);
                char *q = expanded;
                while (*q == ' ' || *q == '\t') q++;
                char *end = NULL;
                long requested = strtol(q, &end, 10);
                if (end == q || requested <= 0 || requested > 2147483647L)
                    error("#line requires a positive decimal line number");
                q = end;
                while (*q == ' ' || *q == '\t') q++;
                if (*q) {
                    if (*q != '"')
                        error("#line filename must be a string literal");
                    char *name_start = ++q;
                    while (*q && *q != '"') q++;
                    if (!*q)
                        error("unterminated #line filename");
                    char *next_file = strndup(name_start, (size_t)(q - name_start));
                    q++;
                    while (*q == ' ' || *q == '\t') q++;
                    if (*q)
                        error("extra tokens after #line directive");
                    free(logical_file);
                    logical_file = next_file;
                }
                line_offset = (int)requested - (line_no + 1);
                free(expanded);
            } else if (is_cond_active() && !strcmp(directive, "error")) {
                error("#error %s", start);
            }

            free(directive);
            free(line);
            continue;
        }

        if (is_cond_active()) {
            char *expanded = expand_text(line, NULL, &in_block_comment);
            sb_puts(&out, expanded);
            sb_putc(&out, '\n');
            free(expanded);
        }
        free(line);
    }

    free(spliced);
    if (cond_stack != base_cond)
        error("unterminated conditional directive");
    preprocess_depth--;
    current_pp_file = saved_file;
    current_pp_line = saved_line;
    free(logical_file);
    return out.data;
}

char *preprocess_v2(char *input) {
    return preprocess_v2_source(input, "<stdin>");
}
