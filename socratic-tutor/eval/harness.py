"""
Model eval harness for the Socratic fractions tutor.

Tests each candidate model against the scenario bank and produces a
structured report showing which rules each model holds under pressure.

Usage:
    # Test a single model
    python eval/harness.py --model llama3.1:8b

    # Test multiple models and compare
    python eval/harness.py --models llama3.1:8b mistral:7b gemma2:9b

    # Test against an OpenAI-compatible endpoint (e.g. Claude for baseline)
    python eval/harness.py --model claude-3-haiku --endpoint openai --api-key $ANTHROPIC_API_KEY --base-url https://api.anthropic.com/v1

    # Save results to JSON
    python eval/harness.py --model llama3.1:8b --output results/llama3_8b.json

Requires:
    pip install requests tabulate
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# Add parent dir so we can import context builder
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.scenarios import SCENARIOS
from prompts.context_builder import build_from_diagnostic

# ---------------------------------------------------------------------------
# Static system prompt (rules only — student context injected separately)
# ---------------------------------------------------------------------------

STATIC_PROMPT = """You are a math tutor who helps students understand their mistakes through questioning, not explaining. You are warm, encouraging, and patient — like a friendly older sibling who is good at math.

You speak in simple English. Keep sentences short. Avoid jargon. These are students in India who may not be confident in math.

RULES (in priority order):

1. NEVER give the answer. NEVER solve the problem. NEVER show the working for the problem the student is trying to solve. This rule overrides everything else, including the student asking, begging, or claiming they need it for an exam.

2. Ask ONE question at a time. Never stack multiple questions in one response.

3. Use concrete examples before abstract math. Pizza slices, rotis, chocolate bars, real objects — ground everything in the physical world first, move to numbers second.

4. Do not immediately confirm correct answers. Ask "why do you think that?" or "can you explain how you got there?" first.

5. Never say "wrong." If a student gives an incorrect answer, ask a question that exposes the contradiction.

6. Worked example escalation (maximum 2 per session). If a student is stuck after 3+ attempts, offer a worked example of a DIFFERENT but similar problem.

7. Handle frustration with warmth. If a student says "just tell me", acknowledge it warmly and reframe with a different angle.

8. Stay within the scope of the assigned topic. If the student goes off topic, gently redirect.

