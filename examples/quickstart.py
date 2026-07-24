"""Regress quickstart demo.

Run `regress up` in one terminal, then this script in another:

    regress up &
    export OPENAI_API_KEY=sk-...
    python examples/quickstart.py
    regress traces

`instrument()` patches the OpenAI client so every chat completion emits an
OTel GenAI span to the local collector, with no other code changes. The
`@task` decorator groups a whole function's spans (including nested SDK
calls) into one trace; `feedback()` attaches a score to a trace after the
fact, e.g. from a user thumbs-down in your app.
"""

from __future__ import annotations

from openai import OpenAI

from regress import current_trace_id, feedback, instrument, task

instrument()

client = OpenAI()


@task(name="answer_support_question")
def answer_support_question(question: str) -> tuple[str, str | None]:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a terse customer support agent."},
            {"role": "user", "content": question},
        ],
    )
    answer = response.choices[0].message.content or ""
    # current_trace_id() only resolves inside an active @task or instrumented
    # call, so read it here rather than after answer_support_question returns.
    return answer, current_trace_id()


def main() -> None:
    answer, trace_id = answer_support_question("What's your refund policy?")
    print(answer)

    # In a real app this comes from a user reaction (e.g. a thumbs-down),
    # fired later once you have the trace_id captured above.
    if trace_id is not None:
        feedback(trace_id=trace_id, score=1.0, comment="accurate and concise")


if __name__ == "__main__":
    main()
