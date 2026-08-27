from pathlib import Path

p = Path('test/escape_sequences.sh')
s = p.read_text()
s = s.replace('  printf "%b" "$input" > tmp-escape-bad.c\n', '  printf "%s" "$input" > tmp-escape-bad.c\n')
s = s.replace('    printf "%b\\n" "$input"\n', '    printf "%s\\n" "$input"\n')
s = s.replace("assert_fail 'int main(){char *s=\"abc\\ndef\";return 0;}\\n'\n", "assert_fail $'int main(){char *s=\"abc\\ndef\";return 0;}\\n'\n")
s = s.replace('assert_fail "int main(){return \'a\\n\';}\\n"\n', 'assert_fail $\'int main(){return \\\'a\\n\\\';}\\n\'\n')
p.write_text(s)
