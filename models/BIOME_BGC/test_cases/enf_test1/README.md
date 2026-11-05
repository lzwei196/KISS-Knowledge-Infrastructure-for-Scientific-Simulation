# BIOME_BGC — foundation test case: "enf_test1"

Authentic foundation case: Biome-BGC's official shipped example **enf_test1**
(evergreen needleleaf forest, Missoula `miss5093` meteorology). Nothing synthetic.

| | |
|---|---|
| Engine | Biome-BGC, binary `bgc` |
| Source | NTSG / University of Montana Biome-BGC distribution (shipped example) |
| Case | `enf_test1` — ENF point run, 44 years from 1950, constant CO2 294.842 ppm |
| KI | `BIOME_BGC` |

## Files
```
test_cases/enf_test1/
├── README.md, manifest.json (checksums)
├── inputs/{enf_test1.ini, metdata/miss5093.mtc41, epc/enf.epc}
├── run_reference.py   # clean-dir run + checks
└── expected.json      # authentic results (binary annual output is deterministic)
```

## Run
```
# clean dir with enf_test1.ini, metdata/, epc/ and empty outputs/ restart/:
bgc enf_test1.ini
python run_reference.py        # auto-finds bgc (or $BGC_BIN, --bgc-bin); 0=PASS 3=binary missing
```

## Expected (recorded 2026-10-04)
Runs 1950→1993; writes `outputs/oth.{annout,annavgout,monavgout,dayout}`;
`oth.annout` = 132 float64 (44 yr × 3 vars), deterministic sha256
`ef99fc60…`; final-year annual var0 ≈ 0.0029. Large binary daily output is
reproducible and not committed. Binary-missing is reported, never marked passed.
