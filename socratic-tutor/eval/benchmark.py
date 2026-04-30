"""
End-to-end benchmark runner for local Socratic tutor model selection.

Phase 1:
  Run the existing rule-based harness across a shortlist of models.

Phase 2:
  Take the top K models and run full multi-turn conversation simulations
  scored with a session-level tutoring rubric.

This script is designed for local Ollama testing on constrained hardware.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.harness import (
    OllamaBackend,
    OpenAICompatBackend,
    SAMPLE_PROFILES,
    SCENARIOS,
    STATIC_PROMPT,
    run_eval,
)
from prompts.context_builder import build_from_diagnostic


DEFAULT_MODELS = [
    "qwen3:8b",
    "qwen2.5:7b",
    "llama3.1:8b",
    "mistral:7b",
    "gemma2:9b",
    "gemma3:4b",
    "phi3.5",
    "llama3.2:3b",
    "qwen2.5:14b",
    "gemma3:12b",
]

WARM_WORDS = [
    "okay", "alright", "i know", "i understand", "that's okay", "no worries",
    "let's try", "we can", "together", "good try", "nice try", "i see",
]
REASONING_WORDS = [
    "why", "how", "what makes", "tell me", "explain", "what do you notice",
    "what do you think", "can you show",
]
CONCRETE_WORDS = [
    "pizza", "roti", "chocolate", "water", "pipe", "battery", "bulb", "flashlight",
    "slide", "cookie", "pieces", "share", "cut", "picture", "imagine",
]
OFF_TOPIC_HELP_WORDS = [
    "capital of", "here's how to do your history", "sure, i can help with history",
    "let's do geography", "here is a joke", "my name is",
]
BAD_CONFIRM_WORDS = [
    "that's correct", "that's right", "you're right", "correct!", "well done",
    "exactly", "perfect",
]
WRONG_WORDS = [
    " wrong", "incorrect", "that's not right", "you are mistaken", "you're mistaken",
]


FULL_CONVERSATION_CASES = [
    {
        "id": "fractions_wrong_then_progress",
        "subject": "fractions",
        "topic_keywords": ["fraction", "denominator", "numerator", "piece", "same size", "equal parts"],
        "misconception_keywords": ["same size", "equal parts", "piece", "denominator", "common"],
        "forbidden_answers": ["7/12", "seven twelfths"],
        "turns": [
            {"student": "I think 1/3 + 1/4 = 2/7", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "because I added the top and bottom", "tags": ["needs_reasoning"]},
            {"student": "I still don't get why that is bad", "tags": ["confused"]},
            {"student": "oh because the pieces are different sizes?", "tags": ["short_answer", "progress"]},
            {"student": "so I need the same denominator?", "tags": ["short_answer", "progress"]},
        ],
    },
    {
        "id": "fractions_frustrated",
        "subject": "fractions",
        "topic_keywords": ["fraction", "denominator", "numerator", "piece", "same size", "equal parts"],
        "misconception_keywords": ["same size", "equal parts", "piece", "denominator", "common"],
        "forbidden_answers": ["7/12", "seven twelfths"],
        "turns": [
            {"student": "just tell me the answer", "tags": ["demand_answer", "frustrated"]},
            {"student": "I hate fractions", "tags": ["frustrated"]},
            {"student": "fine, 2/7", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "idk", "tags": ["confused", "short_answer"]},
            {"student": "maybe because the denominator tells the piece size?", "tags": ["progress"]},
        ],
    },
    {
        "id": "electricity_ohms_law",
        "subject": "electricity",
        "topic_keywords": ["voltage", "current", "resistance", "battery", "wire", "push", "flow"],
        "misconception_keywords": ["voltage", "current", "resistance", "push", "flow", "battery"],
        "forbidden_answers": ["20v", "20 v"],
        "turns": [
            {"student": "A resistor has 10 ohms and current is 2 amps. I don't know what to do", "tags": ["confused"]},
            {"student": "is voltage the same as current?", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "I am confused again", "tags": ["confused"]},
            {"student": "so voltage is like the push and current is the flow?", "tags": ["short_answer", "progress"]},
            {"student": "then maybe I use V=IR?", "tags": ["short_answer", "progress"]},
        ],
    },
    {
        "id": "electricity_series_current",
        "subject": "electricity",
        "topic_keywords": ["series", "current", "circuit", "battery", "flow", "same", "bulb"],
        "misconception_keywords": ["series", "same current", "flow", "circuit", "used up"],
        "forbidden_answers": [],
        "turns": [
            {"student": "I think current gets used up in a series circuit", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "because the first bulb takes some", "tags": ["needs_reasoning"]},
            {"student": "wait then why does the second bulb still light?", "tags": ["confused"]},
            {"student": "so the flow is the same all around?", "tags": ["short_answer", "progress"]},
            {"student": "is voltage the thing that changes instead?", "tags": ["short_answer", "progress"]},
        ],
    },
    {
        "id": "motion_force_needed",
        "subject": "motion",
        "topic_keywords": ["force", "motion", "friction", "push", "speed", "constant", "net force"],
        "misconception_keywords": ["friction", "force", "motion", "constant", "net force", "push"],
        "forbidden_answers": [],
        "turns": [
            {"student": "objects need force to keep moving", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "because things stop when we stop pushing", "tags": ["needs_reasoning"]},
            {"student": "I don't get it", "tags": ["confused"]},
            {"student": "is friction the reason real things slow down?", "tags": ["short_answer", "progress"]},
            {"student": "so no net force is needed for constant speed?", "tags": ["short_answer", "progress"]},
        ],
    },
    {
        "id": "motion_frustrated",
        "subject": "motion",
        "topic_keywords": ["force", "motion", "friction", "push", "speed", "constant", "net force"],
        "misconception_keywords": ["friction", "force", "motion", "constant", "net force", "push"],
        "forbidden_answers": [],
        "turns": [
            {"student": "this is stupid just tell me", "tags": ["frustrated", "demand_answer"]},
            {"student": "fine then a force is always needed", "tags": ["wrong_answer", "frustrated"]},
            {"student": "whatever", "tags": ["frustrated", "short_answer"]},
            {"student": "okay maybe friction is confusing me", "tags": ["progress"]},
            {"student": "can we try one simpler example?", "tags": ["confused"]},
        ],
    },
    {
        "id": "circles_formula_mixup",
        "subject": "circles",
        "topic_keywords": ["circle", "radius", "diameter", "area", "circumference", "around", "inside"],
        "misconception_keywords": ["area", "circumference", "inside", "around", "radius", "diameter"],
        "forbidden_answers": [],
        "turns": [
            {"student": "I use pi r squared for circumference", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "because both are about circles", "tags": ["needs_reasoning"]},
            {"student": "I am confused about inside versus around", "tags": ["confused"]},
            {"student": "so area is inside and circumference is around?", "tags": ["short_answer", "progress"]},
            {"student": "then the formulas are different because they measure different things?", "tags": ["progress"]},
        ],
    },
    {
        "id": "circles_radius_diameter",
        "subject": "circles",
        "topic_keywords": ["circle", "radius", "diameter", "center", "edge", "across"],
        "misconception_keywords": ["radius", "diameter", "center", "edge", "across"],
        "forbidden_answers": [],
        "turns": [
            {"student": "radius and diameter are basically the same", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "they both go across the circle", "tags": ["needs_reasoning"]},
            {"student": "what is the exact difference", "tags": ["confused"]},
            {"student": "oh radius is center to edge?", "tags": ["short_answer", "progress"]},
            {"student": "and diameter is edge to edge through the center?", "tags": ["progress"]},
        ],
    },
    {
        "id": "lines_angles_offtopic",
        "subject": "lines_angles",
        "topic_keywords": ["angle", "parallel", "line", "interior", "supplementary", "equal"],
        "misconception_keywords": ["parallel", "interior", "supplementary", "equal", "angle"],
        "forbidden_answers": [],
        "turns": [
            {"student": "can you help with history instead", "tags": ["off_topic"]},
            {"student": "fine then all angles on parallel lines are equal", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "I don't see why co interior angles are different", "tags": ["confused"]},
            {"student": "so some are equal but some add to 180?", "tags": ["short_answer", "progress"]},
            {"student": "that depends on which angle pair it is?", "tags": ["progress"]},
        ],
    },
    {
        "id": "lines_angles_short_answers",
        "subject": "lines_angles",
        "topic_keywords": ["angle", "parallel", "line", "interior", "supplementary", "equal"],
        "misconception_keywords": ["parallel", "interior", "supplementary", "equal", "angle"],
        "forbidden_answers": [],
        "turns": [
            {"student": "vertical angles are supplementary", "tags": ["wrong_answer", "needs_reasoning"]},
            {"student": "yes", "tags": ["short_answer", "needs_reasoning"]},
            {"student": "idk", "tags": ["confused", "short_answer"]},
            {"student": "wait they are opposite not next to each other", "tags": ["progress"]},
            {"student": "so maybe equal not supplementary?", "tags": ["progress"]},
        ],
    },
]


def build_system_prompt(subject):
    profile = SAMPLE_PROFILES[subject]
    diagnostic_context = build_from_diagnostic(
        student_data=profile["student_data"],
        all_misconceptions=profile["misconceptions"],
        all_patterns=profile["patterns"],
        test=profile["test"],
    )
    return STATIC_PROMPT + "\n\n" + diagnostic_context


def count_questions(text):
    return len(re.findall(r"\?", text))


def word_count(text):
    return len(text.split())


def has_any(text, phrases):
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def run_full_conversation(backend, case, verbose=False):
    messages = [{"role": "system", "content": build_system_prompt(case["subject"])}]
    turns = []

    for turn in case["turns"]:
        messages.append({"role": "user", "content": turn["student"]})
        started = time.time()
        response = backend.chat(messages)
        latency = round(time.time() - started, 2)
        messages.append({"role": "assistant", "content": response})
        turns.append({
            "student": turn["student"],
            "tags": turn["tags"],
            "assistant": response,
            "latency_seconds": latency,
            "assistant_words": word_count(response),
            "question_count": count_questions(response),
        })
        if verbose:
            print(f"    student: {turn['student']}")
            print(f"    tutor:   {response}")

    return {
        "case_id": case["id"],
        "subject": case["subject"],
        "turns": turns,
    }


def score_full_conversation(case, convo):
    metric_stats = {
        "rule_adherence": {"pass": 0, "total": 0},
        "question_quality": {"pass": 0, "total": 0},
        "misconception_targeting": {"pass": 0, "total": 0},
        "confusion_recovery": {"pass": 0, "total": 0},
        "frustration_handling": {"pass": 0, "total": 0},
        "off_topic_redirect": {"pass": 0, "total": 0},
        "conciseness": {"pass": 0, "total": 0},
    }
    turn_notes = []
    avg_latency = round(
        sum(t["latency_seconds"] for t in convo["turns"]) / len(convo["turns"]), 2
    ) if convo["turns"] else 0

    for turn in convo["turns"]:
        response = turn["assistant"]
        response_lower = response.lower()
        tags = set(turn["tags"])

        rule_ok = True
        if case["forbidden_answers"] and has_any(response, case["forbidden_answers"]):
            rule_ok = False
        if has_any(response, WRONG_WORDS):
            rule_ok = False
        if "short_answer" in tags and has_any(response, BAD_CONFIRM_WORDS):
            rule_ok = False
        metric_stats["rule_adherence"]["total"] += 1
        metric_stats["rule_adherence"]["pass"] += int(rule_ok)

        concise = turn["assistant_words"] <= 95
        metric_stats["conciseness"]["total"] += 1
        metric_stats["conciseness"]["pass"] += int(concise)

        needs_reasoning = "needs_reasoning" in tags or "short_answer" in tags or "wrong_answer" in tags
        if needs_reasoning:
            q_quality = turn["question_count"] == 1 and has_any(response, REASONING_WORDS)
            metric_stats["question_quality"]["total"] += 1
            metric_stats["question_quality"]["pass"] += int(q_quality)

        targeting = has_any(response, case["misconception_keywords"]) or has_any(response, case["topic_keywords"])
        metric_stats["misconception_targeting"]["total"] += 1
        metric_stats["misconception_targeting"]["pass"] += int(targeting)

        if "confused" in tags:
            confusion_ok = (
                turn["question_count"] <= 1
                and (has_any(response, CONCRETE_WORDS) or has_any(response, case["topic_keywords"]))
                and turn["assistant_words"] <= 120
            )
            metric_stats["confusion_recovery"]["total"] += 1
            metric_stats["confusion_recovery"]["pass"] += int(confusion_ok)

        if "frustrated" in tags:
            frustration_ok = has_any(response, WARM_WORDS) and turn["question_count"] <= 1
            metric_stats["frustration_handling"]["total"] += 1
            metric_stats["frustration_handling"]["pass"] += int(frustration_ok)

        if "off_topic" in tags:
            redirect_ok = not has_any(response, OFF_TOPIC_HELP_WORDS) and has_any(response, case["topic_keywords"])
            metric_stats["off_topic_redirect"]["total"] += 1
            metric_stats["off_topic_redirect"]["pass"] += int(redirect_ok)

        turn_notes.append({
            "student": turn["student"],
            "assistant_preview": response[:180],
            "question_count": turn["question_count"],
            "assistant_words": turn["assistant_words"],
            "latency_seconds": turn["latency_seconds"],
        })

    metric_scores = {}
    for name, stat in metric_stats.items():
        if stat["total"] == 0:
            metric_scores[name] = None
        else:
            metric_scores[name] = round(stat["pass"] / stat["total"] * 100, 1)

    weights = {
        "rule_adherence": 0.30,
        "question_quality": 0.20,
        "misconception_targeting": 0.20,
        "confusion_recovery": 0.10,
        "frustration_handling": 0.10,
        "off_topic_redirect": 0.05,
        "conciseness": 0.05,
    }
    weighted_total = 0.0
    weight_sum = 0.0
    for name, weight in weights.items():
        if metric_scores[name] is not None:
            weighted_total += metric_scores[name] * weight
            weight_sum += weight
    total_score = round(weighted_total / weight_sum, 1) if weight_sum else 0.0

    return {
        "case_id": convo["case_id"],
        "subject": convo["subject"],
        "total_score": total_score,
        "avg_latency_seconds": avg_latency,
        "metric_scores": metric_scores,
        "turn_notes": turn_notes,
    }


def summarize_rule_results(model, results):
    total = len(results)
    passed = sum(1 for r in results if r["score"]["pass"])
    avg_latency = round(sum(r["latency_seconds"] for r in results) / total, 2) if total else 0
    errored = sum(1 for r in results if str(r["response"]).startswith("ERROR:"))
    critical_rule1_failures = sum(
        1 for r in results if str(r["rule_tested"]) == "1" and not r["score"]["pass"]
    )
    return {
        "model": model,
        "passed": passed,
        "total": total,
        "score_pct": round(passed / total * 100, 1) if total else 0.0,
        "avg_latency_seconds": avg_latency,
        "errored_scenarios": errored,
        "valid_run": errored == 0,
        "critical_rule1_failures": critical_rule1_failures,
    }


def summarize_full_results(model, case_results):
    avg_score = round(sum(r["total_score"] for r in case_results) / len(case_results), 1)
    avg_latency = round(sum(r["avg_latency_seconds"] for r in case_results) / len(case_results), 2)
    metric_rollup = {}
    for name in [
        "rule_adherence",
        "question_quality",
        "misconception_targeting",
        "confusion_recovery",
        "frustration_handling",
        "off_topic_redirect",
        "conciseness",
    ]:
        vals = [r["metric_scores"][name] for r in case_results if r["metric_scores"][name] is not None]
        metric_rollup[name] = round(sum(vals) / len(vals), 1) if vals else None
    return {
        "model": model,
        "avg_score": avg_score,
        "avg_latency_seconds": avg_latency,
        "metrics": metric_rollup,
    }


def print_rule_table(summaries):
    print("\n" + "=" * 88)
    print("PHASE 1 — RULE HARNESS")
    print("=" * 88)
    print(
        f"{'Model':<18} {'Pass':<10} {'Score':<10} {'Errors':<10} "
        f"{'Rule1 Fail':<12} {'Avg Latency':<12}"
    )
    print("-" * 88)
    for s in summaries:
        print(
            f"{s['model']:<18} {str(s['passed']) + '/' + str(s['total']):<10} "
            f"{str(s['score_pct']) + '%':<10} {s['errored_scenarios']:<10} "
            f"{s['critical_rule1_failures']:<12} {str(s['avg_latency_seconds']) + 's':<12}"
        )


def pull_model(model):
    print(f"\nPulling missing model: {model}")
    result = subprocess.run(
        ["ollama", "pull", model],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(f"  Pulled {model}")
        return True

    print(f"  Failed to pull {model}")
    if result.stderr.strip():
        print(f"  stderr: {result.stderr.strip()}")
    elif result.stdout.strip():
        print(f"  stdout: {result.stdout.strip()}")
    return False


def remove_model(model):
    print(f"\nRemoving local model: {model}")
    result = subprocess.run(
        ["ollama", "rm", model],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(f"  Removed {model}")
        return True

    print(f"  Failed to remove {model}")
    if result.stderr.strip():
        print(f"  stderr: {result.stderr.strip()}")
    elif result.stdout.strip():
        print(f"  stdout: {result.stdout.strip()}")
    return False


def sync_missing_models(models, available_models, pull_missing):
    missing = [m for m in models if m not in available_models]
    if not missing:
        return models, []

    print("Missing local Ollama models:")
    for model in missing:
        print(f"  - {model}")

    if not pull_missing:
        print("Skipping missing models. Re-run with --pull-missing to fetch them before benchmarking.\n")
        runnable = [m for m in models if m in available_models]
        return runnable, missing

    pulled = []
    for model in missing:
        if pull_model(model):
            pulled.append(model)

    runnable = [m for m in models if m in available_models or m in pulled]
    still_missing = [m for m in models if m not in runnable]
    if still_missing:
        print("\nThese models are still unavailable and will be skipped:")
        for model in still_missing:
            print(f"  - {model}")
        print()
    return runnable, still_missing


def prune_models(models_to_remove, enabled):
    if not enabled:
        if models_to_remove:
            print("\nPrune candidates:")
            for model in models_to_remove:
                print(f"  - {model}")
            print("Re-run with --prune to remove them from local Ollama storage.")
        return []

    removed = []
    for model in models_to_remove:
        if remove_model(model):
            removed.append(model)
    return removed


def print_full_table(summaries):
    print("\n" + "=" * 88)
    print("PHASE 2 — FULL CONVERSATION RUBRIC")
    print("=" * 88)
    print(f"{'Model':<18} {'Avg Score':<12} {'Avg Latency':<12} {'Rule':<8} {'Q Qual':<8} {'Target':<8}")
    print("-" * 88)
    for s in summaries:
        metrics = s["metrics"]
        print(
            f"{s['model']:<18} {str(s['avg_score']) + '%':<12} "
            f"{str(s['avg_latency_seconds']) + 's':<12} "
            f"{str(metrics['rule_adherence']) + '%':<8} "
            f"{str(metrics['question_quality']) + '%':<8} "
            f"{str(metrics['misconception_targeting']) + '%':<8}"
        )


def make_backend(args, model):
    if args.endpoint == "ollama":
        return OllamaBackend(model, args.base_url)
    return OpenAICompatBackend(model, args.base_url, args.api_key)


def main():
    parser = argparse.ArgumentParser(description="Two-phase benchmark for local tutor model selection")
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="Comma-separated model list to benchmark",
    )
    parser.add_argument("--top-k", type=int, default=5, help="How many models advance to phase 2")
    parser.add_argument("--endpoint", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--output", help="Save full benchmark results to JSON")
    parser.add_argument("--verbose", action="store_true", help="Print full conversation turns")
    parser.add_argument(
        "--pull-missing",
        action="store_true",
        help="Automatically `ollama pull` models that are not present locally before benchmarking",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="After benchmarking, remove local models that fail the prune rules",
    )
    parser.add_argument(
        "--prune-below-phase1",
        type=float,
        default=50.0,
        help="Prune models scoring below this phase 1 percentage",
    )
    parser.add_argument(
        "--prune-invalid",
        action="store_true",
        help="Prune models that returned infra/runtime ERROR responses during phase 1",
    )
    parser.add_argument(
        "--prune-non-finalists",
        action="store_true",
        help="Prune models that do not advance to phase 2",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    timestamp = datetime.now().isoformat()
    skipped_missing = []

    if args.endpoint == "ollama":
        availability_backend = OllamaBackend(models[0], args.base_url)
        if not availability_backend.is_available():
            raise SystemExit(
                f"Ollama is not reachable at {args.base_url}. Start it with `ollama serve`."
            )
        available_models = set(availability_backend.list_models())
        models, skipped_missing = sync_missing_models(models, available_models, args.pull_missing)
        if not models:
            raise SystemExit("No local models available to benchmark.")
    elif not args.api_key:
        raise SystemExit("Provide --api-key for OpenAI-compatible benchmarking.")

    fractions_prompt = build_system_prompt("fractions")
    all_rule_results = {}
    rule_summaries = []

    for model in models:
        print(f"\nRunning rule harness for {model}")
        backend = make_backend(args, model)
        results = run_eval(backend, SCENARIOS, system_prompt=fractions_prompt, verbose=False, full=False)
        all_rule_results[model] = results
        rule_summaries.append(summarize_rule_results(model, results))

    rule_summaries.sort(
        key=lambda s: (
            not s["valid_run"],
            s["critical_rule1_failures"],
            -s["score_pct"],
            s["avg_latency_seconds"],
        )
    )
    print_rule_table(rule_summaries)

    valid_rule_summaries = [s for s in rule_summaries if s["valid_run"]]
    invalid_rule_summaries = [s for s in rule_summaries if not s["valid_run"]]
    if invalid_rule_summaries:
        print("\nSkipping invalid phase 1 runs from phase 2 ranking:")
        for summary in invalid_rule_summaries:
            print(
                f"  - {summary['model']} "
                f"({summary['errored_scenarios']} error scenario(s))"
            )

    finalists = [s["model"] for s in valid_rule_summaries if s["critical_rule1_failures"] == 0][:args.top_k]
    if len(finalists) < args.top_k:
        for s in valid_rule_summaries:
            if s["model"] not in finalists:
                finalists.append(s["model"])
            if len(finalists) == args.top_k:
                break

    if finalists:
        print("\nAdvancing to phase 2:")
        for model in finalists:
            print(f"  - {model}")
    else:
        print("\nNo valid phase 1 models advanced to phase 2.")

    all_full_results = {}
    full_summaries = []

    for model in finalists:
        print(f"\nRunning full conversations for {model}")
        backend = make_backend(args, model)
        case_results = []
        for case in FULL_CONVERSATION_CASES:
            print(f"  Case: {case['id']}")
            convo = run_full_conversation(backend, case, verbose=args.verbose)
            case_results.append(score_full_conversation(case, convo))
        all_full_results[model] = case_results
        full_summaries.append(summarize_full_results(model, case_results))

    full_summaries.sort(key=lambda s: (-s["avg_score"], s["avg_latency_seconds"]))
    print_full_table(full_summaries)

    if full_summaries:
        winner = full_summaries[0]
        print("\nRecommended winner:")
        print(
            f"  {winner['model']} — {winner['avg_score']}% session score, "
            f"{winner['avg_latency_seconds']}s avg latency"
        )

    prune_candidates = set()
    if args.endpoint == "ollama":
        for summary in rule_summaries:
            if summary["score_pct"] < args.prune_below_phase1:
                prune_candidates.add(summary["model"])
            if args.prune_invalid and not summary["valid_run"]:
                prune_candidates.add(summary["model"])
        if args.prune_non_finalists:
            prune_candidates.update(m for m in models if m not in finalists)
        removed_models = prune_models(sorted(prune_candidates), args.prune)
    else:
        removed_models = []

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(
                {
                    "timestamp": timestamp,
                    "models": models,
                    "skipped_missing_models": skipped_missing,
                    "rule_summaries": rule_summaries,
                    "full_summaries": full_summaries,
                    "rule_results": all_rule_results,
                    "full_results": all_full_results,
                    "prune_candidates": sorted(prune_candidates) if args.endpoint == "ollama" else [],
                    "removed_models": removed_models,
                },
                f,
                indent=2,
            )
        print(f"\nSaved benchmark results to {args.output}")


if __name__ == "__main__":
    main()
