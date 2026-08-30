#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="system-include-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(system include/dependency): $*" >&2
  exit 1
}

mkdir -p "$work/project" "$work/user" "$work/system"

cat > "$work/user/which.h" <<'SRC'
#define WHICH_VALUE 11
SRC
cat > "$work/system/which.h" <<'SRC'
#define WHICH_VALUE 101
SRC
cat > "$work/user/user-detail.h" <<'SRC'
#define USER_DETAIL_VALUE 13
SRC
cat > "$work/user/user.h" <<'SRC'
#include "user-detail.h"
#define USER_VALUE USER_DETAIL_VALUE
SRC
cat > "$work/system/system-detail.h" <<'SRC'
#define SYSTEM_DETAIL_VALUE 17
SRC
cat > "$work/user/from-system-user-path.h" <<'SRC'
#define FROM_SYSTEM_USER_PATH_VALUE 23
SRC
cat > "$work/system/system.h" <<'SRC'
#include "system-detail.h"
#include <from-system-user-path.h>
#define SYSTEM_VALUE (SYSTEM_DETAIL_VALUE + FROM_SYSTEM_USER_PATH_VALUE)
SRC
cat > "$work/system/quoted-system.h" <<'SRC'
#define QUOTED_SYSTEM_VALUE 19
SRC
cat > "$work/project/main.c" <<'SRC'
#include <which.h>
#include <user.h>
#include <system.h>
#include "quoted-system.h"
#include <stddef.h>
int main(void) {
    return WHICH_VALUE + USER_VALUE + SYSTEM_VALUE + QUOTED_SYSTEM_VALUE == 83 ? 0 : 1;
}
SRC

./minicc --help > "$work/help.out"
grep -F -- '-MM' "$work/help.out" >/dev/null || fail '--help missing -MM'
grep -F -- '-MMD' "$work/help.out" >/dev/null || fail '--help missing -MMD'
grep -F -- '-isystem <dir>' "$work/help.out" >/dev/null || fail '--help missing -isystem'

# User -I directories are searched before -isystem directories even when the
# system option appears first on argv. A quoted include can also resolve through
# -isystem and is classified by the directory, not by quote-vs-angle syntax.
(
  cd "$work"
  "$compiler" -isystem system -I user project/main.c > main.s
  cc -o main main.s
  ./main
)
echo 'OK(system include): -I precedes -isystem and compilation succeeds'

# Accept the attached -isystemDIR spelling as a driver convenience too.
(
  cd "$work"
  "$compiler" -E -Iuser -isystemsystem project/main.c > attached.i
  grep -q 'return 11 + 13 + (17 + 23) + 19 == 83' attached.i
)
echo 'OK(system include): attached -isystem form works'

# -M retains all physical dependencies, including system headers and the quoted
# private header included from a system header.
(
  cd "$work"
  "$compiler" -M -Iuser -isystem system project/main.c > all.mk
  grep -F 'user/which.h' all.mk >/dev/null
  grep -F 'user/user.h' all.mk >/dev/null
  grep -F 'user/user-detail.h' all.mk >/dev/null
  grep -F 'system/system.h' all.mk >/dev/null
  grep -F 'system/system-detail.h' all.mk >/dev/null
  grep -F 'user/from-system-user-path.h' all.mk >/dev/null
  grep -F 'system/quoted-system.h' all.mk >/dev/null
)
echo 'OK(system dependency): -M retains user and system headers'

# -MM omits a header found in -isystem and every header reached from it through
# source-relative quoted includes. Angle-vs-quote spelling alone does not decide
# whether a dependency is considered system.
(
  cd "$work"
  "$compiler" -MM -Iuser -isystem system project/main.c > user-only.mk
  grep -F 'project/main.c' user-only.mk >/dev/null
  grep -F 'user/which.h' user-only.mk >/dev/null
  grep -F 'user/user.h' user-only.mk >/dev/null
  grep -F 'user/user-detail.h' user-only.mk >/dev/null
  ! grep -F 'system/system.h' user-only.mk >/dev/null
  ! grep -F 'system/system-detail.h' user-only.mk >/dev/null
  ! grep -F 'user/from-system-user-path.h' user-only.mk >/dev/null
  ! grep -F 'system/quoted-system.h' user-only.mk >/dev/null
)
echo 'OK(system dependency): -MM filters direct and indirect system headers'

# -MMD is the compilation-side-effect analogue of -MM. It must still compile
# normally, choose the output-derived .d path, and exclude system prerequisites.
(
  cd "$work"
  "$compiler" -MMD -Iuser -isystem system -o mmd.s project/main.c
  cc -o mmd mmd.s
  ./mmd
  test -s mmd.d
  grep -F 'mmd.s:' mmd.d >/dev/null
  grep -F 'user/user.h' mmd.d >/dev/null
  grep -F 'user/user-detail.h' mmd.d >/dev/null
  ! grep -F 'system/system.h' mmd.d >/dev/null
  ! grep -F 'system/system-detail.h' mmd.d >/dev/null
  ! grep -F 'user/from-system-user-path.h' mmd.d >/dev/null
  ! grep -F 'system/quoted-system.h' mmd.d >/dev/null
)
echo 'OK(system dependency): -MMD emits user-only sidecar dependencies'

