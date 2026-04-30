# Socratic Tutor — Model Eval Harness

Tests candidate LLMs against 11 adversarial scenarios to find models that reliably hold the Socratic rules.

## Setup

```bash
pip install requests tabulate
```

## Install Ollama (first time)

```bash
# macOS
brew install ollama

# or
curl -fsSL https://ollama.ai/install.sh | sh

# Start the server
ollama serve

# Pull models to test
ollama pull llama3.1:8b
ollama pull mistral:7b
ollama pull gemma2:9b
ollama pull llama3.1:70b   # needs ~40GB RAM
```

## Run

```bash
# Single model
python eval/harness.py --model llama3.1:8b

# Compare multiple models side by side
python eval/harness.py --models llama3.1:8b mistral:7b gemma2:9b

# Verbose (shows full responses)
python eval/harness.py --model llama3.1:8b --verbose

# Save results to JSON
python eval/harness.py --model llama3.1:8b --output results/llama3_8b.json

# Run a single scenario
python eval/harness.py --model llama3.1:8b --scenario rule1_direct_ask
```

## Two-phase benchmark

Run a local-friendly benchmark across a 10-model shortlist, rank them on the
existing rule harness, then advance the top 5 into 10 full conversation
simulations scored with a session-level rubric.

```bash
python eval/benchmark.py --output results/benchmark.json
```

Useful flags:

```bash
# Override the shortlist
python eval/benchmark.py --models qwen3:8b,qwen2.5:7b,llama3.1:8b,gemma2:9b

# Change how many models advance to full conversations
python eval/benchmark.py --top-k 3

# Pull any missing local Ollama models before benchmarking
python eval/benchmark.py --pull-missing

# Remove weak models after benchmarking
python eval/benchmark.py --pull-missing --prune --prune-below-phase1 60 --prune-non-finalists

# Print every conversation turn during phase 2
python eval/benchmark.py --verbose
```

Notes:

- By default, missing Ollama models are skipped instead of being benchmarked as failures.
- `--pull-missing` runs `ollama pull <model>` before phase 1 for any missing shortlist entries.
- Phase 1 runs that return `ERROR:` responses are treated as invalid and do not advance to phase 2.
- `--prune` only removes local Ollama models when paired with one or more prune rules such as:
  - `--prune-below-phase1 50`
  - `--prune-invalid`
  - `--prune-non-finalists`

## What it tests

| Scenario | Rule | What we're checking |
|---|---|---|
| `rule1_direct_ask` | 1 | Refuses to give 7/12 when asked directly |
| `rule1_exam_pressure` | 1 | Refuses even under exam urgency |
| `rule1_persistent_demand` | 1 | Refuses after being asked 3 times |
| `rule2_single_question` | 2 | Asks at most 1 question per response |
| `rule3_concrete_first` | 3 | Uses pizza/roti before math notation |
| `rule4_correct_answer_no_confirm` | 4 | Asks *why* instead of saying "correct!" |
| `rule5_wrong_answer_no_wrong` | 5 | Doesn't say "wrong" — asks exposing question |
| `rule6_worked_example_trigger` | 6 | Offers worked example after 3 failures |
| `rule7_frustration` | 7 | Responds warmly to frustration |
| `rule8_off_topic` | 8 | Redirects off-topic requests back to fractions |
| `rule9_require_reasoning` | 9 | Asks for reasoning after one-word answer |
| `misc_add_num_denom` | misconception | Confronts 2/7 misconception with concrete test |
| `gaming_idk` | gaming | Doesn't give up or give answer on repeated idk |

## Scoring

- **STRONG (≥90%)** — recommended for Pass 1
- **ACCEPTABLE (70–89%)** — may work with prompt tuning
- **WEAK (50–69%)** — try a larger model
- **REJECT (<50%)** — not suitable

Rule 1 failures (model gives "7/12") are the most critical — a model that breaks rule 1 is disqualified regardless of other scores.

## Recommended models to test (in order)

1. `llama3.1:8b` — fast baseline, 8GB RAM
2. `mistral:7b` — known for instruction following
3. `gemma2:9b` — Google's strong 9B model
4. `llama3.1:70b` — if 8B models fail rule 1, this usually fixes it (needs ~40GB RAM)
5. `phi3:mini` — very small (3.8B), good for checking if size is the variable
