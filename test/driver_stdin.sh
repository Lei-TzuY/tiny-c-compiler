#!/bin/bash
set -eu

src='int twice(int x){return x*2;} int main(){return twice(21)==42 ? 0 : 1;}'
printf '%s' "$src" | ./minicc - > tmp-stdin.s
cc -o tmp-stdin tmp-stdin.s
./tmp-stdin

echo 'OK(driver stdin): compiled non-newline-terminated source from a pipe'

{
  printf '/*'
  head -c 12000 /dev/zero | tr '\0' x
  printf '*/\nint main(){return 0;}\n'
} | ./minicc - > tmp-stdin-large.s
cc -o tmp-stdin-large tmp-stdin-large.s
./tmp-stdin-large

echo 'OK(driver stdin): compiled source larger than the initial stream buffer'
