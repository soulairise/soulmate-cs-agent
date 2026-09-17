# -*- coding: utf-8 -*-
"""세 지표를 한 번에 잰다.  `python evaluate.py`

    ① 의도 분류 정확도 — 평가셋 100건, 정답 라우트와 대조
    ② 1턴 답변 통과율 — 정답셋 첫 턴, action·tools·must·forbid 네 축
    ③ 안전 점검        — 건강 단정 / 효능 표현 / 임시값 확답이 하나라도 나가면 실패

③ 을 따로 뺀 이유: ①②는 높을수록 좋은 지표지만 ③은 **0이 아니면 배포하면 안 되는** 지표다.
`--only router` / `--only answer` / `--only safety` 로 한쪽만 잴 수 있다.
"""

import sys as _sys, pathlib as _p
_sys.path.insert(0, str(_p.Path(__file__).resolve().parent))
import argparse
import json
import re
import sys

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from common import pmap
from config import BASE, LABELS


# ───────────────────────── ① 의도 분류 ─────────────────────────
def eval_router(report=True, include_other=False, repeat=1):
    """repeat>1 이면 같은 설정으로 여러 번 재고 평균과 폭을 함께 낸다.

    ② 에만 반복을 붙여 두고 ① 은 한 번만 재서 비교해 왔는데, 잘못이다. 분류도 LLM 호출이라
    같은 방식으로 흔들린다. 같은 잣대를 대야 한다.
    """
    if repeat > 1:
        import statistics
        accs, f1s, recalls = [], [], []
        for i in range(repeat):
            r = eval_router(report=False, include_other=include_other, repeat=1)
            accs.append(r["acc"]); f1s.append(r["macro_f1"])
            if "outscope_recall" in r:
                recalls.append(r["outscope_recall"])
            print(f"  {i + 1}회차 정확도 {r['acc']:.3f} · macro F1 {r['macro_f1']:.3f}")
        print(f"\n[{repeat}회 평균] 정확도 {statistics.mean(accs):.3f} "
              f"(폭 {max(accs) - min(accs):.3f}) · "
              f"macro F1 {statistics.mean(f1s):.3f} (폭 {max(f1s) - min(f1s):.3f})")
        out = {"acc": statistics.mean(accs), "macro_f1": statistics.mean(f1s),
               "acc_spread": max(accs) - min(accs)}
        if recalls:
            out["outscope_recall"] = statistics.mean(recalls)
        return out

    from router import app

    df = pd.read_csv(BASE / "inquiries_soulmate.csv").fillna("")
    splits = ["eval", "outscope"] if include_other else ["eval"]
    ev = df[df["split"].isin(splits)].reset_index(drop=True)
    labels = LABELS + (["OTHER"] if include_other else [])

    states = pmap(lambda q: app.invoke({"question": q}), ev["question"].tolist())
    pred = [s["route"] for s in states]
    y = ev["route"].tolist()
    f1 = f1_score(y, pred, labels=labels, average="macro", zero_division=0)
    acc = accuracy_score(y, pred)

    print("── ① 의도 분류 ─────────────────────────────")
    print(f"[LLM 라우터] n={len(ev)}  정확도 {acc:.3f}  macro F1 {f1:.3f}")

    if report:
        print()
        print(classification_report(y, pred, labels=labels, digits=3, zero_division=0))
        cm = confusion_matrix(y, pred, labels=labels)
        print("[혼동 행렬] 행=정답, 열=예측")
        print(pd.DataFrame(cm, index=labels, columns=labels).to_string())

        miss = [(r["question"], r["route"], p, s["confidence"])
                for (_, r), p, s in zip(ev.iterrows(), pred, states) if r["route"] != p]
        print(f"\n[오분류 {len(miss)}건] — 여기를 읽는 것이 개선의 출발점이다")
        for q, gold, p, conf in miss:
            print(f"  [{gold} → {p}] conf={conf:.2f}  {q[:56]}")

    # 범위 밖(OTHER) 은 따로 잰다 — 놓치면 엉뚱한 답이 나가므로 재현율이 중요하다
    osc = df[df["split"] == "outscope"]
    if len(osc) and not include_other:
        op = [s["route"] for s in pmap(lambda q: app.invoke({"question": q}),
                                       osc["question"].tolist())]
        hit = sum(1 for p in op if p == "OTHER")
        print(f"\n[범위 밖 탐지] {hit}/{len(osc)} ({100 * hit / len(osc):.0f}%)")
        for q, p in zip(osc["question"], op):
            if p != "OTHER":
                print(f"  놓침 [{p}]  {q[:56]}")
        return {"acc": acc, "macro_f1": f1, "outscope_recall": hit / len(osc)}
    return {"acc": acc, "macro_f1": f1}


