# -*- coding: utf-8 -*-
"""라우터 · 조회 · 생성 · 가드레일을 하나의 그래프로 잇는다.

route → answer → guard → (END | answer 재시도 | escalate)
"""
import operator
from typing import Annotated, List, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from answer import answer_with_tools
from guardrail import guardrail
from router import app as router_app
from tools import escalate_to_agent


class AgentState(TypedDict, total=False):
    question: str
    history: Annotated[list, operator.add]   # 리듀서가 붙어 턴마다 덮이지 않고 쌓인다
                                            # [{"role": "customer"|"agent", "text": ...}]
    route: str
    confidence: float
    action: str                 # HANDLE / ASK / ANSWER / ESCALATE / OUT_OF_SCOPE / RETRY
    tools: List[str]
    results: dict
    answer: str
    guardrail_ok: Optional[bool]
    violations: list
    attempts: int


def with_history(state: AgentState) -> str:
    """분류·가드레일용으로 고객 발화만 이어 붙인다.

    라우팅은 "그건 얼마예요?" 같은 이어지는 말을 앞 발화 없이는 못 가른다. 그래서 여기서는
    이어 붙이는 게 맞다. 다만 **답변 생성에는 쓰지 않는다** — 그쪽은 역할이 붙은 메시지로
    넘겨야 지난 질문까지 다시 답하는 일이 없다 (answer_with_tools 의 history 인자).
    """
    prior = [t["text"] for t in (state.get("history") or []) if t["role"] == "customer"]
    return " ".join(prior + [state["question"]])


def node_route(state):
    """① 분류 — 라우터 그래프를 그대로 부른다."""
    r = router_app.invoke({"question": with_history(state)})
    return {"route": r["route"], "confidence": r["confidence"], "action": r["action"]}


def node_answer(state: AgentState) -> AgentState:
    """② 조회 + ③ 생성 — 안에서 도구 호출 그래프가 한 바퀴 돈다."""
    text, results = answer_with_tools(state["question"], state["route"],
                                      history=state.get("history") or [])
    turn = [{"role": "customer", "text": state["question"]},
            {"role": "agent", "text": text}]
    if not results:                       # 조회할 식별자가 없어 모델이 되물은 경우
        return {"action": "ASK", "tools": [], "results": {}, "answer": text,
                "history": turn}
    return {"tools": list(results), "results": results, "answer": text,
            "history": turn,
            "attempts": state.get("attempts", 0) + 1}


def node_guard(state: AgentState) -> AgentState:
    """④ 가드레일 — 출처 없는 숫자·건강 단정·효능 표현·임시값 확답을 되돌려 보낸다."""
    g = guardrail(state["answer"], state["results"], with_history(state))
    return {"guardrail_ok": g["ok"], "violations": g["violations"],
            "action": "ANSWER" if g["ok"] else "RETRY"}


def node_escalate(state: AgentState) -> AgentState:
    reason = {"ESCALATE": "분류확신도미달", "OUT_OF_SCOPE": "응대범위밖"}.get(
        state["action"], "가드레일위반")
    msg = ("문의하신 내용은 소울매트에서 확인이 어려운 사항입니다. 담당 창구를 안내해 드릴 수 있도록 상담원에게 연결해 드리겠습니다."
           if state["action"] == "OUT_OF_SCOPE"
           else escalate_to_agent(reason, {"q": state["question"]})["message"])
    return {"answer": msg, "guardrail_ok": state.get("guardrail_ok")}


def after_route(state: AgentState) -> str:
    return "answer" if state["action"] == "HANDLE" else "escalate"


def after_answer(state: AgentState) -> str:
    # ASK 도 가드레일을 통과시킨다. 되묻는 문장에도 건강 단정이나 임시값이 섞일 수 있다.
    return "guard"


def after_guard(state: AgentState) -> str:
    """통과하면 끝. 위반이면 한 번 더 생성해 보고, 그래도 안 되면 이관한다."""
    if state["guardrail_ok"]:
        return END
    return "answer" if state.get("attempts", 0) < 2 else "escalate"


def build_agent(checkpointer=None):
    g = StateGraph(AgentState)
    g.add_node("route", node_route)
    g.add_node("answer", node_answer)
    g.add_node("guard", node_guard)
    g.add_node("escalate", node_escalate)
    g.add_edge(START, "route")
    g.add_conditional_edges("route", after_route, {"answer": "answer", "escalate": "escalate"})
    g.add_conditional_edges("answer", after_answer, {"guard": "guard"})
    g.add_conditional_edges("guard", after_guard,
                            {"answer": "answer", "escalate": "escalate", END: END})
    g.add_edge("escalate", END)
    return g.compile(checkpointer=checkpointer)


agent_app = build_agent()
chat_app = build_agent(checkpointer=InMemorySaver())     # 대화용(맥락 유지)


def customer_agent(question):
    """문의 한 줄을 파이프라인에 통과시킨다."""
    out = agent_app.invoke({"question": question})
    if out["action"] == "RETRY":
        out["action"] = "ESCALATE"
    return {"question": question, **out}
