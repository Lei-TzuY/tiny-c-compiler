#!/bin/bash
set -eu

cat > tmp-pp-stringify.c <<'EOF'
#define STR(x) #x

int streq(const char *a, const char *b) {
  while (*a && *a == *b) {
    a++;
    b++;
  }
  return *a == *b;
}

int main(void) {
  /* The # operator must preserve the spelling of quoted preprocessing tokens,
     escaping embedded quotes and backslashes so the result is a valid string. */
  if (!streq(STR("a\\b\"c"), "\"a\\\\b\\\"c\"")) return 1;
  if (!streq(STR('\n'), "'\\\\n'")) return 2;
  if (!streq(STR('\\'), "'\\\\\\\\'")) return 3;

  /* Whitespace outside quoted tokens collapses, while whitespace inside a
     string-literal preprocessing token remains part of that token spelling. */
  if (!streq(STR(alpha       beta), "alpha beta")) return 4;
  if (!streq(STR("alpha   beta"), "\"alpha   beta\"")) return 5;

  return 0;
}
EOF

./minicc tmp-pp-stringify.c > tmp-pp-stringify.s
cc -o tmp-pp-stringify tmp-pp-stringify.s
./tmp-pp-stringify

echo "OK(preprocessor stringification): quoted literal escaping and whitespace"
rm -f tmp-pp-stringify.c tmp-pp-stringify.s tmp-pp-stringify
