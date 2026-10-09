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
- **Pick the period.** On a sport's page (wall and phone), choose how far back "Am I improving?" looks: 2, 4, 6 or 8 weeks, 3 or 6 months, or a year. The answer (with a period ago → now and the change), the chart, the session list below it and its type counts all follow it, and the sport cards show the same period. The choice is kept per device; until you pick one, running and gym use 6 weeks and cycling 3 months. Running: the s/km you got faster at your reference HR, heat-adjusted, from a slope through every outdoor run's steady time at that HR (a long run counts at most 20 min). It needs 4 runs, counted back from your newest one, so the number changes only when a run comes in. Cycling: % more power per heartbeat (heat-adjusted, rides with power, at least 3). Gym: e1RM change and sessions against the same length before. Short periods react fast but are noisier; long ones show the big picture.

Readiness, the planned workouts and the plan come from Garmin endpoints GarminDB doesn't download; they are fetched after every successful sync with the same cached login (`sync/garmin_coach.py`).

## Training plan page

Tap any day of the week strip. The plan page shows the plan (name, week n of N, progress), the week as cards, and the chosen day's workout: profile, step-by-step targets, estimated load. Done days add the result — verdict, how many work blocks hit the target pace, and a link to the session. For today it also says whether you're ready for it and what it does for your weekly load, streak and form. Garmin Coach only plans about a week ahead, so that's as far as the page goes.

## Post-activity verdict

Each new activity is compared with your *similar* sessions from the last 8 to 17 weeks: same sport, same session type (easy / long / tempo / intervals / race), a comparable duration, and indoor vs outdoor kept apart. The result is **Better / In line / Worse**, with the top reasons in plain language, a confidence level, and the effect on your fitness, fatigue and form. It takes over the wall for an hour after the activity. Tapping another person's avatar pauses it — the verdict comes back after a minute without a tap; only *Overview* on the verdict ends it early.
When there are fewer than 3 comparable sessions it says **"Not comparable yet"** instead of guessing.

| Sport | What "improved" means |
|---|---|
| Running | Grade-adjusted pace per heartbeat (Minetti energy-cost model), pace at a fixed HR, aerobic decoupling (HR drift), all heat adjusted |
| Cycling (with power, e.g. a smart trainer) | Power per heartbeat and Power:HR drift (heat adjusted outdoors), best 5-min power, power-curve PRs, eFTP |
| Cycling without power | Training load only, marked low confidence (wind and terrain make speed meaningless) |
| Swimming | Pace per 100 m and SWOLF, compared only against the same main stroke |
| Gym | Estimated 1-rep max per exercise (Epley) vs the best of your last 3 sessions, plus PRs. Needs reps and weight logged on the watch |
| Everything else | Training load and recovery impact |

**Heat and humidity.** Outdoor runs and rides are adjusted for the weather during the session, for how much heat costs *you*, and for **Garmin's heat acclimation**.

The weather comes from **Open-Meteo**, which is free, needs no API key and works worldwide. Fitvio takes its hourly temperature, dew point, humidity and wind for each hour of the session, at the place you were in that hour, the same way for every watch and platform. Only a rough route is sent and stored: a point every 30 minutes, rounded to 0.1° (about 11 km). Your exact home or route never leaves the server.

If Open-Meteo can't be reached, the session falls back to the platform's weather: Garmin's weather box (a station near the start, at start time) or Intervals.icu's temperature. A later sync then fills in the hours and works the verdict out again; a verdict already shown doesn't take over the wall a second time. The history is filled in a few requests per sync. Open-Meteo can be switched off per person in the phone's **Me** screen, which brings back exactly the platform-weather verdicts.

The starting point is the runners' temperature + dew point rule: the sum in °F sets how much harder the same effort was (0 % up to 100 °F, up to 12 % above 180 °F). Fitvio applies it to each hour of the session and averages over the session's time, so a ride that ends in the midday heat counts its hot end. Heat acclimation reduces that load by up to half, which is a heuristic.

How much that load costs differs between people by a factor of two to three, and at the same heart rate it costs more than race-pace tables suggest. A lab study found 17 % less power at the same HR at 33 °C than at 18 °C, though without the airflow you get outside. So Fitvio learns your **heat response** per sport. Each steady outdoor session is compared with your similar sessions from three weeks either side, and the differences in efficiency and HR drift are set against the differences in heat. Using both sides means a summer build-up in fitness doesn't look like "heat doesn't matter". Until there are enough warm sessions, the response stays near the standard: the table for runs and half of it for rides, because riding at 25–35 km/h cools you better. Drift gets no correction until your own sessions show extra drift in the heat.

The response is relearned after syncs that bring new sessions. When it moves, the verdicts of that sport are worked out again; a verdict already shown doesn't take over the wall a second time. The phone's **Me** screen shows your factor per sport (e.g. "heat costs you 1.4× the standard"). Switching *Learn my heat response* off goes back to the standard factors. `fitvio heat-report` prints the numbers behind it. Indoor and treadmill sessions get no heat adjustment. The wrist temperature sensor isn't used for this, because body heat skews it, and FIT files use 127 as a "no value" marker.
Garmin's weather and acclimation are downloaded with each sync. For older history, run `fitvio backfill-extras` once (a first download does this automatically).

**Verdict check.** Rate *How did you feel* and *Perceived effort* on your watch after each activity. The app tracks how often the verdicts agree with how you felt, and lists the disagreements.

## Training buddy

A little animal that lives on the wall and reacts to your data: *overjoyed* after a "Better" workout or a new best, *hungry* after 3 days without training, *sleepy* when readiness or sleep is low, *happy* when you're fresh, *content* otherwise, and asleep at night. Tap it to pet it. Each person picks their own animal (mouse, cat, bunny, fox, bear, penguin, frog or hedgehog) in Accounts.

## Around the wall

- **Glance → tap → detail.** Every card opens a detail page: every number, HR and pace/power charts, laps, sets, the exact baseline sessions you were compared with, "Am I improving?" per sport, and health trends over up to 365 days. The display returns to the wall after 2 minutes idle.
- **Day and night screens.** After a minute without a tap the overview fades to a calm day screen — big clock, today's headline, a few facts and your buddy. Between `night_start` and `night_end` a dark night screen takes over. A tap wakes the wall.
- **Multi-user.** Each person has their own Garmin login and their own GarminDB. The newest activity takes over the wall with that person's avatar; tap an avatar to switch.
- **On your phone.** Open the same address on a phone (home Wi-Fi) and you get a personal app instead of the wall: pick yourself once (remembered on that phone), then four tabs — Today, Plan, Trends, Me. A fresh workout shows as a card on top of Today, not a takeover. Tap a sport (or *All activities* on Trends) for its whole history, newest first and loading as you scroll, filterable by session type. Nothing on the phone changes what the wall shows.
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
- Weather is a model value for a ~10 km grid cell, hour by hour along the route. It doesn't capture sun, shade or valleys.
- Garmin has no public webhook. A new activity is found by polling (every 2 min, 05:00–24:00); at night it waits for the hourly sync.
- Pool HR from a wrist sensor is unreliable. Swimming verdicts rely on pace and SWOLF, not HR.
- Garmin's strength categories are broad (for example "squat" covers goblet and back squat). The numeric variant is kept in the exercise key so different variants aren't mixed.
- The FIT parsing has only been tested against GarminDB's documented layout and synthetic data. Check `fitvio backtest` after your first real sync.
