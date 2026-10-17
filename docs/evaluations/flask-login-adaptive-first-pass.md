# Flask-Login adaptive-configured first-pass success

Artifact: `.keel/transition-trials/flask-login-adaptive-v1`.

The live run passed the five frozen Docker cases (import, login query parameters, next URL, signed cookie roundtrip, local session flow). It modified only `src/flask_login/utils.py`: removed Werkzeug URL helpers and used stdlib query parsing/encoding with blank-value preservation.

Observed cost: 4 model calls, 7,200 reported tokens, 14 tool calls and 29.5 runtime seconds. Prepared SHA-256: `c83830b3b79e232ece269f28d2f5bcddbcbd323adb66d62615886375006495a0`.

The saved runtime result has one plan (revision 0), one verification round, zero used recovery actions and no Critic routing decisions. Therefore this is a first-pass repair under adaptive configuration, not a live demonstration of failed-verification recovery or replanning. Do not attribute success or a repair-rate gain to the new Critic loop.

This remains a known development task with curated acceptance in a reconstructed environment. It is not full upstream-suite validation, a security review, a held-out result or a benchmark resolve rate. Earlier failures are retained. The next evaluation should freeze the implementation and exercise a new task; any naturally triggered recovery must be identified from actual route/verification records rather than inferred from the configuration name.
