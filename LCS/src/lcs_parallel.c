#include <limits.h>
#include <mpi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FILE_A "fileA.in"
#define FILE_B "fileB.in"
#define TILE_SIZE 256
#define BORDER_TAG 0

typedef unsigned short mtype;

static char *read_sequence(const char *filename, size_t *length) {
    FILE *file = fopen(filename, "rb");
    if (file == NULL) {
        fprintf(stderr, "Erro ao abrir %s.\n", filename);
        return NULL;
    }

    if (fseek(file, 0, SEEK_END) != 0) {
        fprintf(stderr, "Erro ao medir %s.\n", filename);
        fclose(file);
        return NULL;
    }

    long file_size = ftell(file);
    if (file_size < 0 || fseek(file, 0, SEEK_SET) != 0) {
        fprintf(stderr, "Erro ao medir %s.\n", filename);
        fclose(file);
        return NULL;
    }

    char *sequence = malloc((size_t)file_size + 1);
    if (sequence == NULL) {
        fprintf(stderr, "Memoria insuficiente para ler %s.\n", filename);
        fclose(file);
        return NULL;
    }

    // le uma sequencia formada por letras e numeros.
    if (fscanf(file, "%s", sequence) != 1) {
        sequence[0] = '\0';
    }

    *length = strlen(sequence);
    fclose(file);
    return sequence;
}

static mtype *allocate_matrix(size_t rows, size_t columns) {
    if (rows == 0 || columns == 0 || rows > SIZE_MAX / columns ||
        rows * columns > SIZE_MAX / sizeof(mtype)) {
        return NULL;
    }

    // calloc zera a matriz
    return calloc(rows * columns, sizeof(mtype));
}

static mtype lcs_distributed(mtype *matrix, size_t columns,
                             size_t local_rows, size_t first_global_row,
                             const char *seq_a, const char *seq_b,
                             size_t size_a, int rank, int process_count,
                             MPI_Comm communicator) {
    size_t row_tile_count = (local_rows + TILE_SIZE - 1) / TILE_SIZE;
    size_t column_tile_count = (size_a + TILE_SIZE - 1) / TILE_SIZE;
    size_t diagonal_count = row_tile_count + column_tile_count - 1;

    // cada processo calcula um grupo de linhas e as threads dividem os blocos.
    #pragma omp parallel
    {
        for (size_t tile_diagonal = 0; tile_diagonal < diagonal_count; ++tile_diagonal) {
            #pragma omp master
            {
                if (rank > 0 && tile_diagonal < column_tile_count) {
                    size_t column_tile = tile_diagonal;
                    size_t first_column = column_tile * TILE_SIZE + 1;
                    size_t last_column = first_column + TILE_SIZE - 1;
                    if (last_column > size_a) {
                        last_column = size_a;
                    }

                    // recebe do processo anterior a borda superior do bloco.
                    size_t border_length = last_column - first_column + 2;
                    MPI_Recv(&matrix[first_column - 1], (int)border_length,
                             MPI_UNSIGNED_SHORT, rank - 1, BORDER_TAG,
                             communicator, MPI_STATUS_IGNORE);
                }
            }

            // espera a borda chegar antes de iniciar o calculo do bloco.
            #pragma omp barrier

            size_t first_row_tile = 0;
            if (tile_diagonal >= column_tile_count) {
                first_row_tile = tile_diagonal - column_tile_count + 1;
            }

            size_t last_row_tile = tile_diagonal;
            if (last_row_tile >= row_tile_count) {
                last_row_tile = row_tile_count - 1;
            }

            // os blocos da mesma antidiagonal nao dependem entre si.
            #pragma omp for schedule(static)
            for (size_t row_tile = first_row_tile; row_tile <= last_row_tile; ++row_tile) {
                size_t column_tile = tile_diagonal - row_tile;
                size_t first_row = row_tile * TILE_SIZE + 1;
                size_t last_row = first_row + TILE_SIZE - 1;
                size_t first_column = column_tile * TILE_SIZE + 1;
                size_t last_column = first_column + TILE_SIZE - 1;

                if (last_row > local_rows) {
                    last_row = local_rows;
                }
                if (last_column > size_a) {
                    last_column = size_a;
                }

                // percorre por linhas para preservar as dependencias acima e esquerda.
                for (size_t row = first_row; row <= last_row; ++row) {
                    size_t global_row = first_global_row + row - 1;
                    for (size_t column = first_column; column <= last_column; ++column) {
                        size_t current_index = row * columns + column;

                        if (seq_a[column - 1] == seq_b[global_row - 1]) {
                            matrix[current_index] = matrix[current_index - columns - 1] + 1;
                        } else {
                            mtype above = matrix[current_index - columns];
                            mtype left = matrix[current_index - 1];
                            matrix[current_index] = above > left ? above : left;
                        }
                    }
                }
            }

            // a barreira implicita do omp for conclui a antidiagonal atual.
            #pragma omp master
            {
                if (rank + 1 < process_count && tile_diagonal + 1 >= row_tile_count) {
                    size_t column_tile = tile_diagonal + 1 - row_tile_count;
                    if (column_tile < column_tile_count) {
                        size_t first_column = column_tile * TILE_SIZE + 1;
                        size_t last_column = first_column + TILE_SIZE - 1;
                        if (last_column > size_a) {
                            last_column = size_a;
                        }

                        size_t border_length = last_column - first_column + 2;
                        size_t bottom =
                            local_rows * columns + first_column - 1;
                        MPI_Send(&matrix[bottom], (int)border_length,
                                 MPI_UNSIGNED_SHORT, rank + 1, BORDER_TAG,
                                 communicator);
                    }
                }
            }

            // espera o envio da borda terminar antes de avancar.
            #pragma omp barrier
        }
    }

    return matrix[local_rows * columns + size_a];
}

