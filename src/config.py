# -*- coding: utf-8 -*-
"""소울매트 고객응대 에이전트 설정. 여기 값만 바꿔도 동작이 달라진다."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "data"

def _load_key(path=Path.home() / ".config" / "harness-lab" / "env"):
    """키가 환경에 없으면 프로젝트 **밖**의 파일에서 읽어 온다.

    키를 저장소에 두지 않기 위한 장치다. 읽기만 하고 쓰지 않으며, 파일이 없으면 조용히 넘어간다
    (그 경우 OPENAI_API_KEY 를 직접 export 해야 한다).
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_key()
_load_key(Path.home() / ".config" / "soulmate-cs-agent" / "env")   # 웹 접속코드

MODEL = os.environ.get("SM_MODEL", "gpt-5.6-luna")              # 라우팅용
ANSWER_MODEL = os.environ.get("SM_ANSWER_MODEL", "gpt-5.6-terra")  # 답변 생성용

CONF_THRESHOLD = 0.5
MAX_TOOL_TURNS = 3
GUARDRAIL_RETRY = 1
WORKERS = 12

# 모두몰(5개)과 다른 점: 수업·워크숍 축이 있어 CLASS_BOOKING 이 추가된다.
ROUTES = ["ORDER_PLACE", "PRODUCT_INFO", "SHIPPING", "RETURN_REFUND", "CLASS_BOOKING", "OTHER"]
LABELS = ["ORDER_PLACE", "PRODUCT_INFO", "SHIPPING", "RETURN_REFUND", "CLASS_BOOKING"]
