"""
crimlaw_tutor.py -- a Criminal Law study tutor for Professor Rago's night students.

Coding for Lawyers final project. Adapted from the Criminal Procedure tutor
(rago_tutor.py, version 0.4); the engine is the same, the course settings and the
hypo/grading instructions are written for Criminal Law.

WHAT IT DOES
  Part 1  OFFICE HOURS  -- a student asks questions about one topic and gets answers
                           drawn ONLY from the professor's slide deck for that topic.
  Part 2  PRACTICE HYPO -- the tutor writes a bar-style fact pattern from the same deck,
                           times the student's first answer (30 minutes, like one MEE
                           essay), grades it against a hidden answer key, and then asks
                           pointed Socratic questions about whatever the student missed.

HOW THE FILE IS ORGANIZED
  Section 1  Settings
  Section 2  Reading the PowerPoint decks       (python-pptx; Class 4 string cleaning)
  Section 3  Talking to Claude                  (Anthropic SDK; tool-use 'forms')
  Section 4  The closed-universe instructions   (system prompts)
  Section 5  Part 1 -- Office Hours             (a chat loop that keeps its history)
  Section 6  Part 2 -- The Hypo                 (generate -> grade -> follow up)

THE AUDIT TRAIL
  If a Tutor is given an AuditLog (audit.py), every step below is recorded in a
  hash-chained log, along with fingerprints of the slide deck and of this file, so any
  record can be traced to the exact slides and code that produced it.

Nothing here prints or asks for input. The two front ends (run_tutor.py for Colab or a
terminal, app.py for the browser) do all the printing; this file only does the work and
returns results -- the "deliverable, not announcement" rule from Class 10.
"""

import glob
import json
import os
import time

import anthropic
from pptx import Presentation

from audit import fingerprint, new_session_id, sha256_text


# ============================================================
# SECTION 1 - SETTINGS
# Every number a professor might want to change lives here, once.
# ============================================================

COURSE_NAME = "Criminal Law"      # shown on screen and used in every prompt
PROFESSOR = "Professor Rago"      # whose slides are the closed universe

MODEL = "claude-sonnet-4-6"       # tutoring and grading take judgment -> Sonnet, not Haiku
BAR_TIME_LIMIT_MINUTES = 30       # one MEE essay = 30 minutes (six essays in three hours)
MAX_FOLLOW_UP_ROUNDS = 6          # total Socratic questions per hypo, across all issues
MAX_QUESTIONS_PER_ISSUE = 2       # after two nudges on one issue, move on to the next
DECK_FOLDER = "decks"             # where the professor's .pptx files go

APP_VERSION = "1.0"               # bump this with each entry in CHANGELOG.md
LOG_STUDENT_TEXT = True           # False -> the audit log keeps only a fingerprint of what
                                  # students write, not the words themselves (privacy)

# A fingerprint of THIS FILE's code. If anyone edits crimlaw_tutor.py, the fingerprint
# changes -- so every audit record shows exactly which version of the code was running.
with open(__file__, encoding="utf-8") as _source:
    CODE_FINGERPRINT = fingerprint(_source.read())

# Grade labels, ranked so a later grade can never be WORSE than an earlier one.
STATUS_RANK = {"missing": 0, "partial": 1, "complete": 2}


# ============================================================
# SECTION 2 - READING THE POWERPOINT DECKS
# A deck becomes a Deck object holding a list of Slide objects (Class 9).
# ============================================================

def clean_text(text):
    """Collapse every run of whitespace to one space (the Class 4 split/join trick)."""
    return " ".join(text.split())


def clean_lines(text):
    """Clean each line but keep the line breaks, so bullet points stay separate."""
    lines = []
    for line in text.split("\n"):
        if line.strip():
            lines.append(clean_text(line))
    return "\n".join(lines)


class Slide:
    """One slide: its number, title, body text, and speaker notes."""

    def __init__(self, number, title, body, notes):
        self.number = number
        self.title = title
        self.body = body
        self.notes = notes

    def as_text(self):
        """The slide written out for Claude, labeled so Claude can cite it."""
        text = f"[Slide {self.number}] {self.title}\n{self.body}"
        if self.notes:
            text = text + f"\nSpeaker notes: {self.notes}"
        return text

    def __repr__(self):
        return f"<Slide {self.number}: {self.title}>"


