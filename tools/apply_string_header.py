from pathlib import Path

pp = Path('preprocess_v2.c')
text = pp.read_text()
old = '''    if (!strcmp(name, "limits.h")) {
'''
new = '''    if (!strcmp(name, "string.h")) {
        return "#ifndef __MINICC_STRING_H\\n"
               "#define __MINICC_STRING_H 1\\n"
               "#include <stddef.h>\\n"
               "void *memcpy(void * restrict s1, const void * restrict s2, size_t n);\\n"
               "void *memmove(void *s1, const void *s2, size_t n);\\n"
               "char *strcpy(char * restrict s1, const char * restrict s2);\\n"
               "char *strncpy(char * restrict s1, const char * restrict s2, size_t n);\\n"
               "char *strcat(char * restrict s1, const char * restrict s2);\\n"
               "char *strncat(char * restrict s1, const char * restrict s2, size_t n);\\n"
               "int memcmp(const void *s1, const void *s2, size_t n);\\n"
               "int strcmp(const char *s1, const char *s2);\\n"
               "int strcoll(const char *s1, const char *s2);\\n"
               "int strncmp(const char *s1, const char *s2, size_t n);\\n"
               "size_t strxfrm(char * restrict s1, const char * restrict s2, size_t n);\\n"
               "void *memchr(const void *s, int c, size_t n);\\n"
               "char *strchr(const char *s, int c);\\n"
               "size_t strcspn(const char *s1, const char *s2);\\n"
               "char *strpbrk(const char *s1, const char *s2);\\n"
               "char *strrchr(const char *s, int c);\\n"
               "size_t strspn(const char *s1, const char *s2);\\n"
               "char *strstr(const char *s1, const char *s2);\\n"
               "char *strtok(char * restrict s1, const char * restrict s2);\\n"
               "void *memset(void *s, int c, size_t n);\\n"
               "char *strerror(int errnum);\\n"
               "size_t strlen(const char *s);\\n"
               "#endif\\n";
    }
    if (!strcmp(name, "limits.h")) {
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one limits header anchor, found {text.count(old)}')
pp.write_text(text.replace(old, new, 1))

mk = Path('Makefile')
text = mk.read_text()
old = '''\tbash ./test/limits_header.sh
\tbash ./test/stddef_header.sh
\tbash ./test/noreturn.sh
'''
new = '''\tbash ./test/limits_header.sh
\tbash ./test/stddef_header.sh
\tbash ./test/string_header.sh
\tbash ./test/noreturn.sh
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one stddef test anchor, found {text.count(old)}')
mk.write_text(text.replace(old, new, 1))
