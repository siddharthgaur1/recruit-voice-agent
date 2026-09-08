"""Held-out personas, frozen and unused during prompt development.

These exist to answer one question honestly: "how does the frozen prompt
behave on inputs it was never tuned against?" They are run exactly ONCE
after the prompt is frozen (see eval_report.py) and the result is reported
raw, mismatches included -- do not edit the extraction prompt in response to
a bad result here without re-declaring a new baseline.

Two batches, both held out:
  101-105  the original five.
  106-112  added later to widen the set (5 personas was too thin to read
           much into a 92.3% accuracy figure). Written from the slot
           conventions in src/agent/slots.py, NOT from any observed failure,
           and never run during prompt development. `expected_slots` is what
           a careful human would take from the words -- deliberately not
           "whatever the current code returns", or the set would only ever
           confirm itself.
"""

from src.sim.personas import Persona

HELD_OUT_PERSONAS: list[Persona] = [
    Persona(
        id=101, name="Self-correcting",
        replies=["yes", "3 years, sorry, 3 and a half years actually",
                  "Python", "Bangalore", "1 month", "yes go ahead"],
        expected_slots={
            "interested": True, "yoe": 3.5, "domain": "Python", "city": "Bengaluru",
            "notice_period_days": 30, "confirmed": True,
        },
    ),
    Persona(
        id=102, name="Negotiating",
        replies=["yes", "5 years", "DevOps", "Pune",
                  "depends on the package you're offering",
                  "depends what you offer honestly",
                  "only if the offer is good",
                  "let's see the offer first"],
        expected_slots={
            "interested": True, "yoe": 5.0, "domain": "DevOps", "city": "Pune",
            "notice_period_days": None, "confirmed": None,
        },
    ),
    Persona(
        id=103, name="Fragmentary",
        replies=["yeah", "four", "java", "pune", "two", "yeah"],
        expected_slots={
            "interested": True, "yoe": 4.0, "domain": "Java", "city": "Pune",
            "notice_period_days": None, "confirmed": True,
        },
    ),
    Persona(
        id=104, name="Out-of-order-contradicting",
        replies=["yes, 4 years experience, based in Mumbai", "Java",
                  "actually I'm based in Pune now, not Mumbai", "2 months", "yes"],
        expected_slots={
            "interested": True, "yoe": 4.0, "domain": "Java", "city": "Pune",
            "notice_period_days": 60, "confirmed": True,
        },
    ),
    Persona(
        id=105, name="Heavy-Hinglish",
        replies=["haan bilkul, dekhna chahta hoon", "paanch saal se IT mein hoon",
                  "mostly Python aur cloud pe kaam karta hoon", "Pune mein rehta hoon abhi",
                  "ek mahine ka notice period hai bas", "haan zaroor bhej dijiye"],
        expected_slots={
            "interested": True, "yoe": 5.0, "domain": "Python", "city": "Pune",
            "notice_period_days": 30, "confirmed": True,
        },
    ),
    Persona(
        id=106, name="Fresher",
        replies=["yes definitely", "no experience yet, just graduated",
                 "machine learning", "Bangalore", "I can join immediately",
                 "yes please"],
        expected_slots={
            "interested": True, "yoe": 0.0, "domain": "Data Science",
            "city": "Bengaluru", "notice_period_days": 0, "confirmed": True,
        },
    ),
    Persona(
        id=107, name="Serving-notice",
        replies=["yeah I'm listening", "6 years", "I'm an SDET", "Gurgaon",
                 "already serving, 45 days left", "sure, send it across"],
        expected_slots={
            # "Gurgaon" -> "Gurugram" and "SDET" -> "QA/Testing" both go
            # through the alias tables, not the model's own wording.
            "interested": True, "yoe": 6.0, "domain": "QA/Testing",
            "city": "Gurugram", "notice_period_days": 45, "confirmed": True,
        },
    ),
    Persona(
        id=108, name="Asks-to-repeat",
        replies=["sorry, what was that?", "yes I'm interested",
                 "sorry could you repeat", "8 years", "react native",
                 "Noida", "3 weeks", "yes"],
        expected_slots={
            "interested": True, "yoe": 8.0, "domain": "Mobile",
            "city": "Noida", "notice_period_days": 21, "confirmed": True,
        },
    ),
    Persona(
        id=109, name="Over-explainer",
        replies=["well I wasn't really looking but go on I suppose",
                 "so I started in 2019 straight out of college which makes it "
                 "about 7 years now give or take",
                 "mostly Spring Boot microservices, some Kafka",
                 "I moved to Hyderabad during the pandemic and stayed",
                 "my contract says three months but I might negotiate it down",
                 "yeah alright send it over"],
        expected_slots={
            "interested": True, "yoe": 7.0, "domain": "Java",
            "city": "Hyderabad", "notice_period_days": 90, "confirmed": True,
        },
    ),
    Persona(
        id=110, name="Reluctant-then-willing",
        replies=["not really, I'm happy where I am",
                 "well, depends -- what's the role?",
                 "okay fine, 5 years", "front end", "Chennai",
                 "two weeks", "go on then, send it"],
        expected_slots={
            "interested": True, "yoe": 5.0, "domain": "Frontend",
            "city": "Chennai", "notice_period_days": 14, "confirmed": True,
        },
    ),
    Persona(
        id=111, name="Career-switcher",
        replies=["yes", "9 years total", "I was in QA for years but I've been "
                 "doing Kubernetes and CI/CD for the last two",
                 "Bombay", "one month", "yes send it"],
        expected_slots={
            # The current role is what counts, not the history: DevOps, not QA.
            "interested": True, "yoe": 9.0, "domain": "DevOps",
            "city": "Mumbai", "notice_period_days": 30, "confirmed": True,
        },
    ),
    Persona(
        id=112, name="Fractional-units",
        replies=["haan", "one and a half years", "full stack", "poona",
                 "10 din", "haan bhej do"],
        expected_slots={
            # 1.5 is what the words mean; a first-integer-wins parse gives 1.0.
            # Left as 1.5 on purpose -- the set exists to find that, not hide it.
            "interested": True, "yoe": 1.5, "domain": "Full Stack",
            "city": "Pune", "notice_period_days": 10, "confirmed": True,
        },
    ),
]

HELD_OUT_IDS = {p.id for p in HELD_OUT_PERSONAS}
