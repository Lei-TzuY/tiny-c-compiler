from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()
marker = '    if (!strcmp(name, "stdbool.h")) {'
if '    if (!strcmp(name, "assert.h")) {' not in text:
    block = r'''    if (!strcmp(name, "assert.h")) {
        return "#ifdef assert\n"
               "#undef assert\n"
               "#endif\n"
               "#ifdef NDEBUG\n"
               "#define assert(expression) ((void)0)\n"
               "#else\n"
               "#include <stdio.h>\n"
               "#include <stdlib.h>\n"
               "#define assert(expression) ((void)((expression) || (fprintf(stderr, \\\"%s:%d: %s: Assertion `%s' failed.\\\\n\\\", __FILE__, __LINE__, __func__, #expression), abort(), 0)))\n"
               "#endif\n";
    }
'''
    pos = text.index(marker)
    text = text[:pos] + block + text[pos:]
    pp.write_text(text)

makefile = Path("Makefile")
mk = makefile.read_text()
needle = "\tbash ./test/stdlib_header.sh\n"
entry = "\tbash ./test/assert_header.sh\n"
if entry not in mk:
    mk = mk.replace(needle, needle + entry)
    makefile.write_text(mk)

Path("test/assert_header.sh").write_text(r'''#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-assert-h.c
  "$MINICC" tmp-assert-h.c > tmp-assert-h.s
  cc -o tmp-assert-h tmp-assert-h.s
  set +e
  ./tmp-assert-h >tmp-assert-h.out 2>tmp-assert-h.err
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(assert.h): expected $expected, got $actual"
    cat tmp-assert-h.err >&2 || true
    echo "$input"
    exit 1
  fi
}

# A successful assertion evaluates its expression exactly once.
assert_run 0 '#include <assert.h>
int main(void){int n=0;assert(++n==1);return n!=1;}'

# NDEBUG removes the assertion expression entirely, including invalid or
# side-effecting source that would otherwise be semantically significant.
assert_run 0 '#define NDEBUG 1
#include <assert.h>
int main(void){int n=0;assert(++n);assert(undeclared_identifier);return n;}'

# C requires assert.h to react to the current NDEBUG state on every inclusion.
# Re-including after toggling NDEBUG must therefore redefine assert rather than
# behaving like an ordinary include-guarded header.
assert_run 0 '#include <assert.h>
#define NDEBUG 1
#include <assert.h>
#undef NDEBUG
#include <assert.h>
int main(void){int n=0;assert(++n==1);return n!=1;}'

# A failing assertion must diagnose the original (unexpanded) expression text,
# logical file/line location, and function name, then terminate abnormally.
cat > tmp-assert-h.c <<'EOF'
#include <assert.h>
#define ZERO 0
#line 700 "logical-assert.c"
static void trigger(void){assert(ZERO);}
int main(void){trigger();return 0;}
EOF
"$MINICC" tmp-assert-h.c > tmp-assert-h.s
cc -o tmp-assert-h tmp-assert-h.s
set +e
./tmp-assert-h >tmp-assert-h.out 2>tmp-assert-h.err
status="$?"
set -e
if [ "$status" -eq 0 ]; then
  echo 'FAIL(assert.h): failing assert unexpectedly succeeded' >&2
  exit 1
fi
grep -F 'logical-assert.c:700' tmp-assert-h.err >/dev/null || {
  echo 'FAIL(assert.h): diagnostic missing logical file/line' >&2
  cat tmp-assert-h.err >&2
  exit 1
}
grep -F 'trigger' tmp-assert-h.err >/dev/null || {
  echo 'FAIL(assert.h): diagnostic missing function name' >&2
  cat tmp-assert-h.err >&2
  exit 1
}
grep -F 'ZERO' tmp-assert-h.err >/dev/null || {
  echo 'FAIL(assert.h): diagnostic missing unexpanded expression text' >&2
  cat tmp-assert-h.err >&2
  exit 1
}

rm -f tmp-assert-h.c tmp-assert-h.s tmp-assert-h tmp-assert-h.out tmp-assert-h.err

echo 'All <assert.h> tests passed!'
''')
