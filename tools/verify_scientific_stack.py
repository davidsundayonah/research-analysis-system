"""Exercise the scientific and charting dependencies used by the desktop app."""

from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


matrix = np.array([[1.0, 2.0], [3.0, 4.0]])
if not np.allclose(matrix @ matrix, [[7.0, 10.0], [15.0, 22.0]]):
    raise SystemExit("NumPy calculation failed.")

test = stats.ttest_1samp([1.0, 2.0, 3.0, 4.0, 5.0], popmean=3.0)
if not np.isfinite(test.statistic) or not np.isfinite(test.pvalue):
    raise SystemExit("SciPy calculation failed.")

figure, axis = plt.subplots()
axis.plot([1, 2, 3], [2, 4, 3])
axis.set_title("ResearchAnalysis packaging check")
output = BytesIO()
figure.savefig(output, format="png")
plt.close(figure)
if not output.getvalue().startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("Matplotlib chart rendering failed.")

print("NumPy calculation, SciPy t-test, and Matplotlib PNG rendering passed.")
