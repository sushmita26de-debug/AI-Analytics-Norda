# Review deck checks - run 2026-08

Script: `.claude/skills/ppt-review/check.py` · Review month: 2025-12 · Deck: `reports/ppt/december-review.pptx` · Road B: pandas on `data/raw`

**PASS - deck OK**

| ID | Check | Result | Detail |
|---|---|---|---|
| F01 | Deck exists and opens | PASS | reports/ppt/december-review.pptx (49 KB) |
| F02 | 4 slides: 3 questions + what to say out loud | PASS | 4 slides |
| F03 | Every slide has speaker notes | PASS | ok |
| F04 | Built from the current mart (deck newer than every mart CSV) | PASS | ok |
| D01 | Dark background on every slide | PASS | ok |
| D02 | One amber item per question slide (the big number), none on the last | PASS | ok |
| D03 | Every slide has exactly one chart or table | PASS | ok |
| D04 | No lines or decoration shapes | PASS | only title, text boxes, chart/table |
| D05 | Font Segoe UI, nothing under 13pt | PASS | ok |
| D06 | Each answer is one sentence (after Yes./No.), at most 120 characters | PASS | ok |
| D07 | Only the dashboard colours (text tokens, calm bars, amber) | PASS | ok |
| N01 | S1 chart: Computers | PASS | deck −13% = raw −13% |
| N02 | S1 chart: Phones & Tablets | PASS | deck +22% = raw +22% |
| N03 | S1 chart: Monitors | PASS | deck +15% = raw +15% |
| N04 | S1 chart: Audio | PASS | deck +23% = raw +23% |
| N05 | S1 chart: Accessories | PASS | deck +24% = raw +24% |
| N06 | S1 big number | PASS | deck −13% = raw −13% |
| N07 | S1 answer names the weakest category | PASS | deck 'No. Every category grew except Computers, because three of i…' = raw Computers |
| N08 | S1 number of best sellers that ran out | PASS | deck in answer = raw three |
| N09 | S1 notes: all sales previous month | PASS | deck notes = raw €3,091,301.45 |
| N10 | S1 notes: all sales review month | PASS | deck notes = raw €3,417,243.75 |
| N11 | S1 notes: country Spain down | PASS | deck notes = raw country Spain −2%. Without Computers it was +13%. |
| N12 | S2 number of products that ran out | PASS | deck 11 = raw 11 |
| N13 | S2 big number | PASS | deck €432K = raw €432K |
| N14 | S2 notes: exact total | PASS | deck notes = raw €432,466.73 |
| N15 | S2 row: Kova K7-2800 | PASS | deck ['Kova K7-2800', '104', '0', '€221K'] = raw ['Kova K7-2800', '104', '0', '€221K'] |
| N16 | S2 row: Kova K7-2200X | PASS | deck ['Kova K7-2200X', '85', '0', '€147K'] = raw ['Kova K7-2200X', '85', '0', '€147K'] |
| N17 | S2 row: Kova K5-1500 | PASS | deck ['Kova K5-1500', '70', '0', '€64K'] = raw ['Kova K5-1500', '70', '0', '€64K'] |
| N18 | S2 row: other products | PASS | deck ['8 other products', '6', '0', 'under €1K'] = raw ['8 other products', '6', '0', 'under €1K'] |
| N19 | S3 big number (products to order first) | PASS | deck 4 = raw 4 |
| N20 | S3 row: Kova K7-2800 | PASS | deck ['Kova K7-2800', '0', '71', '0'] = raw ['Kova K7-2800', '0', '71', '0'] |
| N21 | S3 row: Kova K7-2200X | PASS | deck ['Kova K7-2200X', '0', '50', '0'] = raw ['Kova K7-2200X', '0', '50', '0'] |
| N22 | S3 row: Pavo Max 2 128GB | PASS | deck ['Pavo Max 2 128GB', '194', '211', '0.9'] = raw ['Pavo Max 2 128GB', '194', '211', '0.9'] |
| N23 | S3 row: Kova K5-1500 | PASS | deck ['Kova K5-1500', '0', '48', '0'] = raw ['Kova K5-1500', '0', '48', '0'] |
| N24 | S3 row: the rest | PASS | deck 7 more, smaller sellers = raw 7 more |
| N25 | S4 product-months without a stock record | PASS | deck 302 product-months have no stock record. = raw 302 |
| N26 | S4 of them in December | PASS | deck They are left out, not counted as 0 (2 of them in December). = raw 2 |
| N27 | S4 estimate repeats the big number | PASS | deck The €432K is an estimate. = raw €432K |
| N28 | S4 'December is our biggest month' said only when true | PASS | deck True = raw True |
