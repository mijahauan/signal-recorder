#!/usr/bin/env python3
"""
Transmission Time Solver - Back-Calculate UTC(NIST) from Observed Arrival Times

This module implements the "Holy Grail" of HF time transfer: turning a passive
receiver into a PRIMARY frequency/time standard by back-calculating the actual
emission time at WWV/WWVH.

Physics Background:
-------------------
T_emit = T_arrival - T_prop

Where T_prop = τ_geo + τ_iono + τ_mode
  - τ_geo:  Speed-of-light time for Great Circle distance (invariant)
  - τ_iono: Wave slowing due to ionospheric electron density
  - τ_mode: Extra path length from ionospheric hops (N bounces)

Key Insight:
------------
Propagation modes are DISCRETE. For a given path, the possible delays are:
  - Ground wave: ~distance/c
  - 1-hop E-layer (1E): ~110 km reflection height
  - 1-hop F-layer (1F): ~250-350 km reflection height  
  - 2-hop F-layer (2F): Two bounces, longer path
  - etc.

By calculating all possible mode delays and matching to observed ToA, we can:
1. Identify the propagation mode
2. Subtract the correct delay
3. Recover UTC(NIST) with ~1ms accuracy

Usage:
------
    solver = TransmissionTimeSolver(
        receiver_lat=39.0, receiver_lon=-94.5,  # Kansas
        sample_rate=20000
    )
    
    # Solve for transmission time given observed arrival
    result = solver.solve(
        station='WWV',
        frequency_mhz=10.0,
        arrival_rtp=12345678,      # RTP timestamp of detected pulse
        delay_spread_ms=0.5,       # From correlation analysis
        doppler_std_hz=0.1,        # Path stability indicator
        fss_db=-2.0               # Frequency selectivity (D-layer indicator)
    )
    
    print(f"Mode: {result.mode}")           # "1F2" 
    print(f"T_emit offset: {result.emission_offset_ms:.2f} ms")  # -14.23
    print(f"Confidence: {result.confidence:.1%}")  # 95%
"""

import math
import logging
from typing import Optional, List, Dict, Tuple, NamedTuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Physical constants
SPEED_OF_LIGHT_KM_S = 299792.458  # km/s
EARTH_RADIUS_KM = 6371.0

# Ionospheric layer heights (typical, varies with time of day and solar activity)
E_LAYER_HEIGHT_KM = 110.0    # E-layer (daytime)
F1_LAYER_HEIGHT_KM = 200.0   # F1-layer (daytime)
F2_LAYER_HEIGHT_KM = 300.0   # F2-layer (day and night, primary HF reflector)
F2_NIGHT_HEIGHT_KM = 350.0   # F2-layer at night (rises)

# Station locations (WGS84)
STATIONS = {
    'WWV': {'lat': 40.6781, 'lon': -105.0469, 'name': 'Fort Collins, CO'},
    'WWVH': {'lat': 21.9869, 'lon': -159.7644, 'name': 'Kauai, HI'},
    'CHU': {'lat': 45.2950, 'lon': -75.7564, 'name': 'Ottawa, ON'},
}

# Ionospheric delay factor (approximate, frequency-dependent)
# Higher frequencies experience less ionospheric delay
IONO_DELAY_FACTOR = {
    2.5: 1.5,   # More delay at lower frequencies
    3.33: 1.3,
    5.0: 1.1,
    7.85: 1.05,
    10.0: 1.0,   # Reference
    14.67: 0.95,
    15.0: 0.95,
    20.0: 0.9,
    25.0: 0.85,
}


class PropagationMode(Enum):
    """Discrete propagation modes for HF signals"""
    GROUND_WAVE = "GW"      # Direct ground wave (short range only)
    ONE_HOP_E = "1E"        # Single E-layer reflection
    ONE_HOP_F = "1F"        # Single F-layer reflection
    TWO_HOP_F = "2F"        # Two F-layer reflections
    THREE_HOP_F = "3F"      # Three F-layer reflections
    MIXED_EF = "EF"         # E-layer + F-layer combination
    UNKNOWN = "UNK"


@dataclass
class ModeCandidate:
    """A candidate propagation mode with calculated delay"""
    mode: PropagationMode
    layer_height_km: float
    n_hops: int
    path_length_km: float
    geometric_delay_ms: float
    iono_delay_ms: float
    total_delay_ms: float
    elevation_angle_deg: float
    plausibility: float  # 0-1, based on physics constraints


