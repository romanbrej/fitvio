# How it works

```
Garmin watch → Garmin Connect → GarminDB (per person, on your server) → fitvio ingest + verdicts → API → wall display (any browser)
```

## Today's mission

The wall opens with one headline for the day ("Ready to push.", "Keep building.", "Recover today.") from **Garmin's Training Readiness** (the score your watch shows) or, without it, from your form. Below it:

- **Your Garmin plan's week**: the workouts in your Garmin Connect calendar (Garmin Coach's adaptive plan or workouts you scheduled), Monday to Sunday — on a Sunday the next 7 days. Today is shown wide with the workout's shape and target; the other days show ✓ done, × missed, planned or rest. A past day counts as done when a session of the same sport (10 min or more) was on that day; a run started from the workout ("City - Schwelle") wins. No plan → no strip. If Garmin can't be reached, the last good copy stays.
- **Training load**: fitness, fatigue and form on one chart, and this week's load against a **sweet spot** taken from your fitness (the weekly load that raises fitness by about 1–5 points: 7 × fitness + 46 … + 228). All loads are the app's heart-rate TRIMP, not Garmin's load.
- **Recovery**: Garmin Training Readiness, last night's HRV against your normal range, resting HR, sleep, Body Battery and VO₂max.
- **Week streak**: weeks in a row with at least 3 workouts of 10 minutes or more.
- **Sport cards**: your current pace, power or swim pace in real units with its 6-week trend; running also shows cadence (easy and long runs, information only — it never counts toward a verdict).

Readiness, the planned workouts and the plan come from Garmin endpoints GarminDB doesn't download; they are fetched after every successful sync with the same cached login (`sync/garmin_coach.py`).

## Training plan page

Tap any day of the week strip. The plan page shows the plan (name, week n of N, progress), the week as cards, and the chosen day's workout: profile, step-by-step targets, estimated load. Done days add the result — verdict, how many work blocks hit the target pace, and a link to the session. For today it also says whether you're ready for it and what it does for your weekly load, streak and form. Garmin Coach only plans about a week ahead, so that's as far as the page goes.

## Post-activity verdict

Each new activity is compared with your *similar* sessions from the last 8 to 17 weeks: same sport, same session type (easy / long / tempo / intervals / race), a comparable duration, and indoor vs outdoor kept apart. The result is **Better / In line / Worse**, with the top reasons in plain language, a confidence level, and the effect on your fitness, fatigue and form. It takes over the wall for an hour after the activity. Tapping another person's avatar pauses it — the verdict comes back after a minute without a tap; only *Overview* on the verdict ends it early.
When there are fewer than 3 comparable sessions it says **"Not comparable yet"** instead of guessing.

| Sport | What "improved" means |
|---|---|
| Running | Grade-adjusted pace per heartbeat (Minetti energy-cost model, heat-normalised), pace at a fixed HR, aerobic decoupling (HR drift) |
| Cycling (with power, e.g. a smart trainer) | Power per heartbeat, Power:HR drift, best 5-min power, power-curve PRs, eFTP |
| Cycling without power | Training load only, marked low confidence (wind and terrain make speed meaningless) |
| Swimming | Pace per 100 m and SWOLF, compared only against the same main stroke |
| Gym | Estimated 1-rep max per exercise (Epley) vs the best of your last 3 sessions, plus PRs. Needs reps and weight logged on the watch |
| Everything else | Training load and recovery impact |

**Heat and humidity.** Running efficiency is adjusted with **Garmin's own weather for the activity** (the same weather box Garmin Connect shows, taken from a station near the start at start time) and **Garmin's heat acclimation**. It uses the runners' temperature + dew point rule: the sum in °F sets how much harder the same effort was (0 % up to 100 °F, up to 12 % above 180 °F). Heat acclimation reduces that effect by up to half, which is a heuristic. Indoor and treadmill sessions get no heat adjustment. The wrist temperature sensor isn't used for this, because body heat skews it, and FIT files use 127 as a "no value" marker.
Weather and acclimation are downloaded with each sync. For older history, run `fitvio backfill-extras` once (a first download does this automatically).

