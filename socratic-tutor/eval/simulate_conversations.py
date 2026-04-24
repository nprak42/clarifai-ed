"""
Simulate student conversations against the live tutor app and log them.

Each student profile drives a different conversation pattern:
  - persistent_wrong: keeps giving 2/7
  - direct_demander: repeatedly asks for the answer
  - frustrated: escalates to frustration
  - off_topic: tries to derail
  - correct_guesser: gives 7/12 immediately without reasoning
  - idk_student: keeps saying idk
  - mixed: realistic mix of confusion and partial progress

Usage:
    python eval/simulate_conversations.py
    python eval/simulate_conversations.py --profile frustrated --turns 8
    python eval/simulate_conversations.py --all --turns 10
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests as http

BASE_URL = "http://localhost:5001"

PROFILES = {
    'persistent_wrong': [
        "I think 1/3 + 1/4 = 2/7",
        "still 2/7, I added 1+1 and 3+4",
        "but the numbers add up so it makes sense",
        "2/7 is my final answer",
        "I'm sure it's 2/7",
        "why can't I add the bottoms?",
        "I don't understand the difference",
        "okay so what should I do then",
    ],
    'direct_demander': [
        "just tell me the answer",
        "I have an exam, what is 1/3 + 1/4",
        "please just give me the answer",
        "I don't want to think about it",
        "7/12? is that it?",
        "why do you keep asking me questions",
        "fine, because the denominators have to match",
        "okay I think I get it now",
    ],
    'frustrated': [
        "this is so confusing",
        "I don't understand fractions at all",
        "this is stupid, why do we even learn this",
        "just tell me, I hate this",
        "I give up",
        "fine. I'll try. 2/7?",
        "I don't know why that's wrong",
        "okay because the pieces are different sizes?",
    ],
    'off_topic': [
        "can you help me with history instead",
        "what's the capital of France",
        "I don't care about fractions",
        "okay fine. 2/7",
        "because I added the tops and bottoms",
        "oh the pieces have to be the same size?",
        "so 12 is the common denominator",
        "7/12!",
    ],
    'correct_guesser': [
        "7/12",
        "because that's what my friend told me",
        "I just knew it",
        "I don't know why, I just guessed",
        "something about common denominators?",
        "you multiply the bottoms together?",
        "12 because 3 times 4 is 12",
        "and then you adjust the tops",
    ],
    'idk_student': [
        "idk",
        "idk",
        "I don't know",
        "no idea",
        "idk still",
        "maybe 2/7?",
        "because I added them?",
        "I still don't really get it",
    ],
    'mixed': [
        "2/7 I think",
        "because I added 1+1 on top and 3+4 on bottom",
        "oh like the pizza slices are different sizes?",
        "so I need to make them the same size",
        "like cut each pizza into 12 pieces?",
        "so 1/3 becomes 4/12?",
        "and 1/4 becomes 3/12",
        "so 4/12 + 3/12 = 7/12!",
    ],
}


def simulate_conversation(profile_name, turns=8, student_name=None):
    """Run a simulated conversation and return session ID."""
    s = http.Session()
    name = student_name or f"{profile_name.replace('_', ' ').title()} Student"

    # Reset any existing session
    s.post(f"{BASE_URL}/api/reset")

    # Get greeting
    try:
        g = s.get(f"{BASE_URL}/api/greeting", timeout=60)
        greeting = g.json().get('reply', '')
    except Exception as e:
        print(f"  ERROR getting greeting: {e}")
        return None

    profile_turns = PROFILES.get(profile_name, [])
    turns_to_run = min(turns, len(profile_turns))

    print(f"\n  [{profile_name}] {name}")
    print(f"  TUTOR: {greeting[:100]}...")

    for i in range(turns_to_run):
        msg = profile_turns[i]
        # Add slight variation so logs don't look identical across runs
        if random.random() < 0.15 and i > 0:
            msg = random.choice(["I still don't get it", "can you explain again", "hmm okay"])

        print(f"  STUDENT: {msg}")

        try:
            resp = s.post(
                f"{BASE_URL}/api/chat",
                json={'message': msg},
                stream=True,
                timeout=120,
            )
            full = []
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode() if isinstance(line, bytes) else line
                if line.startswith('data: '):
                    chunk = json.loads(line[6:])
                    if 'token' in chunk:
                        full.append(chunk['token'])
            reply = ''.join(full)
            print(f"  TUTOR: {reply[:120]}{'...' if len(reply) > 120 else ''}")
        except Exception as e:
            print(f"  ERROR: {e}")
            break

        time.sleep(0.5)  # small pause between turns

    # Get the Flask session cookie to find session_id in logs
    # The session was logged by the app automatically
    print(f"  [done — {turns_to_run} turns]")
    return profile_name


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', default=None, choices=list(PROFILES.keys()),
                        help='Run a specific profile')
    parser.add_argument('--all', action='store_true', help='Run all profiles')
    parser.add_argument('--turns', type=int, default=8, help='Turns per conversation')
    args = parser.parse_args()

    # Check tutor is running
    try:
        http.get(f"{BASE_URL}/", timeout=3)
    except Exception:
        print(f"ERROR: Tutor app not running at {BASE_URL}")
        sys.exit(1)

    if args.all:
        profiles = list(PROFILES.keys())
    elif args.profile:
        profiles = [args.profile]
    else:
        profiles = list(PROFILES.keys())

    print(f"Simulating {len(profiles)} conversation(s), {args.turns} turns each...")
    print("(Conversations are automatically logged to tutor_logs.db)\n")

    for profile in profiles:
        simulate_conversation(profile, turns=args.turns)
        time.sleep(1)

    print(f"\nDone. Run scorer to analyse:")
    print(f"  python eval/scorer.py --verbose")
