# #175 probes (2026-10-11)

Throwaway replay probes from diagnosing #175. They import `brain/src` and work on a copy of
`brain/history.sqlite` in a `work/` (and `work2/`) folder next to them: copy the history and
`grades.toml` there first. Run with `..\..\..\.venv\Scripts\python.exe sweep.py` from this folder.

- `sweep.py`: every Scan since 10-02, rows / passing / why-not counts (output in `sweep-output.txt`).
- `raw.py`: raw cheap outliers per Scan, no Brain logic.
- `h23.py`: dropped-rows gate off; gold as of a later Character Read.
- `h5.py off`: dropped items not left out of the Sell Rate.
- `h6.py`: cheap-stock cutoff off (the one that moves the low Scans).
- `h7.py`: which keys the cutoff takes and how old their stretch is.

Findings are on issue #175.
