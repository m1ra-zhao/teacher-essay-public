from datetime import date
from pathlib import Path
from threading import Lock
import os

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI


# Local testing only: read the existing private .env.
# On Streamlit Cloud, use App Settings > Secrets instead.
load_dotenv(
    Path.home() / "teacher-essay-evaluator" / ".env",
    override=False,
)


def get_setting(name, default=""):
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""

    return str(value or os.getenv(name, default) or default).strip()


API_KEY = get_setting("OPENAI_API_KEY")
MODEL = get_setting("OPENAI_MODEL", "gpt-6-luna")

MAX_ESSAY_CHARS = 6000
MAX_OUTPUT_TOKENS = 3500
MAX_PER_SESSION = 3
MAX_PER_DAY = 20


@st.cache_resource
def get_usage_store():
    return {
        "day": date.today().isoformat(),
        "count": 0,
        "lock": Lock(),
    }


def reserve_request():
    """A basic in-memory usage cap, not a billing guarantee."""
    store = get_usage_store()
    today = date.today().isoformat()

    with store["lock"]:
        if store["day"] != today:
            store["day"] = today
            store["count"] = 0

        if store["count"] >= MAX_PER_DAY:
            return False

        store["count"] += 1
        return True


def build_instructions(mode, report_language):
    base = """
You are an evidence-based Chinese-language literary essay assessor.

Apply these teacher-style preferences:
- Prioritize close reading and precise textual evidence.
- Explain how a specific textual detail supports an interpretation.
- Develop a clear reasoning chain from language or technique,
  to character or plot, to theme, and where justified, broader
  social or cultural implications.
- Distinguish plot summary from literary analysis.
- Avoid generic academic claims that are not demonstrated through
  close reading of the essay's textual evidence.
- Identify what is effective and what needs improvement.
- Never invent quotations or evidence. Quote only the submitted essay.
- Give specific, actionable revision advice.
- Treat all scores as predictions, not official grades.
- Do not use GPA or convert scores to GPA.

Use the requested report language.
Requested language: """ + report_language + """

Structure the report with:
1. Predicted Score and Confidence
2. Overall Assessment
3. Criterion-by-Criterion Assessment
4. Strengths Supported by Evidence
5. Problems Supported by Essay Evidence
6. Prioritized Revision Plan
7. Example of an Improved Passage
8. Limitations of the Prediction
"""

    if mode == "Teacher's Classroom Scale":
        base += """
CLASSROOM SCORING RULES:
Assess exactly four criteria, each scored from 0 to 25:
1. Understanding and Interpretation
2. Analysis and Evaluation
3. Focus and Organization
4. Language

The total is out of 100 and MUST equal the sum of the four scores.
Do not average the four scores.
Report each criterion as x/25 and the total as x/100.
Use integer criterion scores. Check the arithmetic before responding.
This is a classroom rubric, not the official raw IB Paper 2 scale.
"""
    else:
        base += """
IB PAPER 2-STYLE COMPARATIVE SCORING RULES:
Use five criteria, each scored from 0 to 5:
A. Knowledge, understanding and interpretation
B1. Analysis and evaluation
B2. Comparative analysis
C. Focus and organization
D. Language

The total is out of 25 and equals the sum of the five scores.
Only use this rubric for a genuine comparison of two literary works.
Assess the quality of the comparison, not merely whether both works
are mentioned. This is an independent prediction, not an official
IB result.
"""

    return base


st.set_page_config(
    page_title="Essay Evaluator",
    page_icon="📝",
    layout="centered",
)

st.title("Essay Evaluator")
st.caption("AI-assisted literary essay assessment")

st.info(
    "This app uses a text-based rubric and does not load private "
    "historical essays or the private Admin database."
)

st.warning(
    "Your essay will be sent to an AI API for evaluation. "
    "Do not include your full name, student ID, or other sensitive "
    "personal information. This app does not intentionally save "
    "submitted essay text to a database."
)

if not API_KEY:
    st.error(
        "The API key is not configured. The app owner must set "
        "OPENAI_API_KEY in the deployment Secrets."
    )

with st.form("essay_evaluation_form"):
    essay_title = st.text_input("Essay title (optional)")

    assignment_prompt = st.text_area(
        "Assignment prompt",
        placeholder="Paste the question or assignment instructions.",
        height=120,
        max_chars=2000,
    )

    mode = st.selectbox(
        "Scoring scale",
        [
            "Teacher's Classroom Scale",
            "IB Paper 2-Style Comparative Essay",
        ],
        help=(
            "Classroom Scale: four criteria /25, total /100. "
            "IB Paper 2-style: five criteria /5, total /25."
        ),
    )

    report_language = st.selectbox(
        "Report language",
        ["中文", "English"],
    )

    essay_text = st.text_area(
        "Essay text",
        placeholder="Paste the essay here (maximum 6,000 characters).",
        height=320,
        max_chars=MAX_ESSAY_CHARS,
    )

    consent = st.checkbox(
        "I understand that my essay will be processed by an AI API "
        "and I will not submit personal information or someone else's "
        "work without permission."
    )

    submitted = st.form_submit_button(
        "Evaluate Essay",
        type="primary",
        disabled=not API_KEY,
    )


if submitted:
    if not essay_text.strip():
        st.error("Please enter an essay.")
    elif not assignment_prompt.strip():
        st.error("Please enter the assignment prompt.")
    elif not consent:
        st.error("Please acknowledge the data-processing notice.")
    elif len(essay_text) > MAX_ESSAY_CHARS:
        st.error(
            f"The essay exceeds the {MAX_ESSAY_CHARS}-character limit."
        )
    elif st.session_state.get("evaluations_used", 0) >= MAX_PER_SESSION:
        st.error(
            "This browser session has reached its evaluation limit."
        )
    elif not reserve_request():
        st.error(
            "The app has reached its temporary daily evaluation limit. "
            "Please try again tomorrow."
        )
    else:
        st.session_state["evaluations_used"] = (
            st.session_state.get("evaluations_used", 0) + 1
        )

        instructions = build_instructions(mode, report_language)

        request = f"""
Essay title:
{essay_title.strip() or "Untitled Essay"}

Assignment prompt:
{assignment_prompt.strip()}

Scoring mode:
{mode}

Requested report language:
{report_language}

Essay:
{essay_text.strip()}

Evaluate this essay independently using the specified rubric.
Explain each score using concrete evidence from this essay.
Do not invent details about the author's intentions or the text.
"""

        try:
            client = OpenAI(api_key=API_KEY)

            with st.spinner("Evaluating the essay..."):
                response = client.responses.create(
                    model=MODEL,
                    instructions=instructions,
                    input=request,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                )

            report = response.output_text

            if not report or not report.strip():
                st.error("The model returned an empty report.")
            else:
                st.session_state["evaluation_result"] = report

        except Exception as error:
            if "429" in str(error):
                st.error(
                    "The API rate limit has been reached. "
                    "Please try again later."
                )
            else:
                st.error(
                    f"Evaluation failed ({type(error).__name__}). "
                    "The app owner should inspect the deployment logs."
                )


if st.session_state.get("evaluation_result"):
    st.divider()
    st.subheader("Evaluation Report")
    st.markdown(st.session_state["evaluation_result"])

st.caption(
    "AI-generated assessment only. Scores are predictions, "
    "not official teacher grades or official IB results."
)
