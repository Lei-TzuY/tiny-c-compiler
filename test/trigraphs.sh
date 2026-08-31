#!/bin/bash
set -eu

cleanup() {
  rm -f tmp-trigraphs.c tmp-trigraphs.s tmp-trigraphs \
        tmp-trigraphs-e.c tmp-trigraphs-e.out
}
trap cleanup EXIT

# All nine C11 trigraphs are replaced in translation phase 1.  This one source
# exercises directive '#', line-splice '\\', ^, [, ], |, {, }, and ~, plus
# replacement inside character/string literals and before comment recognition.
cat > tmp-trigraphs.c <<'EOF'
??=define ADD2(a, b) ((a) + ??/
                     (b))
??=define ENABLED 1

??=if ENABLED
static int sum3(int a??(3??)) ??<
  return a??(0??) + a??(1??) + a??(2??);
??>
??=else
??=error trigraph directive handling failed
??=endif

int main(void) ??<
  int values??(3??) = ??< 1, 2, 4 ??>;
  int x = values??(0??) ??' values??(1??);
  if (x != 3)
    return 1;
  if ((x ??! values??(2??)) != 7)
    return 2;
  if (sum3(values) != 7)
    return 3;
  if (ADD2(10, 5) != 15)
    return 4;
  if ((??-0u) != ~0u)
    return 5;

  char tilde = '??-';
  if (tilde != '~')
    return 6;

  // Trigraph replacement also occurs inside literals, before escape parsing.
  char *escaped = "A??/nB";
  if (escaped??(0??) != 'A' || escaped??(1??) != '\n' || escaped??(2??) != 'B')
    return 7;
  char *hash = "??=";
  if (hash??(0??) != '#' || hash??(1??) != 0)
    return 8;

  int untouched = 11;
  // A ??/ at physical end of a // comment becomes backslash-newline before
  // comments are recognized, so the following assignment belongs to comment.
  // comment extends here ??/
  untouched = 99;
  if (untouched != 11)
    return 9;

  return 0;
??>
EOF

./minicc tmp-trigraphs.c > tmp-trigraphs.s
cc -o tmp-trigraphs tmp-trigraphs.s
./tmp-trigraphs

# Phase-1 replacement must happen before preprocessing, so trigraph-spelled
# directives and a trigraph-created continuation work under -E as well.
cat > tmp-trigraphs-e.c <<'EOF'
??=define TOTAL 20 ??/
+ 22
TOTAL
EOF
./minicc -E tmp-trigraphs-e.c > tmp-trigraphs-e.out
grep -Eq '20[[:space:]]*\+[[:space:]]*22' tmp-trigraphs-e.out

# Conversely, trigraph-looking text created by macro replacement is too late
# for phase 1 and must not be rescanned.  Build ??= from three separate macro
# arguments so the physical source itself never contains that trigraph.
cat > tmp-trigraphs-e.c <<'EOF'
#define CAT3_RAW(a,b,c) a ## b ## c
CAT3_RAW(?, ?, =)
EOF
./minicc -E tmp-trigraphs-e.c > tmp-trigraphs-e.out
grep -F '??=' tmp-trigraphs-e.out >/dev/null

# Unknown ??x triples are ordinary question-mark tokens/text, not trigraphs.
cat > tmp-trigraphs-e.c <<'EOF'
#define S "??x"
S
EOF
./minicc -E tmp-trigraphs-e.c > tmp-trigraphs-e.out
grep -F '"??x"' tmp-trigraphs-e.out >/dev/null

echo 'All C11 trigraph translation-phase tests passed!'
