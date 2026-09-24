#!/usr/bin/env bash
# Starts RoboCurate reachable from other machines on the same local network.
# There is no login, so only run this on a network you trust. Pass --local
# (or set ROBOCURATE_HOST=127.0.0.1) to restrict it to this machine.
set -euo pipefail
RDS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$RDS_DIR"

HOST="${ROBOCURATE_HOST:-0.0.0.0}"
PORT="${ROBOCURATE_PORT:-8421}"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lan) HOST=0.0.0.0 ;;
    --local) HOST=127.0.0.1 ;;
    --host)
      [ $# -ge 2 ] || { echo "--host 需要一个监听地址" >&2; exit 2; }
      HOST="$2"; shift ;;
    --host=*) HOST="${1#*=}" ;;
    --port)
      [ $# -ge 2 ] || { echo "--port 需要一个端口号" >&2; exit 2; }
      PORT="$2"; shift ;;
    --port=*) PORT="${1#*=}" ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi

case "$HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    LAN_IP="$(ip -4 -o route get 1.1.1.1 2>/dev/null |
      awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1);exit}}' || true)"
    echo "局域网地址 / from another computer: http://${LAN_IP:-<this-host-ip>}:${PORT}/"
    ;;
esac

exec .venv/bin/python studio.py --host "$HOST" --port "$PORT" "${ARGS[@]}"
