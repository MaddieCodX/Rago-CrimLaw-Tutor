"""
run_tutor.py -- the text version of the tutor, for Google Colab or a terminal.

In Colab:
  1. Upload crimlaw_tutor.py, audit.py and run_tutor.py, and put the .pptx decks in a folder named decks/
  2. Add ANTHROPIC_API_KEY to Colab Secrets (the key icon in the left sidebar)
  3. In a cell:  !pip -q install anthropic python-pptx
  4. In a cell:  %run run_tutor.py

In a terminal:  python run_tutor.py
"""

import getpass
import os

from audit import AuditLog, verify_log
from crimlaw_tutor import (BAR_TIME_LIMIT_MINUTES, COURSE_NAME, PROFESSOR, HypoSession,
                           OfficeHours, Tutor, generate_hypo, load_all_decks)

AUDIT_PATH = "audit_log.jsonl"     # the activity log; it grows across runs


def show(text):
    """Display the tutor's Markdown as formatted text in Colab/Jupyter (headings, bold,
    bullets). In a plain terminal there is nothing to render with, so just print it."""
    try:
        from IPython import get_ipython
        from IPython.display import Markdown, display
        if get_ipython() is not None:
            display(Markdown(text))
            return
    except ImportError:
        pass
    print(text)


def get_api_key():
    """Colab Secrets first, then an environment variable, then ask (the Class 19 pattern)."""
    try:
        from google.colab import userdata
        key = userdata.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    return getpass.getpass("Paste your Anthropic API key: ").strip()


def read_long_answer():
    """input() reads one line, but an essay has paragraphs. Keep reading lines until
    the student types END on a line by itself."""
    print("(Type your answer. Press Enter for new paragraphs. Type END on its own line to submit.)")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def choose_deck(decks):
    print("\nTopics:")
    for number, deck in enumerate(decks, start=1):
        print(f"  {number}. {deck.label}")
    while True:
        choice = input("Pick a topic number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(decks):
            return decks[int(choice) - 1]
        print("Please type one of the numbers above.")


def office_hours(tutor):
    print(f"\n=== OFFICE HOURS: {tutor.deck.label} ===")
    print("Ask anything about this topic. Type DONE to go back to the menu.\n")
    session = OfficeHours(tutor)
    while True:
        question = input("You: ").strip()
        if question.upper() == "DONE":
            return
        if not question:
            continue
        print("\nTutor:")
        show(session.ask(question))
        print()


def practice_hypo(tutor, past_titles):
    print("\nWriting a hypo from the slides... (this takes a few seconds)")
    try:
        hypo = generate_hypo(tutor, avoid_titles=past_titles)
    except Exception as e:
        print("Could not write a hypo:", e)
        return
    past_titles.append(hypo.title)

    session = HypoSession(tutor, hypo)
    print(f"\nYou will have {BAR_TIME_LIMIT_MINUTES} minutes, like one MEE essay.")
    input("Press Enter to see the hypo and start the clock...")
    session.start_clock()

    print("\n" + "=" * 70)
    show(hypo.student_view())
    print("=" * 70 + "\n")

    answer = read_long_answer()
    while True:
        print("\nReading your answer...")
        try:
            question = session.submit_answer(answer)     # this stops the clock
            break
        except Exception as e:
            print(f"The tutor couldn't grade that ({e}).")
            input("Press Enter to try again with the same answer...")
    print(session.timing_report())

    # The follow-ups are not timed.
    while question is not None:
        print("\nTutor:")
        show(question)
        reply = read_long_answer()
        try:
            question = session.respond(reply)
        except Exception as e:
            print(f"The tutor couldn't read that response ({e}). Please answer again.")

    print("\n" + "=" * 70)
    print("DEBRIEF")
    print("=" * 70)
    show(session.final_report())


def main():
    decks = load_all_decks()
    if not decks:
        print("No .pptx files found in the decks/ folder.")
        return
    audit = AuditLog(AUDIT_PATH)
    tutor = Tutor(choose_deck(decks), get_api_key(), audit=audit)
    past_titles = []

    print(f"\n{COURSE_NAME} tutor. It answers ONLY from {PROFESSOR}'s slides. It is a study "
          f"aid; the slides and {PROFESSOR} have the final word.")

    while True:
        print(f"\nTopic: {tutor.deck.label}")
        print("  1. Office hours")
        print("  2. Practice hypo (timed)")
        print("  3. Change topic")
        print("  4. Quit")
        choice = input("Choose: ").strip()
        if choice == "1":
            office_hours(tutor)
        elif choice == "2":
            practice_hypo(tutor, past_titles)
        elif choice == "3":
            tutor = Tutor(choose_deck(decks), tutor.client.api_key, audit=audit)
            past_titles = []
        elif choice == "4":
            ok, message = verify_log(AUDIT_PATH)
            print(f"\nAudit log ({AUDIT_PATH}): " + ("verified -- " if ok else "PROBLEM -- ") + message)
            print("Good luck studying.")
            return


if __name__ == "__main__":
    main()
