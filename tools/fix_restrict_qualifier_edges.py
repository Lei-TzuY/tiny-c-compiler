from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    "static bool qualifier_superset(Type *dst, Type *src) {\n"
    "    return dst && src &&\n"
    "           (!src->is_const || dst->is_const) &&\n"
    "           (!src->is_volatile || dst->is_volatile);\n"
    "}\n",
    "static bool qualifier_superset(Type *dst, Type *src) {\n"
    "    return dst && src &&\n"
    "           (!src->is_const || dst->is_const) &&\n"
    "           (!src->is_volatile || dst->is_volatile) &&\n"
    "           (!src->is_restrict || dst->is_restrict);\n"
    "}\n",
)

replace_once(
    "parse.c",
    "        bool merged_const = tt->base->is_const || et->base->is_const;\n"
    "        bool merged_volatile = tt->base->is_volatile || et->base->is_volatile;\n\n"
    "        if (type_compatible_ignoring_top_qual(tt->base, et->base))\n"
    "            return pointer_to(qualify_type(tt->base, merged_const, merged_volatile, false));\n",
    "        bool merged_const = tt->base->is_const || et->base->is_const;\n"
    "        bool merged_volatile = tt->base->is_volatile || et->base->is_volatile;\n"
    "        bool merged_restrict = tt->base->is_restrict || et->base->is_restrict;\n\n"
    "        if (type_compatible_ignoring_top_qual(tt->base, et->base))\n"
    "            return pointer_to(qualify_type(tt->base, merged_const, merged_volatile,\n"
    "                                           merged_restrict));\n",
)

p = Path("test/restrict_qualifier.sh")
text = p.read_text()
marker = "# Address-of preserves the restricted pointer object's nested type identity.\n"
insert = r'''# Nested restrict qualification participates in pointer assignment conversion:
# adding it is permitted, discarding it is not.
assert_compile 'int main(void){int **src=0;int *restrict *dst=src;return dst!=0;}'
assert_reject 'int main(void){int *restrict *src=0;int **dst=src;return dst!=0;}'

# Conditional pointer composition unions the immediate pointed-to qualifier set.
assert_run 0 'int main(void){int *restrict *a=0;int **b=0;return _Generic(1?a:b,int *restrict *:0,default:1);}'
assert_reject 'int main(void){int *restrict *a=0;int **b=0;int **r=1?a:b;return r!=0;}'

'''
if insert not in text:
    if marker not in text:
        raise SystemExit("test marker not found")
    text = text.replace(marker, insert + marker, 1)
p.write_text(text)

print("restrict qualifier edge cases fixed")
