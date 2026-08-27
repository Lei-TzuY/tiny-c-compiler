#!/bin/bash
set -eu

cat > tmp-gnu-stack.c <<'EOF'
int main(){return 0;}
EOF

./minicc tmp-gnu-stack.c > tmp-gnu-stack.s

grep -F '.section .note.GNU-stack,"",@progbits' tmp-gnu-stack.s >/dev/null

cc -c -o tmp-gnu-stack.o tmp-gnu-stack.s
readelf -SW tmp-gnu-stack.o | grep -F '.note.GNU-stack' >/dev/null

# Linker warnings are fatal here so the historical
# "missing .note.GNU-stack section implies executable stack" regression cannot
# silently return.
cc -Wl,--fatal-warnings -o tmp-gnu-stack tmp-gnu-stack.o 2>tmp-gnu-stack.err
if grep -F 'missing .note.GNU-stack' tmp-gnu-stack.err >/dev/null; then
  cat tmp-gnu-stack.err
  exit 1
fi

# The resulting ELF must not request an executable GNU_STACK segment.
if readelf -W -l tmp-gnu-stack | grep 'GNU_STACK' | grep -q 'RWE'; then
  echo 'GNU_STACK is unexpectedly executable'
  readelf -W -l tmp-gnu-stack | grep 'GNU_STACK'
  exit 1
fi

./tmp-gnu-stack

echo 'All GNU-stack note tests passed!'
