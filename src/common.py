# -*- coding: utf-8 -*-
"""여러 모듈이 함께 쓰는 잡동사니."""
from concurrent.futures import ThreadPoolExecutor

from config import WORKERS


def pmap(fn, items, workers=WORKERS):
    """여러 건을 동시에 호출한다. 결과 순서는 입력 순서와 같다."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def show_graph(compiled):
    print(compiled.get_graph().draw_mermaid())
