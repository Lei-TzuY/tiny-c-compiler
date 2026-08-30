from pathlib import Path

main = Path("main.c")
text = main.read_text()
old = '''static char *path_with_extension(const char *path, const char *extension,
                                 bool basename_only) {
    const char *base = path;
    if (basename_only) {
        const char *slash = strrchr(path, '/');
        if (slash)
            base = slash + 1;
    }

    const char *dot = strrchr(base, '.');
    size_t stem_len = (dot && dot != base) ? (size_t)(dot - base) : strlen(base);
    size_t ext_len = strlen(extension);
    char *result = calloc(1, stem_len + ext_len + 1);
    memcpy(result, base, stem_len);
    memcpy(result + stem_len, extension, ext_len + 1);
    return result;
}
'''
new = '''static char *path_with_extension(const char *path, const char *extension,
                                 bool basename_only) {
    const char *slash = strrchr(path, '/');
    const char *component = slash ? slash + 1 : path;
    const char *base = basename_only ? component : path;
    const char *dot = strrchr(component, '.');
    size_t stem_len = (dot && dot != component) ? (size_t)(dot - base) : strlen(base);
    size_t ext_len = strlen(extension);
    char *result = calloc(1, stem_len + ext_len + 1);
    memcpy(result, base, stem_len);
    memcpy(result + stem_len, extension, ext_len + 1);
    return result;
}
'''
if text.count(old) != 1:
    raise SystemExit(f"path helper: expected one match, found {text.count(old)}")
main.write_text(text.replace(old, new, 1))

test = Path("test/dependency_generation.sh")
text = test.read_text()
old = '''./minicc -MD -MF tmp-deps-custom.d -MT custom-target -o tmp-deps-custom.s tmp-deps-main.c
grep -F 'custom-target:' tmp-deps-custom.d >/dev/null || fail '-MF/-MT did not override -MD defaults'
test -s tmp-deps-custom.s || fail '-MD -MF/-MT lost compiler output'
'''
new = old + '''
# Only the final path component contributes an extension. A dotted directory
# name must be preserved when deriving the default .d sidecar from -o.
mkdir -p tmp-deps-tree/build.v1
./minicc -MD -o tmp-deps-tree/build.v1/program.s tmp-deps-main.c
test -s tmp-deps-tree/build.v1/program.d || fail 'dotted output directory corrupted .d path derivation'
grep -F 'tmp-deps-tree/build.v1/program.s:' tmp-deps-tree/build.v1/program.d >/dev/null || \
  fail 'dotted output directory corrupted dependency target'
'''
if text.count(old) != 1:
    raise SystemExit(f"dependency regression insertion: expected one match, found {text.count(old)}")
test.write_text(text.replace(old, new, 1))
