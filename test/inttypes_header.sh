#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-inttypes.c
  "$MINICC" tmp-inttypes.c > tmp-inttypes.s
  cc -o tmp-inttypes tmp-inttypes.s
  set +e
  ./tmp-inttypes
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(inttypes.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# The header must be safely repeatable, pull in stdint.h, and expose the C11
# intmax conversion/division APIs with compatible host ABI types.
assert_run 0 '#include <inttypes.h>
#include <inttypes.h>
int main(void){
  int64_t i=1; uint64_t u=2; intmax_t m=3; uintmax_t um=4;
  intmax_t (*a)(intmax_t)=imaxabs;
  imaxdiv_t (*d)(intmax_t,intmax_t)=imaxdiv;
  intmax_t (*s)(const char *,char **,int)=strtoimax;
  uintmax_t (*t)(const char *,char **,int)=strtoumax;
  return !(sizeof(i)==8&&sizeof(u)==8&&sizeof(m)==8&&sizeof(um)==8&&a&&d&&s&&t);
}'

# PRI macros must compose as string literals and match this x86-64 LP64 target.
assert_run 0 '#include <inttypes.h>
#include <stdio.h>
#include <string.h>
int main(void){
  char b[128];
  int n=snprintf(b,sizeof(b),"%" PRId8 " %" PRIu16 " %" PRId32 " %" PRIu64 " %" PRIxMAX,
                 (int8_t)-7,(uint16_t)42,(int32_t)-99,(uint64_t)123456789UL,(uintmax_t)255ULL);
  return n<0 || strcmp(b,"-7 42 -99 123456789 ff")!=0;
}'

# Least/fast/max/pointer format aliases must all expand and interoperate with
# the corresponding typedefs.
assert_run 0 '#include <inttypes.h>
#include <stdio.h>
int main(void){
  int_least16_t a=-12; uint_fast32_t b=34; intmax_t c=-56;
  int x=7; uintptr_t p=(uintptr_t)&x, q=0;
  char s[128];
  if(snprintf(s,sizeof(s),"%" PRIdLEAST16 " %" PRIuFAST32 " %" PRIdMAX " %" PRIxPTR,a,b,c,p)<0)return 1;
  if(sscanf(s,"%" SCNdLEAST16 " %" SCNuFAST32 " %" SCNdMAX " %" SCNxPTR,&a,&b,&c,&q)!=4)return 2;
  return a!=-12||b!=34||c!=-56||q!=p;
}'

# SCN macros cover the concrete fixed-width pointer types through host sscanf.
assert_run 0 '#include <inttypes.h>
#include <stdio.h>
int main(void){
  int8_t a=0; uint16_t b=0; int32_t c=0; uint64_t d=0; uintmax_t e=0;
  if(sscanf("-8 65530 -123 987654321 7f","%" SCNd8 " %" SCNu16 " %" SCNd32 " %" SCNu64 " %" SCNxMAX,&a,&b,&c,&d,&e)!=5)return 1;
  return a!=-8||b!=65530||c!=-123||d!=987654321UL||e!=127;
}'

# intmax arithmetic functions exercise both scalar calls and the two-word
# aggregate return ABI used by imaxdiv_t.
assert_run 0 '#include <inttypes.h>
int main(void){
  if(imaxabs(-123)!=123)return 1;
  imaxdiv_t d=imaxdiv(-17,5);
  return d.quot!=-3||d.rem!=-2;
}'

# Narrow and wide integer conversion functions must return host-libc results
# and update their end pointers correctly.
assert_run 0 '#include <inttypes.h>
int main(void){
  char *e1=0,*e2=0;
  intmax_t a=strtoimax("-123z",&e1,10);
  uintmax_t b=strtoumax("ff!",&e2,16);
  if(a!=-123||*e1!='"'"'z'"'"'||b!=255||*e2!='"'"'!'"'"')return 1;
  wchar_t w1[4]={'"'"'4'"'"','"'"'2'"'"','"'"'x'"'"',0};
  wchar_t w2[4]={'"'"'f'"'"','"'"'f'"'"','"'"'!'"'"',0};
  wchar_t *we1=0,*we2=0;
  if(wcstoimax(w1,&we1,10)!=42||*we1!='"'"'x'"'"')return 2;
  if(wcstoumax(w2,&we2,16)!=255||*we2!='"'"'!'"'"')return 3;
  return 0;
}'

rm -f tmp-inttypes.c tmp-inttypes.s tmp-inttypes

echo 'All <inttypes.h> tests passed!'
