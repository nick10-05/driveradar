# Golden set

One JSON file per notice: the raw text plus the hand-labelled fields a perfect
extractor + normaliser would produce (DESIGN §4.9).

```json
{
  "id": "real-001",
  "synthetic": false,
  "source": "email",
  "as_of": "2026-11-19",
  "note": "why this notice is in the set",
  "raw_text": "...",
  "expected": {
    "company": "...", "role_title": "...", "location": null, "apply_link": null,
    "ctc_lpa": 4.5, "deadline": "2026-11-25T18:29:00Z",
    "min_cgpa": 6.5, "max_active_backlogs": 0, "grad_years": [2027],
    "allowed_branches": ["CSE", "IT"]
  }
}
```

- `null` / `[]` means "the notice doesn't say": the extractor should abstain.
- `deadline` is UTC. A notice without a timezone is IST; without a time, 23:59 IST.
- `allowed_branches` are codes from the `branches` table; `[]` = all branches.
- `as_of` is "today" for that notice (year-less dates, deadline sanity checks), so
  re-running the eval later gives the same expectations.

**`synthetic-*` files are written by hand to exercise specific rules** (percentages,
"all branches", unknown branches, explicit timezones, no deadline, a prompt-injection
line). They are not real notices and the README must not present their scores as such.
Real notices go in as `real-*.json`, anonymised first: remove personal names, phone
numbers and email addresses (DESIGN §4.9).
