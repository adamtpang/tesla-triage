"""Tests for the urgency rules and the traps in this batch.

Run: python -m unittest
"""

import unittest

from pydantic import ValidationError

from rules import RULES, AlertCodeRule, FaultMessage, Tag, UrgencyRules
from triage import tag_message


def msg(text, subject="", code="NONE", **over):
    row = {"message_id": "MSG-00001", "received_at": "2026-11-15T18:00:00", "channel": "email",
           "customer_name": "Test Driver", "vehicle_model": "Model 3", "model_year": "2022",
           "vin_last6": "ABC123", "odometer_km": "1000", "service_center": "Fremont Service Center",
           "vehicle_alert_code": code, "message_subject": subject, "message_text": text,
           "hand_checked": "FALSE", "hand_checked_safety_fault": "FALSE"}
    row.update(over)
    return FaultMessage.model_validate(row)


def tag(text, **kw):
    return tag_message(msg(text, **kw)).tag


class AlertCodes(unittest.TestCase):
    def test_every_safety_code_is_safety_urgent(self):
        for code in ["BRK_a001", "BRK_w003", "ABS_w002", "ESP_w003", "EPAS_w202", "EPAS_a191"]:
            self.assertEqual(tag("A warning came on.", code=code), Tag.SAFETY_URGENT, code)

    def test_non_safety_codes(self):
        self.assertEqual(tag("Charge port will not latch.", code="CP_a004"), Tag.SOON)
        self.assertEqual(tag("Cabin is slow to heat.", code="HVAC_w003"), Tag.ROUTINE)
        self.assertEqual(tag("Screen froze once.", code="UI_a004"), Tag.ROUTINE)

    def test_unknown_code_is_not_silently_routine(self):
        d = tag_message(msg("Something came on.", code="XYZ_w999"))
        self.assertEqual(d.tag, Tag.SOON)
        self.assertTrue(d.flags)


class HiddenSafetyRule(unittest.TestCase):
    def test_polite_soft_pedal_with_no_alert(self):
        d = tag_message(msg("No rush at all, the car is lovely. The brake pedal feels a bit "
                            "softer and sinks a little further before it bites. Happy to wait."))
        self.assertEqual(d.tag, Tag.SAFETY_URGENT)
        self.assertTrue(d.soft_tone)

    def test_grinding_when_stopped_at_lights(self):
        self.assertEqual(tag("There's a grinding noise from the front wheels when I'm stopped "
                             "at the lights. Thanks so much."), Tag.SAFETY_URGENT)

    def test_pulls_when_braking(self):
        self.assertEqual(tag("The car tugs to the left when I brake gently."), Tag.SAFETY_URGENT)

    def test_alarming_wiper_is_not_safety(self):
        self.assertEqual(tag("The wiper arm makes a horrible grinding noise when it parks and "
                             "sounds like something is about to snap."), Tag.ROUTINE)

    def test_brakes_feel_normal_is_not_a_fault(self):
        self.assertEqual(tag("Clunk over speed bumps. The car drives normally and the brakes "
                             "feel just the same as always."), Tag.ROUTINE)
        self.assertEqual(tag("A thump over joints. The car still tracks straight and brakes and "
                             "steers exactly as before."), Tag.ROUTINE)


class Soon(unittest.TestCase):
    def test_streak_across_view_is_soon(self):
        self.assertEqual(tag("The wiper leaves a big streak across my eyeline in the rain."),
                         Tag.SOON)

    def test_cut_off_message_is_soon(self):
        d = tag_message(msg("Owner says the charge port latch sticks and the owner is"))
        self.assertEqual(d.tag, Tag.SOON)

    def test_cut_off_safety_message_stays_safety_urgent(self):
        d = tag_message(msg("Owner says ABS light came on and the call dropped while describing the",
                            code="ABS_w002"))
        self.assertEqual(d.tag, Tag.SAFETY_URGENT)
        self.assertTrue(d.flags)

    def test_sign_off_is_not_cut_off(self):
        self.assertEqual(tag("Cabin fan is loud. Could it be looked at? Thanks, Dana"), Tag.ROUTINE)


class RuleValidation(unittest.TestCase):
    def test_safety_code_cannot_be_tagged_routine(self):
        with self.assertRaises(ValidationError):
            AlertCodeRule(code="BRK_a001", system="brakes", safety_fault=True,
                          tag=Tag.ROUTINE, why="wrong")

    def test_missing_fix_path_is_rejected(self):
        data = RULES.model_dump()
        data["fix_paths"] = data["fix_paths"][:2]
        with self.assertRaises(ValidationError):
            UrgencyRules.model_validate(data)

    def test_response_windows_must_get_longer(self):
        data = RULES.model_dump()
        data["fix_paths"][0]["respond_within_hours"] = 100
        with self.assertRaises(ValidationError):
            UrgencyRules.model_validate(data)

    def test_bad_regex_is_rejected(self):
        data = RULES.model_dump()
        data["soon_symptoms"][0]["patterns"] = ["(unclosed"]
        with self.assertRaises(ValidationError):
            UrgencyRules.model_validate(data)

    def test_bad_message_row_is_rejected(self):
        with self.assertRaises(ValidationError):
            msg("text", vin_last6="bad")


class Ordering(unittest.TestCase):
    def test_car_off_the_road_goes_first(self):
        d = tag_message(msg("My brake pedal dropped to the floor. I have not driven it since."))
        self.assertTrue(d.off_the_road)


if __name__ == "__main__":
    unittest.main()