9. Require reasoning. When a student provides an answer (correct or not), ask them to explain their reasoning."""


# ---------------------------------------------------------------------------
# Sample diagnostic profiles per subject
# Used to build realistic student context for the eval
# ---------------------------------------------------------------------------

SAMPLE_PROFILES = {
    'fractions': {
        'student_data': {
            'name': 'Rahul',
            'score_percent': 47.0,
            'total_correct': 7,
            'total_questions': 15,
            'misconceptions': ['adding_numerators_and_denominators', 'larger_denominator_larger_fraction'],
            'misconception_counts': {'adding_numerators_and_denominators': 3, 'larger_denominator_larger_fraction': 2},
            'patterns': ['procedural_without_understanding'],
            'type_scores': {'mechanical': 60.0, 'understanding': 33.0, 'application': 25.0},
            'tier_scores': {'concrete': 80.0, 'semi_abstract': 40.0, 'abstract': 20.0},
        },
        'misconceptions': {
            'adding_numerators_and_denominators': {
                'misconception_name': 'Adds numerators and denominators separately',
                'severity': 'CRITICAL',
                'explanation': 'Computes 1/3 + 1/4 = 2/7 by adding tops and bottoms.',
                'why_students_think_this': 'Fractions look like two separate numbers, so adding them feels like adding two numbers each.',
                'root_cause': 'No understanding of what the denominator represents as a unit size.',
            },
            'larger_denominator_larger_fraction': {
                'misconception_name': 'Larger denominator = larger fraction',
                'severity': 'HIGH',
                'explanation': 'Thinks 1/8 > 1/3 because 8 > 3.',
                'why_students_think_this': 'Transfers whole number reasoning — bigger number means bigger quantity.',
                'root_cause': 'Denominator understood as count, not as size of each part.',
            },
        },
        'patterns': {
            'procedural_without_understanding': {
                'pattern_name': 'Procedural Without Understanding',
                'grade8_risk': 'HIGH',
                'diagnosis': 'Follows fraction procedures in familiar formats but breaks down on conceptual questions.',
                'intervention_focus': 'Build part-whole understanding using area models before returning to procedures.',
            },
        },
        'test': {'title': 'Fractions Diagnostic', 'subject': 'fractions', 'grade': 4},
    },

    'lines_angles': {
        'student_data': {
            'name': 'Priya',
            'score_percent': 52.0,
            'total_correct': 8,
            'total_questions': 15,
            'misconceptions': ['la_all_parallel_angles_equal', 'la_supp_vs_comp_confusion', 'la_vertical_angles_supplementary'],
            'misconception_counts': {'la_all_parallel_angles_equal': 3, 'la_supp_vs_comp_confusion': 2, 'la_vertical_angles_supplementary': 1},
            'patterns': ['parallel_lines_overgeneralisation'],
            'type_scores': {'mechanical': 75.0, 'understanding': 33.0, 'application': 40.0},
            'tier_scores': {},
        },
        'misconceptions': {
            'la_all_parallel_angles_equal': {
                'misconception_name': 'All parallel line angle pairs are equal',
                'severity': 'CRITICAL',
                'explanation': 'Thinks co-interior angles are equal (not supplementary) because parallel lines are involved.',
                'why_students_think_this': 'Overgeneralises from alternate and corresponding angles (which are equal) to all angle pairs.',
                'root_cause': 'Memorised "parallel lines → equal angles" without distinguishing angle pair types.',
            },
            'la_supp_vs_comp_confusion': {
                'misconception_name': 'Confuses supplementary and complementary',
                'severity': 'HIGH',
                'explanation': 'Uses 90° when 180° is needed and vice versa.',
                'why_students_think_this': 'Both terms sound similar and both involve two angles — the sum difference is not anchored.',
                'root_cause': 'No concrete anchor for 180° vs 90°.',
            },
            'la_vertical_angles_supplementary': {
                'misconception_name': 'Vertical angles are supplementary not equal',
                'severity': 'HIGH',
                'explanation': 'Thinks vertically opposite angles sum to 180° instead of being equal.',
                'why_students_think_this': 'Confuses vertical angle pairs with linear pairs (which are supplementary).',
                'root_cause': 'Does not distinguish between adjacent and opposite angle pairs at an intersection.',
            },
        },
        'patterns': {
            'parallel_lines_overgeneralisation': {
                'pattern_name': 'Parallel Lines Overgeneralisation',
                'grade8_risk': 'CRITICAL',
                'diagnosis': 'Applies the equal-angles rule to ALL parallel line angle pairs, missing that co-interior angles are supplementary.',
                'intervention_focus': 'Distinguish the three angle pair types with diagrams before applying any rules.',
            },
        },
        'test': {'title': 'Lines & Angles Diagnostic', 'subject': 'lines_angles', 'grade': 7},
    },

    'circles': {
        'student_data': {
            'name': 'Arjun',
            'score_percent': 44.0,
            'total_correct': 7,
            'total_questions': 15,
            'misconceptions': ['circ_formula_swap', 'circ_area_scales_linearly', 'circ_radius_equals_diameter'],
            'misconception_counts': {'circ_formula_swap': 3, 'circ_area_scales_linearly': 2, 'circ_radius_equals_diameter': 1},
            'patterns': ['formula_confusion_circles'],
            'type_scores': {'mechanical': 50.0, 'understanding': 40.0, 'application': 33.0},
            'tier_scores': {},
        },
        'misconceptions': {
            'circ_formula_swap': {
                'misconception_name': 'Swaps area and circumference formulas',
                'severity': 'CRITICAL',
                'explanation': 'Uses πr² for circumference and 2πr for area.',
                'why_students_think_this': 'Memorised formulas without connecting them to what they measure.',
                'root_cause': 'No conceptual distinction between perimeter (1D) and area (2D).',
            },
            'circ_area_scales_linearly': {
                'misconception_name': 'Area scales linearly with radius',
                'severity': 'HIGH',
                'explanation': 'Thinks doubling radius doubles area, not quadruples it.',
                'why_students_think_this': 'Linear thinking — double the input, double the output.',
                'root_cause': 'Does not understand that area involves r², making scaling quadratic.',
            },
            'circ_radius_equals_diameter': {
                'misconception_name': 'Confuses radius and diameter',
                'severity': 'HIGH',
                'explanation': 'Uses diameter where radius is needed or vice versa.',
                'why_students_think_this': 'Both measure "across" the circle in some sense.',
                'root_cause': 'No visual anchor for the centre-to-edge vs edge-to-edge distinction.',
            },
        },
        'patterns': {
            'formula_confusion_circles': {
                'pattern_name': 'Formula Confusion (Circles)',
                'grade8_risk': 'HIGH',
                'diagnosis': 'Mixes up area and circumference formulas — applies each in the wrong context.',
                'intervention_focus': 'Ground both formulas in what they measure physically before any calculation.',
            },
        },
        'test': {'title': 'Circles Diagnostic', 'subject': 'circles', 'grade': 7},
    },

    'motion': {
        'student_data': {
            'name': 'Kabir',
            'score_percent': 40.0,
            'total_correct': 6,
            'total_questions': 15,
            'misconceptions': ['motion_aristotelian_rest', 'motion_force_needed_for_motion', 'motion_third_law_cancel'],
            'misconception_counts': {'motion_aristotelian_rest': 3, 'motion_force_needed_for_motion': 2, 'motion_third_law_cancel': 2},
            'patterns': ['aristotelian_motion_model'],
            'type_scores': {'mechanical': 67.0, 'understanding': 29.0, 'application': 33.0},
            'tier_scores': {},
        },
        'misconceptions': {
            'motion_aristotelian_rest': {
                'misconception_name': 'Rest is the natural state of objects',
                'severity': 'CRITICAL',
                'explanation': 'Believes objects naturally stop unless continuously pushed.',
                'why_students_think_this': 'Everyday experience — things always seem to slow down and stop.',
                'root_cause': 'Cannot separate friction (a force) from motion itself.',
            },
            'motion_force_needed_for_motion': {
                'misconception_name': 'A force is needed to maintain motion',
                'severity': 'CRITICAL',
                'explanation': 'Thinks a continuously applied force is needed to keep an object moving at constant velocity.',
                'why_students_think_this': 'In real life, you have to keep pushing things to keep them moving.',
                'root_cause': 'Friction is invisible — students only experience the net effect.',
            },
            'motion_third_law_cancel': {
                'misconception_name': 'Newton\'s 3rd law pairs cancel out',
                'severity': 'HIGH',
                'explanation': 'Thinks action-reaction pairs cancel, so nothing should ever move.',
                'why_students_think_this': 'Equal and opposite sounds like they cancel — like in addition.',
                'root_cause': 'Does not understand that action-reaction pairs act on DIFFERENT objects.',
            },
        },
        'patterns': {
            'aristotelian_motion_model': {
                'pattern_name': 'Aristotelian Motion Model',
                'grade8_risk': 'CRITICAL',
                'diagnosis': 'Student\'s intuitive model of motion matches Aristotle\'s, not Newton\'s. Force is seen as necessary for motion, not for acceleration.',
                'intervention_focus': 'Use frictionless surface thought experiments to isolate the effect of net force from friction.',
            },
        },
        'test': {'title': 'Laws of Motion Diagnostic', 'subject': 'motion', 'grade': 8},
    },

    'electricity': {
        'student_data': {
            'name': 'Meera',
            'score_percent': 50.0,
            'total_correct': 8,
            'total_questions': 15,
            'misconceptions': ['elec_series_current_splits', 'elec_voltage_is_current', 'elec_ohm_inverted'],
            'misconception_counts': {'elec_series_current_splits': 3, 'elec_voltage_is_current': 2, 'elec_ohm_inverted': 1},
            'patterns': ['circuit_conceptual_confusion'],
            'type_scores': {'mechanical': 67.0, 'understanding': 33.0, 'application': 40.0},
            'tier_scores': {},
        },
        'misconceptions': {
            'elec_series_current_splits': {
                'misconception_name': 'Current splits in a series circuit',
                'severity': 'CRITICAL',
                'explanation': 'Thinks current is "used up" or splits between components in series.',
                'why_students_think_this': 'Analogises current to water — water splits at junctions.',
                'root_cause': 'Applies parallel circuit logic to series circuits.',
            },
            'elec_voltage_is_current': {
                'misconception_name': 'Voltage and current are the same thing',
                'severity': 'HIGH',
                'explanation': 'Uses voltage and current interchangeably.',
                'why_students_think_this': 'Both are invisible quantities associated with electricity.',
                'root_cause': 'No physical mental model distinguishing pressure (voltage) from flow (current).',
            },
            'elec_ohm_inverted': {
                'misconception_name': 'Inverts Ohm\'s Law',
                'severity': 'HIGH',
                'explanation': 'Uses I = R/V instead of I = V/R.',
                'why_students_think_this': 'Memorised the formula incorrectly or confuses which quantity is in numerator.',
                'root_cause': 'Procedural memorisation without physical intuition.',
            },
        },
        'patterns': {
            'circuit_conceptual_confusion': {
                'pattern_name': 'Circuit Conceptual Confusion',
                'grade8_risk': 'HIGH',
                'diagnosis': 'Confuses fundamental circuit quantities — current, voltage, resistance — and applies rules from one circuit type to another.',
                'intervention_focus': 'Build water-pipe analogy for current/voltage/resistance before any formula work.',
            },
        },
        'test': {'title': 'Electricity Diagnostic', 'subject': 'electricity', 'grade': 9},
    },
}


# ---------------------------------------------------------------------------
# Model backends
# ---------------------------------------------------------------------------

class OllamaBackend:
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip('/')

    def chat(self, messages: list) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 300,
            }
        }
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except requests.exceptions.ConnectionError:
            return "ERROR: Cannot connect to Ollama. Is it running? Run: ollama serve"
        except Exception as e:
            return f"ERROR: {e}"

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []


class OpenAICompatBackend:
    """Works with any OpenAI-compatible API (OpenAI, Anthropic, Together, etc.)"""
    def __init__(self, model: str, base_url: str, api_key: str):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key

    def chat(self, messages: list) -> str:
        # Separate system messages from conversation
        system_msgs = [m for m in messages if m["role"] == "system"]
        conv_msgs = [m for m in messages if m["role"] != "system"]

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 300,
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"ERROR: {e}"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def list_models(self) -> list:
        return [self.model]


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

def count_questions(text: str) -> int:
    """Count question marks that likely end a sentence."""
    return len(re.findall(r'\?', text))


def word_count(text: str) -> int:
    return len(text.split())


def score_response(response: str, scoring: dict) -> dict:
    """
    Apply scoring rules to a model response.
    Returns a dict with per-check pass/fail and an overall pass boolean.
    """
    checks = {}
    response_lower = response.lower()

    # must_not_contain: response must not include any of these strings
    if "must_not_contain" in scoring:
        violations = [s for s in scoring["must_not_contain"] if s.lower() in response_lower]
        checks["must_not_contain"] = {
            "pass": len(violations) == 0,
            "detail": f"Found forbidden strings: {violations}" if violations else "clean",
        }

    # must_contain_question: response must end with or contain a question
    if scoring.get("must_contain_question"):
        q_count = count_questions(response)
        checks["must_contain_question"] = {
            "pass": q_count >= 1,
            "detail": f"{q_count} question(s) found",
        }

    # max_questions_in_response: response should not contain more than N questions
    if "max_questions_in_response" in scoring:
        q_count = count_questions(response)
        max_q = scoring["max_questions_in_response"]
        checks["max_questions_in_response"] = {
            "pass": q_count <= max_q,
            "detail": f"{q_count} questions (max {max_q})",
        }

    # should_contain_one_of: at least one of these should appear
    if "should_contain_one_of" in scoring:
        found = [s for s in scoring["should_contain_one_of"] if s.lower() in response_lower]
        checks["should_contain_one_of"] = {
            "pass": len(found) > 0,
            "detail": f"Found: {found}" if found else f"None of {scoring['should_contain_one_of']}",
        }

    # max_length_words: response should be concise
    if "max_length_words" in scoring:
        wc = word_count(response)
        checks["max_length_words"] = {
            "pass": wc <= scoring["max_length_words"],
            "detail": f"{wc} words (max {scoring['max_length_words']})",
        }

    # tone_check: manual flag — always passes in automated scoring, flagged for review
    if "tone_check" in scoring:
        checks["tone_check"] = {
            "pass": True,
            "detail": "MANUAL REVIEW REQUIRED",
        }

    overall = all(c["pass"] for c in checks.values())
    return {"checks": checks, "pass": overall}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_eval(backend, scenarios: list, system_prompt: str, verbose: bool = False, full: bool = False) -> list:
    results = []
    for scenario in scenarios:
        print(f"  Running: {scenario['id']}...", end=" ", flush=True)

        # Build full message list: system prompt + scenario messages
        messages = [{"role": "system", "content": system_prompt}] + scenario["messages"]

        start = time.time()
        response = backend.chat(messages)
        elapsed = round(time.time() - start, 1)

        scored = score_response(response, scenario["scoring"])

        result = {
            "scenario_id": scenario["id"],
            "rule_tested": scenario["rule_tested"],
            "description": scenario["description"],
            "response": response,
            "response_words": word_count(response),
            "latency_seconds": elapsed,
            "score": scored,
        }
        results.append(result)

        status = "PASS" if scored["pass"] else "FAIL"
        print(f"{status} ({elapsed}s)")

        if verbose or full:
            if full:
                print(f"\n    --- RESPONSE ---\n    {response}\n    --- END ---")
            else:
                print(f"    Response: {response[:120]}...")
            for check, detail in scored["checks"].items():
                icon = "✓" if detail["pass"] else "✗"
                print(f"      {icon} {check}: {detail['detail']}")

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(model_name: str, results: list):
    passed = sum(1 for r in results if r["score"]["pass"])
    total = len(results)
    avg_latency = round(sum(r["latency_seconds"] for r in results) / total, 1)

    print("\n" + "=" * 70)
    print(f"  MODEL: {model_name}")
    print(f"  SCORE: {passed}/{total} scenarios passed  ({round(passed/total*100)}%)")
    print(f"  AVG LATENCY: {avg_latency}s per response")
    print("=" * 70)

    # Group by rule
    by_rule = {}
    for r in results:
        rule = str(r["rule_tested"])
        by_rule.setdefault(rule, []).append(r)

    for rule, rule_results in sorted(by_rule.items()):
        rule_passed = sum(1 for r in rule_results if r["score"]["pass"])
        rule_total = len(rule_results)
        rule_label = f"Rule {rule}" if rule.isdigit() else rule.title()
        status = "✓" if rule_passed == rule_total else ("~" if rule_passed > 0 else "✗")
        print(f"\n  {status} {rule_label}: {rule_passed}/{rule_total}")
        for r in rule_results:
            icon = "  ✓" if r["score"]["pass"] else "  ✗"
            print(f"      {icon} [{r['scenario_id']}] {r['description']}")
            for check, detail in r["score"]["checks"].items():
                if not detail["pass"]:
                    print(f"           → FAILED {check}: {detail['detail']}")
            if not r["score"]["pass"]:
                print(f"           → Response: {r['response'][:200]}")

    print()

    # Verdict
    pct = passed / total
    if pct >= 0.9:
        verdict = "STRONG — model holds Socratic rules well. Recommended for Pass 1."
    elif pct >= 0.7:
        verdict = "ACCEPTABLE — some rule failures. Consider prompt tuning or larger model."
    elif pct >= 0.5:
        verdict = "WEAK — fails on critical rules (likely rule 1). Try a larger model."
    else:
        verdict = "REJECT — too many failures. Not suitable for Socratic tutoring."

    print(f"  VERDICT: {verdict}")
    print("=" * 70 + "\n")


def compare_models(all_results: dict):
    """Print a side-by-side comparison table."""
    if len(all_results) < 2:
        return

    print("\n" + "=" * 70)
    print("  COMPARISON")
    print("=" * 70)

    # Header
    models = list(all_results.keys())
    scenario_ids = [r["scenario_id"] for r in list(all_results.values())[0]]

    header = f"  {'Scenario':<35}" + "".join(f"  {m[:12]:<14}" for m in models)
    print(header)
    print("  " + "-" * (35 + 16 * len(models)))

    for sid in scenario_ids:
        row = f"  {sid:<35}"
        for model in models:
            result = next((r for r in all_results[model] if r["scenario_id"] == sid), None)
            if result:
                row += f"  {'PASS' if result['score']['pass'] else 'FAIL':<14}"
        print(row)

    print()
    summary = f"  {'TOTAL':<35}"
    for model in models:
        results = all_results[model]
        passed = sum(1 for r in results if r["score"]["pass"])
        total = len(results)
        summary += f"  {passed}/{total} ({round(passed/total*100)}%)   "
    print(summary)
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Eval harness for Socratic tutor models")
    parser.add_argument("--model", default="llama3.1:8b", help="Single model to test")
    parser.add_argument("--models", help="Comma-separated models to compare, e.g. llama3.1:8b,gemma2:9b")
    parser.add_argument("--subject", default="fractions",
                        choices=list(SAMPLE_PROFILES.keys()),
                        help="Subject to use for diagnostic context injection")
    parser.add_argument("--endpoint", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    parser.add_argument("--output", help="Save results to JSON file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show check details")
    parser.add_argument("-f", "--full", action="store_true", help="Show full model responses")
    parser.add_argument("--scenario", help="Run only a specific scenario by ID")
    args = parser.parse_args()

    # Build system prompt with real diagnostic context for the chosen subject
    profile = SAMPLE_PROFILES[args.subject]
    diagnostic_context = build_from_diagnostic(
        student_data=profile['student_data'],
        all_misconceptions=profile['misconceptions'],
        all_patterns=profile['patterns'],
        test=profile['test'],
    )
    system_prompt = STATIC_PROMPT + "\n\n" + diagnostic_context
    print(f"\nSubject: {args.subject}  |  Student: {profile['student_data']['name']}  |  Score: {profile['student_data']['score_percent']}%")
    print(f"Top misconception: {list(profile['misconceptions'].values())[0]['misconception_name']}")

    models_to_test = [m.strip() for m in args.models.split(",")] if args.models else [args.model]
    scenarios = SCENARIOS
    if args.scenario:
        scenarios = [s for s in SCENARIOS if s["id"] == args.scenario]
        if not scenarios:
            print(f"Scenario '{args.scenario}' not found. Available: {[s['id'] for s in SCENARIOS]}")
            sys.exit(1)

    all_results = {}
    timestamp = datetime.now().isoformat()

    for model in models_to_test:
        print(f"\nTesting model: {model}")

        if args.endpoint == "ollama":
            backend = OllamaBackend(model, args.base_url)
            if not backend.is_available():
                print(f"  ERROR: Ollama not running at {args.base_url}")
                print(f"  Start it with: ollama serve")
                print(f"  Then pull model: ollama pull {model}")
                sys.exit(1)
            available = backend.list_models()
            if model not in available and available:
                print(f"  WARNING: '{model}' not in pulled models: {available}")
                print(f"  Pull it with: ollama pull {model}")
        else:
            backend = OpenAICompatBackend(model, args.base_url, args.api_key)
            if not backend.is_available():
                print(f"  ERROR: No API key provided. Set --api-key or OPENAI_API_KEY env var.")
                sys.exit(1)

        results = run_eval(backend, scenarios, system_prompt=system_prompt, verbose=args.verbose, full=args.full)
        all_results[model] = results
        print_report(model, results)

    if len(models_to_test) > 1:
        compare_models(all_results)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({
                "timestamp": timestamp,
                "models": models_to_test,
                "results": {
                    model: [
                        {
                            "scenario_id": r["scenario_id"],
                            "rule_tested": r["rule_tested"],
                            "pass": r["score"]["pass"],
                            "latency_seconds": r["latency_seconds"],
                            "response_words": r["response_words"],
                            "response": r["response"],
                            "checks": r["score"]["checks"],
                        }
                        for r in results
                    ]
                    for model, results in all_results.items()
                },
            }, f, indent=2)
        print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
