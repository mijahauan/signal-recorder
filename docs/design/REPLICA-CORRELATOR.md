# The replica correlator

`src/hf_timestd/replica/` correlates a received tick-band envelope against a locally generated
WWV/WWVH broadcast. A ruler error stretches the received program against that replica, so the
drift of the correlation lag measures the ruler — reading no host clock at any point. The
correlation score answers a second question the fold-peak method could not: does this channel
carry WWV structure **at all**.

It ships as a library with no consumers, like the estimator beside it, so its arithmetic could
be proven against recorded signal before anything depended on it.

## 1 · Why it exists

On 2026-09-08 a devbox shadow run drove all sixteen committed witness series through the station
timing estimator. Nine published a rate wrong by one to three orders of magnitude. Two of them,
AC0G-ND's `WWV_20000` and `WWV_25000`, published −46.8 ppm and −216.6 ppm off channels carrying
no usable signal: their fold-peak series had coin-flipped its whole-second cycle choice, and
nothing downstream could tell that from a real measurement.

The estimator now refuses those (`thin_fit` and `fit_scatter`, see
[`STATION-TIMING-ESTIMATOR.md`](STATION-TIMING-ESTIMATOR.md) §4). But refusing a number is not
the same as never manufacturing it. A correlation score separates the two cases at the source,
and by a wide margin: **57.8 to 71.0 on channels that work, against 6.2 and 7.2 on those two.**
The lower pair is simply what pure noise scores, since the largest of many Gaussian samples sits
near 4.5 sigma while their median absolute value sits near 0.674 sigma. `MIN_CC_SNR` sits at 20,
geometrically between the two, with a threefold margin on either side.

## 2 · The template

One minute, read off `gen_ticks` in Phil Karn's `wwvsim` (github.com/ka9q/wwvsim): an 800 ms
marker at second 0 in the station's tick band, a 5 ms tick on every second from 1 to 58 except
29, and nothing at 29 or 59. On the hour the marker moves to 1500 Hz, which falls outside both
tick bands and so leaves the template alone.

WWV ticks at 1000 Hz and WWVH at 1200 Hz, so **the two stations share this time structure
exactly and one template serves both** — the band picks the station, not the template. The
template therefore carries no tone: a band envelope has already discarded the carrier, and what
survives is duration and position. Cross-checked against wwvsim's own output through the
acquirer's own band filter, the template lands at +0.034 ms with a score of 103.1, and WWV in
band 1000 scores identically to WWVH in band 1200.

`wwvsim` is a validation oracle, not a runtime dependency. To rebuild it: **delete** the
`#define USE_PORTAUDIO` line (the guard is `#ifdef`, so setting it to 0 does nothing), generate
`paths.h` by hand, then `gcc -O2 -o wwvsim wwvsim.c timecode.c -lm -lpthread`. Generate a minute
with `-r 24000 -t -d -c [-H]`, which strips tones, voice and the 100 Hz timecode. ⛔ Its `-1`
flag does **not** bound the output — bound it with `head -c`, because one minute at 24 kHz
16-bit mono is exactly 2,880,000 bytes and the unbounded form fills a disk.

## 3 · What it measures, and how well

Ten one-minute correlations per recording, the lag fitted against time:

    row                              replica ppm   sigma   rms ms   fold sigma
    nd-20260906/SHARED_10000/1000       +0.0256    0.188    0.103      1.16
    nd-20260906-bad/SHARED_10000/1200   -0.1275    0.054    0.029      1.16
    b4-20260906-day/SHARED_10000/1000   +0.5566    0.249    0.047      3.01
    nd-20260906 resampled -60 ppm      -59.5907    0.269    0.125      1.21

Per-observation residual lands at 0.029 to 0.125 ms against the fold method's 1 ms witness
sigma. Repeatability across INDEPENDENT recordings hours apart — the measure that means
something — came to **0.05 ppm at B4 and 0.15 ppm at ND**, against the fold method's 1.16 to
3.01 ppm.

⚡ Those two ND readings, from windows 9.2 hours apart, also say the converter's ruler sat within
0.08 ppm of nominal at two different times of day. The GPSDO held lock across that span.

## 4 · Four limits, each measured rather than assumed

**The whole-second ambiguity SURVIVES.** A replica was expected to end it, and does not. The
minute-unique features — the 800 ms marker and the missing ticks at 29 and 59 — do not outweigh
the 1 s tick train's energy, so the correlation peak still slips whole seconds. Rate survives
regardless, because a rate needs only consistency between minutes, so the lag series unwraps on
the second lattice. **Absolute second-of-minute needs a dedicated marker-and-gap match over 60
discrete hypotheses, which this module does not attempt.** So the correlator buys rate, not
absolute time.

**The score does NOT identify the station.** WWV read through WWVH's band still scores 371.9
against 103.1 in its own, because the leakage carries the same time structure and the score is
normalised by its own noise floor. Station identity lives in the bands' relative energy, never
in this number. A test asserts the limit so nobody later reads identity into it.

**A path-delay floor nobody can filter away.** The correlator measures ruler rate PLUS
path-delay rate. Ionospheric delay drifting 30 µs across ten minutes is 0.05 ppm of apparent
rate — the very threshold an A1 demands. Separating the two needs the common-mode argument:
several channels on one converter see different paths but share the ruler.

**An injection ladder is NOT a valid accuracy check.** Resampling a recording by a known ppm and
re-measuring it re-uses that recording's own fading, which couples to the injection: across four
fixtures the apparent scale error ran from −6.3 % to +4.1 %, sign included, while the pipeline
recovers synthetic signal to 0.009–0.094 ppm. An earlier reading of that ladder as "a 0.7 % scale
bias" was wrong and is retracted. Repeatability across independent recordings replaces it.

## 5 · The uncertainty

Fading and path drift move a lag **smoothly**, and a smooth drift is degenerate with a slope:
no fit can tell one from the other over a short span. Least squares assuming independent
residuals is therefore confident about exactly what it cannot see. `fit_rate` widens itself by
the standard effective-sample-size factor, `sqrt((1+rho)/(1-rho))` on the residuals' lag-1
autocorrelation, capped at rho = 0.95 because a pure ramp cannot be told from a rate at all.

Measured: the inflation reaches 1.82 on a smooth residual and 1.09 on a rough one of the same
size at ten points, and falls to 1.04 by forty. It only ever widens — a negative autocorrelation
says the noise alternates, which licenses no more confidence than independence would.

`MIN_POINTS` is 4: two points fit a line exactly, a third leaves one degree of freedom, and a
fourth is the fewest that can show an autocorrelation at all.

## 6 · What it does not do

No consumer constructs it. It emits no `PhaseObservation` and no `RateObservation`, so nothing
reaches the estimator from here yet.

⛔ **When something does wire it up:** a replica correlator and a fold-peak witness on the SAME
channel share one antenna, one converter and one propagation path. They are **not** independent
tiers. Labelling them as two would rebuild the fake quorum measured on 2026-09-08, which moved
ND's answer from −0.0475 to +0.5231 ppm — the wrong sign. They must share a tier, or the quorum
has to be reasoned about differently.
