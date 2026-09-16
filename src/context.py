# -*- coding: utf-8 -*-
"""매뉴얼을 장 단위로 쪼개고, 라우트에 필요한 장만 골라 컨텍스트를 만든다.

전문을 넣지 않는 이유는 두 가지다. 입력이 길어 비용과 지연이 늘고, 관련 없는 정책이
오답을 유도한다(수업 취소 규정이 반품 문의에 섞여 들어가는 식).
"""
import json
import re

from config import BASE

POLICY = BASE / "policy_soulmate.md"


def split_sections(text):
    """'## ' 헤딩 단위로 매뉴얼을 쪼갠다. 키는 장 번호(문자열), 부록은 제외."""
    parts = re.split(r"^## ", text, flags=re.M)
    out = {"_header": parts[0].strip()}
    for p in parts[1:]:
        title = p.split("\n", 1)[0].strip()
        if title.startswith("부록"):
            continue
        m = re.match(r"(\d+)\.", title)
        key = m.group(1) if m else title
        out[key] = "## " + p.rstrip()
    return out


SECTION_MAP = {
    "ORDER_PLACE":   ["2"],          # 2장 주문·구매
    "PRODUCT_INFO":  ["3"],          # 3장 상품
    "SHIPPING":      ["4"],          # 4장 배송
    "RETURN_REFUND": ["5", "6"],     # 5장 접수 + 6장 비용과 처리
    "CLASS_BOOKING": ["7"],          # 7장 수업·워크숍
    "OTHER":         [],
}

# 어느 라우트든 항상 붙이는 장. 7장을 넣지 않는 대신 7.2(안전 경계)는 ANSWER_RULES 7번에
# 문장으로 박아 두었다 — 건강 문의가 엉뚱한 라우트로 새도 막혀야 하기 때문이다.
ALWAYS = ["이 매뉴얼을 쓰는 방법", "0", "1", "8", "9"]


sections = split_sections(POLICY.read_text(encoding="utf-8"))


def build_context(route, secs=None):
    """라우트에 필요한 매뉴얼 조각만 이어 붙여 프롬프트용 컨텍스트를 만든다."""
    secs = sections if secs is None else secs
    keys = [k for k in ALWAYS + SECTION_MAP.get(route, []) if k in secs]
    return "\n\n".join([secs["_header"]] + [secs[k] for k in keys])


# ── 매뉴얼에 값이 그대로 적힌 고정값 ──────────────────────────────
# CONFIRMED : 대표님이 확정한 값. 가드레일이 출처로 인정한다.
# PROVISIONAL: [임시] 값. 가드레일은 출처로 인정하되, 답변이 이 숫자를 확답처럼 쓰면
#              별도 규칙(guardrail.py 의 provisional 점검)이 경고한다.
CONFIRMED_POLICY = {
    "base_shipping_fee": 3500,          # 4장 [확정]
    "free_shipping_over": 50000,        # 4장 [확정]
    "withdrawal_days": 7,               # 5장 [확정] 전자상거래법 제17조
    "defect_months": 3,                 # 5장 [확정]
    "session_fee": 20000,               # 7장 [확정] 가을 요가 위켄드 기본 참가비
    "session_fee_potluck": 10000,       # 7장 [확정] 포트락 준비 시
}

PROVISIONAL_POLICY = {
    "cutoff_hour": 14,                  # 4장 [임시]
    "delivery_days_metro": [1, 2],      # 4장 [임시]
    "delivery_days_other": [2, 3],      # 4장 [임시]
    "jeju_extra_fee": 3000,             # 4장 [임시]
    "return_fee_full": 6000,            # 6장 [임시]
    "return_fee_partial": 3500,         # 6장 [임시]
    "return_total_days": [3, 7],        # 6장 [임시]
    "inspect_days": [2, 3],             # 6장 [임시]
    "pickup_days": [1, 2],              # 6장 [임시]
    "refund_days": 3,                   # 6장 [임시]
}

FIXED_POLICY = {**CONFIRMED_POLICY, **PROVISIONAL_POLICY}


def build_answer_prompt(question, route, tool_results=None):
    """답변 생성용 시스템 프롬프트를 조립한다."""
    from prompts import ANSWER_RULES
    ctx = build_context(route)
    tr = json.dumps(tool_results or {}, ensure_ascii=False, indent=1)
    return (f"{ANSWER_RULES}\n"
            f"===== 업무 매뉴얼 (라우트: {route}) =====\n{ctx}\n\n"
            f"===== 조회 결과 =====\n{tr}\n")
