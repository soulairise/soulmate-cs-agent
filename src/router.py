# -*- coding: utf-8 -*-
"""의도 분류 라우터. State 하나와 노드 둘로 된 그래프다.

classify 는 모델이 하는 일(분류), gate 는 정책이 정하는 일(처리/이관/범위밖)이다.
둘을 나눠 둔 덕에 임계값만 바꿀 때 모델을 다시 부르지 않아도 된다.
"""
import re
from typing import Literal, Optional, TypedDict

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from config import CONF_THRESHOLD, MODEL
from prompts import ROUTE_GUIDE


class RouterState(TypedDict, total=False):
    question: str
    route: str
    confidence: float
    reason: str
    action: str             # HANDLE / ESCALATE / OUT_OF_SCOPE
    message: Optional[str]


# 수업 어휘를 먼저 본다 — 매뉴얼 1.2의 우선순위를 규칙 버전에도 그대로 반영했다.
RULES = [
    (r"워크숍|수업|클래스|세션|강의|신청|정원|참가비|입금|선착순|위켄드|리트릿", "CLASS_BOOKING"),
    (r"환불|반품|교환|반송|수거|검품", "RETURN_REFUND"),
    (r"배송비|택배비|무료\s?배송|배송|택배|출고|도착|언제\s?(오|와)|어디쯤|송장", "SHIPPING"),
    (r"주문할|구매할게|살게요|사고\s?싶|결제|주문\s?가능|구매\s?가능|낱개|따로|단품", "ORDER_PLACE"),
    (r"구성|포함|소재|재질|두께|사이즈|치수|재고|색상|품질|세탁|몇\s?(장|개|mm)", "PRODUCT_INFO"),
    (r"매장|오프라인|지점|영업\s?시간|주차|채용|제휴|협찬|취재", "OTHER"),
]


def classify(state: RouterState) -> RouterState:
    """노드 ① 분류 — 키워드 규칙 버전(대조용)."""
    q = state["question"]
    for pattern, route in RULES:
        if re.search(pattern, q):
            return {"route": route, "confidence": 0.8, "reason": "키워드 규칙 매치"}
    return {"route": "OTHER", "confidence": 0.3, "reason": "매치되는 규칙 없음"}


def gate(state: RouterState) -> RouterState:
    """노드 ② 판정 — 확신도와 응대 범위를 보고 처리/이관/범위밖을 정한다."""
    if state["confidence"] < CONF_THRESHOLD:
        return {"action": "ESCALATE",
                "message": "정확한 확인을 위해 상담원에게 연결해 드리겠습니다."}
    if state["route"] == "OTHER":
        return {"action": "OUT_OF_SCOPE",
                "message": "문의하신 내용은 소울매트에서 확인이 어려운 사항입니다. 담당 창구를 안내해 드릴 수 있도록 상담원에게 연결해 드리겠습니다."}
    return {"action": "HANDLE", "message": None}


def build(node=None):
    """노드를 이름으로 찾아 그래프를 만든다. 같은 이름으로 다시 정의하면 그 노드만 갈린다."""
    g = StateGraph(RouterState)
    g.add_node("classify", node or globals()["classify"])
    g.add_node("gate", globals()["gate"])
    g.add_edge(START, "classify")
    g.add_edge("classify", "gate")
    g.add_edge("gate", END)
    return g.compile()


class RouteDecision(BaseModel):
    """고객 문의 한 건에 대한 라우팅 판단 결과."""

    route: Literal["ORDER_PLACE", "PRODUCT_INFO", "SHIPPING",
                   "RETURN_REFUND", "CLASS_BOOKING", "OTHER"] = Field(
        description="문의를 배정할 라우트. 6개 값 중 하나만 사용한다.")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="판단의 확신도. 두 라우트 사이에서 애매하면 0.5 미만으로 낮춘다.")
    reason: str = Field(
        description="그 라우트로 판단한 근거를 한 문장으로. 고객이 원하는 결과를 기준으로 쓴다.")


_router_chain = None


def llm_classify(state):
    """분류 노드 — LLM 버전. 이것이 기본값이다."""
    global _router_chain
    if _router_chain is None:
        _router_chain = init_chat_model(
            MODEL, temperature=0, timeout=60, max_retries=2
        ).with_structured_output(RouteDecision)
    d = _router_chain.invoke(
        [("system", ROUTE_GUIDE), ("human", f"고객 문의: {state['question']}")])
    return {"route": d.route, "confidence": d.confidence, "reason": d.reason}


rule_classify = classify
classify = llm_classify
app = build()


def route(question):
    return app.invoke({"question": question})
