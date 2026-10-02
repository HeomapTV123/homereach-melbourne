# Raw data rules

Store original downloaded files here without editing them.

Suggested folders:

```text
data/raw/
├── rent/
├── geography/
├── transport/
├── demographics/
└── environment/
```

Rules:

1. Never overwrite an official source file.
2. Record source page, download date, reporting period, filename and licence.
3. Convert to Parquet only in `data/interim/` or `data/processed/`.
4. Avoid committing large source files to GitHub.
5. Treat suppressed rental values such as `-` or blank as missing, not zero.
