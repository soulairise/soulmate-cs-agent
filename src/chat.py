# -*- coding: utf-8 -*-
"""터미널에서 직접 말을 걸어 본다.  `python chat.py`

숫자로 안 잡히는 어색함은 직접 대화해 봐야 보인다. 종료는 빈 줄 또는 Ctrl-D.
"""
import uuid

from agent import chat_app


def main():
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print("소울매트 고객응대 에이전트입니다. 무엇을 도와드릴까요? (종료: 빈 줄)")
    while True:
        try:
            q = input("\n고객 > ").strip()
        except EOFError:
            break
        if not q:
            break
        out = chat_app.invoke({"question": q}, cfg)
        print(f"\n상담 > {out['answer']}")
        v = [x["type"] for x in out.get("violations") or []]
        print(f"      [{out['route']} conf={out.get('confidence', 0):.2f} "
              f"→ {out['action']}] 조회={out.get('tools', [])}"
              + (f" ⚠{v}" if v else ""))
    print("\n감사합니다.")


if __name__ == "__main__":
    main()
