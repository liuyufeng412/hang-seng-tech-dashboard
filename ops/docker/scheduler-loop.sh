#!/bin/sh
set -eu

mkdir -p data/runtime/logs

while true; do
  python -m pipeline.scheduler >> data/runtime/logs/scheduler.log 2>> data/runtime/logs/scheduler-error.log || true
  sleep 300
done
