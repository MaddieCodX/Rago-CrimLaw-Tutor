"""
app.py -- the browser version of the tutor, built with Streamlit.

All the real work happens in crimlaw_tutor.py; this file only draws the screen.

Run it on your own computer:
    pip install -r requirements.txt
    streamlit run app.py
The API key comes from Streamlit secrets (.streamlit/secrets.toml) or the
ANTHROPIC_API_KEY environment variable -- students never see or type it.

A Streamlit note: the whole script re-runs from the top every time a student clicks
or types. Anything that has to survive between clicks (the chat history, the hypo,
the timer) is kept in st.session_state, which works like a dictionary that persists.
"""

import os

import streamlit as st

from audit import AuditLog, verify_log
from crimlaw_tutor import (APP_VERSION, BAR_TIME_LIMIT_MINUTES, CODE_FINGERPRINT, COURSE_NAME,
                           PROFESSOR, HypoSession, OfficeHours, Tutor, deck_signature,
                           generate_hypo, load_all_decks)

AUDIT_PATH = "audit_log.jsonl"

st.set_page_config(page_title=f"{COURSE_NAME} Tutor -- {PROFESSOR}", page_icon="⚖️")


# ---------- setup: the key and the decks ----------
def get_api_key():
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY")


@st.cache_resource            # read the decks once, not on every click...
def get_decks(signature, code_version):
    # ...but the two arguments are part of the cache's key. When a deck is added or
    # replaced (signature) or the code changes (code_version), the key changes and the
    # decks are read again -- no reboot needed. The arguments are only used as the key.
    return load_all_decks()


@st.cache_resource            # ONE log shared by every student's session
def get_audit_log():
    return AuditLog(AUDIT_PATH)


def get_secret(name):
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name)


api_key = get_api_key()
decks = get_decks(deck_signature(), CODE_FINGERPRINT)
audit = get_audit_log()

st.title(f"{COURSE_NAME} Tutor")
st.caption(f"Answers come only from {PROFESSOR}'s slides. This is a study aid; the slides "
           f"and {PROFESSOR} have the final word. Your questions and answers are logged "
           "anonymously to check the tutor's work.")

if not api_key:
    st.error("No API key found. Add ANTHROPIC_API_KEY to Streamlit secrets.")
    st.stop()
if not decks:
    st.error("No .pptx files found in the decks/ folder yet. Upload the slide decks to "
             "the decks folder on GitHub.")
    st.stop()

# ---------- topic picker ----------
topics = [deck.label for deck in decks]
chosen_topic = st.sidebar.selectbox("Topic", topics)
deck = decks[topics.index(chosen_topic)]

# A new topic means a fresh tutor, a fresh chat, and no hypo in progress.
if st.session_state.get("topic") != chosen_topic or st.session_state.tutor.deck is not deck:
    st.session_state.topic = chosen_topic
    st.session_state.tutor = Tutor(deck, api_key, audit=audit)
    st.session_state.office_hours = OfficeHours(st.session_state.tutor)
    st.session_state.hypo_session = None
    st.session_state.past_titles = []

tutor = st.session_state.tutor

# ---------- instructor panel: the audit trail ----------
# Shown only to someone who enters the code stored in secrets as AUDIT_ADMIN_CODE.
admin_code = get_secret("AUDIT_ADMIN_CODE")
if admin_code:
    with st.sidebar.expander("Instructor"):
        entered = st.text_input("Instructor code", type="password")
        if entered == admin_code:
            ok, message = verify_log(AUDIT_PATH)
            (st.success if ok else st.error)(message)
            st.caption(f"Code version {APP_VERSION} · code fingerprint {CODE_FINGERPRINT}")
            if os.path.exists(AUDIT_PATH):
                with open(AUDIT_PATH, "rb") as f:
                    st.download_button("Download audit log", f.read(),
                                       file_name="audit_log.jsonl")
            st.caption("The log on the server resets when the app restarts or sleeps. "
                       "Download it regularly to keep a permanent record.")
        elif entered:
            st.error("Incorrect code.")

