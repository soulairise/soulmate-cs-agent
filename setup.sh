#!/usr/bin/env bash
# 새 맥에서 처음 한 번 실행한다.  ./setup.sh
#
# 하는 일: 파이썬 확인 → 가상환경 → 패키지 설치 → 키 자리 만들기 → 점검.
# 키는 절대 저장소에 들어가지 않는다. 이 스크립트도 키를 파일에 써 넣지 않고,
# 어디에 무엇을 넣어야 하는지 알려주기만 한다.
set -u
cd "$(dirname "$0")"
ok=0; warn=0
say()  { printf "\n\033[1m%s\033[0m\n" "$1"; }
pass() { printf "  ✅ %s\n" "$1"; ok=$((ok+1)); }
fail() { printf "  ❌ %s\n" "$1"; warn=$((warn+1)); }
info() { printf "     %s\n" "$1"; }

say "1. 파이썬"
if command -v python3 >/dev/null; then
  pass "python3 $(python3 -V 2>&1 | awk '{print $2}')"
else
  fail "python3 없음 — https://www.python.org 에서 설치하거나 'brew install python'"
fi

say "2. 가상환경과 패키지"
if command -v uv >/dev/null; then
  uv venv -q 2>/dev/null && uv pip install -q -r requirements.txt 2>&1 | tail -2
  pass "uv 로 설치 완료"
else
  info "uv 가 없어 표준 venv 로 설치합니다 (조금 느립니다)"
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip \
    && .venv/bin/pip install -q -r requirements.txt && pass "설치 완료" \
    || fail "설치 실패 — 위 메시지를 확인하세요"
fi

say "3. OpenAI 키"
KEYDIR="$HOME/.config/harness-lab"; KEYFILE="$KEYDIR/env"
if [ -n "${OPENAI_API_KEY:-}" ]; then
  pass "환경변수에 이미 있음 (${#OPENAI_API_KEY}자)"
elif [ -f "$KEYFILE" ] && grep -q OPENAI_API_KEY "$KEYFILE"; then
  pass "$KEYFILE 에 있음"
else
  mkdir -p "$KEYDIR"; chmod 700 "$KEYDIR"
  fail "키가 없습니다 — 직접 넣어 주세요"
  info "  1) https://platform.openai.com/api-keys 에서 키 발급"
  info "  2) 아래 한 줄을 실행 (sk-... 자리에 본인 키)"
  info ""
  info "     echo 'export OPENAI_API_KEY=\"sk-...\"' > $KEYFILE && chmod 600 $KEYFILE"
  info ""
  info "  ※ 키는 대표님이 직접 넣으셔야 합니다. 저장소에 넣지 마세요."
fi

say "4. 웹 접속코드 (웹을 남에게 열어 줄 때만 필요)"
WEBFILE="$HOME/.config/soulmate-cs-agent/env"
if [ -f "$WEBFILE" ] && grep -q SM_WEB_CODE "$WEBFILE"; then
  pass "$WEBFILE 에 있음"
else
  mkdir -p "$(dirname "$WEBFILE")"; chmod 700 "$(dirname "$WEBFILE")"
  CODE="soulmate-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c6)"
  printf 'export SM_WEB_CODE="%s"\n' "$CODE" > "$WEBFILE"; chmod 600 "$WEBFILE"
  pass "새로 만들었습니다 → 접속코드: $CODE"
  info "코드가 없으면 주소만 아는 사람이 API 크레딧을 씁니다. 지우지 마세요."
fi

say "5. 데이터"
for f in policy_soulmate.md mockdata_soulmate.json inquiries_soulmate.csv \
         goldenset_soulmate.json safety_probes.json; do
  [ -f "data/$f" ] && pass "data/$f" || fail "data/$f 없음"
done

say "6. 코드가 실제로 뜨는지 (API 호출 없음)"
if .venv/bin/python -c "
import sys; sys.path.insert(0,'src')
import config, context, tools, guardrail
from guardrail import HEALTH_ASK
assert HEALTH_ASK.search('허리가 아픈데 해도 될까요?'), '안전 규칙이 동작하지 않습니다'
assert not HEALTH_ASK.search('매트 두께가 몇 mm인가요?'), '안전 규칙이 과잉 동작합니다'
assert len(tools.TOOLS) == 13, f'도구 수가 다릅니다: {len(tools.TOOLS)}'
print(f'     도구 {len(tools.TOOLS)}개 · 매뉴얼 {len(context.sections)-1}장 · 상품 {len(tools.PRODUCTS)} · 세션 {len(tools.SESSIONS)}')
" 2>&1; then
  pass "모듈 적재와 안전 규칙 정상"
else
  fail "코드 적재 실패 — 위 메시지를 확인하세요"
fi

say "결과"
printf "  통과 %d · 확인 필요 %d\n" "$ok" "$warn"
if [ "$warn" -eq 0 ]; then
  cat <<'NEXT'

  준비 끝났습니다. 이렇게 쓰시면 됩니다.

    ./run.sh                 터미널에서 대화
    ./run.sh web             브라우저에서 대화 → http://localhost:8848
    ./run.sh eval --repeat 3 네 가지 지표 측정

  ※ 첫 실행 때 OpenAI 크레딧이 있는지 확인하세요.
    https://platform.openai.com/settings/organization/billing/
NEXT
else
  printf "\n  위의 ❌ 항목을 먼저 해결한 뒤 다시 ./setup.sh 를 실행하세요.\n"
fi