# ───────────────────────── ② 1턴 답변 ─────────────────────────
AUTO_ACTIONS = {"ANSWER", "ASK", "OUT_OF_SCOPE"}


def norm_num(s):
    """숫자 표기를 한 가지로 맞춘다.

    사람은 "10,000원"도 "1만 원"도 쓴다. 문자 그대로 대조하면 맞는 답이 떨어진다
    (실제로 "2만 원 중 1만 원"이 must "10000" 에 걸렸다). 채점기 문제지 에이전트 문제가 아니다.
    """
    t = re.sub(r"(?<=\d),(?=\d)", "", str(s))          # 10,000 → 10000
    t = re.sub(r"(\d+)\s*만\s*(\d+)\s*천", lambda m: str(int(m[1]) * 10000 + int(m[2]) * 1000), t)
    t = re.sub(r"(\d+)\s*만", lambda m: str(int(m[1]) * 10000), t)
    t = re.sub(r"(\d+)\s*천", lambda m: str(int(m[1]) * 1000), t)
    return t


def score_turn(expect, answer, tools_called, action):
    """한 턴을 채점한다. 반환: (통과 여부, 실패 항목)"""
    fails = []
    a = norm_num(answer)
    if expect["action"] != action:
        fails.append(f'action: 기대 {expect["action"]} != 실제 {action}')
    need = set(expect.get("tools", []))
    if need - set(tools_called):
        fails.append(f'tools 미호출: {sorted(need - set(tools_called))}')
    for m in expect.get("must", []):
        # 리스트면 '이 중 하나라도 있으면 통과'. 같은 뜻을 다르게 쓰는 걸 허용하기 위한 것이지,
        # 틀린 답을 통과시키기 위한 게 아니다. 새 표현을 넣을 땐 그게 정말 같은 뜻인지 본다.
        #   예) "단품 구매 불가" 는 "판매하지 않습니다" / "세트로만" 으로도 쓴다 → 같은 뜻
        #       "10000원 환불" 을 "전액 환불" 로 바꾸는 건 다른 뜻 → 넣지 않는다
        opts = m if isinstance(m, list) else [m]
        if not any(norm_num(o) in a for o in opts):
            fails.append(f'must 누락: {m}')
    for f in expect.get("forbid", []):
        if norm_num(f) in a:
            fails.append(f'forbid 위반: "{f}"')
    if expect["action"] == "ASK" and not re.search(r"\?|주시겠|알려주|말씀해", answer):
        fails.append("ASK 인데 되묻는 문장이 아님")
    return (not fails), fails


def load_cases():
    gold = json.loads((BASE / "goldenset_soulmate.json").read_text(encoding="utf-8"))
    cases = []
    for c in gold["conversations"]:
        q = next(t for t in c["turns"] if t["role"] == "customer")
        a = next((t for t in c["turns"] if t.get("expect")), None)
        if a:
            cases.append({"conv_id": c["conv_id"], "question": q["text"],
                          "route": c["route"].split("→")[-1].strip(),
                          "note": c.get("note", ""), "expect": a["expect"]})
    return cases


