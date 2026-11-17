#!/usr/bin/env bash
# Roda todos os testes no computador (precisa de g++). Uso:  bash test/run_tests.sh
set -e
cd "$(dirname "$0")"
echo "== Testes do nucleo (fila_core.h) =="
g++ -std=c++17 -Wall -Wextra -O1 -fsanitize=address,undefined -o /tmp/test_core test_fila_core.cpp
/tmp/test_core
echo
echo "== Simulacao do sketch.ino com hardware simulado =="
g++ -std=c++17 -Wall -Wextra -O1 -fsanitize=address,undefined -Istubs -x c++ ../sketch.ino -x c++ test_sketch_sim.cpp -o /tmp/test_sketch
/tmp/test_sketch
