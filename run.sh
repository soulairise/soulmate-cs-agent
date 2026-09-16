#!/usr/bin/env bash
# 소울매트 고객응대 에이전트 실행기
#   ./run.sh          대화
#   ./run.sh eval     세 지표 측정 (--repeat 3 등 인자 그대로 전달)
#
# 키는 저장소에 두지 않는다. ~/.config/harness-lab/env 에서 읽어 온다.
set -e
cd "$(dirname "$0")"

ENVFILE="$HOME/.config/harness-lab/env"
if [ -z "$OPENAI_API_KEY" ]; then
  if [ -f "$ENVFILE" ]; then
    . "$ENVFILE"
  else
    echo "키를 찾을 수 없습니다. $ENVFILE 에 OPENAI_API_KEY 를 넣거나" >&2
    echo "export OPENAI_API_KEY=... 로 직접 넣어 주세요." >&2
    exit 1
  fi
fi

cmd="${1:-chat}"; shift || true
case "$cmd" in
  eval) exec .venv/bin/python src/evaluate.py "$@" ;;
  chat) exec .venv/bin/python src/chat.py ;;
  web)  exec .venv/bin/python -m uvicorn web:app --app-dir src --port 8848 "$@" ;;
  *)    echo "사용법: ./run.sh [chat|eval|web]" >&2; exit 1 ;;
esac
