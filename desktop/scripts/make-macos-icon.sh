#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ICON="$ROOT_DIR/renderer/assets/icon.png"
ICONSET_DIR="$ROOT_DIR/build/icon.iconset"
OUTPUT_ICON="$ROOT_DIR/build/icon.icns"

if [[ ! -f "$SOURCE_ICON" ]]; then
  echo "Source icon not found: $SOURCE_ICON" >&2
  exit 1
fi

rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

sizes=(16 32 64 128 256 512)
for size in "${sizes[@]}"; do
  small_name="icon_${size}x${size}.png"
  sips -z "$size" "$size" "$SOURCE_ICON" --out "$ICONSET_DIR/$small_name" >/dev/null

  retina_size=$((size * 2))
  retina_name="icon_${size}x${size}@2x.png"
  sips -z "$retina_size" "$retina_size" "$SOURCE_ICON" --out "$ICONSET_DIR/$retina_name" >/dev/null
done

iconutil -c icns "$ICONSET_DIR" -o "$OUTPUT_ICON"
echo "Created $OUTPUT_ICON"
