#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define FILE_A "fileA.in"
#define FILE_B "fileB.in"

typedef unsigned short mtype;

static double wall_time(void) {
    struct timespec now;
    timespec_get(&now, TIME_UTC);
    return (double)now.tv_sec + (double)now.tv_nsec / 1000000000.0;
}

static char *read_sequence(const char *filename, size_t *length) {
    FILE *file = fopen(filename, "rb");
    if (file == NULL) {
        fprintf(stderr, "Erro ao abrir %s.\n", filename);
        return NULL;
    }

    fseek(file, 0, SEEK_END);
    long file_size = ftell(file);
    rewind(file);

    if (file_size < 0) {
        fclose(file);
        return NULL;
    }

    char *sequence = malloc((size_t)file_size + 1);
    if (sequence == NULL) {
        fclose(file);
        return NULL;
    }

    if (fscanf(file, "%s", sequence) != 1) {
        sequence[0] = '\0';
    }
    *length = strlen(sequence);
    fclose(file);
    return sequence;
}

int main(void) {
    double total_start = wall_time();

    size_t size_a;
    size_t size_b;
    char *seq_a = read_sequence(FILE_A, &size_a);
    char *seq_b = read_sequence(FILE_B, &size_b);
    double input_end = wall_time();

    if (seq_a == NULL || seq_b == NULL) {
        free(seq_a);
        free(seq_b);
        return EXIT_FAILURE;
    }

    size_t rows = size_b + 1;
    size_t columns = size_a + 1;
    mtype *matrix = calloc(rows * columns, sizeof(*matrix));
    double allocation_end = wall_time();
    if (matrix == NULL) {
        fprintf(stderr, "Memoria insuficiente para a matriz.\n");
        free(seq_a);
        free(seq_b);
        return EXIT_FAILURE;
    }

    for (size_t row = 1; row < rows; ++row) {
        for (size_t column = 1; column < columns; ++column) {
            size_t current = row * columns + column;
            if (seq_a[column - 1] == seq_b[row - 1]) {
                matrix[current] = matrix[current - columns - 1] + 1;
            } else {
                mtype above = matrix[current - columns];
                mtype left = matrix[current - 1];
                matrix[current] = above > left ? above : left;
            }
        }
    }

    double kernel_end = wall_time();
    mtype score = matrix[(rows - 1) * columns + columns - 1];
    printf("%hu\n", score);

    if (getenv("LCS_TIMING") != NULL) {
        fprintf(stderr, "input=%.9f allocation=%.9f kernel=%.9f total=%.9f\n",
                input_end - total_start, allocation_end - input_end,
                kernel_end - allocation_end, kernel_end - total_start);
    }

    free(matrix);
    free(seq_a);
    free(seq_b);
    return EXIT_SUCCESS;
}
