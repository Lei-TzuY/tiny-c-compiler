#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  label="$2"
  "$MINICC" tmp-line-splicing.c > tmp-line-splicing.s
  cc -o tmp-line-splicing tmp-line-splicing.s
  set +e
  ./tmp-line-splicing
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(line splicing: $label): expected $expected, got $actual"
    exit 1
  fi
  echo "OK(line splicing): $label"
}

# Translation phase 2 runs before tokenization, so a splice may join pieces of
# identifiers and keywords into one preprocessing token.
cat > tmp-line-splicing.c <<'SRC'
int ma\
in(void) {
  ret\
urn 7;
}
SRC
assert_run 7 'joins identifier and keyword tokens'

# A splice can also create a multi-character punctuator.
cat > tmp-line-splicing.c <<'SRC'
int main(void) {
  return 1 <\
= 1 ? 0 : 1;
}
SRC
assert_run 0 'forms punctuators before lexical analysis'

# Backslash-newline disappears even inside a string literal.
cat > tmp-line-splicing.c <<'SRC'
int main(void) {
  char *s = "ab\
cd";
  return s[0]=='a' && s[1]=='b' && s[2]=='c' && s[3]=='d' && s[4]==0 ? 0 : 1;
}
SRC
assert_run 0 'splices string-literal contents'

# Preprocessor directives see the logical line after splicing.
cat > tmp-line-splicing.c <<'SRC'
#define VALUE 10 + \
20
int main(void) {
  return VALUE;
}
SRC
assert_run 30 'continues macro replacement lists'

# Splicing precedes comment recognition, so // continues onto the next physical
# source line when its newline is escaped.
cat > tmp-line-splicing.c <<'SRC'
int main(void) {
  // the next return is part of this comment \
  return 99;
  return 5;
}
SRC
assert_run 5 'extends line comments before comment removal'

# Translation phase 1 normalizes CRLF before phase-2 splicing. This matters for
# Windows-authored source files: the backslash is immediately followed by the
# logical newline only after CRLF has been mapped to '\n'.
printf '%s\r\n' \
  'int ma\' \
  'in(void) {' \
  '  ret\' \
  'urn 9;' \
  '}' > tmp-line-splicing.c
assert_run 9 'normalizes CRLF before token splicing'

# The same ordering must hold for preprocessor directive continuation.
printf '%s\r\n' \
  '#define VALUE 11 + \' \
  '31' \
  'int main(void) {' \
  '  return VALUE;' \
  '}' > tmp-line-splicing.c
assert_run 42 'normalizes CRLF before macro continuation'

rm -f tmp-line-splicing.c tmp-line-splicing.s tmp-line-splicing

echo 'All C translation-phase line-splicing tests passed!'
