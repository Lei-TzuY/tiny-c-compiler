#!/bin/bash
set -eu

compiler="$(pwd)/minicc"
work="dependency-missing-test.$$"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL(dependency -MG): $*" >&2
  exit 1
}

mkdir -p "$work/project" "$work/inc" "$work/system"

cat > "$work/inc/present.h" <<'SRC'
#define PRESENT_VALUE 7
SRC
cat > "$work/system/sys.h" <<'SRC'
#include <generated-system-child.h>
#define SYS_VALUE 11
SRC
cat > "$work/project/main.c" <<'SRC'
#include <present.h>
#include "generated/config.h"
#include <generated/api.h>
#define GENERATED_NAME "macro/generated.h"
#include GENERATED_NAME
#include "generated/config.h"
int value = PRESENT_VALUE;
SRC

./minicc --help > "$work/help.out"
grep -F -- '-MG' "$work/help.out" >/dev/null || fail '--help missing -MG'

# Without -MG, a missing header remains a preprocessing error.
if (
  cd "$work"
  "$compiler" -M -Iinc project/main.c > no-mg.mk 2> no-mg.err
); then
  fail 'missing header unexpectedly succeeded without -MG'
fi
grep -F 'cannot include generated/config.h' "$work/no-mg.err" >/dev/null

# -MG records unresolved names exactly as include operands, after macro
# expansion, with no project/ or -I prefix. Existing headers still resolve to
# their physical path and duplicate missing names are deduplicated.
(
  cd "$work"
  "$compiler" -M -MG -Iinc project/main.c > mg.mk
  grep -F 'inc/present.h' mg.mk >/dev/null
  grep -F 'generated/config.h' mg.mk >/dev/null
  grep -F 'generated/api.h' mg.mk >/dev/null
  grep -F 'macro/generated.h' mg.mk >/dev/null
  ! grep -F 'project/generated/config.h' mg.mk >/dev/null
  ! grep -F 'inc/generated/config.h' mg.mk >/dev/null
  [ "$(grep -o 'generated/config.h' mg.mk | wc -l)" -eq 1 ]
)
echo 'OK(dependency -MG): raw generated header names and physical existing headers'

# -MF/-MT and -MP compose with -MG. The generated prerequisite receives the
# same empty phony rule as an existing header dependency.
(
  cd "$work"
  "$compiler" -M -MG -MP -MF generated.mk -MT generated-target -Iinc project/main.c
  grep -F 'generated-target: project/main.c' generated.mk >/dev/null
  grep -Fx 'generated/config.h:' generated.mk >/dev/null
  grep -Fx 'generated/api.h:' generated.mk >/dev/null
  grep -Fx 'macro/generated.h:' generated.mk >/dev/null
)
echo 'OK(dependency -MG): composes with -MF/-MT/-MP'

# -MM -MG also keeps a directly missing header because no system directory ever
# resolved it. But a missing child reached while preprocessing a real system
# header remains part of the system subtree and is omitted by -MM.
cat > "$work/project/mm.c" <<'SRC'
#include <sys.h>
#include <generated-direct.h>
int value = 0;
SRC
(
  cd "$work"
  "$compiler" -M -MG -isystem system project/mm.c > all-system.mk
  grep -F 'system/sys.h' all-system.mk >/dev/null
  grep -F 'generated-system-child.h' all-system.mk >/dev/null
  grep -F 'generated-direct.h' all-system.mk >/dev/null

  "$compiler" -MM -MG -isystem system project/mm.c > user-only.mk
  ! grep -F 'system/sys.h' user-only.mk >/dev/null
  ! grep -F 'generated-system-child.h' user-only.mk >/dev/null
  grep -F 'generated-direct.h' user-only.mk >/dev/null
)
echo 'OK(dependency -MG): -MM filters missing headers inside system subtrees'

# Search paths are exhausted before a header is considered generated. A file
# found later in -I order must therefore be recorded by its resolved path.
mkdir -p "$work/empty" "$work/later"
cat > "$work/later/later.h" <<'SRC'
#define LATER_VALUE 1
SRC
cat > "$work/project/later.c" <<'SRC'
#include <later.h>
int value = LATER_VALUE;
SRC
(
  cd "$work"
  "$compiler" -M -MG -Iempty -Ilater project/later.c > later.mk
  grep -F 'later/later.h' later.mk >/dev/null
  [ "$(grep -o 'later.h' later.mk | wc -l)" -eq 1 ]
)
echo 'OK(dependency -MG): normal search resolution wins before generated fallback'

# A raw generated prerequisite must not be stat'ed against the process CWD.
# Angle lookup does not search CWD, so cwd-only.h is generated here even though
# a file with that spelling exists. A separately resolved symlink to that CWD
# file must remain a second physical prerequisite rather than inode-deduping it.
cat > "$work/cwd-only.h" <<'SRC'
#define CWD_ONLY_VALUE 1
SRC
ln -s ../cwd-only.h "$work/inc/cwd-alias.h"
cat > "$work/project/cwd-identity.c" <<'SRC'
#include <cwd-only.h>
#include <cwd-alias.h>
int value = CWD_ONLY_VALUE;
SRC
(
  cd "$work"
  "$compiler" -M -MG -Iinc project/cwd-identity.c > cwd-identity.mk
  grep -F 'cwd-only.h' cwd-identity.mk >/dev/null
  grep -F 'inc/cwd-alias.h' cwd-identity.mk >/dev/null
)
echo 'OK(dependency -MG): missing names do not inherit unrelated CWD inode identity'

# -MG is dependency-only: allowing it with normal compilation or side-effect
# dependency modes would continue without the generated header's contents and
# could silently produce invalid code.
for mode in '' '-MD' '-MMD'; do
  if "$compiler" $mode -MG "$work/project/main.c" > "$work/bad.out" 2> "$work/bad.err"; then
    fail "-MG unexpectedly accepted outside -M/-MM mode: ${mode:-compile}"
  fi
  grep -F "'-MG' requires dependency-only mode '-M' or '-MM'" "$work/bad.err" >/dev/null
done

echo 'All generated-header dependency tests passed!'
