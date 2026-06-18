"""Simulate BIA v2.6.3 scores for PROJECT_NAME RAG chatbot."""

def ics_product(g28, g29):
    if g28 == "Yes" and g29 == "Yes":
        return 6
    if g28 == "Yes":
        return 3
    return 1

def biz_obj(g_start, g_delay, g_one, g_many):
    if g_start == "No":
        return 1
    if g_delay == "No":
        return 2
    if g_one == "Yes":
        return 4
    if g_many == "No":
        return 6
    return 8

def erm_aggregate(scores):
    s = [x for x in scores if x]
    if s.count(8) >= 2 or (s.count(8) == 1 and s.count(6) > 0):
        return 9
    if s.count(8) == 1:
        return 8
    if s.count(6) > 1:
        return 7
    return max(s) if s else 1

def acp_level(x):
    if x < 4:
        return 1
    if x < 8:
        return 2
    return 3

def run(label, answers):
    g12, g13 = answers["g12"], answers["g13"]
    export_c = 2 if g12 == "Yes" and g13 == "Yes" else (1 if g12 == "Yes" or g13 == "Yes" else 0)
    ics_c = ics_product(answers["g28"], answers["g29"])
    ics_i = 4 if answers["g28"] == "Yes" and answers["g29"] == "No" else ics_c
    ics_a = ics_i
    c_biz = biz_obj(answers["g32"], answers["g33"], answers["g34"], answers["g35"])
    i_biz = 1 if answers["g37"] == "No" else 2
    a_biz = 1 if answers["g42"] == "No" else 2
    c_media = 1 if answers["g48"] == "No" else 2
    scores_c = [export_c, ics_c, c_biz, c_media]
    scores_i = [ics_i, i_biz, 1]
    scores_a = [ics_a, a_biz, 1]
    L, M, N = max(1, erm_aggregate(scores_c)), max(1, erm_aggregate(scores_i)), max(1, erm_aggregate(scores_a))
    print(f"{label}")
    print(f"  ERM Score: {L}.{M}.{N}")
    print(f"  ACP Level: {acp_level(L)}.{acp_level(M)}.{acp_level(N)}")
    print(f"  (components C={scores_c} I={scores_i} A={scores_a})")
    print()

base = dict(
    g12="No", g13="Yes", g28="Yes", g29="No",
    g32="Yes", g33="No", g34="No", g35="No",
    g37="No", g42="No", g48="No",
)
run("Scenario A — tech data Yes (honest)", base)
run("Scenario B — tech data No", {**base, "g13": "No"})
run("Scenario C — no product link", {**base, "g28": "No", "g13": "No"})