class Deck:
    """One topic's PowerPoint, as a list of Slide objects."""

    def __init__(self, topic, slides, source_file):
        self.topic = topic
        self.slides = slides
        self.source_file = source_file
        # Every weekly deck may open with the same course-title slide, so the menu label
        # comes from the FILE NAME: "RAGO_PPT_WEEK_9.pptx" -> "RAGO PPT WEEK 9".
        # Name the files descriptively (e.g. "Week 09 - Confessions.pptx") for clean labels.
        self.label = os.path.splitext(source_file)[0].replace("_", " ")

    def as_prompt_text(self):
        """Every slide, in order, as one block of text for the system prompt."""
        return "\n\n".join(slide.as_text() for slide in self.slides)

    def fingerprint(self):
        """A 12-character fingerprint of the slide text. If a deck is swapped or edited,
        the fingerprint changes, so the log proves which slides an answer came from."""
        return fingerprint(self.as_prompt_text())

    def __repr__(self):
        return f"<Deck: {self.label} | {self.topic} | {len(self.slides)} slides>"


def _shape_text(shape):
    """Return the text inside one shape on a slide -- text boxes and tables both."""
    if shape.has_text_frame:
        return clean_lines(shape.text_frame.text)
    if shape.has_table:
        rows = []
        for row in shape.table.rows:
            cells = [clean_text(cell.text) for cell in row.cells]
            rows.append(" | ".join(cells))
        return "\n".join(rows)
    return ""


def load_deck(path):
    """Read one .pptx file and return a Deck."""
    presentation = Presentation(path)
    slides = []

    for number, slide in enumerate(presentation.slides, start=1):
        title_shape = slide.shapes.title          # None if the slide has no title box
        title = ""
        body_parts = []

        for shape in slide.shapes:
            text = _shape_text(shape)
            if not text:
                continue
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                title = clean_text(text)
            else:
                body_parts.append(text)

        notes = ""
        if slide.has_notes_slide:
            notes = clean_text(slide.notes_slide.notes_text_frame.text)

        slides.append(Slide(number, title or "(untitled slide)", "\n".join(body_parts), notes))

    # The topic is the first slide's title; fall back to the file name.
    file_name = os.path.basename(path)
    topic = slides[0].title if slides and slides[0].title != "(untitled slide)" else file_name
    return Deck(topic, slides, file_name)


def deck_signature(folder=DECK_FOLDER):
    """A short description of what is in the decks folder right now: each file's name,
    size and last-modified time. The web app uses it to notice when a deck has been
    added, removed or replaced, and reloads the slides instead of reusing old ones."""
    signature = []
    for path in sorted(glob.glob(os.path.join(folder, "*.pptx"))):
        info = os.stat(path)
        signature.append((os.path.basename(path), info.st_size, int(info.st_mtime)))
    return tuple(signature)


def load_all_decks(folder=DECK_FOLDER):
    """Load every .pptx in the folder, sorted by file name (Class 19's glob pattern)."""
    decks = []
    for path in sorted(glob.glob(os.path.join(folder, "*.pptx"))):
        try:
            decks.append(load_deck(path))
        except Exception as e:                     # one bad file shouldn't sink the rest
            print(f"  ! could not read {path}: {e}")
    return decks


# ============================================================
# SECTION 3 - TALKING TO CLAUDE
# ============================================================

# The "forms" Claude fills in. Each is a JSON Schema: the field names, each field's
# type, and which fields are required. Handing Claude a form as a TOOL (and requiring
# it to use that tool) makes the API return a filled-in dictionary instead of free text
# we would have to parse -- no stray quotation mark can break it.