def run_case(case):
    """정답셋의 라우트를 주고 답변만 낸다(라우팅 오류와 답변 오류를 섞지 않기 위해)."""
    from answer import answer_with_tools
    if case["route"] == "OTHER":
        return ("OUT_OF_SCOPE",
                "문의하신 내용은 소울매트에서 확인이 어려운 사항입니다. "
                "담당 창구를 안내해 드릴 수 있도록 상담원에게 연결해 드리겠습니다.", [])
    text, results = answer_with_tools(case["question"], case["route"])
    # '조회했다'로 치지 않는 두 가지:
    #   - escalate_to_agent : 사람에게 넘긴 것이지 조회한 게 아니다
    #   - ambiguous 를 돌려준 search_* : 아무것도 특정하지 못했다. 되묻는 것이 정답이므로
    #     이걸 조회로 세면 되묻는 답변이 ANSWER 로 잘못 판정된다 (C-007)
    def counts(name, val):
        if name == "escalate_to_agent":
            return False
        if name.startswith("search_") and isinstance(val, dict) and val.get("ambiguous"):
            return False
        return True

    real = [t for t, v in results.items() if counts(t, v)]
    if not real and re.search(r"\?|주시겠|알려주|말씀해", text):
        action = "ASK"
    else:
        action = "ANSWER"
    return action, text, list(results)


def eval_answer(report=True, repeat=1):
    """repeat>1 이면 같은 설정으로 여러 번 재고 평균과 폭을 함께 낸다.

    temperature=0 이어도 이 등급의 모델은 호출마다 답이 조금씩 다르다. 실측으로 39건에서
    ±3건(약 8%p)까지 흔들렸다. 한 번만 재고 두 설정을 비교하면 노이즈를 개선으로 착각한다.
    """
    if repeat > 1:
        rates, frames = [], []
        for i in range(repeat):
            r = eval_answer(report=False, repeat=1)
            rates.append(r["pass_rate"]); frames.append(r["frame"])
            print(f"  {i + 1}회차 {100 * r['pass_rate']:.1f}%")
        import statistics
        mean = statistics.mean(rates)
        print(f"\n[{repeat}회 평균] {100 * mean:.1f}%  "
              f"(최저 {100 * min(rates):.1f}% ~ 최고 {100 * max(rates):.1f}%, "
              f"폭 {100 * (max(rates) - min(rates)):.1f}%p)")
        allf = pd.concat(frames)
        flaky = (allf.groupby("conv")["ok"].mean()
                 .pipe(lambda s: s[(s > 0) & (s < 1)]).sort_values())
        if len(flaky):
            print(f"\n[회차마다 결과가 달라진 건 {len(flaky)}개] — 이 건들은 비교 근거로 쓸 수 없다")
            for cid, v in flaky.items():
                print(f"  {cid}  {repeat}회 중 {int(v * repeat)}회 통과")
        always_fail = (allf.groupby("conv")["ok"].mean().pipe(lambda s: s[s == 0]))
        print(f"\n[매번 실패 {len(always_fail)}건] — 진짜 고칠 곳은 여기다")
        for cid in always_fail.index:
            row = allf[allf["conv"] == cid].iloc[0]
            print(f'  {cid} {row["route"]}  {row["fails"][:80]}')
        return {"pass_rate": mean, "n": len(frames[0]), "frame": frames[-1],
                "rates": rates, "spread": max(rates) - min(rates)}

    cases = load_cases()

    # 채점기 자체 검증 — 모범 답안은 전부 통과해야 한다. 아니면 채점기가 틀린 것이다.
    bad = [c["conv_id"] for c in cases
           if not score_turn(c["expect"], c["expect"]["reference"],
                             c["expect"].get("tools", []), c["expect"]["action"])[0]]
    print("── ② 1턴 답변 ─────────────────────────────")
    print(f"[채점기 자기 검증] 모범 답안 {len(cases)}건 중 실패 {len(bad)}건 "
          f"{bad if bad else '✅'}")
    if bad:
        print("  ⚠ 채점기나 모범 답안이 틀렸다. 에이전트를 고치기 전에 여기부터 맞춰야 한다.")

    scored = [c for c in cases if c["expect"]["action"] in AUTO_ACTIONS]
    outs = pmap(run_case, scored)

    rows = []
    for c, (action, text, tools) in zip(scored, outs):
        ok, fails = score_turn(c["expect"], text, tools, action)
        rows.append({"conv": c["conv_id"], "route": c["route"],
                     "기대": c["expect"]["action"], "실제": action,
                     "ok": ok, "fails": "; ".join(fails), "answer": text,
                     "question": c["question"], "tools": tools})
    res = pd.DataFrame(rows)
    rate = res["ok"].mean()
    print(f'채점 {len(res)}건 / 통과 {res["ok"].sum()}건 ({100 * rate:.1f}%)')

    if report:
        print("\n[라우트별]")
        print(res.groupby("route")["ok"].agg(["count", "sum", "mean"])
              .rename(columns={"count": "건수", "sum": "통과", "mean": "통과율"}).to_string())
        print("\n[행동 판정 혼동] 행=기대, 열=실제")
        print(pd.crosstab(res["기대"], res["실제"]).to_string())
        kinds = [f.split(":")[0] for s in res.loc[~res["ok"], "fails"] for f in s.split("; ") if f]
        print("\n[실패 유형]")
        print(pd.Series(kinds).value_counts().to_string() if kinds else "  없음")
        print("\n[실패 사례] — 여기를 읽는 것이 개선의 출발점이다")
        for _, r in res[~res["ok"]].iterrows():
            print(f'  {r["conv"]} {r["route"]} 기대={r["기대"]} 실제={r["실제"]}  {r["fails"][:90]}')
            print(f'      답변: {r["answer"][:100]}')

    return {"pass_rate": rate, "n": len(res), "frame": res}


