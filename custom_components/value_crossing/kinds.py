"""Physical-kind abstraction and registry for value_crossing.

A ``PhysicalKind`` couples the units / device classes of a physical quantity to
its default estimation model (and a default band and label). A pair's kind is
auto-detected from its source sensors' ``unit_of_measurement`` / ``device_class``;
the resolved kind supplies the default estimator, which the user may override.

To add a new physical quantity: subclass ``PhysicalKind`` and decorate it with
``@register``. No other module needs to change.

This module is intentionally free of any ``homeassistant`` import so it can be
unit-tested in isolation.
"""

from __future__ import annotations

from .const import DEFAULT_WINDOW, MODEL_EXPONENTIAL, MODEL_LINEAR, MODEL_POWER


class PhysicalKind:
    """A physical quantity: its units/device-classes and default estimator.

    Declarative base class: subclasses set the class attributes below and
    register via ``@register``. Instances are stateless singletons held in
    ``KINDS``. Not instantiated directly (use a concrete subclass).
    """

    key: str = "base"
    label: str = "Base"
    default_model: str = MODEL_LINEAR
    default_band: float = 0.0
    default_window: float = DEFAULT_WINDOW  # seconds of history fed to the fit
    units: frozenset[str] = frozenset()
    device_classes: frozenset[str] = frozenset()

    def matches_unit(self, unit: str | None) -> bool:
        """True if ``unit`` is one this kind covers."""
        return unit is not None and unit in self.units

    def matches_device_class(self, device_class: str | None) -> bool:
        """True if ``device_class`` is one this kind covers."""
        return device_class is not None and device_class in self.device_classes


# Registration order is the tie-break order within each matching pass.
KINDS: list[PhysicalKind] = []


def register(cls: type[PhysicalKind]) -> type[PhysicalKind]:
    """Class decorator: add a ``PhysicalKind`` subclass to the registry."""
    KINDS.append(cls())
    return cls


@register
class TemperatureKind(PhysicalKind):
    """Temperatures: relax toward a limit, so default to the exponential model."""

    key = "temperature"
    label = "Temperature"
    default_model = MODEL_EXPONENTIAL
    default_band = 0.5
    default_window = 3600  # temperature drifts slowly; a longer window is steadier
    units = frozenset({"°C", "°F", "K"})
    device_classes = frozenset({"temperature"})


@register
class PowerKind(PhysicalKind):
    """Electrical power: noisy/random, so default to the robust power model."""

    key = "power"
    label = "Power"
    default_model = MODEL_POWER
    default_band = 50.0
    units = frozenset({"W", "kW"})
    device_classes = frozenset({"power"})


@register
class EnergyKind(PhysicalKind):
    """Accumulated energy: steady trends, so default to the linear model."""

    key = "energy"
    label = "Energy"
    default_model = MODEL_LINEAR
    default_band = 0.1
    units = frozenset({"Wh", "kWh"})
    device_classes = frozenset({"energy"})


class GenericKind(PhysicalKind):
    """Fallback when no registered kind matches the unit/device-class."""

    key = "generic"
    label = "Generic"
    default_model = MODEL_LINEAR
    default_band = 0.0


# Single fallback instance; deliberately not in ``KINDS`` (it matches nothing).
GENERIC = GenericKind()


def resolve(
    unit: str | None = None, device_class: str | None = None
) -> PhysicalKind:
    """Resolve the physical kind for a source sensor.

    Precedence: ``device_class`` match first, then ``unit`` match, then the
    ``GenericKind`` fallback (also used for missing/unknown units).
    """
    for kind in KINDS:
        if kind.matches_device_class(device_class):
            return kind
    for kind in KINDS:
        if kind.matches_unit(unit):
            return kind
    return GENERIC
