import multiprocessing as mp

import numpy.testing
import pytest
import stim
from tqecd.match import MatchedDetector
from tqecd.measurement import RelativeMeasurementLocation

from tqec.circuit.measurement import Measurement
from tqec.circuit.qubit import GridQubit
from tqec.compile.detectors.compute import (
    _best_effort_filter_detectors,  # pyright: ignore[reportPrivateUsage]
    _center_plaquette_syndrome_qubits,  # pyright: ignore[reportPrivateUsage]
    _compute_detectors_at_end_of_situation,  # pyright: ignore[reportPrivateUsage]
    _compute_superimposed_template_instantiations,  # pyright: ignore[reportPrivateUsage]
    _get_measurement_offset_mapping,  # pyright: ignore[reportPrivateUsage]
    _get_or_default,  # pyright: ignore[reportPrivateUsage]
    _matched_detectors_to_detectors,  # pyright: ignore[reportPrivateUsage]
    compute_detectors_at_end_of_situation,
    compute_detectors_for_fixed_radius,
)
from tqec.compile.detectors.database import DetectorDatabase
from tqec.compile.detectors.detector import Detector
from tqec.plaquette._test_utils import make_surface_code_plaquette
from tqec.plaquette.plaquette import Plaquettes
from tqec.plaquette.rpng.rpng import RPNGDescription
from tqec.plaquette.rpng.translators.default import DefaultRPNGTranslator
from tqec.templates._testing import FixedTemplate
from tqec.templates.layout import LayoutTemplate
from tqec.templates.qubit import QubitTemplate
from tqec.templates.subtemplates import SubTemplateType
from tqec.utils.coordinates import StimCoordinates
from tqec.utils.enums import Basis
from tqec.utils.exceptions import TQECError
from tqec.utils.frozendefaultdict import FrozenDefaultDict
from tqec.utils.position import BlockPosition2D, Shift2D

_TRANSLATOR = DefaultRPNGTranslator()
_EMPTY_PLAQUETTE = _TRANSLATOR.translate(RPNGDescription.empty())


@pytest.fixture(name="alternating_subtemplate")
def alternating_subtemplate_fixture() -> SubTemplateType:
    return numpy.array([[1, 2, 1], [2, 1, 2], [1, 2, 1]])


@pytest.fixture(name="init_plaquettes")
def init_plaquettes_fixture() -> Plaquettes:
    return Plaquettes(
        FrozenDefaultDict(
            {
                1: make_surface_code_plaquette(Basis.Z, reset=Basis.Z),
                2: make_surface_code_plaquette(Basis.X, reset=Basis.Z),
            }
        )
    )


@pytest.fixture(name="memory_plaquettes")
def memory_plaquettes_fixture() -> Plaquettes:
    return Plaquettes(
        FrozenDefaultDict(
            {
                1: make_surface_code_plaquette(Basis.Z),
                2: make_surface_code_plaquette(Basis.X),
            }
        )
    )


def test_get_measurement_offset_mapping() -> None:
    assert _get_measurement_offset_mapping(stim.Circuit("QUBIT_COORDS(0, 0) 0\nM 0")) == {
        -1: Measurement(GridQubit(0, 0), -1)
    }
    assert _get_measurement_offset_mapping(
        stim.Circuit("QUBIT_COORDS(0, 0) 0\nQUBIT_COORDS(1, 1) 1\nM 0 1")
    ) == {
        -2: Measurement(GridQubit(0, 0), -1),
        -1: Measurement(GridQubit(1, 1), -1),
    }
    assert _get_measurement_offset_mapping(
        stim.Circuit("QUBIT_COORDS(0, 0) 0\nQUBIT_COORDS(1, 1) 1\nM 0 1\nTICK\nM 1 0")
    ) == {
        -1: Measurement(GridQubit(0, 0), -1),
        -2: Measurement(GridQubit(1, 1), -1),
        -3: Measurement(GridQubit(1, 1), -2),
        -4: Measurement(GridQubit(0, 0), -2),
    }


