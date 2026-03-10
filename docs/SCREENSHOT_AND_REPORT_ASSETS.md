# Screenshot and Example Report Asset Plan

Use this as the default shot list for GitHub README, release notes, and beta ads.

## Recommended Screenshots (5-7)

1. **Main dashboard (connected + live session)**
   - Show clear "connected" state and live plots.
2. **Session History + Replay**
   - Show timeline scrubber and replay plots.
3. **Trends view**
   - Show comparison/trend visuals across sessions.
4. **QTc window**
   - Show trend and context note (non-diagnostic wording visible).
5. **Settings/Profile flow**
   - Show profile-aware configuration at a glance.
6. **Report generation moment**
   - Show post-session flow or generated artifacts path.
7. **Optional kiosk screenshot**
   - Show minimal UX if kiosk mode is a target.

## Recommended GIFs (1-2)

- Connect sensor -> start session -> stop/save (30-45s)
- Session replay scrubber interaction (10-20s)

Keep GIFs small and short; use MP4 where possible if hosting supports it.

## Example Report Asset

Yes, include one example report image. Best practice:

- Add one redacted screenshot of the one-page PDF (`session_share.pdf`) first page.
- Optionally add a second image from full DOCX export (redacted values/profile).

Suggested location:

- `docs/assets/reports/example_report_page1.png`
- `docs/assets/reports/example_report_detail.png`

## Redaction Checklist (Before Publishing)

- Remove names/profile identifiers
- Remove exact timestamps if sensitive
- Remove machine paths/usernames if visible
- Keep disclaimer/non-diagnostic wording visible

## README Placement

For best discoverability:

- Put 1 hero screenshot near top of README.
- Put 3-4 additional screenshots in a short "Quick tour" section.
- Link to this document for full asset guidance.
