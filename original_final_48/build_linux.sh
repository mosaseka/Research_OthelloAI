#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "$0")"
javac -encoding UTF-8 OthelloAI_final_48.java
echo "build complete: OthelloAI_final_48.class"
