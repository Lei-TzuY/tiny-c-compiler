#!/bin/bash
set -eu

cat > tmp-datetime-header.h <<'EOF'
const char *header_date(void) { return __DATE__; }
const char *header_time(void) { return __TIME__; }
EOF

cat > tmp-datetime.c <<'EOF'
#if !defined(__DATE__) || !defined(__TIME__)
#error C11 predefined date/time macros must be defined
#endif
#include "tmp-datetime-header.h"
#define DATE_THROUGH_MACRO __DATE__
#define TIME_THROUGH_MACRO __TIME__
int streq(const char *a, const char *b) {
  while (*a && *a == *b) { a++; b++; }
  return *a == *b;
}
int digit(char c) { return c >= '0' && c <= '9'; }
int alpha(char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); }
int main(void) {
  const char *d = __DATE__;
  const char *t = __TIME__;
  if (sizeof(__DATE__) != 12 || sizeof(__TIME__) != 9) return 1;
  if (!alpha(d[0]) || !alpha(d[1]) || !alpha(d[2]) || d[3] != ' ') return 2;
  if (!((d[4] == ' ') || digit(d[4])) || !digit(d[5]) || d[6] != ' ') return 3;
  if (!digit(d[7]) || !digit(d[8]) || !digit(d[9]) || !digit(d[10]) || d[11]) return 4;
  if (!digit(t[0]) || !digit(t[1]) || t[2] != ':' || !digit(t[3]) ||
      !digit(t[4]) || t[5] != ':' || !digit(t[6]) || !digit(t[7]) || t[8]) return 5;
  if (!streq(d, header_date()) || !streq(t, header_time())) return 6;
  if (!streq(d, DATE_THROUGH_MACRO) || !streq(t, TIME_THROUGH_MACRO)) return 7;
  return 0;
}
EOF

./minicc tmp-datetime.c > tmp-datetime.s
cc -o tmp-datetime tmp-datetime.s
./tmp-datetime

echo 'OK(predefined date/time macros): format, definition, macro rescan and translation consistency'
rm -f tmp-datetime-header.h tmp-datetime.c tmp-datetime.s tmp-datetime
