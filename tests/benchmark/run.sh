#!/bin/sh
set -eu

# Send only the checkout files the benchmark needs.
tar -cf - pyproject.toml uv.lock README.md src tests/fixtures/ecommerce.sql tests/benchmark |
    docker build -f tests/benchmark/Dockerfile -t seed-reference-benchmark -
docker run --rm --network none --cpus 4 --memory 8g --memory-swap 8g seed-reference-benchmark
