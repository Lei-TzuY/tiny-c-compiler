#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stdlib.c
  "$MINICC" tmp-stdlib.c > tmp-stdlib.s
  cc -o tmp-stdlib tmp-stdlib.s
  set +e
  ./tmp-stdlib
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stdlib.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# Repeated inclusion, size_t-backed allocation APIs, and standard status macros.
assert_run 0 '#include <stdlib.h>
#include <stdlib.h>
int main(void){void *p=calloc(4,sizeof(int));if(!p)return 1;p=realloc(p,8*sizeof(int));if(!p)return 2;free(p);return EXIT_SUCCESS!=0||EXIT_FAILURE==0;}'

# C11 aligned_alloc integrates with the target alignment model.
assert_run 0 '#include <stdlib.h>
int main(void){void *p=aligned_alloc(16,32);if(!p)return 1;int bad=(unsigned long)p%16!=0;free(p);return bad;}'

# Numeric conversion families preserve end pointers and scalar return types.
assert_run 0 '#include <stdlib.h>
int main(void){char *e=0;if(atoi("-12")!=-12)return 1;if(atol("123456")!=123456L)return 2;if(atoll("-9876543210")!=-9876543210LL)return 3;if(atof("2.5")!=2.5)return 4;if(strtol("-123xyz",&e,10)!=-123L||*e!="x"[0])return 5;if(strtoul("456q",&e,10)!=456UL||*e!="q"[0])return 6;if(strtoll("-789!",&e,10)!=-789LL||*e!="!"[0])return 7;if(strtoull("18446744073709551615",&e,10)!=18446744073709551615ULL||*e)return 8;if(strtod("3.5z",&e)!=3.5||*e!="z"[0])return 9;if(strtof("1.25k",&e)!=1.25f||*e!="k"[0])return 10;return 0;}'

# abs families and div-family host struct returns exercise scalar and record ABI.
assert_run 0 '#include <stdlib.h>
int main(void){if(abs(-7)!=7||labs(-9L)!=9L||llabs(-11LL)!=11LL)return 1;div_t a=div(-17,5);if(a.quot!=-3||a.rem!=-2)return 2;ldiv_t b=ldiv(17L,5L);if(b.quot!=3L||b.rem!=2L)return 3;lldiv_t c=lldiv(-20LL,6LL);if(c.quot!=-3LL||c.rem!=-2LL)return 4;return 0;}'

# qsort calls a minicc comparator from host libc; bsearch calls it again and
# returns a host pointer into the sorted array.
assert_run 0 '#include <stdlib.h>
int cmp(const void *a,const void *b){int x=*(const int*)a;int y=*(const int*)b;return (x>y)-(x<y);}int main(void){int a[6]={9,1,7,3,5,2};qsort(a,6,sizeof(int),cmp);for(int i=0;i<6;i++){int want[6]={1,2,3,5,7,9};if(a[i]!=want[i])return 1;}int key=5;int *p=bsearch(&key,a,6,sizeof(int),cmp);return !p||*p!=5;}'

# Environment, PRNG, and system declarations are backed by libc.
assert_run 0 '#include <stdlib.h>
int main(void){if(!getenv("PATH"))return 1;srand(1);int r=rand();if(r<0||r>RAND_MAX)return 2;return system(":")!=0;}'

# Termination/registration function types must be usable without invoking them.
assert_run 0 '#include <stdlib.h>
void done(void){}int main(void){void (*a)(void)=abort;void (*b)(int)=exit;void (*c)(int)=_Exit;int (*d)(void(*)(void))=atexit;return !a||!b||!c||!d;}'

rm -f tmp-stdlib.c tmp-stdlib.s tmp-stdlib

echo 'All expanded <stdlib.h> tests passed!'
