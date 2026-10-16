# Optimized prompt used to write the Daikon red-team plan

```text
Act as a senior offensive-security engineer and defensive architect doing an authorized
red-team review of Daikon, Dai's own personal AI assistant (see CLAUDE.md,
docs/daikon-design.md v4.1 and docs/daikon-implementation-plan.md as fixed inputs).
I own the system and authorize this review of its design.

Task: think like a realistic attacker and write docs/daikon-red-team-plan.md.
1. Define attacker profiles and the attack surface.
2. List attack scenarios in a table: ID, attacker move, impact, existing control (cite the
   design/plan section), gap, new control, and the test that proves it (RT-xx).
3. Add detection and incident-response steps.
4. Add a long-term prevention program (daily to annual cadence), including aging software,
   expiring credentials, model/vendor changes, and what happens if Dai is unavailable.
5. List the new tasks to add to the implementation plan, and accepted residual risks.

Constraints: design-level only; no working exploit code, no payload strings that would work
against third parties. Prioritize by likelihood x impact. Every control must be testable.
Do not weaken the approval gate. Plain language for a non-specialist approver.
Ask only if a missing detail blocks the analysis; otherwise state the assumption.
```