# -MD continues to include the same system dependencies that -M reports.
(
  cd "$work"
  "$compiler" -MD -Iuser -isystem system -o md.s project/main.c
  test -s md.d
  grep -F 'system/system.h' md.d >/dev/null
  grep -F 'system/system-detail.h' md.d >/dev/null
  grep -F 'user/from-system-user-path.h' md.d >/dev/null
  grep -F 'system/quoted-system.h' md.d >/dev/null
)
echo 'OK(system dependency): -MD retains system dependencies'

# -MP follows the filtered prerequisite set, so -MM must not manufacture phony
# rules for omitted system headers.
(
  cd "$work"
  "$compiler" -MM -MP -MF phony.mk -Iuser -isystem system project/main.c
  grep -Fx 'user/user.h:' phony.mk >/dev/null
  grep -Fx 'user/user-detail.h:' phony.mk >/dev/null
  ! grep -Fx 'system/system.h:' phony.mk >/dev/null
  ! grep -Fx 'system/system-detail.h:' phony.mk >/dev/null
  ! grep -Fx 'user/from-system-user-path.h:' phony.mk >/dev/null
)
echo 'OK(system dependency): -MP respects -MM filtering'

# If an identical directory spelling is supplied through both -I and -isystem,
# GCC treats it as a system directory. The user-path copy must therefore not
# leak into -MM output even if -I appeared first.
cat > "$work/system/classified.h" <<'SRC'
#define CLASSIFIED_VALUE 23
SRC
cat > "$work/project/classified.c" <<'SRC'
#include <classified.h>
int value = CLASSIFIED_VALUE;
SRC
(
  cd "$work"
  "$compiler" -MM -I system -isystem system project/classified.c > classified-mm.mk
  ! grep -F 'system/classified.h' classified-mm.mk >/dev/null
  "$compiler" -M -I system -isystem system project/classified.c > classified-m.mk
  grep -F 'system/classified.h' classified-m.mk >/dev/null
)
echo 'OK(system include): duplicate -I/-isystem directory remains system-classified'

# A physical header first reached through -isystem can later be upgraded to a
# user dependency through an alias. Physical deduplication remains one entry.
cat > "$work/system/shared.h" <<'SRC'
#pragma once
#define SHARED_VALUE 29
SRC
ln -s ../system/shared.h "$work/user/shared-user.h"
cat > "$work/project/upgrade.c" <<'SRC'
#include <shared.h>
#include <shared-user.h>
int value = SHARED_VALUE;
SRC
(
  cd "$work"
  "$compiler" -MM -Iuser -isystem system project/upgrade.c > upgrade.mk
  [ "$(grep -o 'shared.h' upgrade.mk | wc -l)" -eq 1 ]
)
echo 'OK(system dependency): physical dedup can upgrade system dependency to user'

# MMD keeps the existing MD failure-safety guarantee: front-end failure cannot
# truncate a pre-existing dependency file or create compiler output.
cat > "$work/project/bad.c" <<'SRC'
#include <user.h>
int main(void) { return USER_VALUE
SRC
printf '%s\n' keep-mmd-dependency > "$work/keep.d"
cp "$work/keep.d" "$work/keep.expected"
if (
  cd "$work"
  "$compiler" -MMD -MF keep.d -Iuser -isystem system -o bad.s project/bad.c \
    >bad.out 2>bad.err
); then
  fail '-MMD unexpectedly accepted malformed source'
fi
cmp -s "$work/keep.d" "$work/keep.expected" || fail '-MMD rewrote dependency output before validation'
test ! -e "$work/bad.s" || fail '-MMD created compiler output after front-end failure'
echo 'OK(system dependency): -MMD preserves failure-safe sidecar behavior'

# New dependency modes participate in the same diagnostics as their all-header
# counterparts.
if "$compiler" -MM -MD "$work/project/main.c" >"$work/bad-mode.out" 2>"$work/bad-mode.err"; then
  fail '-MM -MD unexpectedly succeeded'
fi
grep -F "'-M', '-MM', '-MD' and '-MMD' are mutually exclusive" "$work/bad-mode.err" >/dev/null
if "$compiler" -MMD -E "$work/project/main.c" >"$work/bad-e.out" 2>"$work/bad-e.err"; then
  fail '-MMD -E unexpectedly succeeded'
fi
grep -F "'-MMD' is not supported with '-E' or '-fsyntax-only'" "$work/bad-e.err" >/dev/null
if "$compiler" -MM -o "$work/nope.mk" "$work/project/main.c" >"$work/bad-o.out" 2>"$work/bad-o.err"; then
  fail '-MM -o unexpectedly succeeded'
fi
grep -F "'-o' is not supported with '-MM'; use '-MF'" "$work/bad-o.err" >/dev/null
if "$compiler" -isystem >"$work/bad-isystem.out" 2>"$work/bad-isystem.err"; then
  fail 'missing -isystem argument unexpectedly succeeded'
fi
grep -F "missing argument after '-isystem'" "$work/bad-isystem.err" >/dev/null

echo 'All system include/dependency tests passed!'
