#!/bin/bash
cd defi-agents/polymarket/src/rust_executor && LIBRARY_PATH=./lib nohup taskset -c 5 ./target/debug/rust_executor --shadow > ../../logs/shadow_run.log 2>&1 & 
sleep 3
tail -n 20 ../../logs/shadow_run.log
