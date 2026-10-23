# Benefits automation

`daily_report.py` reads only the six existing task result files under the
Hermes benefits runtime `delivery/` directory. It reports missing or invalid
daily results, failed execution, and business steps that are not complete or
not applicable. Normal results produce no output. The report names the affected
platform and describes the task status or failure reason.

No benefits API is called and no runtime JSON is modified. Hermes owns the
daily schedule and delivery.
