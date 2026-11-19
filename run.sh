#!/bin/sh
set -eu

case "${1:-}" in
    ""|--build-only) ;;
    *) echo "Usage: sh run.sh [--build-only]" >&2; exit 2 ;;
esac

cd -- "$(dirname -- "$0")"

tools=
if [ -n "${JAVA_HOME:-}" ]; then
    tools="$JAVA_HOME/bin/"
fi
classes=build/othello_gui/swing-classes
dist=build/othello_gui/dist
mkdir -p "$classes" "$dist/original_final_48"

"${tools}javac" --release 17 -encoding UTF-8 -d "$classes" \
    Othello.java OthelloGUI.java original_final_48/OthelloAI_final_48.java
cp -R original_final_48/resources original_final_48/LICENSE "$dist/original_final_48/"
"${tools}jar" --create --file "$dist/othello.jar" --main-class OthelloGUI -C "$classes" .
echo "Created $dist/othello.jar"

if [ "${1:-}" != --build-only ]; then
    exec "${tools}java" -jar "$dist/othello.jar"
fi
