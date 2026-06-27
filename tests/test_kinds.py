"""Unit tests for the physical-kind registry (ARCH-01)."""

from __future__ import annotations

from custom_components.value_crossing import kinds
from custom_components.value_crossing.const import (
    MODEL_EXPONENTIAL,
    MODEL_LINEAR,
    MODEL_POWER,
)
from custom_components.value_crossing.kinds import (
    GenericKind,
    PhysicalKind,
    PowerKind,
    TemperatureKind,
    register,
    resolve,
)


def test_resolve_by_unit() -> None:
    assert isinstance(resolve(unit="°C"), TemperatureKind)
    assert isinstance(resolve(unit="W"), PowerKind)


def test_resolve_by_device_class() -> None:
    assert isinstance(resolve(device_class="temperature"), TemperatureKind)
    assert isinstance(resolve(device_class="power"), PowerKind)


def test_device_class_takes_precedence_over_unit() -> None:
    # Unit says power, device_class says temperature -> device_class wins.
    resolved = resolve(unit="W", device_class="temperature")
    assert isinstance(resolved, TemperatureKind)


def test_generic_fallback_for_unknown_and_missing() -> None:
    assert isinstance(resolve(unit="lux"), GenericKind)
    assert isinstance(resolve(), GenericKind)
    assert isinstance(resolve(device_class="illuminance"), GenericKind)


def test_default_model_bindings() -> None:
    assert TemperatureKind.default_model == MODEL_EXPONENTIAL
    assert PowerKind.default_model == MODEL_POWER
    assert resolve(unit="kWh").default_model == MODEL_LINEAR
    assert GenericKind.default_model == MODEL_LINEAR


def test_adding_a_kind_is_isolated() -> None:
    """Registering a new kind makes resolve() find it, with no other edits."""

    @register
    class FrobnitzKind(PhysicalKind):
        key = "frobnitz"
        label = "Frobnitz"
        default_model = MODEL_LINEAR
        default_band = 1.0
        units = frozenset({"fb"})
        device_classes = frozenset({"frobnitz"})

    try:
        assert isinstance(resolve(unit="fb"), FrobnitzKind)
        assert isinstance(resolve(device_class="frobnitz"), FrobnitzKind)
    finally:
        # Keep global registry clean for other tests.
        kinds.KINDS[:] = [k for k in kinds.KINDS if not isinstance(k, FrobnitzKind)]

    assert isinstance(resolve(unit="fb"), GenericKind)
