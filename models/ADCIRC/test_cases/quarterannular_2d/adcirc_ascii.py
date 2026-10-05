"""Read ADCIRC ASCII time-series outputs (fort.61/62/63/64, maxele.63) into arrays."""
import numpy as np


def read_ts(fp):
    """Return (times[s], values[nsnap, nnode, ncol]) for an ADCIRC full-format ASCII file."""
    L = open(fp).read().split("\n")
    nsnap, nn = int(L[1].split()[0]), int(L[1].split()[1])
    ncol = int(L[1].split()[4])
    times, vals, i = [], [], 2
    for _ in range(nsnap):
        if i >= len(L) or not L[i].strip():
            break
        times.append(float(L[i].split()[0])); i += 1
        blk = np.array([[float(x) for x in L[i + k].split()[1:1 + ncol]] for k in range(nn)])
        vals.append(blk); i += nn
    return np.array(times), np.array(vals)