@dataclass 
class SolverResult:
    """Result of transmission time back-calculation"""
    # Timing results
    arrival_rtp: int
    emission_rtp: int  # Back-calculated emission time in RTP units
    emission_offset_ms: float  # Offset from second boundary (should be ~0 for top-of-second)
    propagation_delay_ms: float
    
    # Mode identification
    mode: PropagationMode
    mode_name: str  # Human readable, e.g., "1-hop F2 layer"
    n_hops: int
    layer_height_km: float
    elevation_angle_deg: float
    
    # Confidence metrics
    confidence: float  # 0-1 overall confidence
    mode_separation_ms: float  # Gap to next-best mode (larger = more confident)
    delay_spread_penalty: float  # Multipath indicator reduces confidence
    doppler_penalty: float  # Unstable path reduces confidence
    fss_consistency: float  # Does FSS match expected for this mode?
    
    # All candidates considered
    candidates: List[ModeCandidate] = field(default_factory=list)
    
    # UTC(NIST) verification
    utc_nist_offset_ms: Optional[float] = None  # Offset from expected UTC second
    utc_nist_verified: bool = False  # True if offset < threshold


class TransmissionTimeSolver:
    """
    Solve for transmission time by identifying propagation mode.
    
    This turns a passive receiver into a primary time standard by
    back-calculating when the signal was actually transmitted at
    WWV/WWVH/CHU, recovering UTC(NIST) with ~1ms accuracy.
    """
    
    def __init__(
        self,
        receiver_lat: float,
        receiver_lon: float,
        sample_rate: int = 20000,
        f_layer_height_km: float = F2_LAYER_HEIGHT_KM
    ):
        """
        Initialize solver with receiver location.
        
        Args:
            receiver_lat: Receiver latitude (degrees, WGS84)
            receiver_lon: Receiver longitude (degrees, WGS84)
            sample_rate: Audio sample rate (Hz), used for RTP conversion
            f_layer_height_km: Assumed F-layer height (can vary with time)
        """
        self.receiver_lat = receiver_lat
        self.receiver_lon = receiver_lon
        self.sample_rate = sample_rate
        self.f_layer_height_km = f_layer_height_km
        
        # Pre-calculate distances to each station
        self.station_distances = {}
        for station, loc in STATIONS.items():
            dist = self._great_circle_distance(
                receiver_lat, receiver_lon,
                loc['lat'], loc['lon']
            )
            self.station_distances[station] = dist
            logger.info(f"Distance to {station}: {dist:.1f} km")
    
    def _great_circle_distance(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        """Calculate great circle distance in km using Haversine formula."""
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * 
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return EARTH_RADIUS_KM * c
    
    def _calculate_hop_path(
        self,
        ground_distance_km: float,
        layer_height_km: float,
        n_hops: int
    ) -> Tuple[float, float]:
        """
        Calculate path length and elevation angle for N-hop propagation.
        
        Args:
            ground_distance_km: Great circle distance on ground
            layer_height_km: Ionospheric layer height
            n_hops: Number of ionospheric reflections
            
        Returns:
            (path_length_km, elevation_angle_deg)
        """
        if n_hops == 0:
            # Ground wave
            return ground_distance_km, 0.0
        
        # Distance per hop (on ground)
        hop_distance = ground_distance_km / n_hops
        
        # Half the hop distance (to the reflection point)
        half_hop = hop_distance / 2
        
        # Elevation angle (from horizon)
        # tan(elevation) = layer_height / half_hop_distance
        elevation_rad = math.atan2(layer_height_km, half_hop)
        elevation_deg = math.degrees(elevation_rad)
        
        # Path length per hop: up to layer, then down
        # Using Pythagorean theorem (simplified, ignores Earth curvature for short hops)
        slant_range = math.sqrt(half_hop ** 2 + layer_height_km ** 2)
        path_per_hop = 2 * slant_range  # Up and down
        
        total_path = path_per_hop * n_hops
        
        return total_path, elevation_deg
    
    def _calculate_mode_delay(
        self,
        mode: PropagationMode,
        ground_distance_km: float,
        frequency_mhz: float
    ) -> Optional[ModeCandidate]:
        """
        Calculate propagation delay for a specific mode.
        
        Returns ModeCandidate with all timing details, or None if mode
        is physically implausible for this path.
        """
        # Determine layer height and hop count
        if mode == PropagationMode.GROUND_WAVE:
            if ground_distance_km > 200:  # Ground wave limited range
                return None
            layer_height = 0
            n_hops = 0
        elif mode == PropagationMode.ONE_HOP_E:
            layer_height = E_LAYER_HEIGHT_KM
            n_hops = 1
            # E-layer only works for shorter paths
            if ground_distance_km > 2500:
                return None
        elif mode == PropagationMode.ONE_HOP_F:
            layer_height = self.f_layer_height_km
            n_hops = 1
            # Check if single hop can reach (max ~4000 km)
            if ground_distance_km > 4000:
                return None
        elif mode == PropagationMode.TWO_HOP_F:
            layer_height = self.f_layer_height_km
            n_hops = 2
        elif mode == PropagationMode.THREE_HOP_F:
            layer_height = self.f_layer_height_km
            n_hops = 3
        elif mode == PropagationMode.MIXED_EF:
            # Approximate as 1.5 hops at intermediate height
            layer_height = (E_LAYER_HEIGHT_KM + self.f_layer_height_km) / 2
            n_hops = 2
        else:
            return None
        
        # Calculate path geometry
        path_length_km, elevation_deg = self._calculate_hop_path(
            ground_distance_km, layer_height, n_hops
        )
        
        # Check elevation angle plausibility (< 5° is very low, may not propagate)
        if n_hops > 0 and elevation_deg < 3:
            plausibility = 0.3  # Low but possible
        elif n_hops > 0 and elevation_deg < 10:
            plausibility = 0.7
        else:
            plausibility = 1.0
        
        # Geometric delay (speed of light)
        geometric_delay_ms = (path_length_km / SPEED_OF_LIGHT_KM_S) * 1000
        
        # Ionospheric delay (frequency-dependent, more delay at lower frequencies)
        iono_factor = IONO_DELAY_FACTOR.get(frequency_mhz, 1.0)
        # Approximate ionospheric delay: ~0.1-0.3 ms per hop for HF
        iono_delay_ms = n_hops * 0.15 * iono_factor
        
        total_delay_ms = geometric_delay_ms + iono_delay_ms
        
        return ModeCandidate(
            mode=mode,
            layer_height_km=layer_height,
            n_hops=n_hops,
            path_length_km=path_length_km,
            geometric_delay_ms=geometric_delay_ms,
            iono_delay_ms=iono_delay_ms,
            total_delay_ms=total_delay_ms,
            elevation_angle_deg=elevation_deg,
            plausibility=plausibility
        )
    
    def _evaluate_mode_fit(
        self,
        candidate: ModeCandidate,
        observed_delay_ms: float,
        delay_spread_ms: float,
        doppler_std_hz: float,
        fss_db: Optional[float]
    ) -> float:
        """
        Evaluate how well a mode candidate fits the observed data.
        
        Returns a score 0-1 where higher is better fit.
        
        CRITICAL MODE DISAMBIGUATION:
        - High delay_spread_ms → favor higher hop count (multipath)
        - Negative FSS → favor higher hop count (D-layer attenuation)
        - When modes are close in delay, these factors break the tie
        """
        # Base score: how close is predicted delay to observed?
        delay_error_ms = abs(candidate.total_delay_ms - observed_delay_ms)
        
        # Delay errors > 2ms are very unlikely to be correct mode
        if delay_error_ms > 2.0:
            delay_score = 0.1
        elif delay_error_ms > 1.0:
            delay_score = 0.5
        elif delay_error_ms > 0.5:
            delay_score = 0.8
        else:
            delay_score = 1.0
        
        # === CRITICAL: Delay spread as multipath indicator ===
        # High delay spread strongly suggests multi-hop propagation
        # This is a TIE-BREAKER when two modes have similar delays
        spread_penalty = 1.0
        multipath_bonus = 0.0
        
        if delay_spread_ms > 1.5:
            # Very high spread: almost certainly multi-hop
            if candidate.n_hops >= 2:
                multipath_bonus = 0.15  # Boost multi-hop modes
            elif candidate.n_hops == 1:
                spread_penalty = 0.6  # Heavily penalize single-hop
        elif delay_spread_ms > 1.0:
            # High spread: likely multi-hop
            if candidate.n_hops >= 2:
                multipath_bonus = 0.10
            elif candidate.n_hops == 1:
                spread_penalty = 0.7
        elif delay_spread_ms > 0.5:
            # Moderate spread: slight preference for multi-hop
            if candidate.n_hops >= 2:
                multipath_bonus = 0.05
            else:
                spread_penalty = 0.9
        
        # Doppler penalty: high Doppler std means unstable path
        if doppler_std_hz > 0.5:
            doppler_penalty = 0.7
        elif doppler_std_hz > 0.2:
            doppler_penalty = 0.9
        else:
            doppler_penalty = 1.0
        
        # === CRITICAL: FSS integration for D-layer detection ===
        # Negative FSS (high frequencies attenuated) indicates D-layer traversal
        # More hops = more D-layer transits = more negative FSS expected
        fss_score = 1.0
        fss_bonus = 0.0
        
        if fss_db is not None:
            # Model: Each hop through D-layer attenuates highs by ~0.8 dB
            expected_fss = -0.8 * candidate.n_hops
            fss_error = abs(fss_db - expected_fss)
            
            # If FSS is very negative (strong D-layer attenuation)
            if fss_db < -2.0:
                # Should be multi-hop; penalize single-hop
                if candidate.n_hops >= 2:
                    fss_bonus = 0.10
                elif candidate.n_hops == 1:
                    fss_score = 0.7
            elif fss_db < -1.0:
                # Moderate D-layer effect
                if candidate.n_hops >= 2:
                    fss_bonus = 0.05
            
            # Also penalize if FSS doesn't match expectation
            if fss_error > 3:
                fss_score *= 0.8
            elif fss_error > 1.5:
                fss_score *= 0.9
        
        # Combine scores
        # Note: bonuses are additive, penalties are multiplicative
        total_score = (
            delay_score * 
            candidate.plausibility * 
            spread_penalty * 
            doppler_penalty * 
            fss_score
        ) + multipath_bonus + fss_bonus
        
        # Clamp to [0, 1]
        total_score = min(1.0, max(0.0, total_score))
        
        return total_score
    
    def solve(
        self,
        station: str,
        frequency_mhz: float,
        arrival_rtp: int,
        delay_spread_ms: float = 0.0,
        doppler_std_hz: float = 0.0,
        fss_db: Optional[float] = None,
        expected_second_rtp: Optional[int] = None
    ) -> SolverResult:
        """
        Solve for transmission time by identifying propagation mode.
        
        Args:
            station: 'WWV', 'WWVH', or 'CHU'
            frequency_mhz: Carrier frequency
            arrival_rtp: RTP timestamp of detected signal arrival
            delay_spread_ms: Observed delay spread (multipath indicator)
            doppler_std_hz: Doppler standard deviation (path stability)
            fss_db: Frequency Selectivity Strength (D-layer indicator)
            expected_second_rtp: RTP timestamp of expected second boundary
            
        Returns:
            SolverResult with mode identification and back-calculated time
        """
        if station not in self.station_distances:
            raise ValueError(f"Unknown station: {station}")
        
        ground_distance = self.station_distances[station]
        
        # Calculate all plausible mode candidates
        candidates = []
        for mode in PropagationMode:
            if mode == PropagationMode.UNKNOWN:
                continue
            candidate = self._calculate_mode_delay(mode, ground_distance, frequency_mhz)
            if candidate:
                candidates.append(candidate)
        
        if not candidates:
            logger.warning(f"No valid propagation modes for {station} at {ground_distance:.0f} km")
            return self._no_solution(arrival_rtp)
        
        # Calculate observed delay (from expected second boundary)
        if expected_second_rtp is not None:
            observed_delay_samples = arrival_rtp - expected_second_rtp
            observed_delay_ms = (observed_delay_samples / self.sample_rate) * 1000
        else:
            # Estimate from minimum plausible delay
            min_delay = min(c.total_delay_ms for c in candidates)
            observed_delay_ms = min_delay  # Assume we're close to minimum
        
        # Score each candidate
        scored_candidates = []
        for candidate in candidates:
            score = self._evaluate_mode_fit(
                candidate, observed_delay_ms,
                delay_spread_ms, doppler_std_hz, fss_db
            )
            scored_candidates.append((score, candidate))
        
        # Sort by score (best first)
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        
        best_score, best_candidate = scored_candidates[0]
        
        # Calculate mode separation (confidence indicator)
        if len(scored_candidates) > 1:
            second_score = scored_candidates[1][0]
            mode_separation = best_score - second_score
            # Also calculate delay separation
            delay_separation_ms = abs(
                best_candidate.total_delay_ms - 
                scored_candidates[1][1].total_delay_ms
            )
        else:
            mode_separation = 1.0
            delay_separation_ms = 10.0
        
        # Back-calculate emission time
        propagation_samples = int(
            (best_candidate.total_delay_ms / 1000) * self.sample_rate
        )
        emission_rtp = arrival_rtp - propagation_samples
        
        # Calculate offset from second boundary
        if expected_second_rtp is not None:
            emission_offset_samples = emission_rtp - expected_second_rtp
            emission_offset_ms = (emission_offset_samples / self.sample_rate) * 1000
            
            # Check if this looks like valid UTC(NIST)
            # WWV transmits at exact second boundaries, so offset should be ~0
            utc_verified = abs(emission_offset_ms) < 2.0  # Within 2ms of second
        else:
            emission_offset_ms = 0.0
            utc_verified = False
        
        # Build human-readable mode name
        mode_names = {
            PropagationMode.GROUND_WAVE: "Ground wave",
            PropagationMode.ONE_HOP_E: "1-hop E-layer",
            PropagationMode.ONE_HOP_F: "1-hop F-layer",
            PropagationMode.TWO_HOP_F: "2-hop F-layer",
            PropagationMode.THREE_HOP_F: "3-hop F-layer",
            PropagationMode.MIXED_EF: "Mixed E/F-layer",
        }
        
        # Calculate confidence
        confidence = best_score * min(1.0, delay_separation_ms / 0.5)
        
        # Apply penalties
        delay_spread_penalty = 1.0 if delay_spread_ms < 0.5 else 0.8
        doppler_penalty = 1.0 if doppler_std_hz < 0.2 else 0.8
        
        return SolverResult(
            arrival_rtp=arrival_rtp,
            emission_rtp=emission_rtp,
            emission_offset_ms=emission_offset_ms,
            propagation_delay_ms=best_candidate.total_delay_ms,
            mode=best_candidate.mode,
            mode_name=mode_names.get(best_candidate.mode, "Unknown"),
            n_hops=best_candidate.n_hops,
            layer_height_km=best_candidate.layer_height_km,
            elevation_angle_deg=best_candidate.elevation_angle_deg,
            confidence=confidence,
            mode_separation_ms=delay_separation_ms,
            delay_spread_penalty=delay_spread_penalty,
            doppler_penalty=doppler_penalty,
            fss_consistency=1.0,  # TODO: Implement
            candidates=[c for _, c in scored_candidates],
            utc_nist_offset_ms=emission_offset_ms if expected_second_rtp else None,
            utc_nist_verified=utc_verified
        )
    
    def _no_solution(self, arrival_rtp: int) -> SolverResult:
        """Return a result indicating no valid solution."""
        return SolverResult(
            arrival_rtp=arrival_rtp,
            emission_rtp=arrival_rtp,
            emission_offset_ms=0.0,
            propagation_delay_ms=0.0,
            mode=PropagationMode.UNKNOWN,
            mode_name="Unknown",
            n_hops=0,
            layer_height_km=0.0,
            elevation_angle_deg=0.0,
            confidence=0.0,
            mode_separation_ms=0.0,
            delay_spread_penalty=1.0,
            doppler_penalty=1.0,
            fss_consistency=0.0,
            candidates=[],
            utc_nist_offset_ms=None,
            utc_nist_verified=False
        )
    
    def solve_multi_frequency(
        self,
        station: str,
        observations: List[Dict],
        expected_second_rtp: int
    ) -> SolverResult:
        """
        Solve using observations from multiple frequencies.
        
        This provides higher confidence by requiring mode consistency
        across frequencies. Different frequencies may use different modes
        but should all point to the same emission time.
        
        Args:
            station: 'WWV', 'WWVH', or 'CHU'
            observations: List of dicts with keys:
                - frequency_mhz
                - arrival_rtp
                - delay_spread_ms (optional)
                - doppler_std_hz (optional)
                - fss_db (optional)
                - snr_db (optional, for weighting)
            expected_second_rtp: RTP timestamp of expected second boundary
            
        Returns:
            Combined SolverResult with multi-frequency confidence
        """
        if not observations:
            raise ValueError("No observations provided")
        
        # Solve each frequency independently
        results = []
        for obs in observations:
            result = self.solve(
                station=station,
                frequency_mhz=obs['frequency_mhz'],
                arrival_rtp=obs['arrival_rtp'],
                delay_spread_ms=obs.get('delay_spread_ms', 0.0),
                doppler_std_hz=obs.get('doppler_std_hz', 0.0),
                fss_db=obs.get('fss_db'),
                expected_second_rtp=expected_second_rtp
            )
            snr = obs.get('snr_db', 10.0)
            results.append((result, snr))
        
        # Weight by SNR and confidence
        weighted_emission_offset = 0.0
        total_weight = 0.0
        
        for result, snr in results:
            if result.confidence > 0.3:  # Only use confident results
                weight = result.confidence * max(1.0, snr / 10.0)
                weighted_emission_offset += result.emission_offset_ms * weight
                total_weight += weight
        
        if total_weight > 0:
            combined_offset_ms = weighted_emission_offset / total_weight
        else:
            combined_offset_ms = results[0][0].emission_offset_ms
        
        # Check consistency: all frequencies should give similar emission times
        offsets = [r.emission_offset_ms for r, _ in results if r.confidence > 0.3]
        if offsets:
            offset_spread = max(offsets) - min(offsets)
            consistency_bonus = 1.0 if offset_spread < 1.0 else 0.7
        else:
            consistency_bonus = 0.5
        
        # Use the highest-confidence single result as base
        best_result, best_snr = max(results, key=lambda x: x[0].confidence * x[1])
        
        # Boost confidence based on multi-frequency agreement
        combined_confidence = min(1.0, best_result.confidence * consistency_bonus * 1.2)
        
        # Verify UTC(NIST) with combined offset
        utc_verified = abs(combined_offset_ms) < 1.5  # Tighter threshold for multi-freq
        
        return SolverResult(
            arrival_rtp=best_result.arrival_rtp,
            emission_rtp=best_result.emission_rtp,
            emission_offset_ms=combined_offset_ms,
            propagation_delay_ms=best_result.propagation_delay_ms,
            mode=best_result.mode,
            mode_name=best_result.mode_name + " (multi-freq)",
            n_hops=best_result.n_hops,
            layer_height_km=best_result.layer_height_km,
            elevation_angle_deg=best_result.elevation_angle_deg,
            confidence=combined_confidence,
            mode_separation_ms=best_result.mode_separation_ms,
            delay_spread_penalty=best_result.delay_spread_penalty,
            doppler_penalty=best_result.doppler_penalty,
            fss_consistency=consistency_bonus,
            candidates=best_result.candidates,
            utc_nist_offset_ms=combined_offset_ms,
            utc_nist_verified=utc_verified
        )


@dataclass
class CombinedUTCResult:
    """
    Combined UTC(NIST) estimate from multiple stations/frequencies.
    
    This is the "Holy Grail" result - a primary time standard from
    passive HF reception by correlating multiple independent measurements.
    """
    # Combined estimate
    utc_offset_ms: float  # Best estimate of UTC(NIST) offset from local clock
    uncertainty_ms: float  # 1-sigma uncertainty
    
    # Confidence and quality
    confidence: float  # 0-1 overall confidence
    consistency: float  # 0-1 how well measurements agree
    n_measurements: int  # Number of independent measurements used
    n_stations: int  # Number of distinct stations
    
    # Individual measurements
    individual_results: List[Dict]  # Per-station/freq results
    
    # Outlier info
    outliers_rejected: int
    
    # Verification
    verified: bool  # True if uncertainty < 2ms and consistency > 0.7
    quality_grade: str  # "A" (sub-ms), "B" (1-2ms), "C" (2-5ms), "D" (>5ms)


class MultiStationSolver:
    """
    Correlate UTC(NIST) estimates from multiple stations and frequencies.
    
    By combining WWV, WWVH, and CHU observations, we can:
    1. Reject outliers from incorrect mode identification
    2. Reduce uncertainty through averaging
    3. Detect systematic errors (e.g., wrong ionospheric model)
    4. Achieve sub-millisecond timing accuracy
    """
    
    def __init__(self, solver: TransmissionTimeSolver):
        """
        Initialize with a base solver (already has receiver location).
        """
        self.solver = solver
        self.pending_observations: List[Dict] = []
    
    def add_observation(
        self,
        station: str,
        frequency_mhz: float,
        arrival_rtp: int,
        expected_second_rtp: int,
        snr_db: float = 10.0,
        delay_spread_ms: float = 0.0,
        doppler_std_hz: float = 0.0,
        fss_db: Optional[float] = None
    ):
        """
        Add an observation to the pending set.
        
        Call this for each detected station/frequency, then call solve_combined().
        """
        self.pending_observations.append({
            'station': station,
            'frequency_mhz': frequency_mhz,
            'arrival_rtp': arrival_rtp,
            'expected_second_rtp': expected_second_rtp,
            'snr_db': snr_db,
            'delay_spread_ms': delay_spread_ms,
            'doppler_std_hz': doppler_std_hz,
            'fss_db': fss_db
        })
    
    def clear_observations(self):
        """Clear pending observations for new minute."""
        self.pending_observations = []
    
    def solve_combined(self) -> CombinedUTCResult:
        """
        Solve for combined UTC(NIST) using all pending observations.
        
        Uses weighted least-squares to find the UTC offset that best
        explains all observations, accounting for different propagation
        modes at each station/frequency.
        """
        if not self.pending_observations:
            return self._no_combined_solution()
        
        # Solve each observation independently
        individual_results = []
        for obs in self.pending_observations:
            try:
                result = self.solver.solve(
                    station=obs['station'],
                    frequency_mhz=obs['frequency_mhz'],
                    arrival_rtp=obs['arrival_rtp'],
                    delay_spread_ms=obs['delay_spread_ms'],
                    doppler_std_hz=obs['doppler_std_hz'],
                    fss_db=obs['fss_db'],
                    expected_second_rtp=obs['expected_second_rtp']
                )
                
                individual_results.append({
                    'station': obs['station'],
                    'frequency_mhz': obs['frequency_mhz'],
                    'snr_db': obs['snr_db'],
                    'mode': result.mode.value,
                    'mode_name': result.mode_name,
                    'n_hops': result.n_hops,
                    'propagation_delay_ms': result.propagation_delay_ms,
                    'utc_offset_ms': result.utc_nist_offset_ms,
                    'confidence': result.confidence,
                    'elevation_deg': result.elevation_angle_deg
                })
            except Exception as e:
                logger.warning(f"Failed to solve {obs['station']} {obs['frequency_mhz']} MHz: {e}")
        
        if not individual_results:
            return self._no_combined_solution()
        
        # Filter to confident results
        confident_results = [r for r in individual_results 
                           if r['confidence'] > 0.3 and r['utc_offset_ms'] is not None]
        
        if not confident_results:
            # Fall back to best individual result
            best = max(individual_results, key=lambda r: r['confidence'])
            return CombinedUTCResult(
                utc_offset_ms=best['utc_offset_ms'] or 0.0,
                uncertainty_ms=5.0,
                confidence=best['confidence'] * 0.5,
                consistency=0.0,
                n_measurements=1,
                n_stations=1,
                individual_results=individual_results,
                outliers_rejected=0,
                verified=False,
                quality_grade='D'
            )
        
        # Weighted average with outlier rejection
        offsets = [r['utc_offset_ms'] for r in confident_results]
        weights = [r['confidence'] * max(1.0, r['snr_db'] / 10.0) for r in confident_results]
        
        # Iterative outlier rejection (2-sigma)
        outliers_rejected = 0
        for _ in range(3):  # Max 3 iterations
            if len(offsets) < 2:
                break
            
            weighted_mean = sum(o * w for o, w in zip(offsets, weights)) / sum(weights)
            residuals = [abs(o - weighted_mean) for o in offsets]
            
            # Estimate std from median absolute deviation (robust)
            mad = sorted(residuals)[len(residuals) // 2]
            sigma = mad * 1.4826  # MAD to std conversion
            
            if sigma < 0.1:
                sigma = 0.1  # Minimum std to avoid over-rejection
            
            # Reject outliers > 2 sigma
            new_offsets = []
            new_weights = []
            for o, w, r in zip(offsets, weights, residuals):
                if r < 2 * sigma:
                    new_offsets.append(o)
                    new_weights.append(w)
                else:
                    outliers_rejected += 1
            
            if len(new_offsets) == len(offsets):
                break  # No more outliers
            offsets = new_offsets
            weights = new_weights
        
        # Final weighted average
        if offsets:
            total_weight = sum(weights)
            combined_offset = sum(o * w for o, w in zip(offsets, weights)) / total_weight
            
            # Uncertainty from weighted std
            if len(offsets) > 1:
                variance = sum(w * (o - combined_offset)**2 for o, w in zip(offsets, weights)) / total_weight
                uncertainty = math.sqrt(variance) / math.sqrt(len(offsets))  # Standard error
            else:
                uncertainty = 2.0  # Single measurement, conservative
        else:
            combined_offset = 0.0
            uncertainty = 10.0
        
        # Calculate consistency (how well measurements agree)
        if len(offsets) > 1:
            spread = max(offsets) - min(offsets)
            consistency = max(0.0, 1.0 - spread / 3.0)  # 0 spread = 1.0, 3ms spread = 0.0
        else:
            consistency = 0.5
        
        # Count distinct stations
        stations_used = set(r['station'] for r in confident_results 
                          if r['utc_offset_ms'] in offsets)
        n_stations = len(stations_used)
        
        # Calculate combined confidence
        avg_individual_conf = sum(r['confidence'] for r in confident_results) / len(confident_results)
        multi_station_bonus = 1.0 + 0.1 * (n_stations - 1)  # Bonus for multiple stations
        combined_confidence = min(1.0, avg_individual_conf * consistency * multi_station_bonus)
        
        # Determine quality grade
        if uncertainty < 0.5 and consistency > 0.8:
            quality_grade = 'A'  # Excellent - sub-millisecond
        elif uncertainty < 1.5 and consistency > 0.6:
            quality_grade = 'B'  # Good
        elif uncertainty < 3.0:
            quality_grade = 'C'  # Fair
        else:
            quality_grade = 'D'  # Poor
        
        # Verify
        verified = uncertainty < 2.0 and consistency > 0.5 and n_stations >= 1
        
        return CombinedUTCResult(
            utc_offset_ms=combined_offset,
            uncertainty_ms=uncertainty,
            confidence=combined_confidence,
            consistency=consistency,
            n_measurements=len(offsets),
            n_stations=n_stations,
            individual_results=individual_results,
            outliers_rejected=outliers_rejected,
            verified=verified,
            quality_grade=quality_grade
        )
    
    def _no_combined_solution(self) -> CombinedUTCResult:
        """Return empty result when no observations available."""
        return CombinedUTCResult(
            utc_offset_ms=0.0,
            uncertainty_ms=999.0,
            confidence=0.0,
            consistency=0.0,
            n_measurements=0,
            n_stations=0,
            individual_results=[],
            outliers_rejected=0,
            verified=False,
            quality_grade='D'
        )


# Convenience function for quick use
def create_solver_from_grid(grid_square: str, sample_rate: int = 20000) -> TransmissionTimeSolver:
    """
    Create a TransmissionTimeSolver from a Maidenhead grid square.
    
    Args:
        grid_square: 4 or 6 character grid square (e.g., "EM38" or "EM38ww")
        sample_rate: Audio sample rate
        
    Returns:
        Configured TransmissionTimeSolver
    """
    # Convert grid square to lat/lon
    lat, lon = grid_to_latlon(grid_square)
    return TransmissionTimeSolver(lat, lon, sample_rate)


def grid_to_latlon(grid: str) -> Tuple[float, float]:
    """Convert Maidenhead grid square to latitude/longitude."""
    grid = grid.upper()
    
    lon = (ord(grid[0]) - ord('A')) * 20 - 180
    lat = (ord(grid[1]) - ord('A')) * 10 - 90
    
    lon += (ord(grid[2]) - ord('0')) * 2
    lat += (ord(grid[3]) - ord('0')) * 1
    
    if len(grid) >= 6:
        lon += (ord(grid[4].lower()) - ord('a')) * (2/24) + (1/24)
        lat += (ord(grid[5].lower()) - ord('a')) * (1/24) + (1/48)
    else:
        lon += 1  # Center of grid
        lat += 0.5
    
    return lat, lon


def create_multi_station_solver(grid_square: str, sample_rate: int = 20000) -> MultiStationSolver:
    """
    Create a MultiStationSolver for correlating WWV/WWVH/CHU.
    
    Args:
        grid_square: Receiver location (e.g., "EM38ww")
        sample_rate: Audio sample rate
        
    Returns:
        Configured MultiStationSolver ready to accept observations
    """
    base_solver = create_solver_from_grid(grid_square, sample_rate)
    return MultiStationSolver(base_solver)
