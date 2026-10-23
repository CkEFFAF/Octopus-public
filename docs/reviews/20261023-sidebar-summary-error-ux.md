# Self-review: sidebar, overview language and error details

Scope: changes after fe03dc03, against the user's three reported problems and
the existing 0035 metadata budget contract. This is a self-review, not an
independent model review.

Checked that reopening Chat retains the selected conversation, manual collapse
preferences remain usable, and both populated and empty desktop headers expose
the recovery control. Manual objectives are excluded from the old-language
refresh hint. Auxiliary calls read only the owning user's preference off the
event loop; source IDs, paths and JSON field names retain their original form.

Checked that inline errors expose concise translated explanations; diagnostic
JSON and technical tags require an explicit Details action. Batch counts come
from the complete persisted grouping, while the modal explicitly states how
many bounded samples are retained. Copy is visible before the scrollable JSON.
No raw prompts, provider response bodies or secrets were added to diagnostics.

The request budget now compares estimated tokens with token limits instead of
UTF-8 bytes. It retains the 12,000-token ceiling, model input/context/output
limits, framing allowance and a 50 percent reserve. Tests distinguish a Chinese
request above 12,000 bytes that fits the token budget from a truly excessive
request rejected before invoking the model.

Evidence: 5127 full-suite passes / 157 skips, final targeted backend+i18n 110
passes, final UI 20 passes and TypeScript. The isolated real application proved
sidebar recovery after refresh without URL change, English-to-Chinese update,
30 failures grouped into two reasons and working Details with a visible copy
action. No production chat content was used in the smoke tests.

Limitations: token estimates are model-independent approximations, with reserve;
they are not exact provider token counts. Older English summaries need the
explicit language refresh action. Screenshot capture timed out, so visual
evidence is DOM, computed style and interaction evidence, not screenshots.
