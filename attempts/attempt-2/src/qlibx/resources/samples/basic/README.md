# qlibx basic real-DW journey

These files are a qlibx product-owned example, not user research code or a built-in alpha claim.
The four market rows are bounded values derived from `data/DW/fng_stock_daily_prices.csv`.
`date` uses 09:00 Asia/Seoul to preserve the DW session date through UTC normalization, while
`available_at` is the confirmed same-session 15:30 close.

From the project root run:

```powershell
uv run python examples/qlibx_owned/basic/run.py .
uv run qlibx artifact list .
```

The script uses only documented public imports and project facade methods. It registers the sample,
runs direct and stored-signal Strategy paths, constructs an optional long-only portfolio, analyzes
the stored signal, renders a machine report, and prints catalog-visible artifact types.
