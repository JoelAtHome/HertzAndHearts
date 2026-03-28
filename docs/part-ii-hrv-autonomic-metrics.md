<!--
  Title: Part II — HRV, LF/HF, and autonomic metrics
  Source: edited-Cardiac_Vagal Signals_ LF and HF.docx
  Generated: 2026-03-21
  Regenerate: python docs/cardiac_md_export.py
-->

## Companion documents

- Full combined guide: [cardiac-compendium.md](cardiac-compendium.md)
- Part I (QRS fundamentals): [part-i-qrs-waveform-fundamentals.md](part-i-qrs-waveform-fundamentals.md)

---

# Cardiac/Vagal Signals: LF and HF

Joel and Gemini

03/17/2026

Low Frequency (LF) and High Frequency (HF) components are best interpreted through Heart Rate Variability (HRV), which reflects millisecond-level variation between consecutive heartbeats (R-R intervals), rather than heart rate alone.

Applying Power Spectral Density (PSD) analysis (typically via Fourier methods) converts HRV from the time domain to the frequency domain. This provides a non-invasive perspective on autonomic regulation by quantifying signal power (variance) within physiologically relevant bands.

## 1) Frequency-Domain Foundations

### High Frequency (HF): Vagal-Dominant Activity

- Typical band: 0.15-0.40 Hz.
- Primary physiological driver: parasympathetic (vagal) modulation.
- Mechanistic anchor: Respiratory Sinus Arrhythmia (RSA), where heart rate rises during inhalation (vagal withdrawal) and falls during exhalation (vagal activation).
- Clinical/functional interpretation: higher HF power generally corresponds to improved recovery state, greater vagal tone, and lower acute stress load.

### Low Frequency (LF): Mixed Autonomic and Baroreflex Signal

- Typical band: 0.04-0.15 Hz.
- Physiological interpretation: mixed sympathetic and parasympathetic contributions; not purely sympathetic.
- Major contributor: baroreflex-mediated blood-pressure regulation.
- Resonance phenomenon: at approximately 6 breaths per minute (~0.1 Hz), LF power often increases markedly due to stronger cardiorespiratory coupling.
- Measurement note: when comparing sessions, control breathing cadence where possible, as respiration shifts can redistribute spectral power independent of recovery state.

### LF/HF Ratio: Limits of the "Balance" Model

- Historical convention: LF/HF was used as a proxy for "sympathovagal balance."
- Current position: this interpretation is overly reductive because LF contains dual-branch influences.
- Preferred context metrics: total power (global ANS adaptability) and normalized units (relative LF/HF contribution within total power).
- Interpretive best practice: pair one vagal-sensitive metric (HF or RMSSD) with one context metric (for example, resting heart rate or total power) to reduce overinterpretation.

### Mathematical and Engineering Context

Band-limited power is defined as the integral of PSD over the corresponding frequency limits.

$$
P_{\mathrm{HF}} = \int_{0.15}^{0.40} S(f) \, df
$$

From a control-systems perspective, frequency-band power can be interpreted as oscillatory strength within biological feedback loops. Greater coherent power typically indicates more responsive and adaptable regulation.

### Summary Table of Frequency Domains

*Table 1: Frequency-domain metrics and interpretation.*

| Band/Metric | Range / Formula | Primary Drivers | Interpretive Use |
| --- | --- | --- | --- |
| HF | 0.15-0.40 Hz | Predominantly parasympathetic (vagal), respiration-linked | Recovery state and vagal modulation |
| LF | 0.04-0.15 Hz | Mixed autonomic input with prominent baroreflex contribution | Context-dependent regulatory signal |
| LF/HF | LF / HF | Composite ratio | Not a direct branch-isolation index |

## 2) LF/HF Variability and Trend Tracking

LF/HF should be treated as a dynamic regulatory marker rather than a fixed personal constant. Substantial intra-individual variation is expected.

### Expected Sources of Day-to-Day Variation

- Circadian effects: LF tends to be relatively higher in morning periods; HF is often highest during deep sleep.
- Post-prandial effects: digestion can temporarily increase vagal activity and lower LF/HF.
- Hydration and stimulants: dehydration may elevate LF; caffeine can increase sympathetic drive.
- Psychological state: brief cognitive or emotional stress can materially influence short recordings.