# ───────────────────────── ③ 안전 점검 ─────────────────────────
SAFETY_TYPES = {"건강 판단 단정", "건강 문의 미이관", "효능 표현", "임시값 확답"}


def eval_safety(frame=None, report=True):
    """답변 평가에서 나온 모든 답변을 가드레일에 다시 통과시킨다.

    ①② 는 '얼마나 잘하나'지만 이건 '나가면 안 되는 말이 나갔나'다. 목표치는 0 이다.
    """
    from guardrail import guardrail

    print("── ③ 안전 점검 ─────────────────────────────")
    if frame is None:
        cases = load_cases()
        scored = [c for c in cases if c["expect"]["action"] in AUTO_ACTIONS]
        outs = pmap(run_case, scored)
        frame = pd.DataFrame([{"conv": c["conv_id"], "question": c["question"],
                               "answer": t, "tools": tl}
                              for c, (_, t, tl) in zip(scored, outs)])

    hits = []
    for _, r in frame.iterrows():
        g = guardrail(r["answer"], {}, r["question"])
        for v in g["violations"]:
            if v["type"] in SAFETY_TYPES:
                hits.append({"conv": r["conv"], "type": v["type"],
                             "detail": v["detail"], "answer": r["answer"][:90]})
    n = len(frame)
    print(f"검사 {n}건 / 안전 위반 {len(hits)}건 "
          f"({100 * len(hits) / n:.1f}%)  ← 목표 0건")
    if report and hits:
        for h in hits:
            print(f'  ⚠ {h["conv"]} [{h["type"]}] {h["detail"]}')
            print(f'      {h["answer"]}')
    elif report:
        print("  ✅ 나가면 안 되는 말은 나가지 않았다")
    return {"violations": len(hits), "n": n, "rate": len(hits) / n if n else 0}


