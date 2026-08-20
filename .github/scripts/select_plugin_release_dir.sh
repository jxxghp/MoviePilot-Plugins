#!/usr/bin/env bash
set -euo pipefail

package_file="${1:?package file is required}"
plugin_id="${2:?lowercase plugin id is required}"

case "$(basename "$package_file")" in
  package.json)
    plugin_dir="plugins/${plugin_id}"
    ;;
  package.v2.json)
    plugin_dir="plugins.v2/${plugin_id}"
    ;;
  package.v3.json)
    plugin_dir="plugins.v3/${plugin_id}"
    ;;
  *)
    echo "Unsupported package file: ${package_file}" >&2
    exit 2
    ;;
esac

test -d "$plugin_dir"
printf '%s\n' "$plugin_dir"
