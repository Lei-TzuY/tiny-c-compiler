#include "minicc.h"
#include "preprocess_v2.h"
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>

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

typedef enum {
    CLI_MACRO_DEFINE,
    CLI_MACRO_UNDEF,
} CliMacroKind;

typedef struct CliMacroAction CliMacroAction;
struct CliMacroAction {
    CliMacroAction *next;
    CliMacroKind kind;
    char *arg;
};

typedef struct OnceFile OnceFile;
struct OnceFile {
    OnceFile *next;
    bool has_stat;
    dev_t dev;
    ino_t ino;
    char *name;
};

typedef struct Dependency Dependency;
struct Dependency {
    Dependency *next;
    bool has_stat;
    dev_t dev;
    ino_t ino;
    char *path;
    bool is_system;
};

typedef struct IncludePath IncludePath;
struct IncludePath {
    IncludePath *next;
    char *path;
    bool is_system;
};

static void parse_define(char *start);

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
static CliMacroAction *cli_macro_actions;
static CliMacroAction *cli_macro_actions_tail;
static OnceFile *once_files;
static Dependency *dependencies;
static Dependency *dependencies_tail;
static IncludePath *include_paths;
static IncludePath *include_paths_tail;

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

static bool stat_source(const char *source_name, struct stat *st) {
    return source_name && source_name[0] != '<' && stat(source_name, st) == 0;
}

static bool once_contains_source(const char *source_name) {
    struct stat st;
    bool has_stat = stat_source(source_name, &st);

    for (OnceFile *file = once_files; file; file = file->next) {
        if (has_stat && file->has_stat) {
            if (file->dev == st.st_dev && file->ino == st.st_ino)
                return true;
            continue;
        }
        if (!has_stat && !file->has_stat && file->name && source_name &&
            !strcmp(file->name, source_name))
            return true;
    }
    return false;
}

static void mark_once_source(const char *source_name) {
    if (!source_name || once_contains_source(source_name))
        return;

    OnceFile *file = calloc(1, sizeof(OnceFile));
    struct stat st;
    file->has_stat = stat_source(source_name, &st);
    if (file->has_stat) {
        file->dev = st.st_dev;
        file->ino = st.st_ino;
    } else {
        file->name = strdup(source_name);
    }
    file->next = once_files;
    once_files = file;
}

static void clear_once_files(void) {
    while (once_files) {
        OnceFile *next = once_files->next;
        free(once_files->name);
        free(once_files);
        once_files = next;
    }
}


static void clear_dependencies(void) {
    while (dependencies) {
        Dependency *next = dependencies->next;
        free(dependencies->path);
        free(dependencies);
        dependencies = next;
    }
    dependencies_tail = NULL;
}

static void record_dependency(const char *path, bool is_system) {
    if (!path || !*path)
        return;

    struct stat st;
    bool has_stat = stat_source(path, &st);
    for (Dependency *dep = dependencies; dep; dep = dep->next) {
        bool same = false;
        if (has_stat && dep->has_stat)
            same = dep->dev == st.st_dev && dep->ino == st.st_ino;
        else if (!has_stat && !dep->has_stat)
            same = !strcmp(dep->path, path);
        if (!same)
            continue;

        // If a physical header is reachable through both a system and a user
        // path, keep one prerequisite but retain the stronger user dependency.
        if (!is_system)
            dep->is_system = false;
        return;
    }

    Dependency *dep = calloc(1, sizeof(Dependency));
    dep->has_stat = has_stat;
    if (has_stat) {
        dep->dev = st.st_dev;
        dep->ino = st.st_ino;
    }
    dep->path = strdup(path);
    dep->is_system = is_system;
    if (dependencies_tail)
        dependencies_tail->next = dep;
    else
        dependencies = dep;
    dependencies_tail = dep;
}

int preprocess_v2_dependency_count(void) {
    int count = 0;
    for (Dependency *dep = dependencies; dep; dep = dep->next)
        count++;
    return count;
}

const char *preprocess_v2_dependency_at(int index) {
    if (index < 0)
        return NULL;
    for (Dependency *dep = dependencies; dep; dep = dep->next)
        if (index-- == 0)
            return dep->path;
    return NULL;
}

int preprocess_v2_dependency_is_system(int index) {
    if (index < 0)
        return 0;
    for (Dependency *dep = dependencies; dep; dep = dep->next)
        if (index-- == 0)
            return dep->is_system ? 1 : 0;
    return 0;
}