HYPO_FORM = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "a short title for the hypo"},
        "facts": {"type": "string",
                  "description": "the fact pattern; separate paragraphs with a blank line"},
        "call_of_question": {"type": "string",
                             "description": "the question the student must answer"},
        "issues": {
            "type": "array",
            "description": "the hidden answer key, one entry per issue (3 to 5 issues)",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "1, 2, 3, ..."},
                    "issue": {"type": "string", "description": "the issue in a few words"},
                    "rule": {"type": "string", "description": "the rule as the slides state it"},
                    "key_facts": {"type": "string",
                                  "description": "the facts in the hypo that raise this issue"},
                    "complete_answer": {"type": "string",
                                        "description": "what a complete analysis must include"},
                    "slides": {"type": "array", "items": {"type": "integer"},
                               "description": "the slide numbers this issue comes from"},
                },
                "required": ["id", "issue", "rule", "key_facts", "complete_answer", "slides"],
            },
        },
        "model_answer": {"type": "string",
                         "description": "a model answer organized by issue, a few short paragraphs"},
    },
    "required": ["title", "facts", "call_of_question", "issues", "model_answer"],
}

GRADE_FORM = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "the issue id from the answer key"},
                    "status": {"type": "string", "enum": ["complete", "partial", "missing"]},
                    "what_is_missing": {"type": "string",
                                        "description": "private note for the tutor; empty if complete"},
                },
                "required": ["id", "status", "what_is_missing"],
            },
        },
    },
    "required": ["issues"],
}


class Tutor:
    """Holds one deck plus the API connection. Every model call goes through here."""

    def __init__(self, deck, api_key, model=MODEL, audit=None):
        self.deck = deck
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)
        self.audit = audit                         # an AuditLog, or None for no logging
        self.session_id = new_session_id()         # anonymous: no names or emails
        self.log("session_start", app_version=APP_VERSION, code_fingerprint=CODE_FINGERPRINT,
                 deck=deck.label, deck_file=deck.source_file,
                 deck_fingerprint=deck.fingerprint(), slides=len(deck.slides), model=model)

    def log(self, event, **details):
        """Record one step in the audit log (if there is one). A logging problem must
        never interrupt a student's studying, so failures are noted, not raised."""
        if self.audit is None:
            return
        try:
            self.audit.record(self.session_id, event, details)
        except Exception as e:
            print(f"  ! audit log write failed: {e}")

    def call(self, system, messages, max_tokens=1500):
        """Send one request; return the model's text (response.content -> text blocks)."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return "".join(block.text for block in response.content if block.type == "text")

    def call_with_form(self, system, user_text, form_name, form, max_tokens=4000, tries=2):
        """Make Claude fill in a form and return it as a Python dictionary.

        The form goes in as a tool, and tool_choice REQUIRES Claude to use it. The answer
        comes back as a tool_use block -- the same block you navigated in Classes 7 and 10
        -- and its .input is already a dictionary, so there is no json.loads to fail.
        If a reply is cut off or missing, try once more before giving up.
        """
        problem = "no reply"
        for attempt in range(tries):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_text}],
                tools=[{"name": form_name,
                        "description": "Record your result by filling in every field.",
                        "input_schema": form}],
                tool_choice={"type": "tool", "name": form_name},
            )
            if response.stop_reason == "max_tokens":
                problem = "the reply was cut off before the form was finished"
                continue
            for block in response.content:
                if block.type == "tool_use" and block.name == form_name:
                    return block.input
            problem = "the reply did not include the form"
        raise ValueError(f"Could not get a usable reply from the model: {problem}.")


def student_text(text):
    """What the audit log keeps of something a student wrote: the words themselves, or --
    if LOG_STUDENT_TEXT is False -- only its fingerprint and length."""
    if LOG_STUDENT_TEXT:
        return text
    return {"sha256": sha256_text(text), "characters": len(text)}


# ============================================================
# SECTION 4 - THE CLOSED-UNIVERSE INSTRUCTIONS
# Every prompt starts from the same rules and the same slides.
# ============================================================

def closed_universe_rules(deck):
    """The rules every part of the tutor follows, with the slides attached."""
    return f"""You are a teaching assistant for {PROFESSOR}'s {COURSE_NAME} course.
