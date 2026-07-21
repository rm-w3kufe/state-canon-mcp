---
name: fix-source-keep-detector
description: Use when a detector, alarm, or audit is firing noisily and someone proposes raising a threshold, suppressing alerts, or declaring the signal out-of-scope. Fix the source; keep the detector calibrated.
---

# Fix the source, keep the detector

## The rule
When a detector fires repeatedly, there are two possible truths: the system is wrong, or the
detector is wrong. **Find out which — then fix that one.** Never take the third option: blunting
the detector (raise the threshold, suppress the alert, reclassify as expected) so the noise stops
while the cause remains.

## How
1. Treat every noisy detector as a diagnosis task, not an annoyance (see confirm-first).
2. If the **system** is wrong → fix the source; the detector goes quiet on its own. That silence
   is your verification.
3. If the **detector** is wrong (a genuine false positive — prove it with independent evidence) →
   fix the *detector's defect*; do not widen its tolerance. A wider ε that "fixes" a false positive
   also hides the future true positive of the same magnitude.
4. Reclassifying historical noise? Reclassify, don't purge — the record of the noise is evidence.
5. The forbidden moves, by name: **raise-ε**, **suppress**, **out-of-scope**. Any proposal
   containing one of these needs the burden of proof reversed.

## The scar
An audit stream flagged hundreds of divergence events. The tempting fix — proposed explicitly —
was to raise the tolerance until the noise stopped. Independent verification showed the events
were real: a capture-ordering bug in the emitter, invisible everywhere else. Raising ε would have
silenced the only witness to a genuine defect — and every future defect under the new, blunter
threshold. The source was fixed; the detector stayed calibrated; the stream went quiet *because
the system got right*, which is the only silence worth having.

## Anti-patterns
- "It's been alerting for weeks, just mute it."
- Tolerance values that ratchet up over time and never back down.
- Deleting noisy history instead of reclassifying it (evidence disposal).
- Declaring a detector "flaky" without proving the false-positive mechanism.
