#!/usr/bin/env bash
#
# Install (or refresh) the Grow systemd unit files this repo owns.
#
# Why this exists:
#   The Grow systemd surface has historically drifted because units lived
#   in two places — repo and /etc/systemd/system — without a clear
#   source-of-truth contract. Twice it bit us as dangling symlinks
#   pointing into a non-existent public-skeleton dir (see
#   `ops/topology.md`, drift D3).
#
# Contract (per supervisor ruling 2026-05-17, GROW-7c):
#   - `ops/systemd/*.{service,timer}` is the canonical source.
#   - `/etc/systemd/system/<unit>` is a real-file copy (NOT a symlink).
#   - Before clobbering an installed unit, this script aborts if the
#     deployed copy differs from the repo copy AND --force is not set,
#     so accidental clobber of a hand-edited live unit can't happen.
#
# Usage:
#   sudo ./ops/install-units.sh                # plan only, no changes
#   sudo ./ops/install-units.sh --install      # cp + daemon-reload
#   sudo ./ops/install-units.sh --install --force   # overwrite even if /etc differs
#   sudo ./ops/install-units.sh --uninstall <unit>  # remove a single unit
#
# Scope:
#   - Refreshes installed units already present in /etc.
#   - Does NOT auto-enable or start units. Activation is a separate
#     deliberate step (`systemctl enable --now <unit>`), kept manual to
#     preserve the gate on live-write services (planner, executor).
#   - Does NOT install units that aren't currently in /etc. Adding a
#     brand-new service is also a separate deliberate step.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="$REPO_DIR/ops/systemd"
DEST_DIR="/etc/systemd/system"

ACTION="plan"
FORCE=0
UNINSTALL_UNIT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) ACTION="install"; shift ;;
    --force) FORCE=1; shift ;;
    --uninstall) ACTION="uninstall"; UNINSTALL_UNIT="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "warn: not running as root; --install will fail to write /etc/systemd/system" >&2
fi

# ── Uninstall path ──────────────────────────────────────────────────────────
if [[ "$ACTION" == "uninstall" ]]; then
  if [[ -z "$UNINSTALL_UNIT" ]]; then
    echo "--uninstall requires a unit name (e.g. glitch-meta-ads-sync.service)" >&2
    exit 2
  fi
  path="$DEST_DIR/$UNINSTALL_UNIT"
  if [[ ! -e "$path" && ! -L "$path" ]]; then
    echo "no-op: $UNINSTALL_UNIT not installed"
    exit 0
  fi
  # Refuse to stop+disable if the unit is active — operator should do it.
  if systemctl is-active --quiet "$UNINSTALL_UNIT"; then
    echo "abort: $UNINSTALL_UNIT is active; stop+disable it manually first" >&2
    exit 1
  fi
  rm -v -- "$path"
  systemctl daemon-reload
  echo "uninstalled $UNINSTALL_UNIT"
  exit 0
fi

# ── Plan / install path ─────────────────────────────────────────────────────
echo "Repo source: $SRC_DIR"
echo "Action: $ACTION  (--force=$FORCE)"
echo

drift=0
to_copy=()
for src in "$SRC_DIR"/*.service "$SRC_DIR"/*.timer; do
  [[ -e "$src" ]] || continue
  unit="$(basename "$src")"
  dest="$DEST_DIR/$unit"

  if [[ -L "$dest" ]]; then
    target="$(readlink "$dest")"
    if [[ -e "$target" ]]; then
      printf "  %-44s SYMLINK -> %s -- convert to real-file copy\n" "$unit" "$target"
    else
      printf "  %-44s DANGLING SYMLINK -> %s -- fix by installing\n" "$unit" "$target"
    fi
    # Symlinks (broken or otherwise) are always safe to replace —
    # they aren't "hand-edited live unit files" we'd be clobbering, so
    # don't count them toward the drift gate.
    to_copy+=("$unit")
    continue
  fi

  if [[ ! -e "$dest" ]]; then
    printf "  %-44s ABSENT in /etc -- repo-only (skip; add via deliberate install)\n" "$unit"
    continue
  fi

  if diff -q "$src" "$dest" >/dev/null 2>&1; then
    printf "  %-44s same\n" "$unit"
  else
    printf "  %-44s DIFFERS\n" "$unit"
    if [[ "$FORCE" -eq 1 ]]; then
      to_copy+=("$unit")
    else
      drift=$((drift+1))
    fi
  fi
done

echo
if [[ "$ACTION" == "plan" ]]; then
  echo "(plan only -- no files changed; pass --install to apply)"
  exit 0
fi

if [[ "$drift" -gt 0 && "$FORCE" -ne 1 ]]; then
  echo "abort: $drift unit(s) differ; rerun with --force to overwrite live copies" >&2
  exit 1
fi

if [[ "${#to_copy[@]}" -eq 0 ]]; then
  echo "nothing to install."
  exit 0
fi

for unit in "${to_copy[@]}"; do
  dest="$DEST_DIR/$unit"
  # `cp` refuses to follow a dangling symlink. Unlink first so a stale
  # symlink (broken or otherwise) gets replaced with a real file rather
  # than skipped with "not writing through dangling symlink".
  if [[ -L "$dest" ]]; then
    rm -- "$dest"
  fi
  cp -v "$SRC_DIR/$unit" "$dest"
done
systemctl daemon-reload
echo
echo "Installed ${#to_copy[@]} unit(s). Active services are unaffected until you restart them."
echo "Next: 'systemctl status <unit>' / 'systemctl restart <unit>' as appropriate."
