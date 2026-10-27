# Implementation plan

The user's video and clarification define the workflow: four stacks, one part at a time, automatic previous-result return on the next Start. Updated requirement: no coordinate calibration; Processor periodically moves to random positions.

1. Build a configurable sequence engine with simulated input. Preserve T/E/A/L order, per-stack counts, guarded input, interruptible waits, and explicit timeouts.
2. Add Windows foreground-window binding, client capture, and input delivery.
3. Detect Processor title and Start, Inventory and stack labels, and the quantity dialog. Reacquire before every cycle and immediately before Start. Stop on missing or ambiguous matches; never reuse a stale coordinate.
4. Replace calibration controls with read-only detection preview in the Tkinter panel.
5. Verify actual recording crops, 2560 x 1440 moved-window compositions, rendered scale variants, and simulated relocation between cycles. Keep the final result without starting an extra run.

Use item appearance in the visually detected Processor input for monitor-only completion, without an empty-slot reference, fixed research wait, or research time limit. Recognize the quantity dialog from opaque title text and the Half control; verify exactly one before confirming. A final single item may skip the quantity dialog if it is absent and the input is occupied. Remove old research durations and timing controls.

Pause during an input gesture aborts the batch and requires manual recovery; pause during research or between cycles can resume. Never repeat a partly executed input gesture automatically.

Live testing was authorized, but the computer-use capture helper timed out repeatedly. No game input was sent. Document this limitation explicitly.
