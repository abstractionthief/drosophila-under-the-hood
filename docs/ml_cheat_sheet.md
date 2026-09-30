# The fly connectome for ML engineers: a cheat sheet

**The connectome constrains who can influence whom. A model of neural
dynamics specifies how those influences change activity over time.**
MaleCNS provides a large, incomplete reconstruction of chemical wiring
from one fly, with synapse counts and cell annotations. It does not supply
a ready-to-run neural network with known physiological parameters.

In the app, **Start Here** explains the dataset and the views. **ML Primer**
introduces state, dynamics and computational motifs. This document is the
longer reference: model assumptions, reproducible graph statistics and
ways to test an interpretation. For the pipeline see
[project overview](project_overview.md); for biological background see
[domain reference](domain_reference.md).

## 1. From wiring to activity

Consider this **example leaky activity model**:

$$
x_{t+1}=(1-\alpha)\odot x_t
       +\alpha\odot\phi(Wx_t+Bu_t+b).
$$

| Symbol | Meaning in this example | What the connectome supplies |
|---|---|---|
| $x_t$ | One model activity value per neuron at time $t$ | No activity recordings or initial state |
| $W_{ij}$ | Effective influence from neuron $j$ to neuron $i$ | Reconstructed connections and synapse counts constrain its support and possible magnitude |
| $u_t$, $B$ | External stimulus and how it enters the model | Sensory annotations help identify inputs; stimulus encoding remains a choice |
| $\phi$, $b$ | Response function and baseline drive | These must be measured, assumed or fitted |
| $\alpha$ | Fraction of the state updated per step, related to a chosen time constant and step size | No measured time constants |

Here $x_t$ is a column vector, so **column $j$ of $W$ contains neuron
$j$'s outgoing influences**. $\odot$ means elementwise multiplication;
$0<\alpha_i\leq1$ gives each neuron its own amount of leak. This is one
possible abstraction, not a biological equation inferred from the wiring.
A rate model also omits spikes, dendritic compartments, conduction delays
and many synaptic processes.

At each step, a neuron combines input from its neighbours with external
drive, applies a response function and retains some previous state.
Parallel outgoing connections let activity affect several targets;
converging inputs combine at a target. Positive and negative effective
weights can implement excitation and inhibition, but the sign assignment
needs evidence beyond a synapse count.

With recurrent connections, the new state influences future inputs. A
stimulus can therefore produce a transient, persistent activity or an
oscillation, depending on the chosen parameters. **Changing activity with
fixed weights is computation; changing parameters through experience is
learning.** Neither a graph path nor a reciprocal connection alone tells
us which dynamics a biological circuit exhibits.

**Relation to the app's Dynamics view.** That view runs a separate toy
model on 24 aggregated groups, not 165,122 individual neurons. Its
[implementation](../src/io_analysis/dynamics.py) uses an Euler step for
$\dot{x}=-x/\tau+\tanh(gW^Tx+u)$, stores sources in matrix rows, and
therefore multiplies by $W^T$. It normalizes outgoing synapse counts and
assigns one coarse sign per group. Its time units and activity traces are
illustrative, not measured physiology; the equation above is not a
description of that exact implementation.

## 2. Dictionary: fly ↔ ML

| Connectome concept | Useful ML analogy | Limit of the analogy |
|---|---|---|
| Neuron | Stateful unit | Real neurons have spatial compartments; some signal with graded potentials rather than spikes |
| Synapse count on an edge | Constraint on weight magnitude | Counts do not specify receptor effects, release probability, synapse location or effective strength |
| Neurotransmitter annotation | Evidence relevant to weight sign | Annotation is not a physiological sign measurement; postsynaptic receptors matter |
| Dale's principle | Sign-constrained excitatory/inhibitory RNN | Consistent transmitter identity does not guarantee one effect on every target; co-transmission and receptor differences complicate the rule |
| Cell type | Parameter sharing across related units | Sharing weights or time constants is a modelling assumption; neurons of one type are not identical |
| Descending neurons | Commands to a downstream controller | They communicate with VNC circuits; they are not a complete list of independent actions or all brain outputs |
| Neuromodulation | Context, gain control or a learning signal | Effects depend on receptor, compartment and timescale; chemical edges alone do not specify them |
| Electrical synapses | Additional coupling between units | Gap junctions are absent from this project's chemical-edge table; this is not a claim that EM can never reveal them |

