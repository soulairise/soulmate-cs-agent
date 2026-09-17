#!/usr/bin/env bash
# 공개·공유 전 민감정보 전수 검사.  ./scan.sh
#
# 계좌·전화는 지웠는데 강사 실명을 놓친 적이 있다. 눈으로 훑지 말고 이걸 돌린다.
cd "$(dirname "$0")"
found=0
check() {  # check "이름" "정규식"
  local hits
  hits=$(git ls-files -z | xargs -0 grep -nE "$2" 2>/dev/null | grep -vE '^scan\.sh:')
  if [ -n "$hits" ]; then
    printf "\033[31m  ⚠ %s\033[0m\n" "$1"
    printf "%s\n" "$hits" | sed 's/^/      /'
    found=1
  else
    printf "  ✅ %s\n" "$1"
  fi
}

echo "민감정보 검사 — 추적 중인 $(git ls-files | wc -l | tr -d ' ')개 파일"
echo
check "계좌·전화번호"   '3333-36-[0-9]|010-[0-9]{4}-[0-9]{4}|0507-[0-9]{4}'
check "실명 (강사·담당자)" '황정심|박수경|박민서|황현숙'
check "실제 신청·채팅 주소" 'forms\.gle|open\.kakao\.com'
check "API 키·토큰"     'sk-[A-Za-z0-9_-]{20,}|gho_[A-Za-z0-9]|ghp_[A-Za-z0-9]|discord\.com/api/webhooks'
check "웹 접속코드 값"   'SM_WEB_CODE="soulmate-[a-z0-9]{4}'
check "로컬 경로"       '/Users/[a-z]'

echo
if [ "$found" -eq 0 ]; then
  echo "  깨끗합니다. 공개·공유해도 됩니다."
else
  echo "  위 항목을 지운 뒤 다시 돌리세요."
  exit 1
fi
