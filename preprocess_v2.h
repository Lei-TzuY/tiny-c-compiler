#ifndef PREPROCESS_V2_H
#define PREPROCESS_V2_H

typedef enum {
    PREPROCESS_DUMP_NONE,
    PREPROCESS_DUMP_DEFINITIONS,
    PREPROCESS_DUMP_NAMES,
} PreprocessDumpMode;

char *preprocess_v2(char *input);
char *preprocess_v2_source(char *input, const char *source_name);
void preprocess_v2_add_define(const char *definition);
void preprocess_v2_add_undef(const char *name);
void preprocess_v2_add_include_path(const char *path);
void preprocess_v2_add_quote_include_path(const char *path);
void preprocess_v2_add_system_include_path(const char *path);
void preprocess_v2_add_after_include_path(const char *path);
void preprocess_v2_enable_missing_header_dependencies(void);
void preprocess_v2_disable_standard_includes(void);
void preprocess_v2_add_forced_include(const char *path);
void preprocess_v2_add_imacros(const char *path);
void preprocess_v2_set_dump_mode(PreprocessDumpMode mode);
char *preprocess_v2_dump_macros(void);
int preprocess_v2_dependency_count(void);
const char *preprocess_v2_dependency_at(int index);
int preprocess_v2_dependency_is_system(int index);

#endif
