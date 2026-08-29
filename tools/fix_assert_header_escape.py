from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()
start_marker = '    if (!strcmp(name, "assert.h")) {'
end_marker = '    if (!strcmp(name, "stdbool.h")) {'
start = text.index(start_marker)
end = text.index(end_marker, start)
replacement = r'''    if (!strcmp(name, "assert.h")) {
        return "#ifdef assert\n"
               "#undef assert\n"
               "#endif\n"
               "#ifdef NDEBUG\n"
               "#define assert(expression) ((void)0)\n"
               "#else\n"
               "#include <stdio.h>\n"
               "#include <stdlib.h>\n"
               "#define assert(expression) ((void)((expression) || (fprintf(stderr, \"%s:%d: %s: Assertion `%s' failed.\\n\", __FILE__, __LINE__, __func__, #expression), abort(), 0)))\n"
               "#endif\n";
    }
'''
pp.write_text(text[:start] + replacement + text[end:])
