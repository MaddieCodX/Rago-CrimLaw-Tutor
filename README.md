# Criminal Law Tutor (Professor Rago)

Coding for Lawyers project: a study tutor for Professor Rago's evening Criminal Law students. It works from his slides only. It's the same engine as the Criminal Procedure tutor, with its prompts rewritten for Criminal Law (elements, mental states, defenses).

## What it does

1. **Office hours.** A student picks a topic and asks questions. Answers come only from that topic's slide deck, with slide citations like `[Slide 4]`. If the slides don't cover something, the tutor says so and points the student to Professor Rago.
2. **Practice hypo.** The tutor writes a bar-style fact pattern from the same deck. The defendant's state of mind is shown through facts rather than announced. The first answer is timed at 30 minutes, the time allowed for one MEE essay. The answer is graded against a hidden answer key, crime by crime and defense by defense. The tutor then asks Socratic follow-up questions about any skipped element or missed issue. At the end the student gets an issue-by-issue debrief and a model answer.

## Files

| File | What it is |
|---|---|
| `crimlaw_tutor.py` | All the logic: reading decks, the prompts, office hours, and the hypo (generate, grade, follow up). **Start your review here.** |
| `app.py` | Browser version built with Streamlit, for students. Only draws the screen. |
| `audit.py` | The tamper-evident activity log (hash-chained SHA-256) and the `verify_log()` checker. |
| `run_tutor.py` | Text version for Colab or a terminal. |
| `requirements.txt` | The libraries Streamlit installs. |
| `CHANGELOG.md` | The development record. |
| `decks/` | Professor Rago's Criminal Law `.pptx` files, one per topic. |
| `tools/make_sample_deck.py` | Builds a SAMPLE deck for local testing. Never upload the sample to `decks/`. |

## Settings (top of `crimlaw_tutor.py`)

`COURSE_NAME` ("Criminal Law"), `PROFESSOR` ("Professor Rago"), `MODEL`, `BAR_TIME_LIMIT_MINUTES` (30), `MAX_FOLLOW_UP_ROUNDS` (6), `MAX_QUESTIONS_PER_ISSUE` (2), `APP_VERSION`, `LOG_STUDENT_TEXT` (True).

## Deploying (GitHub + Streamlit Community Cloud)

1. **GitHub:** create a new **private** repository, for example `rago-crimlaw-tutor`. Upload these files with **Add file → Upload files**: drag in the files and the `decks` and `tools` folders. Upload rather than pasting, which can lose formatting. Check that no file name picked up a ` (1)`.
2. **Slides:** upload Professor Rago's Criminal Law `.pptx` files into `decks/`.
3. **Streamlit:** at share.streamlit.io, choose **Create app → Deploy a public app from GitHub**. Then fill in:
   - **Repository:** the new repository
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. **Secrets** (Advanced settings, or later in Manage app → Settings → Secrets):
   ```
   ANTHROPIC_API_KEY = "sk-ant-..."
   AUDIT_ADMIN_CODE = "pick-a-code"
   ```
5. **Sharing:** after testing, make the app private and invite students, or share the link.

New decks appear on their own about a minute after they're uploaded to GitHub, so a reboot isn't needed for slides. After uploading **new code**, use **Manage app → ⋮ → Reboot app**.

## How the hypo is graded

Claude writes the **hypo and its answer key in the same call**, filling in a "form": a JSON Schema passed as a tool, with `tool_choice` requiring it. The answer arrives as a ready-made dictionary instead of text that has to be parsed. In the answer key, each crime and each defense is its own issue, and the rule is listed element by element as the slides state it.

A crime counts as `complete` only when every element, including the act, the mental state and any result or causation element, is applied to specific facts. Naming a crime without its elements is `partial`. Grades can go up but never down. Each issue gets at most 2 follow-up questions, and each hypo at most 6 in total.

## Audit trail

Every session is recorded in `audit_log.jsonl`, a chain of entries in which each entry's SHA-256 hash covers the one before it. That makes any edit, deletion or reordering detectable. The **Instructor** panel in the sidebar, unlocked with `AUDIT_ADMIN_CODE`, verifies the chain and downloads the log. On Streamlit Cloud, the log resets when the app restarts or sleeps, so download it regularly. Students are identified only by a random session ID. The app tells them their questions and answers are logged.

## Limits to know about

- **"Closed universe" is an instruction, not a guarantee.** Claude knows criminal law and could slip. The slide citations let students check any answer against the deck.
- **The timer is basic.** It measures the first answer and flags overtime. The browser countdown is display-only.
- **Hypo quality depends on the slides.** Image-only slides can't be read. Speaker notes help.
- **Student answers are sent to the Anthropic API.**
- **Study aid only.** The slides and Professor Rago have the final word.
