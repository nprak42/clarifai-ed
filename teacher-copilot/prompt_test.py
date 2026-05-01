"""
Prompt engineering test for the teacher co-pilot.
Simulates a Grade 9 class of 32 students who took the electricity diagnostic
and tests the co-pilot system prompt against Gemini.

Run:
    python teacher-copilot/prompt_test.py
    python teacher-copilot/prompt_test.py --query "how do i group students for tomorrow"
    python teacher-copilot/prompt_test.py --all
    python teacher-copilot/prompt_test.py --show-prompt
"""
import argparse
import os
import re
import sys

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Simulated class diagnostic result
# Represents what analyze_session() would return for a real class
# ---------------------------------------------------------------------------

SIMULATED_CLASS = {
    "test": {
        "title": "Electricity Diagnostic",
        "subject": "electricity",
        "grade": 9,
        "total_questions": 15,
    },
    "class_size": 32,
    "avg_score_percent": 51.0,
    "patterns": [
        {
            "pattern_id": "formula_memorizer_electricity",
            "pattern_name": "Formula Memorizer",
            "student_count": 14,
            "percent_of_class": 44,
            "grade8_risk": "CRITICAL",
            "diagnosis": "Knows WHAT to do but not WHY. Can calculate but can't explain concepts.",
            "intervention_focus": "Build meaning before formulas — what do current, voltage, resistance actually represent physically?",
            "estimated_intervention_time": "2-3 weeks",
        },
        {
            "pattern_id": "cannot_analyze_circuits",
            "pattern_name": "Circuit Analysis Failure",
            "student_count": 9,
            "percent_of_class": 28,
            "grade8_risk": "HIGH",
            "diagnosis": "Can solve isolated formula problems but cannot analyse multi-component circuits.",
            "intervention_focus": "Step-by-step circuit analysis strategy — label knowns, identify circuit type, then apply formula.",
            "estimated_intervention_time": "2-3 weeks",
        },
        {
            "pattern_id": "weak_algebra_electricity",
            "pattern_name": "Cannot Rearrange Formulas",
            "student_count": 7,
            "percent_of_class": 22,
            "grade8_risk": "MEDIUM",
            "diagnosis": "Understands physics concepts but weak algebraic manipulation blocks problem solving.",
            "intervention_focus": "Formula rearrangement practice — solving for each variable in V=IR, P=VI.",
            "estimated_intervention_time": "1-2 weeks",
        },
        {
            "pattern_id": "persistent_unit_errors",
            "pattern_name": "Unit/Conversion Issues",
            "student_count": 5,
            "percent_of_class": 16,
            "grade8_risk": "MEDIUM",
            "diagnosis": "Persistent unit conversion errors — minutes vs seconds, Watts vs Volts.",
            "intervention_focus": "Always write units at every step, dimensional analysis habit.",
            "estimated_intervention_time": "1-2 weeks",
        },
    ],
    "top_misconceptions": [
        {
            "misconception_id": "current_used_up",
            "misconception_name": "Thinks current is consumed in circuit",
            "student_count": 18,
            "percent_of_class": 56,
            "severity": "CRITICAL",
            "root_cause": "Doesn't understand conservation of charge — thinks of current like fuel being burned.",
            "why_students_think_this": "Thinks of current like fuel being consumed. Everyday experience: batteries die, things run out.",
            "grade12_impact": "Cannot understand Kirchhoff's laws, electromagnetic theory.",
        },
        {
            "misconception_id": "current_divides_in_series",
            "misconception_name": "Thinks current splits in series circuits",
            "student_count": 14,
            "percent_of_class": 44,
            "severity": "CRITICAL",
            "root_cause": "Fundamental series/parallel topology confusion — applies parallel logic to series.",
            "why_students_think_this": "Water analogy backfires — water splits at junctions, so they assume current does too.",
            "grade12_impact": "Cannot distinguish series from parallel in any context.",
        },
        {
            "misconception_id": "confuses_voltage_current",
            "misconception_name": "Confuses voltage with current",
            "student_count": 11,
            "percent_of_class": 34,
            "severity": "CRITICAL",
            "root_cause": "No physical mental model distinguishing pressure (voltage) from flow (current).",
            "why_students_think_this": "Both are invisible quantities associated with electricity — no concrete referent.",
            "grade12_impact": "Cannot understand any electrical concepts at higher level.",
        },
        {
            "misconception_id": "inverted_formula_ohms",
            "misconception_name": "Cannot rearrange Ohm's law",
            "student_count": 10,
            "percent_of_class": 31,
            "severity": "HIGH",
            "root_cause": "Weak algebraic manipulation — cannot isolate a variable.",
            "why_students_think_this": "Memorised V=IR as a sequence of symbols, not a relationship.",
            "grade12_impact": "Cannot solve for different variables in any physics formula.",
        },
        {
            "misconception_id": "ammeter_voltmeter_confusion",
            "misconception_name": "Confuses ammeter and voltmeter placement",
            "student_count": 8,
            "percent_of_class": 25,
            "severity": "CRITICAL",
            "root_cause": "Instruments and their functions are confused — placement seen as convention not necessity.",
            "why_students_think_this": "Names not connected to function. Series/parallel placement feels arbitrary.",
            "grade12_impact": "Lab safety risk — will blow ammeter in practical work.",
        },
    ],
    "score_breakdown": {
        "mechanical": 63,
        "conceptual": 38,
        "application": 29,
    },
}


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_system_prompt(class_data: dict) -> str:
    test = class_data["test"]
    patterns = class_data["patterns"]
    misconceptions = class_data["top_misconceptions"]
    breakdown = class_data["score_breakdown"]
    n = class_data["class_size"]
    avg = class_data["avg_score_percent"]

    lines = []
    lines.append(
        "You are a teaching co-pilot for a secondary school science teacher in India. "
        "Your job is to help the teacher act on diagnostic data about their class — not to give generic teaching advice, "
        "but to generate specific, ready-to-use classroom moves tied directly to the evidence in front of you."
    )
    lines.append("")
    lines.append(
        "Your outputs must be concrete and specific. Never say 'reteach the concept' or 'use manipulatives' or "
        "'differentiate instruction'. Every suggestion must name the specific misconception it addresses, "
        "the specific question or task to use, and why it targets the root cause — not the symptom."
    )
    lines.append("")
    lines.append(
        "The teacher is time-constrained. Default to short, prioritised, ready-to-use outputs. "
        "If the teacher asks for a plan, give a plan they can use tomorrow — not a 3-week curriculum. "
        "Use the response template below unless the teacher asks for something different."
    )
    lines.append("")
    lines.append(
        "Treat the conversation as cumulative planning. Reuse the activity, analogy, and constraint from earlier turns "
        "unless the teacher asks to replace them."
    )
    lines.append("")
    lines.append(
        "Be a collaborative planning partner. When the teacher asks for a worksheet, whole-class activity, recall strategy, "
        "teacher script, example set, or explanation, give that thing directly in a usable format instead of redirecting them "
        "back to the earlier plan."
    )
    lines.append("")
    lines.append(
        "Do not add conversational filler like 'Okay, let's try something else' or 'Here's a plan'. "
        "Start with the answer itself."
    )
    lines.append("")

    # Response template
    lines.append("DEFAULT RESPONSE TEMPLATE:")
    lines.append("---")
    lines.append("PRIORITY MISCONCEPTION")
    lines.append("[Name] — [X] of [N] students ([%])")
    lines.append("Root cause: [one sentence, plain language]")
    lines.append("")
    lines.append("TOMORROW'S MOVE")
    lines.append("[One concrete classroom action — specific question to ask or task to set]")
    lines.append("Time: ~[X] minutes")
    lines.append("")
    lines.append("GROUPING SUGGESTION")
    lines.append("[How to split the class for practice — who works with whom and why]")
    lines.append("")
    lines.append("LISTEN FOR (resolution signal)")
    lines.append("[One thing a student says that means the misconception is resolving]")
    lines.append("[One thing that means it isn't]")
    lines.append("")
    lines.append("FOLLOW-UP PROBLEMS")
    lines.append("[One problem to expose the gap — one to confirm resolution]")
    lines.append("---")
    lines.append("")
    lines.append(
        "CRITICAL RULES FOR FOLLOW-UP AND REFINEMENT:\n"
        "- If the teacher asks to refine, adjust, or replace ONE thing (an analogy, a grouping, a problem), "
        "change ONLY that thing. Do not regenerate the full plan.\n"
        "- If the teacher asks for a different analogy or a replacement activity, return only the replacement "
        "TOMORROW'S MOVE and any directly dependent FOLLOW-UP PROBLEM if needed. Do not repeat unchanged sections.\n"
        "- If the teacher says an analogy or approach does not work, do not use it again anywhere in the conversation — "
        "not even for a different misconception.\n"
        "- If the teacher asks a direct question, answer it in 2-4 sentences. No template.\n"
        "- Never produce more output than the teacher asked for.\n"
        "- For follow-up questions, start from the previously suggested move unless the teacher asks to switch focus.\n"
        "- Do not block the teacher's request by insisting on a different prerequisite path. You may note one prerequisite concern in a single sentence, then do exactly what was asked.\n"
        "- If the teacher asks for an instructional artifact such as a worksheet, whole-class activity, board routine, recall strategy, memory pattern, or discussion prompt, return the artifact itself with clear headings or numbered items.\n"
        "- When the teacher shares a pattern or mnemonic they like, build on it and make the structure visible. Do not dismiss it as 'just memorisation' unless the teacher explicitly asks for that critique.\n"
        "- Do not invent student-level certainty you do not have. If the data shows class-level counts but not named students, "
        "say how the teacher should identify who goes in which group.\n"
        "- Do not say 'pair stronger students with struggling students' unless the context includes evidence for who the stronger students are.\n"
        "- Prefer teacher-feasible grouping instructions such as a quick hinge question, desk-zone grouping, or self-sort by confidence."
    )
    lines.append("")

    # Class diagnostic context
    lines.append("=" * 60)
    lines.append("CLASS DIAGNOSTIC CONTEXT")
    lines.append("=" * 60)
    lines.append(f"Test: {test['title']} (Grade {test['grade']})")
    lines.append(f"Class size: {n} students")
    lines.append(f"Average score: {avg}%")
    lines.append(
        f"Score breakdown: mechanical {breakdown['mechanical']}% / "
        f"conceptual {breakdown['conceptual']}% / application {breakdown['application']}%"
    )
    lines.append(
        "Interpretation: students can apply formulas in familiar formats but break down "
        "on conceptual questions and multi-step circuit problems."
    )
    lines.append("")

    lines.append("DETECTED LEARNING PATTERNS (ranked by prevalence):")
    for p in patterns:
        lines.append(
            f"  [{p['grade8_risk']}] {p['pattern_name']} — "
            f"{p['student_count']}/{n} students ({p['percent_of_class']}%)"
        )
        lines.append(f"  Diagnosis: {p['diagnosis']}")
        lines.append(f"  Intervention focus: {p['intervention_focus']}")
        lines.append(f"  Estimated time to address: {p['estimated_intervention_time']}")
        lines.append("")

    lines.append("SPECIFIC MISCONCEPTIONS DETECTED (ranked by prevalence):")
    for m in misconceptions:
        lines.append(
            f"  [{m['severity']}] {m['misconception_name']} — "
            f"{m['student_count']}/{n} students ({m['percent_of_class']}%)"
        )
        lines.append(f"  What students think: {m['why_students_think_this']}")
        lines.append(f"  Root cause: {m['root_cause']}")
        lines.append(f"  If unaddressed: {m['grade12_impact']}")
        lines.append("")

    lines.append("=" * 60)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Test queries — simulates what a teacher would actually ask