static void queue_cli_macro_action(CliMacroKind kind, const char *arg) {
    CliMacroAction *action = calloc(1, sizeof(CliMacroAction));
    action->kind = kind;
    action->arg = strdup(arg);
    if (cli_macro_actions_tail)
        cli_macro_actions_tail->next = action;
    else
        cli_macro_actions = action;
    cli_macro_actions_tail = action;
}

void preprocess_v2_add_define(const char *definition) {
    if (!definition || !*definition || !is_ident1_pp(*definition))
        error("invalid macro name in -D option: %s", definition ? definition : "");

    const char *p = definition + 1;
    while (is_ident2_pp(*p))
        p++;
    if (*p && *p != '=' && *p != '(')
        error("invalid macro name in -D option: %s", definition);

    queue_cli_macro_action(CLI_MACRO_DEFINE, definition);
}

void preprocess_v2_add_undef(const char *name) {
    if (!name || !*name || !is_ident1_pp(*name))
        error("invalid macro name in -U option: %s", name ? name : "");
    for (const char *p = name + 1; *p; p++)
        if (!is_ident2_pp(*p))
            error("invalid macro name in -U option: %s", name);

    queue_cli_macro_action(CLI_MACRO_UNDEF, name);
}

static void add_include_path(const char *path, bool is_system,
                             const char *option_name) {
    if (!path || !*path)
        error("empty include path in %s option", option_name);
    if (!is_system && !strcmp(path, "-"))
        error("'-I-' is not supported");

    IncludePath *entry = calloc(1, sizeof(IncludePath));
    entry->path = strdup(path);
    entry->is_system = is_system;
    if (include_paths_tail)
        include_paths_tail->next = entry;
    else
        include_paths = entry;
    include_paths_tail = entry;
}

void preprocess_v2_add_include_path(const char *path) {
    add_include_path(path, false, "-I");
}

