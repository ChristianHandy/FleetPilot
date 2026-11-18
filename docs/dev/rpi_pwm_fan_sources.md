# GeeekPi three-wire PWM fan: verified wiring and kernel control

## Product and wiring

The user’s case is the GeeekPi Raspberry Pi 4 ABS case sold on Amazon Germany as ASIN `B07XCKNM8J`. Its listing identifies an included `40 × 40 × 10 mm PWM` fan.

The 52Pi documentation for the matching three-wire PWM fan design states the pinout:

- **Red**: Raspberry Pi **5 V**.
- **Black**: Raspberry Pi **GND**.
- **Blue**: Raspberry Pi **GPIO supporting PWM output**.

For the GeeekPi installation used here, the intended physical header locations are:

| Fan wire | Physical pin | BCM function |
|---|---:|---|
| Red | 4 | 5 V power |
| Black | 6 | Ground |
| Blue | 8 | GPIO14 PWM signal |

## Kernel PWM controller

The Raspberry Pi has the built-in `pwm-gpio-fan` device-tree overlay. On the live Pi, its documented parameters include `fan_gpio`, four temperature levels, hysteresis values, and PWM duty values. The live configuration uses GPIO14 with a conservative curve: 45% at 45 °C, 60% at 55 °C, 80% at 65 °C, and 100% at 75 °C.

## Sources

1. Amazon product listing: https://www.amazon.de/GeeekPi-Geh%C3%A4use-Raspberry-40X40X10mm-K%C3%BChlk%C3%B6rper/dp/B07XCKNM8J
2. 52Pi three-wire PWM fan documentation: https://wiki.52pi.com/index.php/EP-0107
3. Raspberry Pi PWM overlay discussion: https://forums.raspberrypi.com/viewtopic.php?t=343570
4. Independent three-wire Raspberry Pi PWM wiring example: https://torgeir.dev/2023/08/pwm-fan-on-raspberry-pi-4/

## Implementation implication

FleetPilot must not use static `pinctrl set` binary switching for this device. It should report the Linux `pwm-fan` cooling-device state and leave the persistent temperature curve to the kernel overlay.
