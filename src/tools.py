# -*- coding: utf-8 -*-
"""어드민 조회 도구. 매뉴얼의 [어드민 조회] 표시에서 도출한 것들이다.

고칠 때 주의할 점 두 가지.
- 선택 인자는 반드시 `Optional[...]` 로 적는다. 타입이 int 인데 기본값이 None 이면
  모델이 '모름'의 뜻으로 None 을 보냈을 때 스키마 검증에서 거부당한다.
- docstring 첫 줄이 모델이 읽는 도구 설명이다. 여기를 고치면 도구 선택이 달라진다.
"""
import json
import re
from typing import Optional

from config import BASE
from context import CONFIRMED_POLICY, PROVISIONAL_POLICY

MOCK = json.loads((BASE / "mockdata_soulmate.json").read_text(encoding="utf-8"))

PRODUCTS = {p["id"]: p for p in MOCK["products"]}
ORDERS = {o["order_id"]: o for o in MOCK["orders"]}
RETURNS = {r["return_id"]: r for r in MOCK["returns"]}
RETURNS_BY_ORDER = {r["order_id"]: r for r in MOCK["returns"]}
SESSIONS = {s["session_id"]: s for s in MOCK["sessions"]}
EVENT = MOCK["event_common"]


def _toks(s):
    return [t for t in re.split(r"[\s·()/+,]+", s) if t]


def _match_score(query, *fields):
    qt = _toks(query)
    if not qt:
        return 0.0
    flat = "".join(fields).replace(" ", "")
    nt = _toks(" ".join(fields))
    n = sum(1 for t in qt if t in flat or any(t in x or x in t for x in nt))
    return round(n / len(qt), 2)


# ── 상품 ────────────────────────────────────────────────────────
def search_product(query: str) -> dict:
    """상품명 일부로 상품을 찾는다. 상품 ID를 모를 때 가장 먼저 부르는 도구다.

    후보를 점수와 함께 돌려준다. 후보가 여럿이면 확정하지 말고 고객에게 되물어야 한다.
    """
    hits = []
    for pid, p in PRODUCTS.items():
        sc = _match_score(query, p["name"], p["category"])
        if sc:
            hits.append({"product_id": pid, "name": p["name"], "category": p["category"],
                         "price": p.get("sale_price") or p["price"], "score": sc})
    hits.sort(key=lambda h: -h["score"])
    top = [h for h in hits if h["score"] == hits[0]["score"]] if hits else []
    return {"query": query, "candidates": hits[:5],
            "resolved_product_id": top[0]["product_id"] if len(top) == 1 else None,
            "ambiguous": len(top) > 1,
            "note": ("후보가 여러 개입니다. 어느 상품인지 고객에게 확인하십시오."
                     if len(top) > 1 else None)}


def get_product_detail(product_id: str) -> dict:
    """상품 ID로 소재·두께·사이즈·무게·구성·세탁법·주의사항을 조회한다."""
    p = PRODUCTS.get(product_id)
    if not p:
        return {"error": "상품을 찾을 수 없습니다", "product_id": product_id}
    keys = ["id", "name", "category", "price", "sale_price", "material", "thickness",
            "size", "weight", "grip", "set_composition", "size_chart", "care",
            "caution", "single_purchase", "single_purchase_note", "sold_out"]
    return {k: p[k] for k in keys if k in p}


def get_product_options(product_id: str) -> dict:
    """상품 ID로 색상·사이즈 옵션별 재고와 구매 가능 여부를 조회한다."""
    p = PRODUCTS.get(product_id)
    if not p:
        return {"error": "상품을 찾을 수 없습니다", "product_id": product_id}
    opts = p.get("options", [])
    return {"product_id": product_id, "name": p["name"], "options": opts,
            "total_stock": sum(o.get("stock", 0) for o in opts),
            "sold_out": bool(p.get("sold_out")) or all(o.get("stock", 0) == 0 for o in opts),
            "single_purchase": p.get("single_purchase"),
            "single_purchase_note": p.get("single_purchase_note"),
            "same_day_delivery": p.get("same_day_delivery")}


