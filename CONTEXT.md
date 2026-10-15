# Fitvio

A wall-mounted fitness and health dashboard for a household, with a phone companion, built on each person's Garmin or Intervals.icu data.

## Language

**Training buddy**:
A little animal per person, on the wall and the phone, whose mood follows that person's data. Each person picks its animal, or **none** to hide it everywhere; picking none keeps the chosen animal for when they pick one again.
_Avoid_: pet

**Shared person**:
A person who chose **Share** under Home Assistant (Accounts or the phone's Me screen). Only shared people's numbers and workouts are published to the MQTT broker; nobody is shared by default, and choosing **None** again removes them from Home Assistant.

**Home Assistant device**:
How a shared person appears in Home Assistant: one device, "Fitvio <name>", holding their sensors, the *Sync now* button and the new-workout, sync-failed and login-expired events.
_Avoid_: integration (Fitvio has no Home Assistant integration of its own; it uses MQTT discovery)

## Example dialogue

> **Dev:** "If Alex hides their **training buddy**, does it still appear sleeping on the night screen?"
> **Domain expert:** "No — none means none, everywhere: wall, night screen and phone."

> **Dev:** "Sam shares with Home Assistant but Alex doesn't. Does Alex's new workout still flash the lights?"
> **Domain expert:** "No. Alex isn't a **shared person**, so there's no **Home Assistant device** for Alex and nothing about Alex reaches the broker."