**Verdict check.** Rate *How did you feel* and *Perceived effort* on your watch after each activity. The app tracks how often the verdicts agree with how you felt, and lists the disagreements.

## Training buddy

A little animal that lives on the wall and reacts to your data: *overjoyed* after a "Better" workout or a new best, *hungry* after 3 days without training, *sleepy* when readiness or sleep is low, *happy* when you're fresh, *content* otherwise, and asleep at night. Tap it to pet it. Each person picks their own animal (mouse, cat, bunny, fox, bear, penguin, frog or hedgehog) in Accounts.

## Around the wall

- **Glance → tap → detail.** Every card opens a detail page: every number, HR and pace/power charts, laps, sets, the exact baseline sessions you were compared with, "Am I improving?" per sport, and health trends over up to 365 days. The display returns to the wall after 2 minutes idle.
- **Day and night screens.** After a minute without a tap the overview fades to a calm day screen — big clock, today's headline, a few facts and your buddy. Between `night_start` and `night_end` a dark night screen takes over. A tap wakes the wall.
- **Multi-user.** Each person has their own Garmin login and their own GarminDB. The newest activity takes over the wall with that person's avatar; tap an avatar to switch.
- **Big screens scale up.** A tablet that renders at pixel ratio 1 (e.g. 1920 × 1080 CSS px in a kiosk browser) gets the whole wall zoomed so it looks like the ~1280 × 800 design.

## Syncing

Every hour, on a new activity (see *Auto-sync* below), and on demand via the sync button in the top bar (at most once a minute), the app runs a *differential* sync:
- It only downloads days and activities that are new or changed, including today.
- It only imports files written since the last successful sync.
- It only recalculates the affected years.
- Activities you rename or rate afterwards in Garmin Connect (feel, effort) are picked up again without re-taking the wall.

A typical sync takes well under a minute. The first tap of the morning also fetches last night's sleep and HRV right away.

**Auto-sync on new activity.** Garmin offers webhooks only to approved business partners, so the app does the next best thing:
- **Quick check:** every 2 minutes (05:00–24:00) it asks Garmin for the newest activity id only. That's one tiny request per person, and nothing is downloaded.
- **Sync on change:** if the id is new, the normal differential sync starts, and the workout is on the wall about 2–3 minutes after your watch uploaded it.
- **Hourly sync:** sleep, HRV, resting HR and the other health data sync hourly, day and night.

It protects your Garmin account, because the app uses the unofficial Garmin Connect login:
- **Expired login:** the check only uses the cached login tokens, never your password or MFA. If the tokens expire, the check pauses for that person and the top bar says *Garmin login expired*. Tap it, then *Sync now* in Accounts to log in again with the saved password.
- **Rate limit:** if Garmin answers "too many requests", the check (and the plan/readiness fetch) pauses for everyone for 6 hours.
- **Stuck activity:** an activity that doesn't arrive after 3 syncs is left alone, so it never syncs in a loop.
- **Off switch:** you can turn it off in *Accounts → Auto-sync on new activity*. The hourly sync and the sync button keep working.

**Failure handling.** If the Garmin sync breaks (GarminDB uses the unofficial Garmin Connect login), the wall shows an amber "Last sync X ago" banner after 24 h. An old verdict is never re-shown as if it were new.

## Known limitations

- Garmin's endpoints used here are unofficial and can change; the parsers are pinned to real (anonymized) answers in `backend/tests/fixtures/garmin`.
- Garmin Coach's adaptive plan only schedules about a week ahead, so the wall shows the next ~7 planned days.
- Weather comes from the nearest Garmin weather station at the start, so it doesn't capture sun, shade or temperature changes during long sessions.
- Garmin has no public webhook. A new activity is found by polling (every 2 min, 05:00–24:00); at night it waits for the hourly sync.
- Pool HR from a wrist sensor is unreliable. Swimming verdicts rely on pace and SWOLF, not HR.
- Garmin's strength categories are broad (for example "squat" covers goblet and back squat). The numeric variant is kept in the exercise key so different variants aren't mixed.
- The FIT parsing has only been tested against GarminDB's documented layout and synthetic data. Check `fitvio backtest` after your first real sync.
