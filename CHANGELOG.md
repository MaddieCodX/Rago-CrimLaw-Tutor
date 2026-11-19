# Change Log: Criminal Law Tutor (Professor Rago)

This file records how the code was built and changed: what changed, why, and how it was tested. `APP_VERSION` in `crimlaw_tutor.py` matches the latest entry, and every audit-log session records that version and a fingerprint of the code.

**Who built it:** Maddie Csikari designed the project with Professor Rago. The code was drafted with Claude, an AI assistant. Maddie reviews it, runs the live tests and deploys it. Professor Rago's slide decks are the tutor's only source.

**History:** this tutor is adapted from the Criminal Procedure tutor (`rago_tutor.py`, version 0.4, November 5–9, 2026). That project's own change log records the original design decisions:
- the closed universe through the system prompt plus slide citations
- the hypo and its answer key written in one call
- grades that only go up
- the 30-minute MEE timer
- tool-use forms instead of parsing JSON text
- rollback when grading fails
- the hash-chained audit log

---

## Version 1.0: Criminal Law adaptation (November 19, 2026)

**Goal:** the same tutor for Professor Rago's Criminal Law course, as a separate repository and Streamlit app.

**Changed from Crim Pro v0.4:**

| Change | Where | Why |
|---|---|---|
| `COURSE_NAME` and `PROFESSOR` settings; prompts and screens read them | `crimlaw_tutor.py` Section 1 and 4; `app.py`; `run_tutor.py` | One place to change the course or professor, instead of names typed into strings |
| Core file renamed to `crimlaw_tutor.py` | All files | Keeps the two projects from being mixed up |
| Hypo writer: never name a crime or defense; show state of mind through facts; call of the question asks what crimes and defenses apply; each crime and each defense is its own issue; rules listed element by element | `hypo_writer_prompt` | Criminal Law essays turn on the elements, especially mental state |
| Grader: `complete` requires every element applied to facts; naming a crime without its elements is `partial` | `grader_prompt` | Matches how Criminal Law answers are graded |
| Follow-up questions point to state-of-mind facts or the skipped element | `follow_up_prompt` | The most common gap in Criminal Law answers |
| `deck_signature()`; the web app's deck cache is keyed on the decks folder's contents and the code fingerprint | `crimlaw_tutor.py` Section 2; `app.py` | In the Crim Pro app, new decks and new code needed a manual reboot, and a stale cache caused an `AttributeError` (November 9). Now the slides reload on their own when they change. |
| The opening screen tells students their questions and answers are logged | `app.py` | Disclosure, recommended in the Crim Pro README |
| `decks/README.txt` placeholder; the sample deck is written outside `decks/` | `decks/`, `tools/` | Keeps the folder on GitHub and keeps the sample from reaching students |

**Unchanged:** `audit.py`, the tool-use forms, rollback on failure, the 30-minute timer, and the follow-up limits (2 per issue, 6 per hypo).

**Testing:**
- Run against a simulated API, as with Crim Pro: a full office-hours plus hypo session through the debrief, with injected grading failures.
- Streamlit's `AppTest`, including the Instructor panel.
- The Colab runner.
- Audit chain verification.
- Adding a deck while the app was running made it appear without a reboot.
- Live testing with Professor Rago's decks is the next step.