office_tab, hypo_tab = st.tabs(["Office Hours", "Practice Hypo"])


# ============================================================
# PART 1 - OFFICE HOURS
# ============================================================
with office_tab:
    st.write(f"Ask anything about **{deck.label}**.")
    chat = st.session_state.office_hours

    for turn in chat.history:
        speaker = "user" if turn["role"] == "user" else "assistant"
        with st.chat_message(speaker):
            st.markdown(turn["content"])

    question = st.chat_input("Your question", key="office_hours_input")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Checking the slides..."):
                st.markdown(chat.ask(question))


# ============================================================
# PART 2 - PRACTICE HYPO
# ============================================================
def countdown(seconds_left):
    """A display-only countdown clock. The official time is still measured in
    crimlaw_tutor.py when the answer is submitted."""
    seconds_left = max(0, int(seconds_left))
    st.iframe(f"""
        <div id="clock" style="font: 600 22px sans-serif; padding: 6px 0;"></div>
        <script>
          let left = {seconds_left};
          const el = document.getElementById("clock");
          function tick() {{
            const m = Math.floor(Math.abs(left) / 60), s = Math.abs(left) % 60;
            const t = m + ":" + String(s).padStart(2, "0");
            el.textContent = left >= 0 ? "Time left: " + t : "OVER TIME by " + t;
            el.style.color = left >= 300 ? "inherit" : "#c0392b";
            left -= 1;
          }}
          tick(); setInterval(tick, 1000);
        </script>""", height=45)


with hypo_tab:
    session = st.session_state.hypo_session

    # --- no hypo yet: offer to write one ---
    if session is None:
        st.write(f"A bar-style essay question built from the **{deck.label}** slides. "
                 f"Your first answer is timed at **{BAR_TIME_LIMIT_MINUTES} minutes**, "
                 "like one MEE essay. Follow-up questions are not timed.")
        if st.button("Write me a hypo"):
            with st.spinner("Writing a hypo from the slides..."):
                try:
                    hypo = generate_hypo(tutor, avoid_titles=st.session_state.past_titles)
                    st.session_state.past_titles.append(hypo.title)
                    st.session_state.hypo_session = HypoSession(tutor, hypo)
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not write a hypo: {e}")

    # --- hypo written, clock not started: hide the facts until the student is ready ---
    elif session.start_time is None:
        st.write("Your hypo is ready. The facts appear when you start the clock.")
        if st.button(f"Start the {BAR_TIME_LIMIT_MINUTES}-minute clock"):
            session.start_clock()
            st.rerun()

    # --- clock running: show facts, take the timed answer ---
    elif session.elapsed_seconds is None:
        countdown(session.seconds_remaining())
        st.markdown(session.hypo.student_view())
        answer = st.text_area("Your answer", height=400)
        if st.button("Submit answer"):
            if not answer.strip():
                st.warning("Write an answer before submitting.")
            else:
                try:
                    with st.spinner("Reading your answer..."):
                        session.submit_answer(answer)
                    st.rerun()
                except Exception as e:
                    # Nothing was saved, and the answer is still in the box above.
                    st.error("The tutor couldn't grade that just now. Your answer is still "
                             "in the box -- please click Submit again. "
                             f"(Details: {e})")

    # --- after the timed answer: follow-ups, then the debrief ---
    else:
        st.info(session.timing_report())
        with st.expander("Show the hypo again"):
            st.markdown(session.hypo.student_view())

        for speaker, text in session.transcript:
            with st.chat_message("user" if speaker == "student" else "assistant"):
                st.markdown(text)

        if not session.finished:
            reply = st.chat_input("Your response", key="hypo_reply")
            if reply:
                try:
                    with st.spinner("Reading your response..."):
                        session.respond(reply)
                    st.rerun()
                except Exception as e:
                    st.error("The tutor couldn't read that response just now. Please send "
                             f"it again. (Details: {e})")
                    st.code(reply, language=None)     # shown so it can be copied back in
        else:
            st.subheader("Debrief")
            st.markdown(session.final_report())
            if st.button("Try another hypo"):
                st.session_state.hypo_session = None
                st.rerun()