def get_restock_info(product_id: str) -> dict:
    """품절 상품의 재입고 예정일을 조회한다. 예정이 없으면 null 이다."""
    p = PRODUCTS.get(product_id)
    if not p:
        return {"error": "상품을 찾을 수 없습니다", "product_id": product_id}
    return {"product_id": product_id, "name": p["name"],
            "restock_date": p.get("restock_date"),
            "note": p.get("caution") or ("재입고 예정이 등록되어 있지 않습니다."
                                         if not p.get("restock_date") else None)}


# ── 주문·배송 ───────────────────────────────────────────────────
def get_order_status(order_id: str) -> dict:
    """주문번호(SM-0000)로 주문의 현재 진행 단계와 배송 정보를 조회한다."""
    o = ORDERS.get(order_id)
    if not o:
        return {"error": "주문을 찾을 수 없습니다", "order_id": order_id}
    return {k: v for k, v in o.items() if not k.startswith("_")}


def get_shipping_policy(order_amount: Optional[int] = None,
                        region: Optional[str] = None) -> dict:
    """주문 금액과 배송 지역으로 배송비와 예상 소요일을 조회한다.

    무료배송 기준액과 지역별 소요일은 이 도구로만 확인한다.
    """
    out = {
        "base_shipping_fee": CONFIRMED_POLICY["base_shipping_fee"],
        "free_shipping_over": CONFIRMED_POLICY["free_shipping_over"],
        "combined_shipping": True,
        "cutoff_hour": PROVISIONAL_POLICY["cutoff_hour"],
        "_provisional": ["cutoff_hour", "delivery_days", "extra_fee"],
    }
    if order_amount is not None:
        free = order_amount >= CONFIRMED_POLICY["free_shipping_over"]
        out["order_amount"] = order_amount
        out["shipping_fee"] = 0 if free else CONFIRMED_POLICY["base_shipping_fee"]
        out["free_shipping_applied"] = free
    if region:
        metro = bool(re.search(r"서울|경기|인천|수도권", region))
        jeju = bool(re.search(r"제주|도서|산간|울릉", region))
        out["region"] = region
        out["delivery_days"] = (PROVISIONAL_POLICY["delivery_days_metro"] if metro
                                else PROVISIONAL_POLICY["delivery_days_other"])
        out["extra_fee"] = PROVISIONAL_POLICY["jeju_extra_fee"] if jeju else 0
    return out


# ── 교환·반품 ───────────────────────────────────────────────────
def get_return_policy(reason: Optional[str] = None) -> dict:
    """반품 사유별로 신청 기한과 배송비 부담 주체를 조회한다."""
    defect = bool(reason and re.search(r"하자|불량|파손|오배송|잘못", reason))
    return {
        "reason": reason,
        "type": "하자·오배송" if defect else "단순변심",
        "window_days": (None if defect else CONFIRMED_POLICY["withdrawal_days"]),
        "window_months": (CONFIRMED_POLICY["defect_months"] if defect else None),
        "fee_bearer": "소울매트" if defect else "고객",
        "return_fee_full": None if defect else PROVISIONAL_POLICY["return_fee_full"],
        "return_fee_partial": None if defect else PROVISIONAL_POLICY["return_fee_partial"],
        "not_returnable": ["고객 과실로 가치가 훼손된 경우",
                           "사용·세탁한 요가복·양말 (위생용품)",
                           "포장을 개봉해 상품 가치가 사라진 경우"],
        "_provisional": ["return_fee_full", "return_fee_partial"],
    }


