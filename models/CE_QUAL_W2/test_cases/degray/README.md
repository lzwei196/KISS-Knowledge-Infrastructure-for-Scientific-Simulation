# CE_QUAL_W2 — foundation test case: "DeGray"

Authentic foundation case: the official **DeGray Lake** example from the
CE-QUAL-W2 v5 distribution (Portland State University). `inputs/` are the
unmodified distribution files. Nothing synthetic.

| | |
|---|---|
| Engine | CE-QUAL-W2 v5, binary `w2_v5` |
| Source | PSU CE-QUAL-W2 v5 distribution, DeGray Lake example |
| Case | DeGray reservoir water-quality run (normal termination ~JDAY 358) |
| KI | `CE_QUAL_W2` |

## Files
```
test_cases/degray/
├── README.md, manifest.json (checksums; 30 input files)
├── inputs/            # distribution DeGray inputs: w2_con.csv, *.csv, *.npt, InputFiles/
├── run_reference.py   # Linux prep (flatten InputFiles, strip Windows paths) + run w2_v5 + checks
└── expected.json
```

## Run
```
python run_reference.py      # auto-finds w2_v5 (or $W2_BIN, --w2-bin); 0=PASS 3=binary missing
```
The runner copies `inputs/` into a clean temp dir, flattens `InputFiles/` into the
working directory, strips the distribution's Windows path prefixes, and runs
`w2_v5` (which reads `w2_con.csv`). PASS = "Normal termination" + the expected
`.opt` outputs. Binary-missing is reported, never marked passed.
