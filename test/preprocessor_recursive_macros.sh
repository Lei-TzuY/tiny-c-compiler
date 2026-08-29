#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-pp-rec.c
  ./minicc tmp-pp-rec.c > tmp-pp-rec.s
  cc -o tmp-pp-rec tmp-pp-rec.s
  ./tmp-pp-rec
}

# A macro is disabled while its own replacement list is being rescanned.  The
# surviving identifier may still be used as an ordinary C identifier after the
# rescan finishes; it must not trigger unbounded recursive expansion.
compile_and_run <<'EOF'
#define SELF SELF
int SELF = 5;
int main(void) { return SELF == 5 ? 0 : 1; }
EOF

# Indirect recursion must also terminate.  Expanding LEFT -> RIGHT -> LEFT
# leaves the second LEFT unavailable for this rescan, rather than cycling.
compile_and_run <<'EOF'
#define LEFT RIGHT
#define RIGHT LEFT
int LEFT = 7;
int main(void) { return LEFT == 7 ? 0 : 1; }
EOF

# Function-like self recursion follows the same disabled-macro rule.  This is
# useful in practice for wrapper-style macro patterns where the surviving name
# refers to a real function once macro expansion stops.
compile_and_run <<'EOF'
#define CALL(x) CALL(x)
int CALL(int x) { return x + 1; }
int main(void) { return CALL(3) == 4 ? 0 : 1; }
EOF

# Mutual function-like recursion must terminate as well, preserving a callable
# identifier instead of repeatedly bouncing between the two macro names.
compile_and_run <<'EOF'
#define FIRST(x) SECOND(x)
#define SECOND(x) FIRST(x)
int FIRST(int x) { return x + 2; }
int main(void) { return FIRST(3) == 5 ? 0 : 1; }
EOF

rm -f tmp-pp-rec.c tmp-pp-rec.s tmp-pp-rec

echo 'All recursive preprocessor macro tests passed!'
