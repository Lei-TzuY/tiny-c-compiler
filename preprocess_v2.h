#ifndef PREPROCESS_V2_H
#define PREPROCESS_V2_H

char *preprocess_v2(char *input);
char *preprocess_v2_source(char *input, const char *source_name);
void preprocess_v2_add_define(const char *definition);
void preprocess_v2_add_undef(const char *name);
void preprocess_v2_add_include_path(const char *path);
void preprocess_v2_add_system_include_path(const char *path);
int preprocess_v2_dependency_count(void);
const char *preprocess_v2_dependency_at(int index);
int preprocess_v2_dependency_is_system(int index);

#endif