def get_return_status(order_id: Optional[str] = None,
                      return_id: Optional[str] = None) -> dict:
    """주문번호 또는 반품번호로 교환·반품의 진행 상태와 검품 결과를 조회한다.

    검품 전이면 inspection_result 와 fee_bearer 가 null 이다. null 을 단정해 답하지 않는다.
    """
    r = RETURNS.get(return_id) if return_id else RETURNS_BY_ORDER.get(order_id)
    if not r:
        return {"error": "접수된 교환·반품 건을 찾을 수 없습니다",
                "order_id": order_id, "return_id": return_id}
    return dict(r)


# ── 수업·워크숍 (소울매트 고유 축) ──────────────────────────────
def search_session(query: str) -> dict:
    """수업·워크숍 이름이나 날짜 일부로 세션을 찾는다. 세션 ID를 모를 때 먼저 부른다.

    후보가 여럿이면 확정하지 말고 어느 세션인지 고객에게 되물어야 한다.
    """
    hits = []
    for sid, s in SESSIONS.items():
        sc = _match_score(query, s["title"], s["date"], s["weekday"], s["place"],
                          s["teacher"], s["time"], s["event"])
        if sc:
            hits.append({"session_id": sid, "title": s["title"], "date": s["date"],
                         "time": s["time"], "place": s["place"], "score": sc})
    hits.sort(key=lambda h: -h["score"])
    top = [h for h in hits if h["score"] == hits[0]["score"]] if hits else []
    return {"query": query, "candidates": hits[:5],
            "resolved_session_id": top[0]["session_id"] if len(top) == 1 else None,
            "ambiguous": len(top) > 1,
            "note": ("후보가 여러 개입니다. 어느 세션인지 고객에게 확인하십시오."
                     if len(top) > 1 else None)}


def get_session_detail(session_id: str) -> dict:
    """세션 ID로 일시·장소·강사·참가비·정원·잔여석·준비물·마감 여부를 조회한다."""
    s = SESSIONS.get(session_id)
    if not s:
        return {"error": "세션을 찾을 수 없습니다", "session_id": session_id}
    return dict(s)


def get_event_info() -> dict:
    """행사 전체에 공통인 값만 조회한다 — 신청 방법·폼 주소·신청 마감일·입금 계좌·오픈채팅·문의처.

    **세션별 값은 여기 없다.** 참가비·장소·일시·강사·정원·잔여석·준비물·우천 시 대체 장소를
    물으면 이 도구가 아니라 search_session → get_session_detail 을 불러야 한다.
    인자가 없어 부르기 쉽다는 이유로 이걸 먼저 부르고 멈추면 세션 정보를 놓친다.
    """
    out = dict(EVENT)
    # 계약을 반환값에도 적어 둔다. docstring 만으로는 모델이 여기서 멈추는 일이 실제로 있었다.
    out["_not_in_this_tool"] = ("참가비·장소·일시·강사·정원·잔여석·준비물·우천 시 대체 장소는 "
                               "이 도구에 없습니다. search_session 으로 세션을 특정한 뒤 "
                               "get_session_detail 을 부르십시오.")
    return out


