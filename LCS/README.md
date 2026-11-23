# LCS paralelo com MPI e OpenMP

Requisitos: GCC, Open MPI, suporte a OpenMP e Python 3.

## Compilar

```bash
make
```

## Executar

```bash
./bin/lcs_seq
mpirun -np 2 ./bin/lcs_parallel
```

Os dois programas leem diretamente `fileA.in` e `fileB.in`. Nos experimentos,
`OMP_NUM_THREADS` define a quantidade de threads e `mpirun -np N` define a
quantidade de processos MPI.

## Testar

```bash
make test
```

O teste cria temporariamente `fileA.in` e `fileB.in` para sequencias iguais,
diferentes, vazias, unitarias, alfanumericas e maiores que um tile. Cada caso
eh executado na versao sequencial e na paralela com diferentes quantidades de
processos e threads.

## Experimentos

```bash
make quick       # validacao curta
make experiment  # campanha completa, 20 repeticoes
```

As campanhas geram dados brutos, medias, desvios, speedup, eficiencia,
porcentagem nao paralelizavel, Lei de Amdahl e comparacao entre as estrategias
OpenMP, MPI e OpenMP+MPI em `resultados/`.

No `amdahl.csv`, o tempo nao paralelizavel eh a soma da leitura das entradas
com a alocacao da matriz na execucao sequencial. O kernel do LCS eh a parte
paralelizavel. As duas porcentagens sao calculadas sobre o tempo sequencial
total.

No `strategies.csv`, `openmp` usa um processo e varias threads, `mpi` usa
varios processos e uma thread por processo, e `openmp_mpi` usa varios
processos e varias threads. Para cada quantidade total de workers, `winner`
marca a configuracao que obteve a menor media de tempo.

## Estrutura

```text
src/            versoes sequencial e paralela autocontidas
tests/          testes de corretude e arquivos de entrada
resultados/     dados da campanha completa
experiments.py  orquestrador dos experimentos
```
