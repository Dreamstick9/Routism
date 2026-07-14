#!/usr/bin/env bash
# Install the `routism` command on your PATH (no pip required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_SRC="$ROOT/bin/routism"
DEST_DIR="${HOME}/.local/bin"
DEST="$DEST_DIR/routism"

if [[ ! -f "$BIN_SRC" ]]; then
  echo "error: missing $BIN_SRC" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
# Wrapper that always points at this checkout
cat > "$DEST" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${ROOT}\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m routism_cli "\$@"
EOF
chmod +x "$DEST"
chmod +x "$BIN_SRC"

echo "Installed: $DEST"
echo
if ! echo ":$PATH:" | grep -q ":$DEST_DIR:"; then
  echo "Add to your PATH (zsh):"
  echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
  echo
fi
echo "Then run:"
echo "  routism          # interactive full setup"
echo "  routism doctor"
echo "  routism start | stop"
