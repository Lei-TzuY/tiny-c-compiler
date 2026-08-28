from pathlib import Path

p = Path('parse.c')
s = p.read_text()

anchor = 'static SwitchContext *current_switch;\n'
if anchor not in s:
    raise RuntimeError('switch context anchor not found')
s = s.replace(anchor, anchor + 'static int current_loop_depth;\n', 1)

old = '''    if (equal(tok, "break")) {
        *rest = skip(tok->next, ";");
        return new_node(ND_BREAK);
    }

    if (equal(tok, "continue")) {
        *rest = skip(tok->next, ";");
        return new_node(ND_CONTINUE);
    }
'''
new = '''    if (equal(tok, "break")) {
        if (current_loop_depth == 0 && !current_switch)
            error_at(tok->loc, "break statement not within loop or switch");
        *rest = skip(tok->next, ";");
        return new_node(ND_BREAK);
    }

    if (equal(tok, "continue")) {
        if (current_loop_depth == 0)
            error_at(tok->loc, "continue statement not within loop");
        *rest = skip(tok->next, ";");
        return new_node(ND_CONTINUE);
    }
'''
if old not in s:
    raise RuntimeError('break/continue anchor not found')
s = s.replace(old, new, 1)

lines = s.splitlines()

def wrap_loop_body(keyword, call_text, window):
    start = next((i for i, line in enumerate(lines)
                  if line.strip() == f'if (equal(tok, "{keyword}")) {{'), None)
    if start is None:
        raise RuntimeError(f'{keyword} loop anchor not found')
    target = next((i for i in range(start, min(len(lines), start + window))
                   if lines[i].strip() == call_text), None)
    if target is None:
        raise RuntimeError(f'{keyword} body call not found')
    indent = lines[target][:len(lines[target]) - len(lines[target].lstrip())]
    original = lines[target]
    lines[target:target + 1] = [
        indent + 'current_loop_depth++;',
        original,
        indent + 'current_loop_depth--;',
    ]

wrap_loop_body('do', 'node->then = stmt(&tok, tok->next);', 30)
wrap_loop_body('while', 'node->then = stmt(&tok, tok);', 30)
wrap_loop_body('for', 'node->then = stmt(rest, tok);', 80)

s = '\n'.join(lines) + '\n'
init_anchor = '    current_scope = calloc(1, sizeof(Scope));\n'
if init_anchor not in s:
    raise RuntimeError('parse initialization anchor not found')
s = s.replace(init_anchor, init_anchor + '    current_loop_depth = 0;\n', 1)
p.write_text(s)

Path('test/control_flow_context.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-flow.c
  ./minicc tmp-control-flow.c > tmp-control-flow.s
  cc -o tmp-control-flow tmp-control-flow.s
  set +e
  ./tmp-control-flow
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(control flow): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(control flow): $actual"
}

assert_reject_msg() {
  pattern="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-control-flow-reject.c
  if ./minicc tmp-control-flow-reject.c > /dev/null 2>tmp-control-flow.err; then
    echo "FAIL(control flow): expected rejection"
    echo "$input"
    exit 1
  fi
  if ! grep -q "$pattern" tmp-control-flow.err; then
    echo "FAIL(control flow): missing diagnostic '$pattern'"
    cat tmp-control-flow.err
    exit 1
  fi
  echo "OK(control flow): rejected with $pattern"
}

assert_run 7 'int main(void){int x=0; while(1){x=7; break;} return x;}'
assert_run 4 'int main(void){int s=0; for(int i=0;i<5;i++){if(i%2==0) continue; s+=i;} return s;}'
assert_run 7 'int main(void){int i=0,s=0; do {i++; if(i<3) continue; s+=i;} while(i<4); return s;}'
assert_run 5 'int main(void){int x=0; switch(2){case 2:x=5;break;default:x=9;} return x;}'
assert_run 46 'int main(void){int s=0; for(int i=0;i<5;i++){switch(i){case 1:continue;case 3:break;default:s+=i;} s+=10;} return s;}'
assert_run 6 'int main(void){int s=0; for(int i=0;i<3;i++){for(int j=0;j<4;j++){if(j==2) break; s++;}} return s;}'
assert_run 3 'int main(void){int i=0; while(i<3){switch(i){case 0:i++;continue;default:i++;break;}} return i;}'

assert_reject_msg 'break statement not within loop or switch' 'int main(void){break;}'
assert_reject_msg 'continue statement not within loop' 'int main(void){continue;}'
assert_reject_msg 'break statement not within loop or switch' 'int main(void){if(1){break;} return 0;}'
assert_reject_msg 'continue statement not within loop' 'int main(void){switch(1){default:continue;} return 0;}'
assert_reject_msg 'continue statement not within loop' 'int main(void){{{continue;}}}'

echo 'All control-flow context tests passed!'
''')

mp = Path('Makefile')
make = mp.read_text()
needle = '\tbash ./test/nested_switch_labels.sh\n'
if needle not in make:
    raise RuntimeError('Makefile switch-test anchor not found')
make = make.replace(needle, needle + '\tbash ./test/control_flow_context.sh\n', 1)
mp.write_text(make)

rp = Path('README.md')
readme = rp.read_text()
lines = readme.splitlines()
idx = next((i for i, line in enumerate(lines) if line.startswith('- **Scope**:')), None)
if idx is None:
    raise RuntimeError('README scope bullet not found')
lines.insert(idx + 1, '- **Control-flow constraints**: `break` is accepted only inside loops or `switch`, while `continue` is accepted only inside loops, including correctly nested loop/switch combinations')
rp.write_text('\n'.join(lines) + '\n')
