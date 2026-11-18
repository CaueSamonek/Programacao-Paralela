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

Os casos em `tests/cases/` cobrem sequencias iguais, diferentes, vazias,
unitarias e o exemplo classico. Cada caso e executado na versao sequencial e
na paralela com diferentes quantidades de processos e threads.

## Experimentos

```bash
make quick       # validacao curta
make calibrate   # procura um tamanho adequado
make experiment  # campanha completa, 20 repeticoes
```

As campanhas geram dados brutos, medias, desvios, speedup, eficiencia, Lei de
Amdahl e um resumo em `resultados/`.

## Estrutura

```text
src/            versoes sequencial e paralela autocontidas
tests/          testes de corretude e arquivos de entrada
resultados/     ultima campanha completa e novas medicoes
experiments.py  orquestrador dos experimentos
```
