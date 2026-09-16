# -*- coding: utf-8 -*-
"""브라우저에서 에이전트와 대화한다.  `./run.sh web`

터미널 chat.py 와 같은 그래프를 쓰되, 라우트·조회 도구·가드레일 판정을 화면에 같이 보여준다.
무엇을 보고 그렇게 답했는지 눈에 보여야 고칠 자리가 보인다.
"""
import sys as _sys, pathlib as _p
_sys.path.insert(0, str(_p.Path(__file__).resolve().parent))

import os
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import chat_app

WEB = _p.Path(__file__).resolve().parent.parent / "web"

# 공유 링크로 열어 둘 때 아무나 호출해 API 크레딧을 쓰지 못하게 막는다.
# 코드는 저장소가 아니라 ~/.config/soulmate-cs-agent/env 에 있다. 비어 있으면 검사하지 않는다.
ACCESS_CODE = os.environ.get("SM_WEB_CODE", "")
app = FastAPI(title="소울매트 고객응대 에이전트")


class Ask(BaseModel):
    question: str
    thread: str | None = None


@app.get("/api/need-code")
def need_code():
    return {"required": bool(ACCESS_CODE)}


@app.post("/api/chat")
def chat(a: Ask, x_access_code: str = Header(default="")):
    if ACCESS_CODE and x_access_code != ACCESS_CODE:
        raise HTTPException(status_code=401, detail="접속코드가 맞지 않습니다")
    thread = a.thread or str(uuid.uuid4())
    out = chat_app.invoke({"question": a.question},
                          {"configurable": {"thread_id": thread}})
    return {
        "thread": thread,
        "answer": out["answer"],
        "route": out.get("route"),
        "confidence": out.get("confidence"),
        "action": out.get("action"),
        "tools": out.get("tools") or [],
        "violations": [v["type"] for v in (out.get("violations") or [])],
    }


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
