from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()
start_marker = '    if (!strcmp(name, "stdlib.h")) {'
end_marker = '    if (!strcmp(name, "stdbool.h")) {'
start = text.index(start_marker)
end = text.index(end_marker, start)

replacement = r'''    if (!strcmp(name, "stdlib.h")) {
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
'''

pp.write_text(text[:start] + replacement + text[end:])

Path("test/stdlib_header.sh").write_text(r'''#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stdlib-h.c
  "$MINICC" tmp-stdlib-h.c > tmp-stdlib-h.s
  cc -o tmp-stdlib-h tmp-stdlib-h.s
  set +e
  ./tmp-stdlib-h
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stdlib.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# Repeated inclusion must preserve the guarded declarations, size_t-backed
# allocation APIs, and the standard success/failure macros.
assert_run 0 '#include <stdlib.h>
#include <stdlib.h>
int main(void){void *(*m)(size_t)=malloc;void *p=m(16);if(!p)return 1;free(p);return EXIT_SUCCESS!=0||EXIT_FAILURE==0;}'

# calloc and realloc keep the existing host-libc ABI coverage while exercising
# size_t arguments from the expanded declaration set.
assert_run 0 '#include <stdlib.h>
int main(void){size_t n=32;unsigned char *p=calloc(n,1);if(!p)return 1;for(size_t i=0;i<n;i++)if(p[i]!=0)return 2;p[0]=7;p[31]=9;char *q=realloc(p,64);if(!q)return 3;if(q[0]!=7||q[31]!=9)return 4;free(q);return 0;}'

# C11 aligned_alloc integrates with the LP64 target alignment model.
assert_run 0 '#include <stdlib.h>
int main(void){void *p=aligned_alloc(16,32);if(!p)return 1;int bad=(unsigned long)p%16!=0;free(p);return bad;}'

# Numeric conversion families preserve end pointers, signedness, and floating
# return types through the host ABI.
assert_run 0 '#include <stdlib.h>
int main(void){char *e=0;if(atoi("-12")!=-12)return 1;if(atol("123456")!=123456L)return 2;if(atoll("-9876543210")!=-9876543210LL)return 3;if(atof("2.5")!=2.5)return 4;if(strtol("-123xyz",&e,10)!=-123L||*e!="x"[0])return 5;if(strtoul("456q",&e,10)!=456UL||*e!="q"[0])return 6;if(strtoll("-789!",&e,10)!=-789LL||*e!="!"[0])return 7;if(strtoull("18446744073709551615",&e,10)!=18446744073709551615ULL||*e)return 8;if(strtod("3.5z",&e)!=3.5||*e!="z"[0])return 9;if(strtof("1.25k",&e)!=1.25f||*e!="k"[0])return 10;return 0;}'

# abs families and div-family host struct returns exercise scalar and record ABI.
assert_run 0 '#include <stdlib.h>
int main(void){if(abs(-7)!=7||labs(-9L)!=9L||llabs(-11LL)!=11LL)return 1;div_t a=div(-17,5);if(a.quot!=-3||a.rem!=-2)return 2;ldiv_t b=ldiv(17L,5L);if(b.quot!=3L||b.rem!=2L)return 3;lldiv_t c=lldiv(-20LL,6LL);if(c.quot!=-3LL||c.rem!=-2LL)return 4;return 0;}'

# qsort calls a minicc-generated comparator from host libc; bsearch calls it
# again and returns a host pointer into the sorted array.
assert_run 0 '#include <stdlib.h>
int cmp(const void *a,const void *b){int x=*(const int*)a;int y=*(const int*)b;return (x>y)-(x<y);}int main(void){int a[6]={9,1,7,3,5,2};int want[6]={1,2,3,5,7,9};qsort(a,6,sizeof(int),cmp);for(int i=0;i<6;i++)if(a[i]!=want[i])return 1;int key=5;int *p=bsearch(&key,a,6,sizeof(int),cmp);return !p||*p!=5;}'

# Environment, PRNG, and system declarations are backed by libc.
assert_run 0 '#include <stdlib.h>
int main(void){if(!getenv("PATH"))return 1;srand(1);int r=rand();if(r<0||r>RAND_MAX)return 2;return system(":")!=0;}'

# Termination/registration function types must be usable without invoking the
# non-returning functions during the ordinary success-path test.
assert_run 0 '#include <stdlib.h>
void done(void){}int main(void){void (*a)(void)=abort;void (*b)(int)=exit;void (*c)(int)=_Exit;int (*d)(void(*)(void))=atexit;return !a||!b||!c||!d;}'

# exit must preserve its status across the declared host-libc prototype.
printf '%s\n' '#include <stdlib.h>
int main(void){exit(7);return 0;}' > tmp-stdlib-h.c
"$MINICC" tmp-stdlib-h.c > tmp-stdlib-h.s
cc -o tmp-stdlib-h tmp-stdlib-h.s
set +e
./tmp-stdlib-h
actual="$?"
set -e
if [ "$actual" != 7 ]; then
  echo "FAIL(stdlib.h exit): expected 7, got $actual"
  exit 1
fi

rm -f tmp-stdlib-h.c tmp-stdlib-h.s tmp-stdlib-h

echo 'All expanded <stdlib.h> tests passed!'
''')
