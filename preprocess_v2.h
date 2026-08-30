#ifndef PREPROCESS_V2_H
#define PREPROCESS_V2_H

char *preprocess_v2(char *input);
char *preprocess_v2_source(char *input, const char *source_name);
void preprocess_v2_add_define(const char *definition);
void preprocess_v2_add_undef(const char *name);

#endif
