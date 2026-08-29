from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()
marker = '    if (!strcmp(name, "assert.h")) {'
if '    if (!strcmp(name, "ctype.h")) {' not in text:
    block = r'''    if (!strcmp(name, "ctype.h")) {
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
'''
    pos = text.index(marker)
    text = text[:pos] + block + text[pos:]
    pp.write_text(text)

makefile = Path("Makefile")
mk = makefile.read_text()
needle = "\tbash ./test/assert_header.sh\n"
entry = "\tbash ./test/ctype_header.sh\n"
if entry not in mk:
    mk = mk.replace(needle, needle + entry)
    makefile.write_text(mk)

Path("test/ctype_header.sh").write_text(r'''#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-ctype-h.c
  "$MINICC" tmp-ctype-h.c > tmp-ctype-h.s
  cc -o tmp-ctype-h tmp-ctype-h.s
  set +e
  ./tmp-ctype-h
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(ctype.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# Repeated inclusion must remain harmless and expose every C11 classification
# and conversion function with the expected int(int) ABI.
assert_run 0 '#include <ctype.h>
#include <ctype.h>
int main(void){
  int (*f0)(int)=isalnum; int (*f1)(int)=isalpha; int (*f2)(int)=isblank;
  int (*f3)(int)=iscntrl; int (*f4)(int)=isdigit; int (*f5)(int)=isgraph;
  int (*f6)(int)=islower; int (*f7)(int)=isprint; int (*f8)(int)=ispunct;
  int (*f9)(int)=isspace; int (*f10)(int)=isupper; int (*f11)(int)=isxdigit;
  int (*f12)(int)=tolower; int (*f13)(int)=toupper;
  return !(f0 && f1 && f2 && f3 && f4 && f5 && f6 && f7 && f8 && f9 && f10 && f11 && f12 && f13);
}'

# Exercise the complete classification surface against representative ASCII
# characters. Classification functions promise zero/nonzero, not specifically 1.
assert_run 0 '#include <ctype.h>
int main(void){
  if(!isalnum('"'"'A'"'"') || !isalnum('"'"'7'"'"') || isalnum('"'"'!'"'"')) return 1;
  if(!isalpha('"'"'z'"'"') || isalpha('"'"'4'"'"')) return 2;
  if(!isblank('"'"' '"'"') || !isblank('"'"'\t'"'"') || isblank('"'"'\n'"'"')) return 3;
  if(!iscntrl('"'"'\n'"'"') || iscntrl('"'"'A'"'"')) return 4;
  if(!isdigit('"'"'0'"'"') || isdigit('"'"'a'"'"')) return 5;
  if(!isgraph('"'"'!'"'"') || isgraph('"'"' '"'"')) return 6;
  if(!islower('"'"'q'"'"') || islower('"'"'Q'"'"')) return 7;
  if(!isprint('"'"' '"'"') || isprint('"'"'\n'"'"')) return 8;
  if(!ispunct('"'"'?'"'"') || ispunct('"'"'A'"'"')) return 9;
  if(!isspace('"'"' '"'"') || !isspace('"'"'\n'"'"') || isspace('"'"'x'"'"')) return 10;
  if(!isupper('"'"'Z'"'"') || isupper('"'"'z'"'"')) return 11;
  if(!isxdigit('"'"'f'"'"') || !isxdigit('"'"'A'"'"') || !isxdigit('"'"'9'"'"') || isxdigit('"'"'g'"'"')) return 12;
  return 0;
}'

# Case conversion must follow the host C locale behavior for ASCII letters and
# leave nonletters and EOF unchanged.
assert_run 0 '#include <ctype.h>
int main(void){
  if(tolower('"'"'A'"'"')!='"'"'a'"'"') return 1;
  if(tolower('"'"'7'"'"')!='"'"'7'"'"') return 2;
  if(toupper('"'"'z'"'"')!='"'"'Z'"'"') return 3;
  if(toupper('"'"'!'"'"')!='"'"'!'"'"') return 4;
  if(tolower(-1)!=-1 || toupper(-1)!=-1) return 5;
  return 0;
}'

# Ensure the declarations interoperate with ordinary loops used by parsers and
# tokenizers, not just isolated calls.
assert_run 0 '#include <ctype.h>
int main(void){
  char *s="Az 19!\t"; int alpha=0,digit=0,space=0,punct=0;
  for(int i=0;s[i];i++){
    unsigned char c=s[i];
    alpha += !!isalpha(c); digit += !!isdigit(c);
    space += !!isspace(c); punct += !!ispunct(c);
  }
  return !(alpha==2 && digit==2 && space==2 && punct==1);
}'

rm -f tmp-ctype-h.c tmp-ctype-h.s tmp-ctype-h

echo 'All <ctype.h> tests passed!'
''')
