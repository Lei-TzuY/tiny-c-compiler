from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()
marker = '    if (!strcmp(name, "stdarg.h")) {'
if '    if (!strcmp(name, "inttypes.h")) {' not in text:
    block = r'''    if (!strcmp(name, "inttypes.h")) {
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
'''
    pos = text.index(marker)
    text = text[:pos] + block + text[pos:]
    pp.write_text(text)

makefile = Path("Makefile")
mk = makefile.read_text()
needle = "\tbash ./test/stdint_header.sh\n"
entry = "\tbash ./test/inttypes_header.sh\n"
if entry not in mk:
    if needle not in mk:
        raise SystemExit("stdint test entry not found")
    makefile.write_text(mk.replace(needle, needle + entry, 1))

Path("test/inttypes_header.sh").write_text(r'''#!/bin/bash
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
''')
