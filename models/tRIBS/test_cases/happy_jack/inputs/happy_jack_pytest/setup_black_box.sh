#!/bin/zsh

# intended to download benchmarks for big_spring_pytest and happy_jack_pytest and update the config.json file if needed.
curl -sS -o hj "https://zenodo.org/records/10909507/files/happy_jack.gz?download=1"
curl -sS -o bs "https://zenodo.org/records/10951574/files/big_spring.gz?download=1"

path_to_dir="benchmarks"
hj_tests_dir="happy_jack_pytest"
bs_tests_dir="big_spring_pytest"

mkdir -p $path_to_dir

# Extract benchmarks into the directory
tar -xzf hj -C $path_to_dir
tar -xzf bs -C $path_to_dir

# Clean up downloaded files
rm hj
rm bs

cp -r $hj_tests_dir/* $path_to_dir/happy_jack
cp -r $bs_tests_dir/* $path_to_dir/big_spring
cp config.json $path_to_dir