def test_matched_detectors_to_detectors() -> None:
    circuit = stim.Circuit("QUBIT_COORDS(0, 0) 0\nQUBIT_COORDS(1, 1) 1\nM 0 1\nTICK\nM 1 0")
    measurement_offset_mapping = _get_measurement_offset_mapping(circuit)
    assert _matched_detectors_to_detectors(
        [MatchedDetector((0, 0, 0), frozenset([RelativeMeasurementLocation(-1, 0)]), resets=())],
        measurement_offset_mapping,
    ) == [Detector(frozenset([Measurement(GridQubit(0, 0), -1)]), StimCoordinates(0, 0, 0))]
    assert _matched_detectors_to_detectors(
        [MatchedDetector((-1, 3, 23), frozenset([RelativeMeasurementLocation(-4, 0)]), resets=())],
        measurement_offset_mapping,
    ) == [Detector(frozenset([Measurement(GridQubit(0, 0), -2)]), StimCoordinates(-1, 3, 23))]
    assert _matched_detectors_to_detectors(
        [MatchedDetector((0, 0, 0), frozenset([RelativeMeasurementLocation(-3, 1)]), resets=())],
        measurement_offset_mapping,
    ) == [Detector(frozenset([Measurement(GridQubit(1, 1), -2)]), StimCoordinates(0, 0, 0))]


@pytest.mark.parametrize(
    "empty_center_plaquette_subtemplate",
    [numpy.array([[0]]), numpy.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])],
)
def test_center_plaquette_syndrome_qubits_empty(
    empty_center_plaquette_subtemplate: SubTemplateType,
) -> None:
    assert (
        _center_plaquette_syndrome_qubits(
            empty_center_plaquette_subtemplate,
            Plaquettes(FrozenDefaultDict({})),
            Shift2D(2, 2),
        )
        == []
    )
    assert (
        _center_plaquette_syndrome_qubits(
            empty_center_plaquette_subtemplate,
            Plaquettes(FrozenDefaultDict({}, default_value=make_surface_code_plaquette(Basis.X))),
            Shift2D(2, 2),
        )
        == []
    )
    assert (
        _center_plaquette_syndrome_qubits(
            empty_center_plaquette_subtemplate,
            Plaquettes(FrozenDefaultDict({}, default_value=make_surface_code_plaquette(Basis.X))),
            Shift2D(4, 2),
        )
        == []
    )


@pytest.mark.parametrize(
    "center_plaquette_subtemplate",
    [numpy.array([[1]]), numpy.array([[0, 0, 0], [0, 1, 0], [0, 0, 0]])],
)
def test_center_plaquette_syndrome_qubits(
    center_plaquette_subtemplate: SubTemplateType,
) -> None:
    r = center_plaquette_subtemplate.shape[0] // 2
    assert _center_plaquette_syndrome_qubits(
        center_plaquette_subtemplate,
        Plaquettes(
            FrozenDefaultDict(
                {1: make_surface_code_plaquette(Basis.X)},
                default_value=_EMPTY_PLAQUETTE,
            )
        ),
        Shift2D(2, 2),
    ) == [GridQubit(2 * r, 2 * r)]
    assert _center_plaquette_syndrome_qubits(
        center_plaquette_subtemplate,
        Plaquettes(
            FrozenDefaultDict(
                {1: make_surface_code_plaquette(Basis.X)},
                default_value=_EMPTY_PLAQUETTE,
            )
        ),
        Shift2D(4, 2),
    ) == [GridQubit(4 * r, 2 * r)]


