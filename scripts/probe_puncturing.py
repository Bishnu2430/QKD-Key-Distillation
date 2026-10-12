"""Does puncturing high-degree columns rescue the high-rate end? (C1 probe)"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model import code as qc, pipeline  # noqa: E402

FRAMES, ITERS, SEED = 25, 60, 4242
nb, mb, z = 256, 84, 32

reg = qc.make_qc_code(nb, mb, z, 3, seed=SEED)
w = qc.irregular_weights(nb, heavy_fraction=0.20, heavy_weight=6, light_weight=3)
irr = qc.make_qc_code(nb, mb, z, w, seed=SEED)
print("regular   R0=%.3f edges=%d" % (reg.rate0, reg.n_edges_base))
print("irregular R0=%.3f edges=%d degrees=%s"
      % (irr.rate0, irr.n_edges_base, np.bincount(irr.column_degrees()).tolist()))
print()
header = ("QBER", "code", "punct_cols", "p_bits", "R", "f", "FER", "iters")
print("%5s %10s %11s %8s %7s %7s %6s %7s" % header)

for q in (0.01, 0.02, 0.03):
    for name, code_obj, pick in (
        ("regular", reg,
         lambda c, n: qc.make_mask(c, 0, punctured_cols=qc.spread_columns(c.n_b, n))),
        ("irregular", irr, lambda c, n: qc.puncture_heavy_columns(c, n)),
    ):
        for n_punct in (26, 38, 51):  # 10%, 15%, 20% of the base columns
            mask = pick(code_obj, n_punct)
            st = pipeline.measure(mask, q, FRAMES, seed=SEED + n_punct, max_iters=ITERS)
            print("%4.1f%% %10s %11d %8d %7.3f %7.3f %6.2f %7.1f"
                  % (q * 100, name, n_punct, mask.p, mask.rate,
                     st["efficiency"], st["fer"], st["avg_iters_ok"]))
    print()
