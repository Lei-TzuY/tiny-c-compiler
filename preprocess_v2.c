#include "minicc.h"
#include "preprocess_v2.h"
#include <errno.h>

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

// Resolve a quoted include relative to the physical source file that
// contains the directive.  `#line` changes __FILE__/__LINE__ diagnostics but
// must not redirect the include search base, so callers pass the immutable
// preprocess_v2_source() source_name rather than current_pp_file/logical_file.
static char *source_relative_include_path(const char *source_name,
                                          const char *header) {
    if (!source_name || !header || !*header || header[0] == '/' ||
        source_name[0] == '<')
        return NULL;

    const char *slash = strrchr(source_name, '/');
    if (!slash)
        return NULL;

    size_t dir_len = (size_t)(slash - source_name + 1);
    size_t header_len = strlen(header);
    char *path = calloc(1, dir_len + header_len + 1);
    memcpy(path, source_name, dir_len);
    memcpy(path + dir_len, header, header_len);
    return path;
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
        return "#ifndef __MINICC_STDLIB_H\n"
               "#define __MINICC_STDLIB_H 1\n"
               "#include <stddef.h>\n"
               "#define EXIT_FAILURE 1\n"
               "#define EXIT_SUCCESS 0\n"
               "#define RAND_MAX 2147483647\n"
               "typedef struct { int quot; int rem; } div_t;\n"
               "typedef struct { long quot; long rem; } ldiv_t;\n"
               "typedef struct { long long quot; long long rem; } lldiv_t;\n"
               "double atof(const char *nptr);\n"
               "int atoi(const char *nptr);\n"
               "long atol(const char *nptr);\n"
               "long long atoll(const char *nptr);\n"
               "double strtod(const char * restrict nptr, char ** restrict endptr);\n"
               "float strtof(const char * restrict nptr, char ** restrict endptr);\n"
               "long strtol(const char * restrict nptr, char ** restrict endptr, int base);\n"
               "unsigned long strtoul(const char * restrict nptr, char ** restrict endptr, int base);\n"
               "long long strtoll(const char * restrict nptr, char ** restrict endptr, int base);\n"
               "unsigned long long strtoull(const char * restrict nptr, char ** restrict endptr, int base);\n"
               "int rand(void);\n"
               "void srand(unsigned int seed);\n"
               "void *malloc(size_t size);\n"
               "void *calloc(size_t nmemb, size_t size);\n"
               "void *realloc(void *ptr, size_t size);\n"
               "void free(void *ptr);\n"
               "void *aligned_alloc(size_t alignment, size_t size);\n"
               "_Noreturn void abort(void);\n"
               "int atexit(void (*func)(void));\n"
               "_Noreturn void exit(int status);\n"
               "_Noreturn void _Exit(int status);\n"
               "char *getenv(const char *name);\n"
               "int system(const char *string);\n"
               "void *bsearch(const void *key, const void *base, size_t nmemb, size_t size, int (*compar)(const void *, const void *));\n"
               "void qsort(void *base, size_t nmemb, size_t size, int (*compar)(const void *, const void *));\n"
               "int abs(int j);\n"
               "long labs(long j);\n"
               "long long llabs(long long j);\n"
               "div_t div(int numer, int denom);\n"
               "ldiv_t ldiv(long numer, long denom);\n"
               "lldiv_t lldiv(long long numer, long long denom);\n"
               "#endif\n";
    }
    if (!strcmp(name, "assert.h")) {
        return "#ifdef assert\n"
               "#undef assert\n"
               "#endif\n"
               "#ifdef NDEBUG\n"
               "#define assert(expression) ((void)0)\n"
               "#else\n"
               "#include <stdio.h>\n"
               "#include <stdlib.h>\n"
               "#define assert(expression) ((void)((expression) || (fprintf(stderr, \\\"%s:%d: %s: Assertion `%s' failed.\\\\n\\\", __FILE__, __LINE__, __func__, #expression), abort(), 0)))\n"
               "#endif\n";
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
    if (!strcmp(name, "stdalign.h")) {
        return "#define alignas _Alignas\n"
               "#define alignof _Alignof\n"
               "#define __alignas_is_defined 1\n"
               "#define __alignof_is_defined 1\n";
    }
    if (!strcmp(name, "stddef.h")) {
        return "#ifndef __MINICC_STDDEF_H\n"
               "#define __MINICC_STDDEF_H 1\n"
               "typedef unsigned long size_t;\n"
               "typedef long ptrdiff_t;\n"
               "typedef int wchar_t;\n"
               "typedef struct { long long __ll; double __d; } max_align_t;\n"
               "#define NULL ((void *)0)\n"
               "#define offsetof(type, member) __builtin_offsetof(type, member)\n"
               "#endif\n";
    }
    if (!strcmp(name, "string.h")) {
        return "#ifndef __MINICC_STRING_H\n"
               "#define __MINICC_STRING_H 1\n"
               "#include <stddef.h>\n"
               "void *memcpy(void * restrict s1, const void * restrict s2, size_t n);\n"
               "void *memmove(void *s1, const void *s2, size_t n);\n"
               "char *strcpy(char * restrict s1, const char * restrict s2);\n"
               "char *strncpy(char * restrict s1, const char * restrict s2, size_t n);\n"
               "char *strcat(char * restrict s1, const char * restrict s2);\n"
               "char *strncat(char * restrict s1, const char * restrict s2, size_t n);\n"
               "int memcmp(const void *s1, const void *s2, size_t n);\n"
               "int strcmp(const char *s1, const char *s2);\n"
               "int strcoll(const char *s1, const char *s2);\n"
               "int strncmp(const char *s1, const char *s2, size_t n);\n"
               "size_t strxfrm(char * restrict s1, const char * restrict s2, size_t n);\n"
               "void *memchr(const void *s, int c, size_t n);\n"
               "char *strchr(const char *s, int c);\n"
               "size_t strcspn(const char *s1, const char *s2);\n"
               "char *strpbrk(const char *s1, const char *s2);\n"
               "char *strrchr(const char *s, int c);\n"
               "size_t strspn(const char *s1, const char *s2);\n"
               "char *strstr(const char *s1, const char *s2);\n"
               "char *strtok(char * restrict s1, const char * restrict s2);\n"
               "void *memset(void *s, int c, size_t n);\n"
               "char *strerror(int errnum);\n"
               "size_t strlen(const char *s);\n"
               "#endif\n";
    }
    if (!strcmp(name, "limits.h")) {
        return "#define CHAR_BIT 8\n"
               "#define SCHAR_MIN (-127 - 1)\n"
               "#define SCHAR_MAX 127\n"
               "#define UCHAR_MAX 255\n"
               "#define CHAR_MIN SCHAR_MIN\n"
               "#define CHAR_MAX SCHAR_MAX\n"
               "#define MB_LEN_MAX 1\n"
               "#define SHRT_MIN (-32767 - 1)\n"
               "#define SHRT_MAX 32767\n"
               "#define USHRT_MAX 65535\n"
               "#define INT_MIN (-2147483647 - 1)\n"
               "#define INT_MAX 2147483647\n"
               "#define UINT_MAX 4294967295U\n"
               "#define LONG_MIN (-9223372036854775807L - 1)\n"
               "#define LONG_MAX 9223372036854775807L\n"
               "#define ULONG_MAX 18446744073709551615UL\n"
               "#define LLONG_MIN (-9223372036854775807LL - 1)\n"
               "#define LLONG_MAX 9223372036854775807LL\n"
               "#define ULLONG_MAX 18446744073709551615ULL\n";
    }
    if (!strcmp(name, "stdint.h")) {
        return "typedef signed char int8_t;\n"
               "typedef unsigned char uint8_t;\n"
               "typedef short int16_t;\n"
               "typedef unsigned short uint16_t;\n"
               "typedef int int32_t;\n"
               "typedef unsigned int uint32_t;\n"
               "typedef long int64_t;\n"
               "typedef unsigned long uint64_t;\n"
               "typedef signed char int_least8_t;\n"
               "typedef unsigned char uint_least8_t;\n"
               "typedef short int_least16_t;\n"
               "typedef unsigned short uint_least16_t;\n"
               "typedef int int_least32_t;\n"
               "typedef unsigned int uint_least32_t;\n"
               "typedef long int_least64_t;\n"
               "typedef unsigned long uint_least64_t;\n"
               "typedef long int_fast8_t;\n"
               "typedef unsigned long uint_fast8_t;\n"
               "typedef long int_fast16_t;\n"
               "typedef unsigned long uint_fast16_t;\n"
               "typedef long int_fast32_t;\n"
               "typedef unsigned long uint_fast32_t;\n"
               "typedef long int_fast64_t;\n"
               "typedef unsigned long uint_fast64_t;\n"
               "typedef long intptr_t;\n"
               "typedef unsigned long uintptr_t;\n"
               "typedef long long intmax_t;\n"
               "typedef unsigned long long uintmax_t;\n"
               "#define INT8_MIN (-127 - 1)\n"
               "#define INT8_MAX 127\n"
               "#define UINT8_MAX 255\n"
               "#define INT16_MIN (-32767 - 1)\n"
               "#define INT16_MAX 32767\n"
               "#define UINT16_MAX 65535\n"
               "#define INT32_MIN (-2147483647 - 1)\n"
               "#define INT32_MAX 2147483647\n"
               "#define UINT32_MAX 4294967295U\n"
               "#define INT64_MIN (-9223372036854775807L - 1)\n"
               "#define INT64_MAX 9223372036854775807L\n"
               "#define UINT64_MAX 18446744073709551615UL\n"
               "#define INT_LEAST8_MIN INT8_MIN\n"
               "#define INT_LEAST8_MAX INT8_MAX\n"
               "#define UINT_LEAST8_MAX UINT8_MAX\n"
               "#define INT_LEAST16_MIN INT16_MIN\n"
               "#define INT_LEAST16_MAX INT16_MAX\n"
               "#define UINT_LEAST16_MAX UINT16_MAX\n"
               "#define INT_LEAST32_MIN INT32_MIN\n"
               "#define INT_LEAST32_MAX INT32_MAX\n"
               "#define UINT_LEAST32_MAX UINT32_MAX\n"
               "#define INT_LEAST64_MIN INT64_MIN\n"
               "#define INT_LEAST64_MAX INT64_MAX\n"
               "#define UINT_LEAST64_MAX UINT64_MAX\n"
               "#define INT_FAST8_MIN INT64_MIN\n"
               "#define INT_FAST8_MAX INT64_MAX\n"
               "#define UINT_FAST8_MAX UINT64_MAX\n"
               "#define INT_FAST16_MIN INT64_MIN\n"
               "#define INT_FAST16_MAX INT64_MAX\n"
               "#define UINT_FAST16_MAX UINT64_MAX\n"
               "#define INT_FAST32_MIN INT64_MIN\n"
               "#define INT_FAST32_MAX INT64_MAX\n"
               "#define UINT_FAST32_MAX UINT64_MAX\n"
               "#define INT_FAST64_MIN INT64_MIN\n"
               "#define INT_FAST64_MAX INT64_MAX\n"
               "#define UINT_FAST64_MAX UINT64_MAX\n"
               "#define INTPTR_MIN INT64_MIN\n"
               "#define INTPTR_MAX INT64_MAX\n"
               "#define UINTPTR_MAX UINT64_MAX\n"
               "#define INTMAX_MIN (-9223372036854775807LL - 1)\n"
               "#define INTMAX_MAX 9223372036854775807LL\n"
               "#define UINTMAX_MAX 18446744073709551615ULL\n"
               "#define INT8_C(value) value\n"
               "#define UINT8_C(value) value\n"
               "#define INT16_C(value) value\n"
               "#define UINT16_C(value) value\n"
               "#define INT32_C(value) value\n"
               "#define UINT32_C(value) value ## U\n"
               "#define INT64_C(value) value ## L\n"
               "#define UINT64_C(value) value ## UL\n"
               "#define INTMAX_C(value) value ## LL\n"
               "#define UINTMAX_C(value) value ## ULL\n";
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

typedef struct {
    uint64_t bits;
    bool is_unsigned;
} PPValue;

static PPValue pp_conditional(PPExpr *e);

static PPValue pp_value(uint64_t bits, bool is_unsigned) {
    return (PPValue){.bits = bits, .is_unsigned = is_unsigned};
}

static PPValue pp_signed_value(int64_t value) {
    return pp_value((uint64_t)value, false);
}

static PPValue pp_unsigned_value(uint64_t value) {
    return pp_value(value, true);
}

static bool pp_truth(PPValue value) {
    return value.bits != 0;
}

static int64_t pp_as_signed(PPValue value) {
    return (int64_t)value.bits;
}

static bool pp_common_unsigned(PPValue lhs, PPValue rhs) {
    return lhs.is_unsigned || rhs.is_unsigned;
}

static PPValue pp_bool_value(bool value) {
    return pp_signed_value(value ? 1 : 0);
}

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

static int pp_hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static PPValue pp_read_char_constant(PPExpr *e) {
    pp_skip_space(e);
    const char *p = e->p;
    if (*p++ != '\'')
        error("internal error while reading #if character constant");
    if (!*p || *p == '\'' || *p == '\n')
        error("empty or unterminated character constant in #if expression");

    unsigned int value = 0;
    if (*p != '\\') {
        value = (unsigned char)*p++;
    } else {
        p++;
        if (!*p)
            error("unterminated escape in #if character constant");
        switch (*p) {
        case '\'': value = '\''; p++; break;
        case '"': value = '"'; p++; break;
        case '?': value = '?'; p++; break;
        case '\\': value = '\\'; p++; break;
        case 'a': value = '\a'; p++; break;
        case 'b': value = '\b'; p++; break;
        case 'f': value = '\f'; p++; break;
        case 'n': value = '\n'; p++; break;
        case 'r': value = '\r'; p++; break;
        case 't': value = '\t'; p++; break;
        case 'v': value = '\v'; p++; break;
        case 'x': {
            p++;
            int d = pp_hex_digit(*p);
            if (d < 0)
                error("hex escape in #if character constant requires a digit");
            while ((d = pp_hex_digit(*p)) >= 0) {
                if (value > (255u - (unsigned)d) / 16u)
                    error("character escape out of byte range in #if expression");
                value = value * 16u + (unsigned)d;
                p++;
            }
            break;
        }
        default:
            if (*p < '0' || *p > '7')
                error("unknown escape in #if character constant");
            for (int i = 0; i < 3 && *p >= '0' && *p <= '7'; i++) {
                unsigned d = (unsigned)(*p++ - '0');
                if (value > (255u - d) / 8u)
                    error("character escape out of byte range in #if expression");
                value = value * 8u + d;
            }
            break;
        }
    }

    if (*p != '\'')
        error("multi-character or unterminated character constant in #if expression");
    e->p = p + 1;
    return pp_signed_value((int64_t)value);
}

static PPValue eval_pp_expr_depth(const char *text, int depth, bool suppress_eval);
static PPValue pp_eval_function_macro(PPExpr *e, Macro *m);

static bool pp_integer_constant_is_unsigned(const char *start, uint64_t value,
                                            bool seen_u, int long_count) {
    if (seen_u)
        return true;

    bool decimal = *start != '0';
    if (decimal) {
        if (value > INT64_MAX)
            error("decimal integer constant is too large in #if expression");
        return false;
    }

    if (long_count > 0)
        return value > INT64_MAX;

    if (value <= INT32_MAX)
        return false;
    if (value <= UINT32_MAX)
        return true;
    if (value <= INT64_MAX)
        return false;
    return true;
}

static PPValue pp_primary(PPExpr *e) {
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
        return pp_bool_value(result);
    }
    if (ident) {
        Macro *m = find_macro(ident);
        PPValue result = pp_signed_value(0);
        if (m && m->builtin == BUILTIN_MACRO_LINE) {
            result = pp_signed_value(current_pp_line);
        } else if (m && m->builtin == BUILTIN_MACRO_FILE) {
            error("__FILE__ expands to a string and is not valid in #if arithmetic");
        } else if (m && m->is_objlike && e->depth < 64) {
            result = eval_pp_expr_depth(m->body, e->depth + 1, e->suppress_eval);
        } else if (m && !m->is_objlike && e->depth < 64) {
            result = pp_eval_function_macro(e, m);
        }
        free(ident);
        return result;
    }
    e->p = saved;

    if (pp_consume(e, "(")) {
        PPValue val = pp_conditional(e);
        if (!pp_consume(e, ")"))
            error("expected ')' in #if expression");
        return val;
    }

    pp_skip_space(e);
    if (*e->p == '\'')
        return pp_read_char_constant(e);
    if (isdigit((unsigned char)*e->p)) {
        const char *number_start = e->p;
        char *end;
        errno = 0;
        unsigned long long val = strtoull(e->p, &end, 0);
        if (errno == ERANGE)
            error("integer constant is too large in #if expression");
        if (end == e->p)
            error("invalid number in #if expression");

        const char *suffix = end;
        bool seen_u = false;
        int long_count = 0;
        if (*suffix == 'u' || *suffix == 'U') {
            seen_u = true;
            suffix++;
        }
        if (*suffix == 'l' || *suffix == 'L') {
            char first = *suffix++;
            long_count = 1;
            if (*suffix == first) {
                suffix++;
                long_count = 2;
            }
        }
        if (!seen_u && (*suffix == 'u' || *suffix == 'U')) {
            seen_u = true;
            suffix++;
        }
        if (*suffix == 'u' || *suffix == 'U' || *suffix == 'l' || *suffix == 'L')
            error("invalid integer suffix in #if expression");
        e->p = suffix;

        bool is_unsigned = pp_integer_constant_is_unsigned(number_start, val,
                                                           seen_u, long_count);
        return pp_value((uint64_t)val, is_unsigned);
    }
    error("invalid #if expression near '%s'", e->p);
}

static PPValue pp_unary(PPExpr *e) {
    if (pp_consume(e, "!"))
        return pp_bool_value(!pp_truth(pp_unary(e)));
    if (pp_consume(e, "~")) {
        PPValue val = pp_unary(e);
        val.bits = ~val.bits;
        return val;
    }
    if (pp_consume(e, "+"))
        return pp_unary(e);
    if (pp_consume(e, "-")) {
        PPValue val = pp_unary(e);
        val.bits = 0 - val.bits;
        return val;
    }
    return pp_primary(e);
}

static PPValue pp_mul(PPExpr *e) {
    PPValue val = pp_unary(e);
    for (;;) {
        if (pp_consume(e, "*")) {
            PPValue rhs = pp_unary(e);
            bool uns = pp_common_unsigned(val, rhs);
            val = pp_value(val.bits * rhs.bits, uns);
        } else if (pp_consume(e, "/")) {
            PPValue rhs = pp_unary(e);
            bool uns = pp_common_unsigned(val, rhs);
            if (e->suppress_eval) {
                val = pp_value(0, uns);
                continue;
            }
            if (!rhs.bits)
                error("division by zero in #if expression");
            if (uns) {
                val = pp_unsigned_value(val.bits / rhs.bits);
            } else {
                int64_t lhs_s = pp_as_signed(val);
                int64_t rhs_s = pp_as_signed(rhs);
                if (lhs_s == INT64_MIN && rhs_s == -1)
                    error("signed division overflow in #if expression");
                val = pp_signed_value(lhs_s / rhs_s);
            }
        } else if (pp_consume(e, "%")) {
            PPValue rhs = pp_unary(e);
            bool uns = pp_common_unsigned(val, rhs);
            if (e->suppress_eval) {
                val = pp_value(0, uns);
                continue;
            }
            if (!rhs.bits)
                error("division by zero in #if expression");
            if (uns) {
                val = pp_unsigned_value(val.bits % rhs.bits);
            } else {
                int64_t lhs_s = pp_as_signed(val);
                int64_t rhs_s = pp_as_signed(rhs);
                if (lhs_s == INT64_MIN && rhs_s == -1)
                    val = pp_signed_value(0);
                else
                    val = pp_signed_value(lhs_s % rhs_s);
            }
        } else {
            return val;
        }
    }
}

static PPValue pp_add(PPExpr *e) {
    PPValue val = pp_mul(e);
    for (;;) {
        if (pp_consume(e, "+")) {
            PPValue rhs = pp_mul(e);
            val = pp_value(val.bits + rhs.bits, pp_common_unsigned(val, rhs));
        } else if (pp_consume(e, "-")) {
            PPValue rhs = pp_mul(e);
            val = pp_value(val.bits - rhs.bits, pp_common_unsigned(val, rhs));
        } else {
            return val;
        }
    }
}

static PPValue pp_shift(PPExpr *e) {
    PPValue val = pp_add(e);
    for (;;) {
        bool left = false;
        if (pp_consume(e, "<<"))
            left = true;
        else if (!pp_consume(e, ">>"))
            return val;

        PPValue rhs = pp_add(e);
        if (e->suppress_eval) {
            val.bits = 0;
            continue;
        }
        int64_t count = pp_as_signed(rhs);
        if (rhs.is_unsigned) {
            if (rhs.bits >= 64)
                error("invalid shift count in #if expression");
            count = (int64_t)rhs.bits;
        }
        if (count < 0 || count >= 64)
            error("invalid shift count in #if expression");
        if (left)
            val.bits <<= (unsigned)count;
        else if (val.is_unsigned)
            val.bits >>= (unsigned)count;
        else
            val.bits = (uint64_t)(pp_as_signed(val) >> (unsigned)count);
    }
}

static PPValue pp_rel(PPExpr *e) {
    PPValue val = pp_shift(e);
    for (;;) {
        enum { PP_NONE, PP_LE, PP_GE, PP_LT, PP_GT } op = PP_NONE;
        if (pp_consume(e, "<=")) op = PP_LE;
        else if (pp_consume(e, ">=")) op = PP_GE;
        else if (pp_consume(e, "<")) op = PP_LT;
        else if (pp_consume(e, ">")) op = PP_GT;
        else return val;

        PPValue rhs = pp_shift(e);
        if (e->suppress_eval) {
            val = pp_signed_value(0);
            continue;
        }
        bool uns = pp_common_unsigned(val, rhs);
        bool result;
        if (uns) {
            if (op == PP_LE) result = val.bits <= rhs.bits;
            else if (op == PP_GE) result = val.bits >= rhs.bits;
            else if (op == PP_LT) result = val.bits < rhs.bits;
            else result = val.bits > rhs.bits;
        } else {
            int64_t lhs_s = pp_as_signed(val);
            int64_t rhs_s = pp_as_signed(rhs);
            if (op == PP_LE) result = lhs_s <= rhs_s;
            else if (op == PP_GE) result = lhs_s >= rhs_s;
            else if (op == PP_LT) result = lhs_s < rhs_s;
            else result = lhs_s > rhs_s;
        }
        val = pp_bool_value(result);
    }
}

static PPValue pp_eq(PPExpr *e) {
    PPValue val = pp_rel(e);
    for (;;) {
        bool is_eq;
        if (pp_consume(e, "==")) is_eq = true;
        else if (pp_consume(e, "!=")) is_eq = false;
        else return val;

        PPValue rhs = pp_rel(e);
        if (e->suppress_eval) {
            val = pp_signed_value(0);
            continue;
        }
        bool result;
        if (pp_common_unsigned(val, rhs))
            result = val.bits == rhs.bits;
        else
            result = pp_as_signed(val) == pp_as_signed(rhs);
        val = pp_bool_value(is_eq ? result : !result);
    }
}

static PPValue pp_bitand(PPExpr *e) {
    PPValue val = pp_eq(e);
    for (;;) {
        pp_skip_space(e);
        if (e->p[0] == '&' && e->p[1] != '&') {
            e->p++;
            PPValue rhs = pp_eq(e);
            val = pp_value(val.bits & rhs.bits, pp_common_unsigned(val, rhs));
        } else {
            return val;
        }
    }
}

static PPValue pp_bitxor(PPExpr *e) {
    PPValue val = pp_bitand(e);
    while (pp_consume(e, "^")) {
        PPValue rhs = pp_bitand(e);
        val = pp_value(val.bits ^ rhs.bits, pp_common_unsigned(val, rhs));
    }
    return val;
}

static PPValue pp_bitor(PPExpr *e) {
    PPValue val = pp_bitxor(e);
    for (;;) {
        pp_skip_space(e);
        if (e->p[0] == '|' && e->p[1] != '|') {
            e->p++;
            PPValue rhs = pp_bitxor(e);
            val = pp_value(val.bits | rhs.bits, pp_common_unsigned(val, rhs));
        } else {
            return val;
        }
    }
}

static PPValue pp_logand(PPExpr *e) {
    PPValue val = pp_bitor(e);
    while (pp_consume(e, "&&")) {
        bool lhs_truth = pp_truth(val);
        bool saved = e->suppress_eval;
        if (!saved && !lhs_truth)
            e->suppress_eval = true;
        PPValue rhs = pp_bitor(e);
        e->suppress_eval = saved;
        if (saved)
            val = pp_signed_value(0);
        else
            val = pp_bool_value(lhs_truth && pp_truth(rhs));
    }
    return val;
}

static PPValue pp_logor(PPExpr *e) {
    PPValue val = pp_logand(e);
    while (pp_consume(e, "||")) {
        bool lhs_truth = pp_truth(val);
        bool saved = e->suppress_eval;
        if (!saved && lhs_truth)
            e->suppress_eval = true;
        PPValue rhs = pp_logand(e);
        e->suppress_eval = saved;
        if (saved)
            val = pp_signed_value(0);
        else
            val = pp_bool_value(lhs_truth || pp_truth(rhs));
    }
    return val;
}

static PPValue pp_conditional(PPExpr *e) {
    PPValue cond = pp_logor(e);
    if (!pp_consume(e, "?"))
        return cond;

    bool saved = e->suppress_eval;
    if (!saved && !pp_truth(cond))
        e->suppress_eval = true;
    PPValue then_val = pp_conditional(e);
    e->suppress_eval = saved;

    if (!pp_consume(e, ":"))
        error("expected ':' in #if conditional expression");

    if (!saved && pp_truth(cond))
        e->suppress_eval = true;
    PPValue else_val = pp_conditional(e);
    e->suppress_eval = saved;

    bool uns = pp_common_unsigned(then_val, else_val);
    if (saved)
        return pp_value(0, uns);
    PPValue selected = pp_truth(cond) ? then_val : else_val;
    selected.is_unsigned = uns;
    return selected;
}

static PPValue eval_pp_expr_depth(const char *text, int depth, bool suppress_eval) {
    PPExpr e = {.p = text, .depth = depth, .suppress_eval = suppress_eval};
    PPValue val = pp_conditional(&e);
    pp_skip_space(&e);
    if (*e.p)
        error("unexpected token in #if expression near '%s'", e.p);
    return val;
}

static bool eval_pp_expr(const char *text) {
    return pp_truth(eval_pp_expr_depth(text, 0, false));
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

static PPValue pp_eval_function_macro(PPExpr *e, Macro *m) {
    const char *call = e->p;
    while (*call == ' ' || *call == '\t')
        call++;
    if (*call != '(')
        return pp_signed_value(0);

    int argc = 0;
    const char *after_call = call;
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
        expanded[i] = expand_text(raw[i], NULL, &arg_comment);
    }

    char *subst = substitute_func_macro(m, raw, expanded);
    Expansion frame = {.macro = m};
    bool nested_comment = false;
    char *rescanned = expand_text(subst, &frame, &nested_comment);
    PPValue result = eval_pp_expr_depth(rescanned, e->depth + 1, e->suppress_eval);

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
    e->p = after_call;
    return result;
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
                char *resolved_path = NULL;
                const char *content = NULL;
                if (quote == '"') {
                    // Quoted headers search next to the physical including file
                    // first. Preserve the historical current-working-directory
                    // fallback for callers using stdin or deliberately shared
                    // project-root headers.
                    resolved_path = source_relative_include_path(source_name, hname);
                    if (resolved_path)
                        owned = read_file_content(resolved_path);
                    if (!owned) {
                        free(resolved_path);
                        resolved_path = NULL;
                        owned = read_file_content(hname);
                        if (owned)
                            resolved_path = strdup(hname);
                    }
                }
                content = owned ? owned : get_builtin_header(hname);
                if (!content)
                    error("cannot include %s", hname);

                // Recursive quoted includes must inherit the resolved physical
                // path so their own relative header names are based on the
                // directory of the header that contains them.
                const char *included_source = owned ? resolved_path : hname;
                char *sub = preprocess_v2_source((char *)content, included_source);
                sb_puts(&out, sub);
                if (out.len && out.data[out.len - 1] != '\n')
                    sb_putc(&out, '\n');
                free(sub);
                free(owned);
                free(resolved_path);
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