def get_class_refund_policy(session_id: Optional[str] = None,
                           session_query: Optional[str] = None,
                           days_before: Optional[int] = None,
                           paid_amount: Optional[int] = None,
                           days_since_payment: Optional[int] = None) -> dict:
    """수업·워크숍 취소 시 환불 규정과 환불액을 조회한다 (매뉴얼 7.3 · 7.4).

    **고객이 세션 이름을 말했으면 session_query 에 그 말을 그대로 넣어라**("싱잉볼", "한강 요가").
    안에서 세션을 찾아 대기자 현황까지 함께 돌려준다 — 대기자가 있으면 시점과 무관하게
    전액 환불이므로, 이걸 빠뜨리면 실제와 다른 금액을 안내하게 된다.
    search_session 을 따로 부를 필요는 없다.

    days_before 는 행사일까지 남은 일수다. 모르면 비워 두고, 돌려받은 tiers 를 안내한 뒤
    언제 취소하시는지 되물으면 된다. 상품 반품(get_return_policy)과 혼동하지 말 것.
    """
    if not session_id and session_query:
        found = search_session(session_query)
        session_id = found.get("resolved_product_id") or found.get("resolved_session_id")
    C = CONFIRMED_POLICY
    out = {
        "tiers": [
            {"when": f"행사 {C['refund_full_before_days']}일 전까지", "refund_rate": 1.0},
            {"when": f"{C['refund_half_from_days']}~{C['refund_half_to_days']}일 전",
             "refund_rate": 0.5},
            {"when": f"{C['refund_none_within_days']}일 전 ~ 당일 (노쇼 포함)",
             "refund_rate": 0.0},
        ],
        "overrides": [
            "취소석을 대기자가 채우면 시점과 무관하게 전액 환불",
            "소울매트·소울라이즈 사정으로 세션이 취소되면 전액 환불",
            f"행사 {C['transfer_deadline_days']}일 전까지 오픈채팅방으로 알리면 명의 양도 가능"
            " (양도는 취소가 아니라 환불이 없다)",
        ],
        "not_a_cancellation": "우천 등으로 장소만 변경되는 경우는 취소 사유가 아니다",
        "withdrawal_days": C["withdrawal_days"],
        "withdrawal_note": ("입금일부터 7일 이내면 위 단계와 무관하게 전액 환불이다"
                            " (전자상거래법 제17조). 수업이 시작된 뒤에는 철회할 수 없다."),
    }

    if days_since_payment is not None and days_since_payment <= C["withdrawal_days"]:
        out["applies"] = "청약철회"
        out["refund_rate"] = 1.0
        out["reason"] = f"입금 후 {days_since_payment}일째라 청약철회 기간(7일) 안이다"
    elif days_before is not None:
        if days_before >= C["refund_full_before_days"]:
            rate, tier = 1.0, f"{C['refund_full_before_days']}일 전까지"
        elif days_before >= C["refund_half_from_days"]:
            rate, tier = 0.5, f"{C['refund_half_from_days']}~{C['refund_half_to_days']}일 전"
        else:
            rate, tier = 0.0, f"{C['refund_none_within_days']}일 전 ~ 당일"
        out.update({"applies": "환불 단계", "days_before": days_before,
                    "tier": tier, "refund_rate": rate})
        out["transfer_available"] = days_before >= C["transfer_deadline_days"]

    if paid_amount is not None and "refund_rate" in out:
        out["paid_amount"] = paid_amount
        out["refund_amount"] = int(paid_amount * out["refund_rate"])

    if not session_id and session_query:
        out["session_lookup"] = (f"'{session_query}' 로 세션을 특정하지 못했습니다. "
                                 "어느 세션인지 확인하면 대기자 현황까지 안내할 수 있습니다.")
    if session_id:
        sess = SESSIONS.get(session_id)
        if not sess:
            out["session_error"] = "세션을 찾을 수 없습니다"
        else:
            out["session_id"] = session_id
            out["session_title"] = sess["title"]
            out["waitlist"] = sess.get("waitlist", 0)
            if sess.get("waitlist", 0) > 0:
                out["waitlist_note"] = (
                    f"대기자가 {sess['waitlist']}명 있어 취소석이 바로 채워질 가능성이 높습니다. "
                    "충원되면 시점과 무관하게 전액 환불됩니다.")
    return out


# ── 이관 ────────────────────────────────────────────────────────
def escalate_to_agent(reason: str, context: Optional[dict] = None) -> dict:
    """사람 상담원에게 넘긴다. 건강·의료 판단, 확신도 미달, 비용 이견일 때 부른다."""
    return {"escalated": True, "reason": reason, "context": context or {},
            "message": "정확한 확인을 위해 상담원에게 연결해 드리겠습니다."}


TOOLS = {f.__name__: f for f in [
    search_product, get_product_detail, get_product_options, get_restock_info,
    get_order_status, get_shipping_policy,
    get_return_policy, get_return_status,
    search_session, get_session_detail, get_event_info, get_class_refund_policy,
    escalate_to_agent,
]}
