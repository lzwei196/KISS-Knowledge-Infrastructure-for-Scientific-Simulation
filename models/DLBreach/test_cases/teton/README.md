# DLBreach — foundation test case: "Teton"

Authentic foundation case: the official **Teton Dam** failure test from the
DLBreach (Wu 2016) distribution test cases. `inputs/Teton_cards.txt` is unmodified.

| | |
|---|---|
| Engine | DLBreach, `DLBreach_Barrier.exe` (Fortran, runs via **WINE**) |
| Source | DLBreach distribution "DLBreach Test cases" (Teton Dam, 1976) |
| KI | `DLBreach` |

## Run
```
python run_reference.py     # finds the exe (or $DLBREACH_BIN) + wine; 0=PASS 3=missing dep
# equivalently: printf 'Teton_cards\n' | wine DLBreach_Barrier.exe   (in a dir with Teton_cards.txt)
```
The binary prompts for the case name on stdin. PASS = peak breach outflow
Qbreach ≈ 64,273 m³/s and end time ≈ 27.8 h (recorded 2026-10-04; deterministic).
Missing binary/wine is reported, never marked passed.
