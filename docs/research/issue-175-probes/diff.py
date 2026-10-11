import pickle
from collections import Counter
from common175 import WORK, ts
d = pickle.load(open(WORK / "loop.pkl", "rb"))
(a_lab, (_, wa)), (b_lab, (_, wb)) = list(d.items())[:2]
A = {w.item_key: w for w in wa}; B = {w.item_key: w for w in wb}
lost = [k for k, w in A.items() if w.failed is None and (k not in B or B[k].failed is not None)]
print(len(lost), "lost;", Counter(("absent" if k not in B else B[k].failed.value) for k in lost))
for k in lost:
    a, b = A[k], B.get(k)
    f = lambda w: f"post {w.post_at and round(w.post_at)} ask {w.ask} clr {w.clear_at} se {w.sale_events} room {w.room} held {w.held} needs {w.needs} cost {w.cost} rank {w.rank}"
    print(k, a.name, "\n   A:", f(a), "\n   B:", (b.failed.value + " " + f(b)) if b else "absent")
