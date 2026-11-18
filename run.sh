#!/bin/sh
set -eu

case "${1:-}" in
    ""|--build-only) ;;
    *) echo "Usage: sh run.sh [--build-only]" >&2; exit 2 ;;
esac

if [ -z "${JAVAFX_LIB:-}" ] || [ ! -f "$JAVAFX_LIB/javafx.controls.jar" ]; then
    echo "Set JAVAFX_LIB to the Linux JavaFX SDK lib directory." >&2
    exit 1
fi
fx_lib=$(cd -- "$JAVAFX_LIB" && pwd)
cd -- "$(dirname -- "$0")"

tools=
if [ -n "${JAVA_HOME:-}" ]; then
    tools="$JAVA_HOME/bin/"
fi
classes=build/othello_gui/classes
dist=build/othello_gui/dist
mkdir -p "$classes" "$dist/original_final_48"

"${tools}javac" -encoding UTF-8 -d "$classes" --module-path "$fx_lib" --add-modules javafx.controls \
    Othello.java OthelloGUI.java original_final_48/OthelloAI_final_48.java
cp -R original_final_48/resources original_final_48/LICENSE "$dist/original_final_48/"
"${tools}jar" --create --file "$dist/othello.jar" --main-class OthelloGUI -C "$classes" . othello-title.css
echo "Created $dist/othello.jar"

if [ "${1:-}" != --build-only ]; then
    exec "${tools}java" --enable-native-access=javafx.graphics,ALL-UNNAMED \
        --module-path "$fx_lib" --add-modules javafx.controls -jar "$dist/othello.jar"
fi
