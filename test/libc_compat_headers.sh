#!/bin/bash
set -eu

run_case() {
  name="$1"
  src="$2"
  printf '%s\n' "$src" > "tmp-libc-${name}.c"
  ./minicc "tmp-libc-${name}.c" > "tmp-libc-${name}.s"
  cc -o "tmp-libc-${name}" "tmp-libc-${name}.s"
  set +e
  timeout 5 "./tmp-libc-${name}"
  status="$?"
  set -e
  if [ "$status" != 0 ]; then
    if [ "$status" = 124 ]; then
      echo "FAIL(libc compatibility headers): ${name} timed out"
    else
      echo "FAIL(libc compatibility headers): ${name} => ${status}"
    fi
    exit 1
  fi
  echo "OK(libc compatibility headers): ${name}"
}

run_case errno '#include <errno.h>
int main(void) {
  errno = 0;
  errno = EDOM;
  if (errno != EDOM) return 1;
  if (ERANGE == EDOM || EILSEQ <= 0) return 2;
  return 0;
}'

run_case time '#include <time.h>
int main(void) {
  if (sizeof(time_t) != 8 || sizeof(clock_t) != 8) return 1;
  if (sizeof(struct timespec) != 16) return 2;
  time_t t = 0;
  struct tm *p = gmtime(&t);
  if (!p) return 3;
  if (p->tm_year != 70 || p->tm_mon != 0 || p->tm_mday != 1) return 4;
  struct timespec ts;
  if (timespec_get(&ts, TIME_UTC) != TIME_UTC) return 5;
  if (CLOCKS_PER_SEC != 1000000L) return 6;
  return 0;
}'

run_case locale '#include <locale.h>
int main(void) {
  char *name = setlocale(LC_ALL, "C");
  struct lconv *lc = localeconv();
  if (!name || !lc || !lc->decimal_point) return 1;
  if (lc->decimal_point[0] != "."[0] || lc->decimal_point[1] != 0) return 2;
  if (LC_CTYPE != 0 || LC_NUMERIC != 1 || LC_TIME != 2 || LC_ALL != 6) return 3;
  return 0;
}'

run_case signal '#include <signal.h>
static void handler(int sig) { (void)sig; }
int main(void) {
  if (sizeof(sig_atomic_t) != 4) return 1;
  void (*old)(int) = signal(SIGTERM, handler);
  if (old == SIG_ERR) return 2;
  if (signal(SIGTERM, old) == SIG_ERR) return 3;
  if (SIGINT != 2 || SIGABRT != 6 || SIGSEGV != 11 || SIGTERM != 15) return 4;
  return 0;
}'

run_case combined '#include <errno.h>
#include <time.h>
#include <locale.h>
#include <signal.h>
int main(void) {
  errno = ERANGE;
  time_t t = 0;
  struct tm *tm = gmtime(&t);
  struct lconv *lc = localeconv();
  return errno == ERANGE && tm && lc && SIGFPE == 8 ? 0 : 1;
}'

# Builtin headers remain part of the standard-include layer and must disappear
# under -nostdinc unless the user supplies a replacement path explicitly.
printf '%s\n' '#include <time.h>' 'int main(void){return 0;}' > tmp-libc-nostdinc.c
if ./minicc -nostdinc tmp-libc-nostdinc.c > /dev/null 2>&1; then
  echo 'FAIL(libc compatibility headers): -nostdinc still found builtin time.h'
  exit 1
fi
echo 'OK(libc compatibility headers): -nostdinc filtering'

echo 'All libc compatibility header tests passed!'
