#!/bin/bash
set -eu

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

# The actual comparator is linked from tokenize.c. Discard unused lexer paths
# so no parser/type stubs are needed; honor the full CI instrumentation flags.
${CC:-cc} ${CFLAGS:--std=c11 -g -fno-common} \
  -ffunction-sections -fdata-sections test/token_equality.c \
  -Wl,--gc-sections ${LDFLAGS:-} -o "$tmp_dir/token-equality"
"$tmp_dir/token-equality"
