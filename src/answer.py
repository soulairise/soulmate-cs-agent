# -*- coding: utf-8 -*-
"""답변 생성. 모델이 스스로 도구를 골라 부르는 그래프다.

agent 노드가 도구를 요청하면 tools 노드로 갔다가 다시 agent 로 돌아온다.
돌아오는 화살표가 곧 루프이고, 상한은 recursion_limit 으로 건다.
"""
import json
from typing import Annotated, TypedDict

from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from config import ANSWER_MODEL, MAX_TOOL_TURNS
from context import build_answer_prompt
from tools import TOOLS

LC_TOOLS = [tool(fn) for fn in TOOLS.values()]

# reasoning_effort="none" 인 이유: 이 등급의 모델은 추론 모드와 도구 호출을 함께 쓸 수 없어
# 그냥 두면 400 을 돌려준다. 도구 호출 자체가 이미 여러 단계로 나뉜 추론이므로 꺼도 된다.
llm_t = init_chat_model(ANSWER_MODEL, temperature=0, reasoning_effort="none",
                        timeout=60, max_retries=2).bind_tools(LC_TOOLS)


class ToolState(TypedDict, total=False):
    messages: Annotated[list, add_messages]


def agent(state: ToolState) -> ToolState:
    """노드 ① 모델 차례 — 도구를 부를지, 답할지 모델이 정한다."""
    return {"messages": [llm_t.invoke(state["messages"])]}


def build_tool_graph():
    g = StateGraph(ToolState)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(LC_TOOLS))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile()


tool_app = build_tool_graph()


def answer_with_tools(question, route, max_turns=MAX_TOOL_TURNS, history=None):
    """그래프를 한 바퀴 돌려 (답변, 호출된 도구 결과) 를 돌려준다.

    history 는 [{"role": "customer"|"agent", "text": ...}] 형태의 앞선 턴들이다.
    이걸 질문 문자열에 이어 붙이면 안 된다 — 모델이 지난 질문까지 이번에 물은 것으로 읽고
    답을 통째로 다시 말한다(실제로 그랬다). 역할이 붙은 별도 메시지로 넘겨야 한다.
    """
    prior = []
    for t in history or []:
        prior.append(("human" if t["role"] == "customer" else "ai", t["text"]))
    init = {"messages": [("system", build_answer_prompt(question, route))]
                        + prior + [("human", question)]}
    try:
        out = tool_app.invoke(init, {"recursion_limit": 2 * max_turns + 1})
    except GraphRecursionError:
        return "정확한 확인을 위해 상담원에게 연결해 드리겠습니다.", {}
        # 그 밖의 예외는 일부러 잡지 않는다 — 조용히 이관으로 바뀌면 원인을 영영 못 찾는다
    used = {}
    for m in out["messages"]:
        if getattr(m, "name", None) in TOOLS:
            try:
                used[m.name] = json.loads(m.content)
            except json.JSONDecodeError:
                used[m.name] = m.content
    return out["messages"][-1].content, used


def answer_with_llm(question, route, tool_results=None, model=None):
    """도구 없이, 우리가 넣어 준 조회 결과만으로 답을 만든다(대조용)."""
    llm = init_chat_model(model or ANSWER_MODEL, temperature=0, timeout=60, max_retries=2)
    return llm.invoke([("system", build_answer_prompt(question, route, tool_results)),
                       ("human", question)]).content
