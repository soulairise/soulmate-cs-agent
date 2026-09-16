# -*- coding: utf-8 -*-
"""답변을 내보내기 전 마지막 점검.

모두몰 버전은 '숫자의 출처'만 봤다. 소울매트는 요가 브랜드라 숫자보다 위험한 것이 두 가지 더 있다.
  ① 건강·의료 판단  — "괜찮습니다"라고 답하는 순간 소울매트가 책임을 진다 (매뉴얼 7.2)
  ② 효능·치료 표현  — 표시광고법 (매뉴얼 3.2)
그래서 점검이 네 가지다. 숫자 하나 · 안전 둘 · 임시값 하나.
"""
import json
import re

from context import CONFIRMED_POLICY, FIXED_POLICY, PROVISIONAL_POLICY


def numbers_in(obj):
    """문자열/딕셔너리/리스트에서 정수들을 모두 뽑아낸다(콤마 제거 후)."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return {int(m) for m in re.findall(r"\d+", text)}


def allowed_numbers(tool_results):
    """조회 결과 + 매뉴얼 고정값 + 한 단계 산술 유도값을 허용 집합으로 만든다."""
    allowed = set()
    for v in FIXED_POLICY.values():
        if isinstance(v, int):
            allowed.add(v)
        elif isinstance(v, list):
            allowed.update(x for x in v if isinstance(x, int))
    tool_nums = set()
    for r in (tool_results or {}).values():
        tool_nums |= numbers_in(r)
    allowed |= tool_nums
    base = sorted(allowed)
    for a in base:
        for b in base:
            if a > b:
                allowed.add(a - b)
            allowed.add(a + b)
    return allowed, tool_nums


# ① 건강·의료 판단 — 고객 질문이 이 범주면 답변이 단정해선 안 된다
HEALTH_Q = re.compile(
    r"임신|임산부|수술|디스크|허리\s?아|무릎\s?아|통증|아픈데|아파서|부상|다쳤|"
    r"골절|염증|고혈압|당뇨|녹내장|약\s?먹|복용|재활|물리치료")
# 단정하는 말투
ASSERT_OK = re.compile(r"괜찮습니다|괜찮아요|가능합니다|하셔도\s?됩니다|문제\s?없|안전합니다|무리\s?없")
ASSERT_NO = re.compile(r"하시면\s?안\s?됩니다|위험합니다|피하셔야")
# 넘겼다는 표시
DEFERRED = re.compile(r"강사|상담원|전문의|병원|의사|상담.*연결|연결.*드리")

# ② 효능·치료 표현 — 표시광고법
EFFICACY = re.compile(
    r"교정(됩|돼|된다|해\s?드)|완치|치료(됩|해|에\s?효과)|낫습니다|나아집니다|"
    r"통증이\s?(사라|없어|줄어)|살이\s?빠|다이어트에\s?효과|디스크가\s?(좋아|나)")


def guardrail(answer, tool_results=None, question="", min_check=1000):
    """네 가지를 본다. 하나라도 걸리면 위반이다."""
    violations = []

    # ① 출처 불명 수치
    allowed, tool_nums = allowed_numbers(tool_results)
    found = numbers_in(answer)
    suspicious = sorted(n for n in found if n >= min_check and n not in allowed)
    if suspicious:
        violations.append({"type": "출처 불명 수치",
                           "detail": f"조회 결과·매뉴얼 고정값에 없는 숫자: {suspicious}"})

    # ② 건강·의료 판단 — 질문이 건강 범주인데 답변이 가부를 단정했다
    if HEALTH_Q.search(question or ""):
        if (ASSERT_OK.search(answer) or ASSERT_NO.search(answer)) and not DEFERRED.search(answer):
            violations.append({"type": "건강 판단 단정",
                               "detail": "건강·의료 문의에 가부를 단정했다 (매뉴얼 7.2)"})
        elif not DEFERRED.search(answer):
            violations.append({"type": "건강 문의 미이관",
                               "detail": "건강·의료 문의인데 강사·상담원 연결을 안내하지 않았다"})

    # ③ 효능·치료 표현
    m = EFFICACY.search(answer)
    if m:
        violations.append({"type": "효능 표현",
                           "detail": f'표시광고법 위반 소지: "{m.group()}"'})

    # ④ [임시] 값을 확답처럼 말했다
    def flatten(d):
        out = set()
        for v in d.values():
            out |= {v} if isinstance(v, int) else set(v)
        return out

    # 확정값과 겹치는 숫자는 뺀다. 3,500원은 기본 배송비(확정)이자 부분 반품비(임시)여서,
    # 빼지 않으면 배송비를 정상 안내한 답변까지 임시값 확답으로 잡힌다.
    prov = flatten(PROVISIONAL_POLICY) - flatten(CONFIRMED_POLICY)
    used_prov = sorted(n for n in found & prov if n >= min_check and n not in tool_nums)
    if used_prov and not re.search(r"확인\s?후|안내드리겠|변동될\s?수|정확한\s?기준", answer):
        violations.append({"type": "임시값 확답",
                           "detail": f"아직 확정되지 않은 값을 확답했다: {used_prov}"})

    return {"ok": not violations, "violations": violations,
            "numbers_in_answer": sorted(found), "from_tools": sorted(tool_nums)}