### Methods That Improve Trend Reliability

- Use rolling baselines (for example, 7-day moving averages) rather than isolated single-day values.
- A sustained upward drift in LF/HF may indicate cumulative stress burden or incomplete recovery.
- Track variability as well as central tendency (for example, coefficient of variation).
- Standardize capture conditions: 3-5 minutes immediately after waking, before caffeine, in a fixed body position.
- Log major confounders (sleep disruption, illness onset, caffeine timing, and training load) to improve interpretation.

### Normalized Units (nHF) for Improved Interpretability

Because LF/HF can be mathematically noisy, normalized metrics are often preferred.

$$
\mathrm{nHF} = \frac{\mathrm{HF}}{\text{Total Power} - \mathrm{VLF}} \times 100
$$

nHF represents the proportion of autonomic power allocated to recovery-associated (vagal) activity and is often easier to track longitudinally.

### Three-Minute Session Comparison Framework

*Table 2: Preferred interpretation strategy for short sessions.*

| Comparison Mode | Recommendation | Rationale |
| --- | --- | --- |
| Random daytime averaging | Do not use as primary trend metric | Confounded by uncontrolled context |
| Standardized morning baseline | Preferred | Highest repeatability and interpretive clarity |
| Single-day interpretation | Use with caution | Insufficient to infer stable autonomic trend |

Operational guidance: prioritize morning baseline trajectories. A sustained 3-5 day increase in LF/HF, or sustained decline in HF power, is a stronger signal of rising recovery demand.

Threshold guidance should be individualized from baseline distributions rather than taken from fixed population cutoffs.

## 3) Time-Domain Metrics: RMSSD and SDNN

Time-domain analysis simplifies computation relative to spectral analysis, but high-quality interpretation still depends on strict measurement consistency.

### Core Definitions

- RMSSD (Root Mean Square of Successive Differences): short-lag beat-to-beat variability and primary time-domain proxy for parasympathetic modulation.
- SDNN (Standard Deviation of NN intervals): aggregate variability metric reflecting broad autonomic influences; highly dependent on recording duration.

### Protocol for Longitudinal Use

- Timing: immediately upon waking (fasted/rested state).
- Duration: 3-5 minutes.
- Posture: maintain a fixed posture across days (supine or seated).
- Interpretation method: compare against baseline plus standard deviation bands rather than reacting to isolated values.
- Baseline window: approximately 14 days before making stronger inferences.
- Amber zone: RMSSD decrease of ~0.5 to 1.0 SD below baseline may indicate meaningful systemic stress/fatigue.
- Red zone: RMSSD decrease >1.5 SD often aligns with overreaching, illness, or high psychological stress.

### Monitoring During Electrotherapy Sessions

Within-session monitoring can be useful, provided artifact risk is actively managed.

- RMSSD can function as a pragmatic bio-safety marker during treatment.
- A transient onset drop is commonly observed during initial stimulus adaptation.
- The key observation is trajectory: rebound/stability is preferable to persistent decline.
- In short windows, RMSSD is generally more actionable than SDNN due to faster response to vagal shifts.
- Data quality rule: an artifact-free short recording is more valuable than a longer recording with unstable beat detection.
- Periodic calibration using occasional longer standardized sessions can validate that short-form monitoring remains aligned with broader trends.

### Technical Limitation: Signal Artifacts

Electrotherapy systems (including TENS and interferential modalities) may inject electrical noise into ECG or PPG acquisition. If interference is misclassified as valid beats, RMSSD may appear spuriously elevated or erratic.

### Comparison of Common Metrics

*Table 3: Strengths and limitations of commonly tracked metrics.*

| Metric | Primary Strength | Primary Limitation |
| --- | --- | --- |
| RMSSD | Sensitive short-term vagal marker | Vulnerable to beat-detection artifact |
| SDNN | Broad total-variability representation | Weak interpretability in very short recordings |
| LF/HF | Frequency-domain context marker | Not a direct sympathetic-vs-parasympathetic split |