For example, glutamate can inhibit fly neurons through chloride channels
or excite them through other receptors. A source-neuron label alone does
not resolve that distinction ([Liu & Wilson 2013](https://www.pnas.org/doi/10.1073/pnas.1220560110)).
The excitatory/inhibitory constraints used in an ML model should be
explicit assumptions supported by relevant physiology.

## 3. Three computational motifs

### Visual circuits: repeated local processing

Repeated cell types and columns in the optic lobe make convolution a useful
analogy. Recurrence, heterogeneous connections and temporal dynamics also
matter; the optic lobe is not simply a feedforward CNN. In a
connectome-constrained visual model, Lappalainen and colleagues used
connectivity across 64 cell types and optimized unknown neuron and synapse
parameters on a motion task. The resulting model was tested against
neural responses from 26 studies. This illustrates how anatomy and
functional validation can work together
([Lappalainen et al. 2024](https://www.nature.com/articles/s41586-024-07939-3)).

### Mushroom body: expansion, sparse coding and a plastic readout

Our traced data contain 686 antennal-lobe projection neurons (PNs) and
4,064 Kenyon cells (KCs). Direct PN→KC edges connect **314 of those PNs
to 3,812 KCs**; among those connected KCs, the median number of distinct
PN partners is **6**, counting every reconstructed edge with at least
one synapse. These are connected populations, not a claim that every PN
in the census projects to every KC.

Sparse combinations of PN inputs and inhibitory control motivate the
analogy to random expansion and a sparse code. The counts alone do not
establish randomness. This motif inspired a similarity-search algorithm,
usually called fly hashing ([Dasgupta et al. 2017](https://science.sciencemag.org/content/358/6364/793)).

A major site of associative plasticity is the KC→mushroom-body-output-neuron
synapse. Hige and colleagues demonstrated odour-specific depression gated
by dopamine and the timing of its arrival; postsynaptic spikes were not
required for that form of plasticity. A universal pre × post × reward
formula would misdescribe this result
([Hige et al. 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4674068/)).
The learned-readout analogy is useful but incomplete: plasticity also
occurs at incoming PN→KC synapses and contributes to memory
([Input-timing-dependent plasticity… 2022](https://www.sciencedirect.com/science/article/pii/S0960982222015548)).

### Heading circuit: recurrent state and learned landmarks

In the central complex's heading circuit, a localized activity pattern
tracks direction, integrates turning and can persist in darkness. A ring
attractor is a useful model of this maintained state
([Seelig & Jayaraman 2015](https://www.nature.com/articles/nature14446)).
The sensory anchoring is plastic: sensorimotor experience can reorganize
visual inputs to compass neurons and shift the represented reference
frame. Recurrent architecture and learning both contribute
([Fisher et al. 2019](https://www.nature.com/articles/s41586-019-1772-4)).

## 4. What the graph statistics measure

Project statistics use MaleCNS v1.0, `status == "Traced"` and chemical
edges between traced neurons. An edge is one ordered neuron pair with at
least one reconstructed synapse. The count on that edge is called
`weight` in the data; it is not the effective weight $W_{ij}$ above.

Regenerate the [statistics artifact](../data/ml_primer_stats.json) from
the repository root:

```sh
.venv/bin/python -m io_analysis.primer_stats
```

The [analysis script](../src/io_analysis/primer_stats.py) records population
definitions and methods alongside the results. Do not mix raw `superclass`
populations with the project's derived `io_role` groups.

| Quantity | Value | Interpretation |
|---|---|---|
| Neurons | 165,122 | Traced population |
| Directed edges | 25,563,197 | Neuron pairs, not cell-type pairs |
| Synapses | 124,025,046 | Sum of edge counts |
| Edge density | 0.094% | Edges divided by $165{,}122^2$, including possible self-pairs |
| Edges with ≥10 synapses | 10.8% of edges, 54% of synapses | Anatomical counts are concentrated on a minority of pairs |
| Reciprocal edges | 29.9% | Share of nonself directed edges whose reverse is also present |
| Largest strongly connected component | 99.0% of neurons | Mutual reachability, not simultaneous activation |
| Recorded cell types | 11,751 | Dataset labels, not a parameter-sharing rule |
| Descending neurons | 1,314 | A small relay population linking brain and VNC |

By the presynaptic neuron's `consensusNt` annotation, acetylcholine,
GABA and glutamate account for approximately **59.2%, 20.7% and 17.0%**
of synapse counts. These are annotation-weighted fractions, **not measured
excitatory/inhibitory fractions**. `consensusNt` and raw prediction fields
are not interchangeable; see the data-quality notes in
[project overview](project_overview.md#5-data-quality-findings-worth-remembering).

Cross-individual comparisons found that stronger **cell-type-to-cell-type**
connections were more consistently recovered across FlyWire and hemibrain.
The reported >10-synapse threshold concerns those aggregated edges. It is
not a universal cutoff for individual-neuron edges in MaleCNS, and variation
does not make a connection functionally irrelevant. Report sensitivity to
thresholds rather than treating small counts as noise
([Schlegel et al. 2024](https://www.nature.com/articles/s41586-024-07686-5)).

### Graph distance is not computational depth

A shortest path measures whether a route exists. It does not establish
signal strength, activation order or transmission time. Even a weighted
traversal based on fractions of anatomical input is a graph summary:
inhibition, thresholds, delays and recurrent processing are missing.

The artifact includes an exploratory **deterministic input-fraction
traversal**. All 15,896 neurons with `io_role == sensory_input` start at
round 0, including 1,829 without a known sensory modality. At each round,
neurons join synchronously if previously reached neurons supply at least
the selected fraction of their total recorded incoming synapse count.

| Required input fraction | Median round, reached nonseed neurons | Descending neurons | Motor neurons | Deepest round |
|---|---|---|---|---|
| 10% | 3 | 2 | 2 | 6 |
| 20% | 4 | 3 | 3 | 10 |
| 30% | 8 | 5 | 4 | 20 |

At each of these thresholds, **148,803 of 149,226 nonseed neurons are
reached; 423 remain unreached**. Medians exclude seeds and unreached neurons.
All 1,314 descending and 815 motor neurons are reached. These populations
use `io_role`; motor neurons include both `cb_motor` and `vnc_motor`.
Unreached neurons have no finite round, so their count belongs beside any
summary of the reached population.

This differs from the probabilistic edge traversal, repeated over many
runs, in [Schlegel et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8298098/).
Neither gives the number of sequential computations performed by the
living network. A recurrent model can reuse the same neurons over many
time steps; short anatomical routes do not make it computationally shallow.

### Where descending and motor neurons receive anatomical input

The entries below are percentages of **all recorded input synapses onto
the target population**, grouped by source `io_role`. They are not average
per-neuron percentages or measured fractions of causal influence.

| Target | Sensory | Central processing | Optic processing | Descending | Ascending | VNC processing | Other roles |
|---|---|---|---|---|---|---|---|
| Descending (1,314 neurons) | 4.44% | 59.63% | 7.07% | 13.06% | 12.50% | 3.18% | 0.13% |
| Motor (815 neurons) | 3.08% | 6.44% | 0.22% | 11.07% | 6.37% | 72.16% | 0.67% |

Other roles combine motor, endocrine, other efferent and unknown sources;
rounding can make a row sum differ from 100%. The anatomy supports looking
at descending neurons together with local VNC circuitry and ascending
feedback. A ratio of brain-neuron count to descending-neuron count would
not establish information bandwidth or independent command channels.

## 5. What remains unmeasured

- **Connectivity is incomplete.** Detection, segmentation and attachment
  errors remain. MaleCNS reports 94% presynaptic and 42% postsynaptic
  attachment completeness relative to automatically detected sites;
  these are not recovery rates for every synapse in the animal. See
  [facts and source definitions](facts.md#connectome-completeness-malecns-vs-other-datasets).
- **Physiology is incomplete.** The edge table lacks effective strengths,
  receptor-specific signs, time constants, thresholds, delays and
  short-term synaptic dynamics. Electrical coupling and neuromodulatory
  volume transmission are outside its chemical-edge representation.
- **State and history are missing.** Hunger, arousal, ongoing activity and
  prior learning can change how the same anatomical circuit responds.
- **A task needs an interface.** Sensory annotations do not define pixel,
  odour or proprioceptive encodings. Motor annotations do not supply
  muscles, body mechanics or an environment.

Connectome-constrained modelling makes these choices explicit: use the
reconstruction to constrain connectivity, justify or fit unknown
parameters, and validate predictions on independent biological data.
It does not require pretending that the reconstruction is complete or that
synapse counts are already physiological weights.

## 6. Experiments that test the wiring

1. **Define the claim and task.** Distinguish task performance from a
   claim about biological computation. State which parameters, encoders
   and decoders were chosen or trained.
2. **Use matched controls.** Compare the recorded graph with rewired
   versions under the same encoding, dynamics, readout, tuning budget and
   held-out evaluation. Preserve degree, weight or cell-type structure
   according to the hypothesis; describe what each control changes.
3. **Treat trained readouts as valid but limited evidence.** A successful
   decoder can exploit task information present in many representations.
   Compare identical training and held-out performance across wiring
   controls. A fixed readout also embeds assumptions and may have been
   selected after seeing results; disclose and test those choices.
4. **Ablate and check specificity.** Remove the proposed circuit and
   compare with matched removals elsewhere. Measure predicted failures
   and unrelated behaviours, rather than attributing every performance
   drop to a specific mechanism.
5. **Test robustness and generalization.** Vary synapse-count thresholds,
   uncertain signs and plausible dynamics. Hold out stimuli, tasks or
   biological measurements from both fitting and model design. Report
   when a conclusion depends on one modelling choice.

## 7. Where to continue in the explorer

- **Overview:** a selected input→processing→output summary; recurrence and
  processing→processing links are omitted.
- **I/O Matrix → Pathway Explorer:** locate candidate routes, inspect
  individual edges and vary the minimum synapse count.
- **Neuron Detail:** inspect metadata and available morphology for the
  cells behind an aggregate.
- **Dynamics:** explore the behaviour of the declared toy model, keeping
  its assumptions separate from findings about the fly.
