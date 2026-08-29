#!/bin/bash
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

# Repeated inclusion must preserve declarations and pointer-return ABI.
assert_run 0 '#include <stdlib.h>
#include <stdlib.h>
int main(void){void *p=malloc(16);if(!p)return 1;free(p);return 0;}'

# malloc/calloc/free must interoperate with host libc using LP64 size arguments.
assert_run 0 '#include <stdlib.h>
int main(void){unsigned long n=32;unsigned char *p=calloc(n,1);if(!p)return 1;for(unsigned long i=0;i<n;i++)if(p[i]!=0)return 2;p[0]=7;p[31]=9;free(p);return 0;}'

# realloc preserves the existing prefix and returns a correctly typed pointer.
assert_run 0 '#include <stdlib.h>
int main(void){char *p=malloc(4);if(!p)return 1;p[0]=1;p[1]=2;p[2]=3;p[3]=4;char *q=realloc(p,64);if(!q)return 2;if(q[0]!=1||q[1]!=2||q[2]!=3||q[3]!=4)return 3;free(q);return 0;}'

# atoi uses the host libc calling convention and signed int return normalization.
assert_run 0 '#include <stdlib.h>
int main(void){return atoi("-12345")!=-12345 || atoi("42")!=42;}'

# exit must be callable through the declared prototype and preserve status.
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

echo 'All <stdlib.h> tests passed!'
