# -*- coding: utf-8 -*-
"""소울매트 고객응대 에이전트 설정. 여기 값만 바꿔도 동작이 달라진다."""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "data"

MODEL = os.environ.get("SM_MODEL", "gpt-5.6-luna")              # 라우팅용
ANSWER_MODEL = os.environ.get("SM_ANSWER_MODEL", "gpt-5.6-terra")  # 답변 생성용

CONF_THRESHOLD = 0.5
MAX_TOOL_TURNS = 3
GUARDRAIL_RETRY = 1
WORKERS = 12

# 모두몰(5개)과 다른 점: 수업·워크숍 축이 있어 CLASS_BOOKING 이 추가된다.
ROUTES = ["ORDER_PLACE", "PRODUCT_INFO", "SHIPPING", "RETURN_REFUND", "CLASS_BOOKING", "OTHER"]
LABELS = ["ORDER_PLACE", "PRODUCT_INFO", "SHIPPING", "RETURN_REFUND", "CLASS_BOOKING"]