int main(int argc, char **argv) {
    int provided;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided);

    int world_rank;
    int world_size;
    MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
    MPI_Comm_size(MPI_COMM_WORLD, &world_size);
    double total_start = MPI_Wtime();

    if (provided < MPI_THREAD_FUNNELED) {
        if (world_rank == 0) {
            fprintf(stderr, "A biblioteca MPI nao oferece MPI_THREAD_FUNNELED.\n");
        }
        MPI_Finalize();
        return EXIT_FAILURE;
    }

    char *seq_a = NULL;
    char *seq_b = NULL;
    size_t size_a = 0;
    size_t size_b = 0;
    int input_ok = 1;

    if (world_rank == 0) {
        seq_a = read_sequence(FILE_A, &size_a);
        seq_b = read_sequence(FILE_B, &size_b);
        input_ok = seq_a != NULL && seq_b != NULL;

        size_t smaller = size_a < size_b ? size_a : size_b;
        if (input_ok && smaller > USHRT_MAX) {
            fprintf(stderr, "O resultado pode exceder o limite de mtype (%u).\n",
                    USHRT_MAX);
            input_ok = 0;
        }
        if (input_ok && (size_a >= INT_MAX || size_b >= INT_MAX)) {
            fprintf(stderr, "Entrada grande demais para as operacoes MPI.\n");
            input_ok = 0;
        }
    }

    MPI_Bcast(&input_ok, 1, MPI_INT, 0, MPI_COMM_WORLD);
    if (!input_ok) {
        free(seq_a);
        free(seq_b);
        MPI_Finalize();
        return EXIT_FAILURE;
    }

    uint64_t lengths[2] = {(uint64_t)size_a, (uint64_t)size_b};
    MPI_Bcast(lengths, 2, MPI_UINT64_T, 0, MPI_COMM_WORLD);
    size_a = (size_t)lengths[0];
    size_b = (size_t)lengths[1];

    if (world_rank != 0) {
        seq_a = malloc(size_a + 1);
        seq_b = malloc(size_b + 1);
    }

    int local_input_memory_ok = seq_a != NULL && seq_b != NULL;
    int all_input_memory_ok;
    MPI_Allreduce(&local_input_memory_ok, &all_input_memory_ok, 1, MPI_INT,
                  MPI_LAND, MPI_COMM_WORLD);
    if (!all_input_memory_ok) {
        if (world_rank == 0) {
            fprintf(stderr, "Memoria insuficiente para distribuir as entradas.\n");
        }
        free(seq_a);
        free(seq_b);
        MPI_Finalize();
        return EXIT_FAILURE;
    }

    MPI_Bcast(seq_a, (int)size_a + 1, MPI_CHAR, 0, MPI_COMM_WORLD);
    MPI_Bcast(seq_b, (int)size_b + 1, MPI_CHAR, 0, MPI_COMM_WORLD);
    double input_end = MPI_Wtime();

    mtype score = 0;
    double allocation_time = 0.0;
    double kernel_time = 0.0;
    double total_time = input_end - total_start;
    int active_count = size_b == 0 ? 1 : world_size;
    if (active_count > (int)size_b && size_b > 0) {
        active_count = (int)size_b;
    }

    // exclui do calculo os processos que nao receberam linhas.
    MPI_Comm active_communicator;
    int color = world_rank < active_count ? 1 : MPI_UNDEFINED;
    MPI_Comm_split(MPI_COMM_WORLD, color, world_rank, &active_communicator);

    if (world_rank < active_count && size_a > 0 && size_b > 0) {
        int rank;
        int process_count;
        MPI_Comm_rank(active_communicator, &rank);
        MPI_Comm_size(active_communicator, &process_count);

        size_t rows_per_process = size_b / (size_t)process_count;
        size_t remainder = size_b % (size_t)process_count;
        size_t local_rows = rows_per_process + ((size_t)rank < remainder);
        size_t first_global_row = 1 + (size_t)rank * rows_per_process;
        first_global_row += (size_t)rank < remainder ? (size_t)rank : remainder;

        size_t columns = size_a + 1;
        double allocation_start = MPI_Wtime();
        mtype *local_matrix = allocate_matrix(local_rows + 1, columns);
        int local_matrix_ok = local_matrix != NULL;
        int all_matrices_ok;
        MPI_Allreduce(&local_matrix_ok, &all_matrices_ok, 1, MPI_INT,
                      MPI_LAND, active_communicator);

        if (!all_matrices_ok) {
            if (world_rank == 0) {
                fprintf(stderr, "Memoria insuficiente para a matriz distribuida.\n");
            }
            free(local_matrix);
            MPI_Abort(MPI_COMM_WORLD, EXIT_FAILURE);
        }
        allocation_time = MPI_Wtime() - allocation_start;

        double kernel_start = MPI_Wtime();
        mtype local_score = lcs_distributed(
            local_matrix, columns, local_rows, first_global_row, seq_a, seq_b,
            size_a, rank, process_count, active_communicator);

        // envia o resultado do ultimo processo ativo para o processo zero.
        score = local_score;
        MPI_Bcast(&score, 1, MPI_UNSIGNED_SHORT, process_count - 1,
                  active_communicator);
        kernel_time = MPI_Wtime() - kernel_start;
        total_time = MPI_Wtime() - total_start;

        free(local_matrix);
    }

    if (world_rank < active_count) {
        MPI_Comm_free(&active_communicator);
    }

    double local_times[4] = {
        input_end - total_start,
        allocation_time,
        kernel_time,
        total_time,
    };
    double maximum_times[4];
    MPI_Reduce(local_times, maximum_times, 4, MPI_DOUBLE, MPI_MAX, 0,
               MPI_COMM_WORLD);

    if (world_rank == 0) {
        printf("%hu\n", score);
        if (getenv("LCS_TIMING") != NULL) {
            fprintf(stderr,
                    "input=%.9f allocation=%.9f kernel=%.9f total=%.9f\n",
                    maximum_times[0], maximum_times[1], maximum_times[2],
                    maximum_times[3]);
        }
    }

    free(seq_a);
    free(seq_b);
    MPI_Finalize();
    return EXIT_SUCCESS;
}
