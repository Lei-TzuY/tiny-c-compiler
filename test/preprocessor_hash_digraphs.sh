#!/bin/bash
set -eu

cat > tmp-pp-hash-digraphs.c <<'EOF'
%:define ANSWER 42
%:define STR(x) %:x
%:define CAT(a, b) a %:%: b
%:define TEMP 1
%:undef TEMP

/* %:define COMMENT_DEFINED 1 */
// %:define LINE_COMMENT_DEFINED 1

%:ifdef TEMP
%:error %:undef did not remove TEMP
%:endif
%:ifdef COMMENT_DEFINED
%:error hash digraph inside block comment became a directive
%:endif
%:ifdef LINE_COMMENT_DEFINED
%:error hash digraph inside line comment became a directive
%:endif

%:if ANSWER != 42
%:error %:define or %:if digraph handling failed
%:endif

int streq(const char *a, const char *b) {
  while (*a && *a == *b) {
    a++;
    b++;
  }
  return *a == *b;
}

int CAT(ma, in)(void) {
  if (ANSWER != 42) return 1;
  if (!streq(STR(alpha      beta), "alpha beta")) return 2;
  if (!streq("%: %:%:", "%: %:%:")) return 3;
  return 0;
}
EOF

# Keep a host compiler as an independent oracle that this is valid C11 source.
cc -std=c11 -pedantic-errors -o tmp-pp-hash-digraphs-host tmp-pp-hash-digraphs.c
./tmp-pp-hash-digraphs-host

./minicc tmp-pp-hash-digraphs.c > tmp-pp-hash-digraphs.s
cc -o tmp-pp-hash-digraphs tmp-pp-hash-digraphs.s
./tmp-pp-hash-digraphs

echo "OK(preprocessor hash digraphs): directives, #, ##, literals and comments"
rm -f tmp-pp-hash-digraphs.c tmp-pp-hash-digraphs.s \
      tmp-pp-hash-digraphs tmp-pp-hash-digraphs-host
