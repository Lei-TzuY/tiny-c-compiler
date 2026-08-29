#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stdio-h.c
  "$MINICC" tmp-stdio-h.c > tmp-stdio-h.s
  cc -o tmp-stdio-h tmp-stdio-h.s
  set +e
  ./tmp-stdio-h >/dev/null 2>&1
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stdio.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

# Repeated inclusion must preserve FILE and the standard stream declarations.
assert_run 0 '#include <stdio.h>
#include <stdio.h>
int main(void){FILE *a=stdin;FILE *b=stdout;FILE *c=stderr;return !a||!b||!c;}'

# sprintf must use the host variadic ABI, including default float promotion.
assert_run 0 '#include <stdio.h>
int main(void){char b[32];float f=2.5f;int n=sprintf(b,"%d %.1f %s",7,f,"ok");if(n!=8)return 1;return b[0]!='"'"'7'"'"'||b[1]!='"'"' '"'"'||b[2]!='"'"'2'"'"'||b[3]!='"'"'.'"'"'||b[4]!='"'"'5'"'"'||b[5]!='"'"' '"'"'||b[6]!='"'"'o'"'"'||b[7]!='"'"'k'"'"'||b[8]!=0;}'

# printf/fprintf exercise variadic calls and FILE * stream arguments without output.
assert_run 0 '#include <stdio.h>
int main(void){if(printf("%s","")!=0)return 1;if(fprintf(stdout,"%s","")!=0)return 2;if(fprintf(stderr,"%s","")!=0)return 3;return 0;}'

# Character-oriented declarations must preserve host libc return values.
assert_run 0 '#include <stdio.h>
int main(void){if(putchar('"'"'A'"'"')!='"'"'A'"'"')return 1;if(puts("")<0)return 2;return 0;}'

rm -f tmp-stdio-h.c tmp-stdio-h.s tmp-stdio-h

echo 'All <stdio.h> tests passed!'