def test_filter_detectors(
    alternating_subtemplate: SubTemplateType, init_plaquettes: Plaquettes
) -> None:
    increments = Shift2D(2, 2)
    syndrome_qubits = _center_plaquette_syndrome_qubits(
        alternating_subtemplate, init_plaquettes, increments
    )
    filtered_out_detectors = [
        Detector(
            frozenset([Measurement(GridQubit(0, 0), -1)]),
            StimCoordinates(0, 0, 0),
        ),
        Detector(
            # The function assumes that there is only one measurement per round
            # and only consider measurements in the last round, meaning that this
            # detectors will be removed.
            frozenset([Measurement(syndrome_qubits[0], -2)]),
            StimCoordinates(0, 0, 0),
        ),
    ]
    non_filtered_detectors = [
        Detector(frozenset([Measurement(syndrome_qubits[0], -1)]), StimCoordinates(0, 0, 0)),
        Detector(
            frozenset([Measurement(GridQubit(0, 0), -1), Measurement(syndrome_qubits[0], -1)]),
            StimCoordinates(0, 0, 0),
        ),
    ]
    assert (
        _best_effort_filter_detectors(
            filtered_out_detectors,
            [alternating_subtemplate],
            [init_plaquettes],
            increments,
        )
        == frozenset()
    )
    assert _best_effort_filter_detectors(
        [*filtered_out_detectors, non_filtered_detectors[0]],
        [alternating_subtemplate],
        [init_plaquettes],
        increments,
    ) == frozenset([non_filtered_detectors[0]])
    assert _best_effort_filter_detectors(
        [filtered_out_detectors[0], *non_filtered_detectors],
        [alternating_subtemplate],
        [init_plaquettes],
        increments,
    ) == frozenset(non_filtered_detectors)


def test_compute_detectors_at_end_of_situation(
    alternating_subtemplate: SubTemplateType,
    init_plaquettes: Plaquettes,
    memory_plaquettes: Plaquettes,
) -> None:
    # No detector due to empty plaquette
    increments = Shift2D(2, 2)
    assert (
        _compute_detectors_at_end_of_situation(
            [numpy.array([[0]])], [Plaquettes(FrozenDefaultDict({}))], increments
        )
        == frozenset()
    )
    assert (
        _compute_detectors_at_end_of_situation(
            [numpy.array([[1]])],
            [Plaquettes(FrozenDefaultDict({1: _EMPTY_PLAQUETTE}))],
            increments,
        )
        == frozenset()
    )
    # Detectors present

    init_round_detectors = _compute_detectors_at_end_of_situation(
        [alternating_subtemplate], [init_plaquettes], increments
    )
    assert init_round_detectors == frozenset(
        [
            Detector(
                frozenset([Measurement(GridQubit(2, 2), -1)]),
                coordinates=StimCoordinates(2, 2, 0),
            )
        ]
    )
    memory_round_detectors = _compute_detectors_at_end_of_situation(
        [alternating_subtemplate, alternating_subtemplate],
        [init_plaquettes, memory_plaquettes],
        increments,
    )
    assert memory_round_detectors == frozenset(
        [
            Detector(
                frozenset([Measurement(GridQubit(2, 2), -1), Measurement(GridQubit(2, 2), -2)]),
                coordinates=StimCoordinates(2, 2, 0),
            )
        ]
    )


def test_public_compute_detectors_at_end_of_situation(
    alternating_subtemplate: SubTemplateType, init_plaquettes: Plaquettes
) -> None:
    increments = Shift2D(2, 2)
    database = DetectorDatabase()
    # No database
    detectors = compute_detectors_at_end_of_situation(
        [alternating_subtemplate], [init_plaquettes], increments, None, False
    )
    assert len(detectors) == 1
    with pytest.raises(TQECError):
        compute_detectors_at_end_of_situation(
            [alternating_subtemplate], [init_plaquettes], increments, None, True
        )
    # With a database
    assert len(database) == 0
    with pytest.raises(TQECError):
        compute_detectors_at_end_of_situation(
            [alternating_subtemplate],
            [init_plaquettes],
            increments,
            database,
            True,
        )
    assert len(database) == 0
    detectors = compute_detectors_at_end_of_situation(
        [alternating_subtemplate], [init_plaquettes], increments, database, False
    )
    assert len(database) == 1
    assert len(detectors) == 1
    detectors = compute_detectors_at_end_of_situation(
        [alternating_subtemplate], [init_plaquettes], increments, database, True
    )
    assert len(detectors) == 1


