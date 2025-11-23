# test_sync handler — Detailed Specification

Source: `codex-rs/core/src/tools/handlers/test_sync.rs`

Purpose
- Test-only coordination tool to synchronize concurrent tool calls and simulate delays. Useful for deterministic snapshot/integration tests.

Inputs
- Payload: `ToolPayload::Function { arguments: String }` with JSON fields (all optional):
  - `sleep_before_ms` (u64) — milliseconds to sleep before barrier.
  - `sleep_after_ms` (u64) — milliseconds to sleep after barrier.
  - `barrier` (object) — optional barrier settings:
    - `id` (string, required)
    - `participants` (usize, required, >0)
    - `timeout_ms` (u64, default 1000, >0)

Outputs
- Success: `ToolOutput::Function { content: "ok", success: Some(true) }`.
- Errors: `FunctionCallError::RespondToModel` for parse errors, invalid params, barrier timeouts, or participant mismatches.

Behaviour
1) Parse JSON args; validate barrier/timeouts if present.
2) If `sleep_before_ms` > 0 → `tokio::time::sleep` that duration.
3) If barrier present → call `wait_on_barrier`:
   - Uses global `OnceLock` `BARRIERS` storing map id→BarrierState { barrier, participants } guarded by Mutex.
   - If barrier id exists with different participant count → RespondToModel error.
   - If new id → create `tokio::sync::Barrier(participants)` and store.
   - Wait on barrier with `timeout_ms` using `tokio::time::timeout`.
   - If the waiter is leader after barrier trip, remove the barrier entry (cleanup) provided Arc ptr matches stored one.
   - Timeout → RespondToModel("test_sync_tool barrier wait timed out").
4) If `sleep_after_ms` > 0 → sleep.
5) Return "ok".

Pseudocode
```
handle(invocation):
  args = parse TestSyncArgs
  if sleep_before_ms>0: sleep
  if barrier: wait_on_barrier(barrier)
  if sleep_after_ms>0: sleep
  return ToolOutput("ok", success=true)

wait_on_barrier(args):
  validate participants>0, timeout_ms>0
  map = global barrier_map()
  entry = map.get_or_insert(id, BarrierState{Barrier(participants), participants})
  if entry.participants != args.participants: error
  result = timeout(timeout_ms, entry.barrier.wait())
  if timeout -> error
  if leader after wait -> remove entry (if same Arc)
```

Edge Cases
- Multiple concurrent callers with same id and participant count will synchronize; mismatched counts error immediately.
- Timeout removes nothing; barrier remains for future waits.

Reimplementation Notes
- Keep barrier lifecycle semantics (leader cleans up) to avoid leaks.
- Sleep values of 0 are no-ops; missing fields default to None.
- This handler is not exposed to end users; fidelity matters for tests.

## Input/Output Examples
- **Simple sleep only**
  Payload: `{"sleep_before_ms":50,"sleep_after_ms":25}`
  Output: `"ok"`, success true after sleeps elapse.

- **Barrier with two participants**
  Caller A payload: `{"barrier":{"id":"b1","participants":2,"timeout_ms":1000}}`
  Caller B payload: same as A. Both block until both arrive, then return `"ok"`, success true. Barrier is cleaned up by leader.

- **Barrier participant mismatch**
  First call registers `participants:2`; second call uses `participants:3` → second call RespondToModel(\"barrier b1 already registered with 2 participants\").

- **Barrier timeout**
  Single caller payload: `{"barrier":{"id":"solo","participants":2,"timeout_ms":100}}` with no other participants → RespondToModel(\"test_sync_tool barrier wait timed out\").

- **Invalid params**
  Payload: `{"barrier":{"id":"bad","participants":0}}` → RespondToModel("barrier participants must be greater than zero").

## Gotchas
- Barriers are keyed by id; subsequent calls must use the same participant count or they error.
- Only the leader removes the barrier entry after the wait; timeouts leave the barrier registered.
- Sleeps before/after are cumulative; large values block the tool call.
- Timeout of 0 or participants of 0 are rejected with user-visible errors.

## Sequence Diagram
```
Model -> ToolRouter: ResponseItem(FunctionCall test_sync_tool)
ToolRouter -> TestSyncHandler: ToolInvocation
TestSyncHandler -> serde_json: parse args
TestSyncHandler -> sleep (before)
TestSyncHandler -> wait_on_barrier (optional)
wait_on_barrier -> BarrierMap: get/create barrier
wait_on_barrier -> tokio::time::timeout(barrier.wait)
wait_on_barrier -> BarrierMap: cleanup on leader
TestSyncHandler -> sleep (after)
TestSyncHandler -> ToolRouter: ToolOutput("ok") or RespondToModel
```