# ---------------------------------------------------------------------------

TEST_QUERIES = [
    "What should I do first with this class?",
    "How do I group students for tomorrow's lesson?",
    "Give me a lesson plan for addressing the top misconception.",
    "Which students are at risk of failing Grade 10 boards if I don't act now?",
    "I only have 20 minutes at the start of class tomorrow. What's the single most useful thing I can do?",
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

MODEL = "gemini-2.5-flash"
GENERATION_CONFIG = types.GenerateContentConfig(
    systemInstruction="",
    temperature=0.3,
)

SECTION_HEADERS = [
    "PRIORITY MISCONCEPTION",
    "TOMORROW'S MOVE",
    "GROUPING SUGGESTION",
    "LISTEN FOR (resolution signal)",
    "FOLLOW-UP PROBLEMS",
]


def _extract_section(text: str, header: str) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(header) + 1
    except ValueError:
        return ""

    collected = []
    for line in lines[start:]:
        if line.strip() in SECTION_HEADERS:
            break
        if line.strip() == "---":
            continue
        collected.append(line.rstrip())
    return "\n".join(collected).strip()


def _compress_model_history(text: str) -> str:
    if "PRIORITY MISCONCEPTION" not in text:
        return text

    priority = _extract_section(text, "PRIORITY MISCONCEPTION").splitlines()
    move = _extract_section(text, "TOMORROW'S MOVE").splitlines()
    follow_up = _extract_section(text, "FOLLOW-UP PROBLEMS").splitlines()

    parts = ["Previous co-pilot plan summary:"]
    if priority:
        parts.append(f"Priority misconception: {priority[0]}")
        if len(priority) > 1:
            parts.append(priority[1])
    if move:
        parts.append(f"Tomorrow's move: {move[0]}")
    if follow_up:
        parts.append(f"Follow-up problems: {follow_up[0]}")
    return "\n".join(parts)


def _turn_specific_instruction(message: str) -> str:
    msg = message.lower()

    if re.search(r"\b(new plan|regenerate plan|what should i do first|what do i do first|priority misconception)\b", msg):
        return "The teacher is explicitly asking for a plan. Use the full plan template."

    if re.search(r"\b(group|grouping|pair|pairs|small group)\b", msg):
        return (
            "The teacher is asking only about grouping. Return only a practical grouping routine for the named activity. "
            "Do not restate the plan or add other template sections."
        )

    if re.search(r"\b(analogy|metaphor|example to explain|different way to explain)\b", msg):
        return (
            "The teacher is asking for an explanation device. Return only the replacement analogy, script, or explanation they asked for. "
            "Do not append adjusted template sections unless explicitly requested."
        )

    if re.search(r"\b(worksheet|activity|task|exit ticket|do now|starter|board work|teacher script|discussion prompt)\b", msg):
        return (
            "The teacher is asking for a classroom artifact. Return the artifact directly in a practical format. "
            "Do not restate the old plan. Do not argue against the request."
        )

    if re.search(r"\b(recall|remember|memor|mnemonic|pattern|special angle|sine|cosine|trig values)\b", msg):
        return (
            "The teacher is asking for an explanatory strategy or memory structure. "
            "Build on the pattern they mention, explain the structure behind it, and avoid dismissing it as rote memorisation."
        )

    return "Answer the teacher's exact request directly and concisely. No full plan template."


def run_query(client, system_prompt, query):
    print(f"\nQUERY: {query}")
    print("-" * 60)
    response = client.models.generate_content(
        model=MODEL,
        contents=query,
        config=types.GenerateContentConfig(
            systemInstruction=f"{system_prompt}\n\nTURN-SPECIFIC INSTRUCTION:\n{_turn_specific_instruction(query)}",
            temperature=GENERATION_CONFIG.temperature,
        ),
    )
    print(response.text)
    print()
    return response.text


def run_conversation(client, system_prompt, turns):
    """Run a multi-turn conversation where each turn sees full history."""
    history = []
    for query in turns:
        print(f"\nTEACHER: {query}")
        print("-" * 60)

        contents = []
        for role, text in history:
            if role == "model":
                text = _compress_model_history(text)
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part(text=text)],
                )
            )
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=query)],
            )
        )

        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                systemInstruction=f"{system_prompt}\n\nTURN-SPECIFIC INSTRUCTION:\n{_turn_specific_instruction(query)}",
                temperature=GENERATION_CONFIG.temperature,
            ),
        )
        reply = response.text
        print(reply)
        print()

        history.append(("user", query))
        history.append(("model", reply))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=None, help="Run a single query")
    parser.add_argument("--all", action="store_true", help="Run all test queries independently")
    parser.add_argument("--convo", action="store_true", help="Run a multi-turn refinement conversation")
    parser.add_argument("--show-prompt", action="store_true", help="Print the system prompt and exit")
    args = parser.parse_args()

    system_prompt = build_system_prompt(SIMULATED_CLASS)

    if args.show_prompt:
        print(system_prompt)
        return

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    if args.convo:
        # Simulates a real teacher refining the plan across turns
        run_conversation(client, system_prompt, [
            "What should I do first with this class?",
            "That conveyor belt analogy won't work — suggest a completely different one with no moving objects or belts.",
            "good. how do I group students for that activity?",
        ])
    elif args.all:
        for q in TEST_QUERIES:
            run_query(client, system_prompt, q)
    elif args.query:
        run_query(client, system_prompt, args.query)
    else:
        run_query(client, system_prompt, TEST_QUERIES[0])


if __name__ == "__main__":
    main()
