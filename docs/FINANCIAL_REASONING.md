# Financial reasoning

The parser associates supported row labels with fiscal columns, detects accounting negatives, and preserves the original value, scale, currency, period, statement basis, and evidence ID. When resolution finds a primary financial statement it prefers those disclosures over secondary tables. Conflicting primary figures require a narrower selection. Some PDF layouts remain unsupported.

The calculation registry uses Decimal arithmetic for growth, CAGR, margins, basic operations, and selected ratios. It normalizes like-currency scales and checks period, unit, basis, and calculation-specific metric requirements. Growth requires a positive annual baseline. No foreign-exchange assumptions are applied. Each result includes its inputs, source citations, formula, and intermediate values when applicable.
