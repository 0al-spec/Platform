# Code Review Heuristics

Use these heuristics systematically during review, especially for workflow,
artifact, CLI, and quality-gate changes.

## Conceptual Checklist

1. **Presence is not quality.**
   Do not treat "file exists" or "field is non-empty" as proof that an
   artifact is usable. If a producer emits lifecycle states such as `ready`,
   `review_required`, `blocked`, or `missing`, verify that the consumer handles
   every state explicitly.

2. **Prefer the authoritative version.**
   When workflows support repair, retry, regeneration, drafts, or finalization,
   check that consumers select the freshest or most authoritative artifact, not
   just the first one found.

3. **Check for state leakage between runs.**
   Any intermediate path written by a tool must be reviewed for scope:
   run-local, task-local, or shared/global. Shared paths can be overwritten or
   accidentally reused by parallel or later runs.

4. **Model operator misuse.**
   Review not only malformed input data, but also likely human mistakes: wrong
   path, wrong directory, wrong flag, or confusing shared vs scoped locations,
   especially in CLI tools and Make targets.

5. **Make quality-gate failure modes explicit.**
   Before calling a check complete, enumerate all ways an artifact can be invalid
   or insufficient: missing, empty, malformed JSON, wrong shape, stale, or marked
   as not ready. Each case should map to an intentional code path.

6. **Trace producer semantics, not only schema shape.**
   When reading files such as `producer_output.json`, verify the real values the
   producer can emit, not only the keys it writes. Inspect producer code for
   actual status values and edge states.

7. **Separate hard failures from silent skips.**
   A crash on bad data is visible, while a silent skip can hide a bug. For
   smoke/reporting tools, prefer structured findings and continued execution. If
   improving this behavior, label it as robustness work unless it fixes a
   masking bug.

## Review Roadmap

1. **Implementation review:** trace producer states, consumer selection logic,
   artifact paths, and CLI/operator entry points.
2. **Verification review:** confirm tests or manual checks cover lifecycle
   states, stale or repaired artifacts, scoped paths, malformed artifacts, and
   likely misuse.
3. **Success metrics:** consumers reject or report non-ready artifacts, prefer
   authoritative outputs, avoid shared intermediate state, and produce structured
   findings instead of silent skips where reporting behavior matters.
