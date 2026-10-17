# Flask-Login validation feedback overflow

The `flask-login-issue5279-location-feedback-v2` development trial failed before writing any files. Its initial proposal request was 23,477 bytes under the 24,000-byte cap. The model returned a response rejected as `Expected edits and summary`. Appending the entire rejected response to the correction request expanded it to 27,068 bytes, so the host stopped before the correction call.

This is feedback assembly overflow, not evidence that the initial source alone exceeded the cap. The localization also selected a large class and unrelated methods; fixing feedback capacity does not establish localization quality or a correct patch.

The generic correction path now preflights full feedback and falls back to explicitly omitted response content with its hash, byte count and validation error. Original raw output remains in the ledger. Both forms retain unchanged source and the original cap. Tests cover successful bounded correction, insufficient remaining capacity, shared budgets and policy failures that must not retry. No new live model success or recovery-rate improvement is claimed.