def test_get_or_default() -> None:
    array = numpy.array([i + numpy.arange(10) for i in range(10)])
    numpy.testing.assert_array_equal(
        _get_or_default(array, [(1, 3), (2, 3)], default=0), [[3], [4]]
    )
    numpy.testing.assert_array_equal(
        _get_or_default(array, [(-1, 3), (2, 3)], default=0), [[0], [2], [3], [4]]
    )
    numpy.testing.assert_array_equal(
        _get_or_default(array, [(-1, 3), (2, 3)], default=34), [[34], [2], [3], [4]]
    )
    numpy.testing.assert_array_equal(
        _get_or_default(array, [(8, 12), (0, 1)], default=34), [[8], [9], [34], [34]]
    )
    numpy.testing.assert_array_equal(
        _get_or_default(array, [(1000, 1002), (345, 347)], default=34),
        numpy.full((2, 2), 34),
    )
    numpy.testing.assert_array_equal(
        _get_or_default(array, [(-1, 1), (0, 2)], default=42),
        [[42, 42], [0, 1]],
    )
    with pytest.raises(TQECError, match="^The provided slices should be non-empty.$"):
        _get_or_default(array, [(10, 5)], default=34)


@pytest.mark.parametrize("k", (1, 2, 5))
def test_compute_superimposed_template_instantiations_no_shift(k: int) -> None:
    template = QubitTemplate()
    templates = [QubitTemplate() for _ in range(3)]
    instantiations = _compute_superimposed_template_instantiations(templates, k)
    for inst in instantiations:
        numpy.testing.assert_array_equal(template.instantiate(k), inst)


@pytest.mark.parametrize("k", (1, 2, 5))
def test_compute_superimposed_template_instantiations_shifted(k: int) -> None:
    template = QubitTemplate()
    templates = [
        LayoutTemplate(
            {
                BlockPosition2D(0, 0): template,
                BlockPosition2D(0, 1): template,
                BlockPosition2D(1, 0): template,
                BlockPosition2D(1, 1): template,
            }
        ),
        LayoutTemplate({BlockPosition2D(0, 0): template, BlockPosition2D(1, 1): template}),
        LayoutTemplate({BlockPosition2D(1, 1): template}),
    ]
    instantiations = _compute_superimposed_template_instantiations(templates, k)
    # The only template that should be left in the returned instantiations is the
    # one at the following position, because this is the only position at which
    # `templates[-1]` is non-zero.
    pos = BlockPosition2D(1, 1)
    for i, inst in enumerate(instantiations):
        # There might be indices shifts.
        indices_map = templates[i].get_indices_map_for_instantiation()[pos]
        reverse_indices = numpy.zeros(
            (templates[i].expected_plaquettes_number + 1,), dtype=numpy.int_
        )
        for j, mapped_j in indices_map.items():
            reverse_indices[j] = mapped_j

        numpy.testing.assert_array_equal(reverse_indices[template.instantiate(k)], inst)


@pytest.mark.parametrize("k", (1, 2, 5))
def test_compute_detectors_for_fixed_radius(
    init_plaquettes: Plaquettes, memory_plaquettes: Plaquettes, k: int
) -> None:
    # A little bit hacky, but avoids having to build the full plaquette map.
    d = 2 * k + 1
    # Instantiation of the template defined below:
    # 1 2 1 ... 2 1
    # 2 1 2 ... 1 2
    # . . . . . . .
    # . . . . . . .
    # . . . . . . .
    # 1 2 1 ... 2 1
    template = FixedTemplate([[0 if (i + j) % 2 == 0 else 1 for j in range(d)] for i in range(d)])
    detectors = compute_detectors_for_fixed_radius([template], k, [init_plaquettes])
    assert len(detectors) == (k + 1) ** 2 + k**2

    detectors = compute_detectors_for_fixed_radius(
        [template, template], k, [init_plaquettes, memory_plaquettes]
    )
    assert len(detectors) == d**2

    # Test the parallel parameter
    # Should get the same results with parallelization as without
    parallel_detectors = compute_detectors_for_fixed_radius(
        [template, template],
        k,
        [init_plaquettes, memory_plaquettes],
        parallel_process_count=mp.cpu_count() // 2 + 1,
    )
    assert set(parallel_detectors) == set(detectors)