Your students are evening law students preparing for the professor's exam and the bar.

YOUR ONLY SOURCE is {PROFESSOR}'s slide deck for this topic: "{deck.label}".
The full deck appears between the <slides> tags below.

Closed-universe rules -- follow all of them, always:
1. Use only what is in the slides. Do not add cases, rules, tests, exceptions, or facts
   that are not in the slides, even if you know them to be true.
2. Cite the slide number for every legal point, in brackets, like [Slide 4].
3. If the slides do not answer something, say so plainly -- "The slides for this topic
   don't cover that; please bring it to {PROFESSOR}." Never fill a gap from outside
   knowledge.
4. If the slides and your general knowledge seem to differ, follow the slides.

<slides>
{deck.as_prompt_text()}
</slides>"""


def office_hours_prompt(deck):
    return closed_universe_rules(deck) + """

YOUR ROLE: OFFICE HOURS.
A student has come to office hours with questions about this topic.
- Explain in plain language, the way a patient professor would.
- When it helps, give a short example built only from concepts on the slides.
- Keep each answer under about 250 words unless the student asks for more.
- Get straight to the substance: no openers like "Great question!"
- Format in simple Markdown: short paragraphs, a few bullet points or a bold term where
  they help. Avoid tables and horizontal rules.
- If a question is vague, ask one clarifying question instead of guessing.
- If a student asks you to just do their graded work, help them understand the rule
  instead."""


def hypo_writer_prompt(deck):
    return closed_universe_rules(deck) + """

YOUR ROLE: WRITE A BAR-STYLE ESSAY HYPOTHETICAL.
Write an original fact pattern that tests the key points of this deck, the way a
Multistate Essay Examination question does. A student who understands the slides should
be able to write a complete answer in 30 minutes.

Requirements:
- 3 to 5 paragraphs of realistic facts with names, dates, and specific details.
- Test 3 to 5 distinct issues. Every issue must come from the slides.
- Never name a crime, a defense or a doctrine in the facts; the student must spot them.
- Give each defendant's acts AND state of mind through facts (what they said, planned,
  knew or saw), so the mental state has to be inferred, never announced.
- End with a call of the question, like "Discuss what crimes, if any, Dana Price can
  be convicted of, and any defenses she may raise."
- You may include one fact that looks important but does not change the outcome.
- Treat each crime as its own issue, and each defense as its own issue. In the answer
  key, "rule" lists the elements exactly as the slides state them, and
  "complete_answer" says how each element applies to these facts.

Record the hypo AND its hidden answer key with the save_hypo tool. Fill in every
field; the answer key must list each issue, its rule, the triggering facts, what a
complete answer includes, and the slide numbers."""


def grader_prompt(deck):
    return closed_universe_rules(deck) + """

YOUR ROLE: GRADE A STUDENT'S ANSWER AGAINST THE ANSWER KEY.
You will receive the hypo, the hidden answer key, and everything the student has written
so far (their timed answer plus any replies to follow-up questions).

For each issue in the key, decide:
- "complete": the student spotted the issue, stated the rule correctly (per the slides),
  applied it to the key facts, and reached a conclusion. For a crime, that means
  every element the slides list -- the act, the mental state, and any result or
  causation element -- is applied to specific facts. For a defense, its elements
  are applied and the student says what effect it has on liability.
- "partial": the student touched the issue but left out the rule, the application, or
  the conclusion -- or skipped an element, or got part of it wrong. Naming a crime
  without walking through its elements is "partial".
- "missing": the student did not address the issue.

Grade on substance, not wording. Credit an answer that says the right thing in different
words. Judge only against the key and the slides.

Record your grades with the save_grades tool, one entry for every issue in the key.
"what_is_missing" is a private note for the tutor, never shown to the student. Be
specific about what the student still has to say."""


def follow_up_prompt(deck):
    return closed_universe_rules(deck) + """

