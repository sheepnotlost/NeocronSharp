# Research workflow observed in the recording

Source: local screen recording `2026-10-23 12-21-51.mp4` (not part of the repository)

Length: 73.33 seconds. Video: 1920 x 1080 at 60 frames per second.

These notes describe the visible interface. They do not establish which physical mouse button or keyboard modifier the user holds.

## Observations

- Inventory and Processor are already open at the start.
- A research tool is already in the first Processor slot and remains there across both attempts.
- Hovering the demonstrated inventory stack shows the tooltip `Unidentified Tech Part`.
- The source is the stack marked T near the top right of the inventory. Its count goes from 42 to 41, then 40.
- A transfer brings up a `Number of Units` dialog with the value 1.
- The first part uses a different free Processor slot from the second part. This suggests the exact free input slot may be configurable; it does not prove that every slot works.
- The Processor is dragged from its initial upper-left position to the left of the inventory during setup. Calibrate after that positioning is finished.
- Start initiates research; a percentage and progress bar are visible during processing.
- Completion clears the processed item from its input slot and displays an item in the right-hand result area.
- The research-fluid count visible near the bottom of inventory goes 136 -> 111 -> 86. No separate fluid transfer into the Processor is visible.
- The next attempt is prepared from the same source stack.
- User clarification: the previous result returns to inventory automatically when a new research run starts. No result-slot click or drag is needed between cycles.

## Approximate timeline

| Video interval | Visible activity |
| --- | --- |
| 0–11 seconds | Select a tech part from the stack and handle the one-unit transfer dialog. |
| 11–16 seconds | Reposition the Processor and initiate the first attempt. |
| 16–38 seconds | Research progresses and the first result appears. |
| 42–49 seconds | Load the next part from the same stack, confirm the quantity, and start again. |
| 50–73 seconds | Second progress cycle and result. |

Times are approximate frame observations, not prescribed macro delays. The demonstrated processing time is roughly 20–25 seconds; use configurable timing or a calibrated completion signal rather than assuming this duration applies to other parts or characters.

## Coordinates visible after repositioning

Reference points in the 1920 x 1080 recording, not verified runtime coordinates:

| Control | Approximate x, y |
| --- | --- |
| Research tool / first input slot | 548, 486 |
| Second input slot | 600, 486 |
| Fourth input slot used in first attempt | 708, 486 |
| Start button | 919, 572 |
| Result area center | 919, 515 |
| Demonstrated T stack | 1420, 478 |
| Research progress bar | x 526–792, y 584 |

## User-confirmed scope

1. Support four stacks: T, E, A, and L.
2. The next research run automatically returns the preceding result to inventory.
3. The last result is left in the Processor; collecting it must not trigger an unwanted additional research attempt.

User update: no calibration; Processor periodically moves to random locations. Implementation now detects Processor, Inventory, labels, and quantity dialogs from current screenshots. The coordinates above are recording-analysis notes only, never runtime defaults. Current supplied setup: 2560 x 1440, borderless fullscreen, UI scale 1.7.
