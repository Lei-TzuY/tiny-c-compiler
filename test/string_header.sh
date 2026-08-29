#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-string-h.c
  "$MINICC" tmp-string-h.c > tmp-string-h.s
  cc -o tmp-string-h tmp-string-h.s
  set +e
  ./tmp-string-h
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(string.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# Repeated inclusion must preserve size_t and all declarations.
assert_run 0 '#include <string.h>
#include <string.h>
int main(void){size_t (*p)(const char*)=strlen;return p("nova")!=4;}'

# Copy/concatenation APIs use the host libc ABI through standard prototypes.
assert_run 0 '#include <string.h>
int main(void){char a[32]="hello";char b[16];strcpy(b," world");strcat(a,b);if(strcmp(a,"hello world"))return 1;strncpy(b,"abcdef",3);b[3]=0;if(strcmp(b,"abc"))return 2;strncat(a,"!!!xyz",3);return strcmp(a,"hello world!!!")!=0;}'

# Memory primitives preserve bytes and support overlapping memmove ranges.
assert_run 0 '#include <string.h>
int main(void){char src[8]="abcde";char dst[8];memset(dst,0,sizeof(dst));memcpy(dst,src,6);if(memcmp(dst,"abcde",6))return 1;memmove(dst+1,dst,5);if(memcmp(dst,"aabcd",5))return 2;memset(dst+5,"!"[0],2);return dst[5]!=33||dst[6]!=33;}'

# Search/span functions expose standard pointer/size_t results.
assert_run 0 '#include <string.h>
int main(void){const char *s="abcabcxyz";if(strchr(s,"b"[0])!=s+1)return 1;if(strrchr(s,"b"[0])!=s+4)return 2;if(memchr(s,"x"[0],9)!=s+6)return 3;if(strstr(s,"cab")!=s+2)return 4;if(strpbrk(s,"zy")!=s+7)return 5;if(strspn("aaab12","ab")!=4)return 6;if(strcspn("hello,world",",")!=5)return 7;return 0;}'

# Tokenization declaration and mutable-buffer behavior match libc.
assert_run 0 '#include <string.h>
int main(void){char s[]="a,b,c";char *p=strtok(s,",");if(!p||strcmp(p,"a"))return 1;p=strtok(0,",");if(!p||strcmp(p,"b"))return 2;p=strtok(0,",");if(!p||strcmp(p,"c"))return 3;return strtok(0,",")!=0;}'

# Locale-sensitive declarations still have valid C-locale ABI/type behavior.
assert_run 0 '#include <string.h>
int main(void){char out[16];size_t n=strxfrm(out,"abc",sizeof(out));return strcoll("abc","abd")>=0||n>=sizeof(out);}'

# strerror is declared with the standard char* return type.
assert_run 0 '#include <string.h>
int main(void){char *s=strerror(0);return s==0;}'

rm -f tmp-string-h.c tmp-string-h.s tmp-string-h

echo 'All <string.h> tests passed!'
