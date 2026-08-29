from pathlib import Path

pp = Path('preprocess_v2.c')
text = pp.read_text()
old = '''    if (!strcmp(name, "stdlib.h")) {
        return "void *malloc(unsigned long size);\\n"
               "void *calloc(unsigned long nmemb, unsigned long size);\\n"
               "void *realloc(void *ptr, unsigned long size);\\n"
               "void free(void *ptr);\\n"
               "void exit(int status);\\n"
               "int atoi(const char *nptr);\\n";
    }
'''
new = '''    if (!strcmp(name, "stdlib.h")) {
        return "#ifndef __MINICC_STDLIB_H\\n"
               "#define __MINICC_STDLIB_H 1\\n"
               "#include <stddef.h>\\n"
               "#define EXIT_FAILURE 1\\n"
               "#define EXIT_SUCCESS 0\\n"
               "#define RAND_MAX 2147483647\\n"
               "typedef struct { int quot; int rem; } div_t;\\n"
               "typedef struct { long quot; long rem; } ldiv_t;\\n"
               "typedef struct { long long quot; long long rem; } lldiv_t;\\n"
               "double atof(const char *nptr);\\n"
               "int atoi(const char *nptr);\\n"
               "long atol(const char *nptr);\\n"
               "long long atoll(const char *nptr);\\n"
               "double strtod(const char * restrict nptr, char ** restrict endptr);\\n"
               "float strtof(const char * restrict nptr, char ** restrict endptr);\\n"
               "long strtol(const char * restrict nptr, char ** restrict endptr, int base);\\n"
               "unsigned long strtoul(const char * restrict nptr, char ** restrict endptr, int base);\\n"
               "long long strtoll(const char * restrict nptr, char ** restrict endptr, int base);\\n"
               "unsigned long long strtoull(const char * restrict nptr, char ** restrict endptr, int base);\\n"
               "int rand(void);\\n"
               "void srand(unsigned int seed);\\n"
               "void *malloc(size_t size);\\n"
               "void *calloc(size_t nmemb, size_t size);\\n"
               "void *realloc(void *ptr, size_t size);\\n"
               "void free(void *ptr);\\n"
               "void *aligned_alloc(size_t alignment, size_t size);\\n"
               "_Noreturn void abort(void);\\n"
               "int atexit(void (*func)(void));\\n"
               "_Noreturn void exit(int status);\\n"
               "_Noreturn void _Exit(int status);\\n"
               "char *getenv(const char *name);\\n"
               "int system(const char *string);\\n"
               "void *bsearch(const void *key, const void *base, size_t nmemb, size_t size, int (*compar)(const void *, const void *));\\n"
               "void qsort(void *base, size_t nmemb, size_t size, int (*compar)(const void *, const void *));\\n"
               "int abs(int j);\\n"
               "long labs(long j);\\n"
               "long long llabs(long long j);\\n"
               "div_t div(int numer, int denom);\\n"
               "ldiv_t ldiv(long numer, long denom);\\n"
               "lldiv_t lldiv(long long numer, long long denom);\\n"
               "#endif\\n";
    }
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one stdlib header block, found {text.count(old)}')
pp.write_text(text.replace(old, new, 1))

mk = Path('Makefile')
text = mk.read_text()
old = '''\tbash ./test/string_header.sh
\tbash ./test/noreturn.sh
'''
new = '''\tbash ./test/string_header.sh
\tbash ./test/stdlib_header.sh
\tbash ./test/noreturn.sh
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one string test anchor, found {text.count(old)}')
mk.write_text(text.replace(old, new, 1))