YOUR ROLE: ASK ONE SOCRATIC FOLLOW-UP QUESTION.
The student's answer to the hypo is incomplete on one issue. Ask ONE pointed question
that leads them to find the gap themselves.
- Do NOT state the rule, name the doctrine, or give the answer.
- Point to specific facts from the hypo that they have overlooked -- often a fact that
  shows the defendant's state of mind, or the element they skipped.
- If this is a second question on the same issue, be more specific than the first.
- One or two sentences. Return only the question -- no greeting, no preamble."""


# ============================================================
# SECTION 5 - PART 1: OFFICE HOURS
# ============================================================

class OfficeHours:
    """A running conversation about one deck. Keeps the whole history so follow-up
    questions like "what if the officer had a warrant?" make sense."""

    def __init__(self, tutor):
        self.tutor = tutor
        self.history = []                          # list of {"role": ..., "content": ...}

    def ask(self, question):
        """Send the student's question; return the tutor's answer."""
        self.history.append({"role": "user", "content": question})
        try:
            answer = self.tutor.call(office_hours_prompt(self.tutor.deck), self.history)
        except Exception as e:
            self.history.pop()                     # keep user/assistant turns alternating
            self.tutor.log("office_hours_error", question=student_text(question), error=str(e))
            return f"(The tutor could not be reached: {e}. Please try again.)"
        self.history.append({"role": "assistant", "content": answer})
        self.tutor.log("office_hours", question=student_text(question), answer=answer)
        return answer


# ============================================================
# SECTION 6 - PART 2: THE HYPO
# Three steps: (1) generate the hypo AND its hidden key in one call,
# (2) grade the student's answer against that key, (3) follow up on the gaps.
# ============================================================

class Hypo:
    """A fact pattern plus its hidden answer key."""

    def __init__(self, data):
        # data["..."] on purpose: if the model left out a required piece, fail loudly now
        # (Class 6: use brackets when the key MUST exist).
        self.title = data["title"]
        self.facts = data["facts"]
        self.call_of_question = data["call_of_question"]
        self.issues = data["issues"]               # the hidden answer key -- never shown early
        self.model_answer = data.get("model_answer", "")
        if len(self.issues) == 0:
            raise ValueError("The hypo came back with no issues in its answer key.")

    def student_view(self):
        """What the student sees: facts and question, with no answer key."""
        return f"### {self.title}\n\n{self.facts}\n\n**{self.call_of_question}**"

    def key_text(self):
        """The answer key written out for the grader and the follow-up writer."""
        return json.dumps(self.issues, indent=2)

    def fingerprint(self):
        """Fingerprint of the whole hypo, answer key included."""
        return fingerprint(json.dumps(
            [self.title, self.facts, self.call_of_question, self.issues, self.model_answer],
            sort_keys=True))

    def issue_by_id(self, issue_id):
        for issue in self.issues:
            if issue["id"] == issue_id:
                return issue
        return None

    def __repr__(self):
        return f"<Hypo: {self.title} | {len(self.issues)} issues>"


def generate_hypo(tutor, avoid_titles=None):
    """Write a new hypo from the deck. avoid_titles keeps repeat visits from getting
    the same fact pattern twice."""
    request = "Write a new hypothetical for this deck."
    if avoid_titles:
        request = request + " Use different facts from these earlier hypos: " + "; ".join(avoid_titles)
    data = tutor.call_with_form(hypo_writer_prompt(tutor.deck), request,
                                "save_hypo", HYPO_FORM, max_tokens=6000)
    hypo = Hypo(data)
    tutor.log("hypo_generated", hypo_fingerprint=hypo.fingerprint(), title=hypo.title,
              facts=hypo.facts, call_of_question=hypo.call_of_question,
              answer_key=hypo.issues, model_answer=hypo.model_answer)
    return hypo


class HypoSession:
    """One student working one hypo: the timer, the transcript, the grades, and the
    follow-up questions."""

    def __init__(self, tutor, hypo, time_limit_minutes=BAR_TIME_LIMIT_MINUTES,
                 max_rounds=MAX_FOLLOW_UP_ROUNDS):
        self.tutor = tutor
        self.hypo = hypo
        self.time_limit_minutes = time_limit_minutes
        self.max_rounds = max_rounds

        self.start_time = None                     # set by start_clock()
        self.elapsed_seconds = None                # set when the first answer comes in
        self.over_time = None

        self.transcript = []                       # list of (speaker, text) pairs
        self.grades = {}                           # issue id -> {"status":..., "note":...}
        self.questions_asked = {}                  # issue id -> follow-ups asked about it
        self.rounds_used = 0
        self.finished = False

    # ---------- the basic timer ----------
    def start_clock(self):
        self.start_time = time.time()
        self.tutor.log("clock_started", hypo_fingerprint=self.hypo.fingerprint(),
                       time_limit_minutes=self.time_limit_minutes)

    def seconds_remaining(self):
        if self.start_time is None:
            return self.time_limit_minutes * 60
        return self.time_limit_minutes * 60 - (time.time() - self.start_time)

    def timing_report(self):
        """A plain-English line about how long the timed answer took."""
        if self.elapsed_seconds is None:
            return "The timed answer has not been submitted yet."
        used = _format_minutes(self.elapsed_seconds)
        limit = _format_minutes(self.time_limit_minutes * 60)
        if self.over_time:
            over = _format_minutes(self.elapsed_seconds - self.time_limit_minutes * 60)
            return f"Time: {used} -- {over} OVER the {limit} bar limit."
        return f"Time: {used} of {limit}. Within bar time."

    # ---------- step 1: the timed answer ----------
    def submit_answer(self, answer):
        """Stop the clock, grade the answer, and return the first follow-up question
        (or None if the answer was already complete).

        If grading fails (a network hiccup, an API error), nothing is saved: the clock
        reading and the answer are rolled back, so the student can simply submit again
        and nothing they wrote is lost. The time recorded is the moment they submitted.
        """
        if self.start_time is None:                # forgot to start? count from now
            self.start_clock()
        elapsed = time.time() - self.start_time
        self.transcript.append(("student", answer))
        try:
            self._grade()
        except Exception as e:
            self.transcript.pop()                  # roll back -- as if never submitted
            self.tutor.log("grading_failed", stage="timed answer", error=str(e))
            raise
        self.elapsed_seconds = elapsed
        self.over_time = elapsed > self.time_limit_minutes * 60
        self.tutor.log("answer_submitted", hypo_fingerprint=self.hypo.fingerprint(),
                       answer=student_text(answer), elapsed_seconds=round(elapsed),
                       over_time=self.over_time)
        self._log_grades()
        return self.next_question()

    # ---------- step 2: grading against the hidden key ----------
    def _grade(self):
        """Grade everything the student has written so far, issue by issue.
        A grade can go up but never down -- a later reply shouldn't erase earlier credit."""
        student_work = "\n\n".join(
            f"{speaker.upper()}: {text}" for speaker, text in self.transcript
        )
        request = (
            f"THE HYPO:\n{self.hypo.facts}\n\n{self.hypo.call_of_question}\n\n"
            f"THE HIDDEN ANSWER KEY:\n{self.hypo.key_text()}\n\n"
            f"EVERYTHING THE STUDENT HAS WRITTEN SO FAR:\n{student_work}"
        )
        result = self.tutor.call_with_form(grader_prompt(self.tutor.deck), request,
                                           "save_grades", GRADE_FORM)

        for graded in result.get("issues", []):
            issue_id = graded.get("id")
            if self.hypo.issue_by_id(issue_id) is None:
                continue                           # ignore an id that isn't in the key
            new_status = graded.get("status", "missing")
            if new_status not in STATUS_RANK:
                new_status = "missing"
            old = self.grades.get(issue_id, {"status": "missing", "note": ""})
            if STATUS_RANK[new_status] >= STATUS_RANK[old["status"]]:
                self.grades[issue_id] = {"status": new_status,
                                         "note": graded.get("what_is_missing", "")}

        # Any issue the grader skipped counts as missing.
        for issue in self.hypo.issues:
            if issue["id"] not in self.grades:
                self.grades[issue["id"]] = {"status": "missing", "note": "not addressed"}

    def open_issues(self):
        """Issue ids that are not yet complete, in answer-key order."""
        return [issue["id"] for issue in self.hypo.issues
                if self.grades.get(issue["id"], {}).get("status") != "complete"]

    # ---------- step 3: Socratic follow-up ----------
    def next_question(self):
        """Pick the next open issue that still has nudges left and ask about it.
        Returns None when everything is complete or the questions run out."""
        if self.rounds_used >= self.max_rounds:
            self._finish("follow-up limit reached")
            return None

        target = None
        for issue_id in self.open_issues():
            if self.questions_asked.get(issue_id, 0) < MAX_QUESTIONS_PER_ISSUE:
                target = issue_id
                break
        if target is None:
            self._finish("all issues complete" if not self.open_issues()
                         else "per-issue question limit reached")
            return None

        issue = self.hypo.issue_by_id(target)
        grade = self.grades[target]
        earlier = self.questions_asked.get(target, 0)
        request = (
            f"THE HYPO:\n{self.hypo.facts}\n\n{self.hypo.call_of_question}\n\n"
            f"THE ISSUE THE STUDENT HAS NOT FULLY ADDRESSED:\n{json.dumps(issue, indent=2)}\n\n"
            f"GRADE SO FAR: {grade['status']}. What is missing: {grade['note']}\n\n"
            f"Earlier questions on this issue: {earlier}\n\n"
            f"THE CONVERSATION SO FAR:\n"
            + "\n\n".join(f"{speaker.upper()}: {text}" for speaker, text in self.transcript)
        )
        try:
            question = self.tutor.call(follow_up_prompt(self.tutor.deck),
                                       [{"role": "user", "content": request}],
                                       max_tokens=300).strip()
        except Exception as e:
            self._finish(f"could not write a follow-up question: {e}")  # go to the debrief
            return None

        self.questions_asked[target] = earlier + 1
        self.rounds_used = self.rounds_used + 1
        self.transcript.append(("tutor", question))
        self.tutor.log("follow_up_asked", issue_id=target, question=question)
        return question

    def _finish(self, reason):
        self.finished = True
        self.tutor.log("session_complete", reason=reason, score=self.score_line(),
                       timing=self.timing_report(), follow_ups_asked=self.rounds_used)

    def respond(self, reply):
        """The student answers a follow-up: regrade, then ask the next question.
        If grading fails, the reply is rolled back so the student can send it again."""
        self.transcript.append(("student", reply))
        try:
            self._grade()
        except Exception as e:
            self.transcript.pop()
            self.tutor.log("grading_failed", stage="follow-up reply", error=str(e))
            raise
        self.tutor.log("student_reply", reply=student_text(reply))
        self._log_grades()
        return self.next_question()

    def _log_grades(self):
        self.tutor.log("graded", grades={str(k): v for k, v in self.grades.items()})

    # ---------- the wrap-up ----------
    def score_line(self):
        complete = sum(1 for g in self.grades.values() if g["status"] == "complete")
        return f"{complete} of {len(self.hypo.issues)} issues fully addressed."

    def final_report(self):
        """The issue-by-issue debrief (in Markdown), shown only after the follow-ups."""
        labels = {"complete": "COMPLETE", "partial": "PARTIAL", "missing": "MISSED"}
        lines = [f"**{self.timing_report()}**", "", f"**Score:** {self.score_line()}", "",
                 "### Issue by issue", ""]
        for issue in self.hypo.issues:
            status = self.grades.get(issue["id"], {}).get("status", "missing")
            slides = ", ".join(str(n) for n in issue.get("slides", []))
            lines.append(f"**[{labels[status]}] {issue['issue']}** (Slides {slides})")
            lines.append(f"- *Rule:* {issue['rule']}")
            lines.append(f"- *A complete answer:* {issue['complete_answer']}")
            lines.append("")
        if self.hypo.model_answer:
            lines.append("### Model answer")
            lines.append("")
            lines.append(self.hypo.model_answer)
        return "\n".join(lines)


def _format_minutes(seconds):
    """1452.3 seconds -> '24:12'."""
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