void preprocess_v2_add_system_include_path(const char *path) {
    add_include_path(path, true, "-isystem");
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

static void apply_cli_macro_actions(void) {
    for (CliMacroAction *action = cli_macro_actions; action; action = action->next) {
        if (action->kind == CLI_MACRO_UNDEF) {
            undef_macro(action->arg);
            continue;
        }

        char *definition = strdup(action->arg);
        char *eq = strchr(definition, '=');
        if (eq) {
            *eq = ' ';
        } else {
            size_t len = strlen(definition);
            definition = realloc(definition, len + 3);
            definition[len] = ' ';
            definition[len + 1] = '1';
            definition[len + 2] = '\0';
        }
        parse_define(definition);
        free(definition);
    }
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
        return strdup(header);

    size_t dir_len = (size_t)(slash - source_name + 1);
    size_t header_len = strlen(header);
    char *path = calloc(1, dir_len + header_len + 1);
    memcpy(path, source_name, dir_len);
    memcpy(path + dir_len, header, header_len);
    return path;
}

static char *join_include_path(const char *dir, const char *header) {
    if (!dir || !*dir || !header || !*header)
        return NULL;
    size_t dir_len = strlen(dir);
    size_t header_len = strlen(header);
    bool need_slash = dir[dir_len - 1] != '/';
    char *path = calloc(1, dir_len + (need_slash ? 1 : 0) + header_len + 1);
    memcpy(path, dir, dir_len);
    size_t pos = dir_len;
    if (need_slash)
        path[pos++] = '/';
    memcpy(path + pos, header, header_len + 1);
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

static bool has_matching_system_include_path(const char *path) {
    for (IncludePath *entry = include_paths; entry; entry = entry->next)
        if (entry->is_system && !strcmp(entry->path, path))
            return true;
    return false;
}

static char *read_include_paths(const char *header, bool system,
                                char **resolved_path) {
    for (IncludePath *entry = include_paths; entry; entry = entry->next) {
        if (entry->is_system != system)
            continue;
        // GCC treats a directory named by both -I and -isystem as a system
        // directory, so suppress the user-path copy and search it in the
        // system-path phase instead.
        if (!system && has_matching_system_include_path(entry->path))
            continue;

        char *candidate = join_include_path(entry->path, header);
        char *content = read_file_content(candidate);
        if (content) {
            *resolved_path = candidate;
            return content;
        }
        free(candidate);
    }
    return NULL;
}

static char *get_builtin_header(char *name) {
    if (!strcmp(name, "stdio.h")) {
        return "#ifndef __MINICC_STDIO_H\n"
               "#define __MINICC_STDIO_H 1\n"
               "#include <stddef.h>\n"
               "#define EOF (-1)\n"
               "#define SEEK_SET 0\n"
               "#define SEEK_CUR 1\n"
               "#define SEEK_END 2\n"
               "typedef struct FILE FILE;\n"
               "extern FILE *stdin, *stdout, *stderr;\n"
               "int remove(const char *filename);\n"
               "int rename(const char *oldname, const char *newname);\n"
               "FILE *fopen(const char * restrict filename, const char * restrict mode);\n"
               "FILE *freopen(const char * restrict filename, const char * restrict mode, FILE * restrict stream);\n"
               "int fclose(FILE *stream);\n"
               "int fflush(FILE *stream);\n"
               "int fprintf(FILE * restrict stream, const char * restrict format, ...);\n"
               "int printf(const char * restrict format, ...);\n"
               "int sprintf(char * restrict s, const char * restrict format, ...);\n"
               "int snprintf(char * restrict s, size_t n, const char * restrict format, ...);\n"
               "int fscanf(FILE * restrict stream, const char * restrict format, ...);\n"
               "int scanf(const char * restrict format, ...);\n"
               "int sscanf(const char * restrict s, const char * restrict format, ...);\n"
               "int fgetc(FILE *stream);\n"
               "char *fgets(char * restrict s, int n, FILE * restrict stream);\n"
               "int fputc(int c, FILE *stream);\n"
               "int fputs(const char * restrict s, FILE * restrict stream);\n"
               "int getc(FILE *stream);\n"
               "int getchar(void);\n"
               "int putc(int c, FILE *stream);\n"
               "int putchar(int c);\n"
               "int puts(const char *s);\n"
               "int ungetc(int c, FILE *stream);\n"
               "size_t fread(void * restrict ptr, size_t size, size_t nmemb, FILE * restrict stream);\n"
               "size_t fwrite(const void * restrict ptr, size_t size, size_t nmemb, FILE * restrict stream);\n"
               "int fseek(FILE *stream, long offset, int whence);\n"
               "long ftell(FILE *stream);\n"
               "void rewind(FILE *stream);\n"
               "void clearerr(FILE *stream);\n"
               "int feof(FILE *stream);\n"
               "int ferror(FILE *stream);\n"
               "void perror(const char *s);\n"
               "#endif\n";
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
    if (!strcmp(name, "ctype.h")) {
        return "#ifndef __MINICC_CTYPE_H\n"
               "#define __MINICC_CTYPE_H 1\n"
               "int isalnum(int c);\n"
               "int isalpha(int c);\n"
               "int isblank(int c);\n"
               "int iscntrl(int c);\n"
               "int isdigit(int c);\n"
               "int isgraph(int c);\n"
               "int islower(int c);\n"
               "int isprint(int c);\n"
               "int ispunct(int c);\n"
               "int isspace(int c);\n"
               "int isupper(int c);\n"
               "int isxdigit(int c);\n"
               "int tolower(int c);\n"
               "int toupper(int c);\n"
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
               "#define assert(expression) ((void)((expression) || (fprintf(stderr, \"%s:%d: %s: Assertion `%s' failed.\\n\", __FILE__, __LINE__, __func__, #expression), abort(), 0)))\n"
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
    if (!strcmp(name, "float.h")) {
        return "#ifndef __MINICC_FLOAT_H\n"
               "#define __MINICC_FLOAT_H 1\n"
               "#define FLT_RADIX 2\n"
               "#define FLT_MANT_DIG 24\n"
               "#define DBL_MANT_DIG 53\n"
               "#define FLT_DIG 6\n"
               "#define DBL_DIG 15\n"
               "#define FLT_MIN_EXP (-125)\n"
               "#define DBL_MIN_EXP (-1021)\n"
               "#define FLT_MIN_10_EXP (-37)\n"
               "#define DBL_MIN_10_EXP (-307)\n"
               "#define FLT_MAX_EXP 128\n"
               "#define DBL_MAX_EXP 1024\n"
               "#define FLT_MAX_10_EXP 38\n"
               "#define DBL_MAX_10_EXP 308\n"
               "#define DECIMAL_DIG 17\n"
               "#define FLT_DECIMAL_DIG 9\n"
               "#define DBL_DECIMAL_DIG 17\n"
               "#define FLT_EVAL_METHOD 0\n"
               "#define FLT_ROUNDS 1\n"
               "#define FLT_HAS_SUBNORM 1\n"
               "#define DBL_HAS_SUBNORM 1\n"
               "#define FLT_MAX 0x1.fffffep+127F\n"
               "#define DBL_MAX 0x1.fffffffffffffp+1023\n"
               "#define FLT_EPSILON 0x1p-23F\n"
               "#define DBL_EPSILON 0x1p-52\n"
               "#define FLT_MIN 0x1p-126F\n"
               "#define DBL_MIN 0x1p-1022\n"
               "#define FLT_TRUE_MIN 0x1p-149F\n"
               "#define DBL_TRUE_MIN 0x1p-1074\n"
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
    if (!strcmp(name, "inttypes.h")) {
        return "#ifndef __MINICC_INTTYPES_H\n"
               "#define __MINICC_INTTYPES_H 1\n"
               "#include <stdint.h>\n"
               "#include <stddef.h>\n"
               "typedef struct { intmax_t quot; intmax_t rem; } imaxdiv_t;\n"
               "intmax_t imaxabs(intmax_t j);\n"
               "imaxdiv_t imaxdiv(intmax_t numer, intmax_t denom);\n"
               "intmax_t strtoimax(const char * restrict nptr, char ** restrict endptr, int base);\n"
               "uintmax_t strtoumax(const char * restrict nptr, char ** restrict endptr, int base);\n"
               "intmax_t wcstoimax(const wchar_t * restrict nptr, wchar_t ** restrict endptr, int base);\n"
               "uintmax_t wcstoumax(const wchar_t * restrict nptr, wchar_t ** restrict endptr, int base);\n"
               "#define PRId8 \"hhd\"\n"
               "#define PRIi8 \"hhi\"\n"
               "#define PRIo8 \"hho\"\n"
               "#define PRIu8 \"hhu\"\n"
               "#define PRIx8 \"hhx\"\n"
               "#define PRIX8 \"hhX\"\n"
               "#define PRId16 \"hd\"\n"
               "#define PRIi16 \"hi\"\n"
               "#define PRIo16 \"ho\"\n"
               "#define PRIu16 \"hu\"\n"
               "#define PRIx16 \"hx\"\n"
               "#define PRIX16 \"hX\"\n"
               "#define PRId32 \"d\"\n"
               "#define PRIi32 \"i\"\n"
               "#define PRIo32 \"o\"\n"
               "#define PRIu32 \"u\"\n"
               "#define PRIx32 \"x\"\n"
               "#define PRIX32 \"X\"\n"
               "#define PRId64 \"ld\"\n"
               "#define PRIi64 \"li\"\n"
               "#define PRIo64 \"lo\"\n"
               "#define PRIu64 \"lu\"\n"
               "#define PRIx64 \"lx\"\n"
               "#define PRIX64 \"lX\"\n"
               "#define PRIdLEAST8 PRId8\n"
               "#define PRIiLEAST8 PRIi8\n"
               "#define PRIoLEAST8 PRIo8\n"
               "#define PRIuLEAST8 PRIu8\n"
               "#define PRIxLEAST8 PRIx8\n"
               "#define PRIXLEAST8 PRIX8\n"
               "#define PRIdLEAST16 PRId16\n"
               "#define PRIiLEAST16 PRIi16\n"
               "#define PRIoLEAST16 PRIo16\n"
               "#define PRIuLEAST16 PRIu16\n"
               "#define PRIxLEAST16 PRIx16\n"
               "#define PRIXLEAST16 PRIX16\n"
               "#define PRIdLEAST32 PRId32\n"
               "#define PRIiLEAST32 PRIi32\n"
               "#define PRIoLEAST32 PRIo32\n"
               "#define PRIuLEAST32 PRIu32\n"
               "#define PRIxLEAST32 PRIx32\n"
               "#define PRIXLEAST32 PRIX32\n"
               "#define PRIdLEAST64 PRId64\n"
               "#define PRIiLEAST64 PRIi64\n"
               "#define PRIoLEAST64 PRIo64\n"
               "#define PRIuLEAST64 PRIu64\n"
               "#define PRIxLEAST64 PRIx64\n"
               "#define PRIXLEAST64 PRIX64\n"
               "#define PRIdFAST8 PRId64\n"
               "#define PRIiFAST8 PRIi64\n"
               "#define PRIoFAST8 PRIo64\n"
               "#define PRIuFAST8 PRIu64\n"
               "#define PRIxFAST8 PRIx64\n"
               "#define PRIXFAST8 PRIX64\n"
               "#define PRIdFAST16 PRId64\n"
               "#define PRIiFAST16 PRIi64\n"
               "#define PRIoFAST16 PRIo64\n"
               "#define PRIuFAST16 PRIu64\n"
               "#define PRIxFAST16 PRIx64\n"
               "#define PRIXFAST16 PRIX64\n"
               "#define PRIdFAST32 PRId64\n"
               "#define PRIiFAST32 PRIi64\n"
               "#define PRIoFAST32 PRIo64\n"
               "#define PRIuFAST32 PRIu64\n"
               "#define PRIxFAST32 PRIx64\n"
               "#define PRIXFAST32 PRIX64\n"
               "#define PRIdFAST64 PRId64\n"
               "#define PRIiFAST64 PRIi64\n"
               "#define PRIoFAST64 PRIo64\n"
               "#define PRIuFAST64 PRIu64\n"
               "#define PRIxFAST64 PRIx64\n"
               "#define PRIXFAST64 PRIX64\n"
               "#define PRIdMAX \"lld\"\n"
               "#define PRIiMAX \"lli\"\n"
               "#define PRIoMAX \"llo\"\n"
               "#define PRIuMAX \"llu\"\n"
               "#define PRIxMAX \"llx\"\n"
               "#define PRIXMAX \"llX\"\n"
               "#define PRIdPTR PRId64\n"
               "#define PRIiPTR PRIi64\n"
               "#define PRIoPTR PRIo64\n"
               "#define PRIuPTR PRIu64\n"
               "#define PRIxPTR PRIx64\n"
               "#define PRIXPTR PRIX64\n"
               "#define SCNd8 \"hhd\"\n"
               "#define SCNi8 \"hhi\"\n"
               "#define SCNo8 \"hho\"\n"
               "#define SCNu8 \"hhu\"\n"
               "#define SCNx8 \"hhx\"\n"
               "#define SCNd16 \"hd\"\n"
               "#define SCNi16 \"hi\"\n"
               "#define SCNo16 \"ho\"\n"
               "#define SCNu16 \"hu\"\n"
               "#define SCNx16 \"hx\"\n"
               "#define SCNd32 \"d\"\n"
               "#define SCNi32 \"i\"\n"
               "#define SCNo32 \"o\"\n"
               "#define SCNu32 \"u\"\n"
               "#define SCNx32 \"x\"\n"
               "#define SCNd64 \"ld\"\n"
               "#define SCNi64 \"li\"\n"
               "#define SCNo64 \"lo\"\n"
               "#define SCNu64 \"lu\"\n"
               "#define SCNx64 \"lx\"\n"
               "#define SCNdLEAST8 SCNd8\n"
               "#define SCNiLEAST8 SCNi8\n"
               "#define SCNoLEAST8 SCNo8\n"
               "#define SCNuLEAST8 SCNu8\n"
               "#define SCNxLEAST8 SCNx8\n"
               "#define SCNdLEAST16 SCNd16\n"
               "#define SCNiLEAST16 SCNi16\n"
               "#define SCNoLEAST16 SCNo16\n"
               "#define SCNuLEAST16 SCNu16\n"
               "#define SCNxLEAST16 SCNx16\n"
               "#define SCNdLEAST32 SCNd32\n"
               "#define SCNiLEAST32 SCNi32\n"
               "#define SCNoLEAST32 SCNo32\n"
               "#define SCNuLEAST32 SCNu32\n"
               "#define SCNxLEAST32 SCNx32\n"
               "#define SCNdLEAST64 SCNd64\n"
               "#define SCNiLEAST64 SCNi64\n"
               "#define SCNoLEAST64 SCNo64\n"
               "#define SCNuLEAST64 SCNu64\n"
               "#define SCNxLEAST64 SCNx64\n"
               "#define SCNdFAST8 SCNd64\n"
               "#define SCNiFAST8 SCNi64\n"
               "#define SCNoFAST8 SCNo64\n"
               "#define SCNuFAST8 SCNu64\n"
               "#define SCNxFAST8 SCNx64\n"
               "#define SCNdFAST16 SCNd64\n"
               "#define SCNiFAST16 SCNi64\n"
               "#define SCNoFAST16 SCNo64\n"
               "#define SCNuFAST16 SCNu64\n"
               "#define SCNxFAST16 SCNx64\n"
               "#define SCNdFAST32 SCNd64\n"
               "#define SCNiFAST32 SCNi64\n"
               "#define SCNoFAST32 SCNo64\n"
               "#define SCNuFAST32 SCNu64\n"
               "#define SCNxFAST32 SCNx64\n"
               "#define SCNdFAST64 SCNd64\n"
               "#define SCNiFAST64 SCNi64\n"
               "#define SCNoFAST64 SCNo64\n"
               "#define SCNuFAST64 SCNu64\n"
               "#define SCNxFAST64 SCNx64\n"
               "#define SCNdMAX \"lld\"\n"
               "#define SCNiMAX \"lli\"\n"
               "#define SCNoMAX \"llo\"\n"
               "#define SCNuMAX \"llu\"\n"
               "#define SCNxMAX \"llx\"\n"
               "#define SCNdPTR SCNd64\n"
               "#define SCNiPTR SCNi64\n"
               "#define SCNoPTR SCNo64\n"
               "#define SCNuPTR SCNu64\n"
               "#define SCNxPTR SCNx64\n"
               "#endif\n";
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

static char *preprocess_v2_source_impl(char *input, const char *source_name,
                                       bool source_is_system) {
    const char *saved_file = current_pp_file;
    int saved_line = current_pp_line;
    bool outermost = preprocess_depth++ == 0;
    if (outermost) {
        clear_once_files();
        clear_dependencies();
        add_macro(strdup("__STDC__"), true, false, NULL, 0, strdup("1"));
        add_macro(strdup("__STDC_VERSION__"), true, false, NULL, 0, strdup("201112L"));
        add_macro(strdup("__STDC_HOSTED__"), true, false, NULL, 0, strdup("1"));
        add_builtin_macro("__LINE__", BUILTIN_MACRO_LINE);
        add_builtin_macro("__FILE__", BUILTIN_MACRO_FILE);
        apply_cli_macro_actions();
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
            } else if (is_cond_active() && !strcmp(directive, "pragma")) {
                // #pragma is implementation-defined.  Support the ubiquitous
                // once form and deliberately ignore unknown pragmas.
                char *pragma = read_directive_ident(&start);
                if (pragma && !strcmp(pragma, "once"))
                    mark_once_source(source_name);
                free(pragma);
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
                bool included_is_system = false;
                if (hname[0] == '/') {
                    owned = read_file_content(hname);
                    if (owned) {
                        resolved_path = strdup(hname);
                        included_is_system = source_is_system;
                    }
                } else if (quote == '"') {
                    // A quoted include found next to the current physical file
                    // inherits that file's system classification. This is what
                    // makes -MM/-MMD omit a system header's private subheaders.
                    resolved_path = source_relative_include_path(source_name, hname);
                    if (resolved_path) {
                        owned = read_file_content(resolved_path);
                        if (owned)
                            included_is_system = source_is_system;
                    }
                }
                if (!owned) {
                    free(resolved_path);
                    resolved_path = NULL;
                    owned = read_include_paths(hname, false, &resolved_path);
                    // Once preprocessing is inside a system header, all of its
                    // indirect includes remain system dependencies even if the
                    // concrete file is found through a user -I directory.
                    included_is_system = source_is_system;
                }
                if (!owned) {
                    free(resolved_path);
                    resolved_path = NULL;
                    owned = read_include_paths(hname, true, &resolved_path);
                    if (owned)
                        included_is_system = true;
                }
                if (!owned && quote == '"') {
                    // Preserve the historical current-working-directory fallback
                    // after explicit user and system include directories.
                    owned = read_file_content(hname);
                    if (owned) {
                        resolved_path = strdup(hname);
                        included_is_system = source_is_system;
                    }
                }
                content = owned ? owned : get_builtin_header(hname);
                if (!content)
                    error("cannot include %s", hname);
                if (!owned)
                    included_is_system = true;

                // Recursive includes inherit both the resolved physical path and
                // system-header classification. Physical dependency deduplication
                // remains device/inode based, independent of path spelling.
                const char *included_source = owned ? resolved_path : hname;
                if (owned)
                    record_dependency(included_source, included_is_system);
                if (!once_contains_source(included_source)) {
                    char *sub = preprocess_v2_source_impl((char *)content, included_source,
                                                         included_is_system);
                    sb_puts(&out, sub);
                    if (out.len && out.data[out.len - 1] != '\n')
                        sb_putc(&out, '\n');
                    free(sub);
                }
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
    if (outermost)
        clear_once_files();
    return out.data;
}

char *preprocess_v2_source(char *input, const char *source_name) {
    return preprocess_v2_source_impl(input, source_name, false);
}

char *preprocess_v2(char *input) {
    return preprocess_v2_source(input, "<stdin>");
}