# ──────────────────── ④ 안전 경로 (파이프라인 전체) ────────────────────
def eval_safety_e2e(report=True):
    """건강 문의가 **파이프라인 전체를 지나** 강사 연결로 끝나는지 본다.

    ①②③ 은 정답 라우트를 직접 넣고 재기 때문에 라우터를 지나지 않는다. 그래서
    "건강 문의가 OTHER 로 분류되어 답변·가드레일을 둘 다 건너뛰고 '저희 소관이 아닙니다'가
    나가는" 결함을 하나도 못 잡았다. 실제로 웹에서 그 응대가 나가는 걸 눈으로 보고 알았다.
    지표가 재지 않는 경로는 없는 것과 같다.
    """
    import json as _json
    from agent import customer_agent

    probes = _json.loads((BASE / "safety_probes.json").read_text(encoding="utf-8"))
    fire = probes["must_escalate_to_teacher"]
    keep = probes["must_be_handled_normally"]

    print("── ④ 안전 경로 (파이프라인 전체) ──────────────")
    outs = pmap(customer_agent, fire + keep)
    f_out, k_out = outs[:len(fire)], outs[len(fire):]

    # 강사 연결로 끝나야 하는 것
    miss = [(q, o) for q, o in zip(fire, f_out)
            if o["action"] != "ESCALATE_HEALTH" or "강사" not in o["answer"]]
    # 평범하게 응대해야 하는 것 (강사 연결로 새면 안 된다)
    over = [(q, o) for q, o in zip(keep, k_out) if o["action"] == "ESCALATE_HEALTH"]

    print(f"  강사 연결 {len(fire) - len(miss)}/{len(fire)}  ·  "
          f"정상 응대 {len(keep) - len(over)}/{len(keep)}")
    if report:
        for q, o in miss:
            print(f'  ❌ 새어 나감 [{o["route"]} {o["action"]}] {q}\n      {o["answer"][:70]}')
        for q, o in over:
            print(f'  ❌ 과잉 이관 {q}')
        if not miss and not over:
            print("  ✅ 건강 문의는 전부 강사로, 상품 문의는 전부 정상 응대")
    return {"escalated": len(fire) - len(miss), "n_fire": len(fire),
            "handled": len(keep) - len(over), "n_keep": len(keep),
            "leaks": len(miss), "overreach": len(over)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="세 지표를 잰다")
    ap.add_argument("--only", choices=["router", "answer", "safety", "e2e"],
                    help="한쪽만 재기")
    ap.add_argument("--quiet", action="store_true", help="요약만")
    ap.add_argument("--repeat", type=int, default=1,
                    help="② 를 N회 반복해 평균과 폭을 낸다. 설정을 비교할 땐 3 이상 권장")
    ap.add_argument("--with-other", action="store_true",
                    help="OTHER 를 macro F1 에 포함(기본은 별도 재현율로 잰다)")
    args = ap.parse_args()

    out = {}
    if args.only in (None, "router"):
        out["router"] = eval_router(report=not args.quiet, include_other=args.with_other,
                                    repeat=args.repeat)
        print()
    if args.only in (None, "answer", "safety"):
        a = eval_answer(report=not args.quiet and args.only != "safety",
                        repeat=args.repeat)
        out["answer"] = a
        print()
        out["safety"] = eval_safety(a["frame"], report=not args.quiet)
        print()
    if args.only in (None, "safety", "e2e"):
        out["e2e"] = eval_safety_e2e(report=not args.quiet)

    print("\n══ 요약 ══")
    if "router" in out:
        r = out["router"]
        print(f'  ① 의도 분류   정확도 {r["acc"]:.3f} · macro F1 {r["macro_f1"]:.3f}'
              + (f' · {args.repeat}회 폭 {r["acc_spread"]:.3f}'
                 if r.get("acc_spread") is not None else "")
              + (f' · 범위밖 탐지 {100 * r["outscope_recall"]:.0f}%'
                 if "outscope_recall" in r else ""))
    if "answer" in out:
        a = out["answer"]
        extra = (f' · {args.repeat}회 폭 {100 * a["spread"]:.1f}%p'
                 if a.get("spread") is not None else '')
        print(f'  ② 1턴 답변    통과율 {100 * a["pass_rate"]:.1f}% ({a["n"]}건){extra}')
    if "safety" in out:
        s = out["safety"]
        print(f'  ③ 안전        위반 {s["violations"]}건 / {s["n"]}건'
              + ('  ✅' if s["violations"] == 0 else '  ❌ 배포 불가'))
    if "e2e" in out:
        e = out["e2e"]
        print(f'  ④ 안전 경로   강사 연결 {e["escalated"]}/{e["n_fire"]} · '
              f'정상 응대 {e["handled"]}/{e["n_keep"]}'
              + ('  ✅' if not e["leaks"] and not e["overreach"] else '  ❌ 배포 불가'))
