# Bounded self-healing

> Write-capable `implement` calls are reported with their partial transcript and workspace delta after a timeout; they are never automatically retried.

> A bridge call performs at most one remedy. It writes one incident record for every fault and appends one health.jsonl line for every completed call, including unsuccessful calls.

> `turn.failed` with `reasoning.effort` or an equivalent structured Claude error may trigger one supported-effort substitution. A missing or unauthenticated CLI, a permission refusal, an unknown fault, or a repeated substitution is reported without retry. Timeout retry is limited to read-only verbs; implement is reported with its partial transcript and workspace delta. An unavailable model and a stale resume session are also reported without remedy: the bridge does not maintain a model fallback ladder, and no verified structured signal distinguishes a stale session from other resume faults.

> Incident records contain the classified fault and reason, model, effort, verb, duration budget, transcript path, and any killed-implementation workspace delta. They deliberately exclude child arguments and environment data because task text and credentials may be present there. The referenced raw transcript retains stdout and stderr for operator diagnosis; stderr is never the primary fault classifier.
